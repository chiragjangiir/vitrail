package app.signflow.player

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.TextureView
import android.view.View
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.exoplayer.ExoPlayer
import org.json.JSONObject

/**
 * ExoController.kt — Rendu vidéo HW natif via ExoPlayer (Media3), alternatif au <video> de
 * la WebView. Sur les box Android TV, la WebView (Chromium souvent ancien, 83 sur le MINIX)
 * ne décode PAS le HEVC et peine sur le h264 4K@60 ; ExoPlayer attaque directement les
 * décodeurs HW de la plateforme (MediaCodec) → HEVC + h264/HEVC 4K@60 fluides, INDÉPENDAMMENT
 * de la version WebView. Pendant Android de l'approche mpv sur Linux (surface vidéo séparée).
 *
 * Architecture : ExoPlayer rend dans une TextureView SŒUR posée au-dessus de la WebView dans
 * la même FrameLayout. La WebView garde tout le reste (image/web/PDF/overlay) ; la TextureView
 * est rendue VISIBLE pendant une vidéo (recouvre la WebView), GONE sinon. TextureView (et non
 * SurfaceView) car sur les box Android TV la SurfaceView va sur un plan overlay matériel NON
 * capturable (PixelCopy → vignette vide) ; la TextureView passe par une texture GPU →
 * getBitmap() capture la vraie frame pour la vignette CMS. Activé par display_config.video_renderer='exo'.
 *
 * Tout passe par le thread principal (ExoPlayer l'exige) : les appels viennent du thread du
 * pont JS WebView → on poste sur mainHandler.
 */
class ExoController(
    private val context: Context,
    private val texture: TextureView,
    private val bridge: SignFlowBridge,
) {
    private val main = Handler(Looper.getMainLooper())
    private var player: ExoPlayer? = null
    private var lastVideoSize: VideoSize = VideoSize.UNKNOWN
    private var posTicking = false
    private var wall: JSONObject? = null   // compensation bezel (video wall) en cours, null = plein cadre

    init {
        // Posée au-dessus de la WebView dans la FrameLayout (ordre d'ajout). Cachée par défaut
        // → la WebView est visible tant qu'aucune vidéo ne joue.
        texture.visibility = View.GONE
        // La Matrix de compensation dépend des dimensions de la vue → ré-appliquée à chaque
        // (re)layout (la TextureView peut ne pas être encore mesurée au moment du setWall).
        texture.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> applyWallMatrix() }
    }

    private fun ensurePlayer(): ExoPlayer {
        player?.let { return it }
        val p = ExoPlayer.Builder(context).build()
        p.setVideoTextureView(texture)
        p.repeatMode = Player.REPEAT_MODE_OFF   // l'avance d'item est pilotée par le renderer (timer)
        p.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                when (state) {
                    Player.STATE_READY -> {
                        bridge.dispatch("exo-ready", null)
                        emitVideoInfo()
                        startPosTicker()
                    }
                    Player.STATE_ENDED -> bridge.dispatch("exo-ended", null)
                    else -> {}
                }
            }
            override fun onVideoSizeChanged(videoSize: VideoSize) {
                lastVideoSize = videoSize
                applyWallMatrix()   // le letterbox dépend du ratio SOURCE → à recalculer ici
                emitVideoInfo()
            }
            override fun onPlayerError(error: PlaybackException) {
                Log.e("SignFlow/Exo", "player error: ${error.errorCodeName} ${error.message}")
                bridge.dispatch("exo-error", JSONObject().put("reason", error.errorCodeName).toString())
            }
        })
        player = p
        return p
    }

    private fun emitVideoInfo() {
        val p = player ?: return
        val dur = p.duration
        val info = JSONObject()
            .put("width", lastVideoSize.width)
            .put("height", lastVideoSize.height)
            .put("duration", if (dur > 0) dur / 1000.0 else 0.0)
        bridge.dispatch("exo-videoinfo", info.toString())
    }

    /** Position courante poussée au renderer (~250ms) pour le report / nudge LAN éventuel. */
    private fun startPosTicker() {
        if (posTicking) return
        posTicking = true
        val r = object : Runnable {
            override fun run() {
                val p = player
                if (p == null) { posTicking = false; return }
                if (p.isPlaying) {
                    bridge.dispatch("exo-timepos", JSONObject().put("timePos", p.currentPosition / 1000.0).toString())
                }
                main.postDelayed(this, 250)
            }
        }
        main.postDelayed(r, 250)
    }

    fun load(url: String, seekMs: Long, muted: Boolean, loop: Boolean = false) = main.post {
        val p = ensurePlayer()
        // Le ratio du média PRÉCÉDENT ne doit pas cadrer le suivant : on repart en plein cadre,
        // onVideoSizeChanged recalculera le letterbox dès que la taille réelle est connue.
        lastVideoSize = VideoSize.UNKNOWN
        applyWallMatrix()
        p.volume = if (muted) 0f else 1f
        p.setPlaybackParameters(PlaybackParameters(1.0f))   // reset vitesse (persiste entre médias)
        // loop = takeover VOD « en boucle » (Feature B) → REPEAT_MODE_ONE ; sinon OFF (avance par
        // timer côté renderer). Reset explicite à chaque load : un load programme normal (loop=false)
        // remet REPEAT_MODE_OFF après une boucle VOD.
        p.repeatMode = if (loop) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
        p.setMediaItem(MediaItem.fromUri(url), if (seekMs > 0) seekMs else 0L)
        p.playWhenReady = true
        p.prepare()
    }

    fun show() = main.post {
        texture.visibility = View.VISIBLE
        player?.let { if (!it.isPlaying) it.play() }   // reprend (ex. après masquage par l'overlay)
    }

    fun hide() = main.post {
        texture.visibility = View.GONE
        player?.let { if (it.isPlaying) it.pause() }
    }

    fun stop() = main.post { player?.stop() }

    fun seek(ms: Long) = main.post { player?.seekTo(if (ms > 0) ms else 0L) }

    fun setRate(rate: Float) = main.post {
        player?.setPlaybackParameters(PlaybackParameters(if (rate > 0f) rate else 1.0f))
    }

    fun setMute(muted: Boolean) = main.post { player?.volume = if (muted) 0f else 1f }

    /**
     * Video Wall (compensation de bezel) — applique un Matrix sur la TextureView, équivalent natif
     * du `video-zoom`/`video-align` mpv (Linux) et de la transform CSS du renderer WebView. tf est
     * le `display_config.wall_transform` calculé serveur (services/video_wall.py) : mode 'overscan'
     * (B, défaut : scale_x/y + align_x/y ∈ {-1,0,1} = bord d'ancrage) ou 'crop' (A, source unique :
     * sous-rect normalisé x/y/w/h). null = reset (plein cadre). Mémorisé → ré-appliqué au relayout
     * (les dimensions de la vue sont nécessaires pour les pivots/translations en pixels).
     */
    fun setWall(tf: JSONObject?) = main.post {
        wall = tf
        applyWallMatrix()
    }

    /**
     * Ratio SOURCE du média courant (pixels carrés compris), ou 0 si inconnu.
     * Une seule définition : sert au letterbox à l'écran ET à la capture de vignette.
     */
    private fun sourceAspect(): Float {
        val vw = lastVideoSize.width.toFloat()
        val vh = lastVideoSize.height.toFloat()
        if (vw <= 0f || vh <= 0f) return 0f
        val par = lastVideoSize.pixelWidthHeightRatio.takeIf { it > 0f } ?: 1f
        return (vw * par) / vh
    }

    private fun applyWallMatrix() {
        texture.setTransform(contentMatrix())
        texture.invalidate()
    }

    /** Transform appliquée à la surface vidéo — UNE seule définition (écran + vignette). */
    private fun contentMatrix(): Matrix {
        val w = texture.width.toFloat()
        val h = texture.height.toFloat()
        val tf = wall
        val m = Matrix()   // identité par défaut = plein cadre
        if (tf == null && w > 0f && h > 0f) {
            // LETTERBOX — ⚠️ une TextureView nue ÉTIRE toujours la vidéo sur toute sa surface :
            // contrairement à PlayerView/AspectRatioFrameLayout, ExoPlayer.setVideoTextureView ne
            // gère AUCUN ratio. Invisible tant que le média et l'écran ont le même ratio (16:9 sur
            // 16:9) ; un 9:16 sur un cadre 16:9 sortait déformé (constat d'Ed 2026-08-14). On réduit
            // l'axe qui déborde autour du centre → bandes noires, jamais de recadrage.
            // ⛔ Ne s'applique PAS quand un wall_transform est actif : le mur d'écrans DOIT déborder.
            val srcAr = sourceAspect()
            if (srcAr > 0f) {
                val dstAr = w / h
                val sx = if (srcAr > dstAr) 1f else srcAr / dstAr
                val sy = if (srcAr > dstAr) dstAr / srcAr else 1f
                m.setScale(sx, sy, w / 2f, h / 2f)
            }
        }
        if (tf != null && w > 0f && h > 0f) {
            if (tf.optString("mode") == "crop") {
                // Mode A : n'afficher que le sous-rect [x..x+w]×[y..y+h] (fractions) → agrandir 1/w,1/h
                // et translater pour amener l'origine du sous-rect en (0,0). Équivaut au CSS
                // translate(-x/w,-y/h) scale(1/w,1/h) avec transform-origin 0,0.
                val cw = tf.optDouble("w", 1.0).toFloat().coerceAtLeast(1e-4f)
                val ch = tf.optDouble("h", 1.0).toFloat().coerceAtLeast(1e-4f)
                val x  = tf.optDouble("x", 0.0).toFloat()
                val y  = tf.optDouble("y", 0.0).toFloat()
                m.setScale(1f / cw, 1f / ch)
                m.postTranslate(-x / cw * w, -y / ch * h)
            } else {
                // Mode B (overscan) : scale autour du bord d'ancrage (align<0 → bord 0, align>0 →
                // bord max, align==0 → centre), pour pousser le contenu hors des joints intérieurs.
                val sx = tf.optDouble("scale_x", 1.0).toFloat()
                val sy = tf.optDouble("scale_y", 1.0).toFloat()
                val ax = tf.optDouble("align_x", 0.0)
                val ay = tf.optDouble("align_y", 0.0)
                val pivotX = if (ax < 0) 0f else if (ax > 0) w else w / 2f
                val pivotY = if (ay < 0) 0f else if (ay > 0) h else h / 2f
                m.setScale(sx, sy, pivotX, pivotY)
            }
        }
        return m
    }

    /**
     * Frame courante TELLE QU'AFFICHÉE, pour la vignette CMS. ⚠️ `TextureView.getBitmap()` rend le
     * contenu BRUT de la surface (vidéo étirée sur toute la vue) : la transform posée par
     * `setTransform` n'est appliquée qu'à la composition. Sans ce passage par `contentMatrix()`,
     * la vignette montrerait une image déformée là où l'écran, lui, est correct — et le letterbox
     * aurait deux définitions divergentes. null si la surface n'est pas lisible.
     */
    fun captureFrame(): Bitmap? {
        val src = try { texture.getBitmap() } catch (e: Exception) { null } ?: return null
        val m = contentMatrix()
        if (m.isIdentity) return src
        return try {
            val out = Bitmap.createBitmap(src.width, src.height, Bitmap.Config.ARGB_8888)
            Canvas(out).also { it.drawColor(Color.BLACK); it.drawBitmap(src, m, null) }
            src.recycle()
            out
        } catch (e: Exception) {
            Log.w("SignFlow/Exo", "captureFrame transform failed: ${e.message}")
            src
        }
    }

    /**
     * Libère le lecteur natif. ⚠️ SYNCHRONE quand on est déjà sur le thread principal — c'est
     * le cas d'`onDestroy`, et un `post` y différerait la libération d'un tour de boucle : le
     * temps que la nouvelle activité (re)crée son ExoPlayer, DEUX lecteurs auraient leur piste
     * audio ouverte sur le même fichier. C'est précisément l'écho entendu par Ed le 2026-07-30
     * après un « Redémarrer le player ». Le code documentait déjà cette classe de défaut pour
     * la bascule de renderer (« un ExoPlayer juste mis en PAUSE garde sa piste audio prête »).
     */
    fun release() {
        if (Looper.myLooper() == Looper.getMainLooper()) { releaseNow(); return }
        main.post { releaseNow() }
    }

    private fun releaseNow() {
        posTicking = false
        player?.release()
        player = null
    }
}
