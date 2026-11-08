package app.signflow.player

import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Typeface
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.PixelCopy
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

private const val TAG = "SignFlow/Main"
private const val LOCAL_CONTROL_PORT = 8765   // Store Control Panel LAN (§19.3)
private const val OFFLINE_POWER_GRACE_MS = 3 * 60 * 1000L  // pilote offline : > backoff reconnect

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var config: PlayerConfig
    private lateinit var bridge: SignFlowBridge

    // Rendu vidéo HW natif (ExoPlayer) hors WebView — HEVC + 4K@60 sur box Android TV.
    // TextureView sœur au-dessus de la WebView (capturable, cf. ExoController) ; activé par
    // display_config.video_renderer='exo'.
    private var videoSurface: TextureView? = null
    private var exo: ExoController? = null
    // Écran idle NATIF (sœur au-dessus de tout, GONE par défaut) : logo + message quand rien à
    // diffuser. Vue native (pas du HTML WebView) car la WebView de certaines box (Amlogic, Chromium
    // 83) cesse de composer quand rien ne bouge → le repli HTML restait invisible.
    private var idleView: View? = null
    private var idleMsgView: TextView? = null
    private lateinit var wsClient: PlayerWebSocketClient

    // OTA §XXX slice 2 : applique le bloc `update` du player:sync (télécharge l'APK, sha256, install
    // Device Owner, reboot). Lazy : `config` + `wsClient` sont prêts au 1er player:sync.
    private val otaUpdater by lazy {
        OtaUpdater(this, config) { j -> if (::wsClient.isInitialized) wsClient.send(j) }
    }
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val httpClient = OkHttpClient()
    private var appliedRotation: String? = null   // évite de re-logguer/ré-appliquer la même rotation
    private var reportedSink: String? = null       // idem pour le routage audio

    // Store Control Panel LAN (§19.3)
    private var localControlServer: LocalControlServer? = null
    private var localControlProfile: JSONObject? = null    // profil reçu dans player:sync
    @Volatile private var lastAudioStatus = JSONObject()   // état audio poussé par le renderer (cache)
    @Volatile private var lastDisplayConfig: JSONObject? = null  // dernier display_config (overlay maintenance)
    @Volatile private var lastVodMedia = JSONArray()       // médias VOD à la demande (Feature B Phase 3) — panneau LAN-local
    @Volatile private var lastVodLan: JSONObject? = null   // { secret, self_id, peers[] } — trigger VOD multi-cible LAN
    private var vodLan: VodLanController? = null            // contrôleur UDP 7779 (broadcast/réception)

    // LAN sync (§III.3)
    private var lanSync: LanSyncController? = null
    private var appliedLanConfig: String? = null               // "group|master" appliqué (recrée sur changement)
    @Volatile private var lastPlaybackPos: JSONObject? = null   // position poussée par le renderer (+reportedAt)

    // Offline-first / Local Content Store (P0→P3)
    private lateinit var contentStore: ContentStore
    // Download-then-play STRICT (anti-stream auto serveur) : `allow_streaming` (display_config) OFF
    // par défaut → jamais de streaming d'une vidéo non cachée. Nouveau contenu RETENU (downloadGate)
    // tant que toutes ses vidéos ne sont pas cachées ; le programme courant continue.
    private var allowStreaming = false
    private var downloadGate: JSONObject? = null
    private var pinnedKeys: List<String> = emptyList()          // cache_keys de la playlist courante
    private var currentFp: String? = null                       // empreinte du contenu courant (barrière LAN Q1)
    private val releasedFps = HashSet<String>()                 // empreintes déjà relâchées par la barrière
    private var fallbackReady = HashSet<String>()               // cache_keys servis satisfaits via le parent caché (repli offline)

    // Watchdog mémoire (F3) : log périodique + relance préventive si pression critique
    private val memHandler = Handler(Looper.getMainLooper())
    private var memLowTicks = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        config = PlayerConfig(this)

        Log.i(TAG, "backend effectif = ${config.backendUrl}")   // diagnostic au démarrage

        // Redirect to setup if not configured
        if (!config.isConfigured()) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        setupKioskWindow()
        config.screenResolution?.let { applyScreenResolution(it) }

        startMemoryWatchdog()   // F3 : log mémoire (~1/min) + relance si pression critique persistante

        // Local Content Store (offline-first P0) : télécharge les octets et les sert au
        // WebView en file:// (seek natif). Un média prêt → patch des items du renderer.
        contentStore = ContentStore(filesDir) { Log.i("SignFlow/Store", it) }
        contentStore.onReady = { cacheKey, url ->
            runOnUiThread {
                bridge.dispatch("store-update", JSONObject().apply {
                    put("cache_key", cacheKey); put("url", url)
                }.toString())
                // Download-then-play : un contenu retenu attend que TOUTES ses vidéos soient cachées.
                // On re-patche ses urls puis, si tout est prêt, on forwarde (bascule propre).
                downloadGate?.let { g ->
                    rewriteSyncForStore(g)
                    if (localVideosCached(g)) {
                        downloadGate = null
                        Log.i(TAG, "[DownloadGate] toutes les vidéos cachées → bascule vers le nouveau programme")
                        emitSyncToRenderer(g)
                    }
                }
            }
            updateLanReadiness()   // barrière LAN : le dernier octet peut rendre le groupe prêt
        }

        setupWebView()
        registerWatchdog()

        // Proof of Play (§XXIV) : reprend la file persistée + flush périodique best-effort (60s).
        loadPopQueue()
        scope.launch { while (true) { delay(60_000); flushPopQueue() } }
    }

    private fun setupKioskWindow() {
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
        )
    }

    private fun setupWebView() {
        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true           // localStorage support
                allowFileAccess = true             // offline-first : <video src=file://content_store/...>
                // ⚠️ NE PAS désactiver ces 2 flags sans WebViewAssetLoader (REGRESSION AUDIO prouvée HW
                // 2026-06-30 : plus de son sur le MINIX). Le renderer ne fait aucun fetch/XHR (pont natif),
                // MAIS audio_player.js (ducking §XIX.5) route le son contenu+musique via la Web Audio API
                // (AudioContext.createMediaElementSource). Avec ces flags à false, les médias file://
                // deviennent CORS-tainted → la Web Audio SILENCE la sortie (el.crossOrigin='anonymous' ne
                // suffit pas, file:// ne sert pas de CORS). Le vrai durcissement XSS = servir le renderer
                // sous une vraie origine via WebViewAssetLoader (https://appassets…) → file:// disparaît.
                allowFileAccessFromFileURLs = true
                allowUniversalAccessFromFileURLs = true
                mediaPlaybackRequiresUserGesture = false   // autoplay video/audio
                cacheMode = WebSettings.LOAD_DEFAULT
                mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                useWideViewPort = true
                loadWithOverviewMode = true
            }
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            setBackgroundColor(0xFF1C1E2A.toInt())
        }

        bridge = SignFlowBridge(webView) { action, params ->
            handleNativeCall(action, params)
        }
        webView.addJavascriptInterface(bridge, "Android")

        // Pilote auto-power offline : tick minute permanent (lit lastDisplayConfig à chaque
        // tick, n'agit que WS down > grace — cf. offlinePowerTick).
        offlinePowerHandler.postDelayed(offlinePowerRunnable, 60_000L)

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                Log.i(TAG, "WebView loaded — applying cached config + connecting WebSocket")
                // Boot offline : rejoue le display_config persisté (sync LAN, audio, écran, contrôle
                // local) AVANT la connexion → la sync LAN inter-players démarre sans attendre un
                // sync serveur. Idempotent : le sync live reconfirme (manageLanSync no-op si inchangé).
                loadDisplayConfig()?.let { applyDisplayConfig(it) }
                connectWebSocket()
            }

            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError,
            ) {
                Log.e(TAG, "WebView error: ${error.description} @ ${request.url}")
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                Log.d("SignFlow/JS", "${message.message()} [${message.sourceId()}:${message.lineNumber()}]")
                return true
            }
        }

        // Racine = FrameLayout : WebView (fond, tout le contenu non-vidéo + overlay) + TextureView
        // ExoPlayer (sœur, ajoutée APRÈS la WebView → dessinée par-dessus, GONE par défaut) pour
        // la vidéo native. TextureView (pas SurfaceView) → capturable pour la vignette CMS.
        val root = FrameLayout(this)
        val fill = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT,
        )
        root.addView(webView, fill)
        val tex = TextureView(this)
        root.addView(tex, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT,
        ))
        videoSurface = tex
        exo = ExoController(this, tex, bridge)   // GONE posé dans son init

        // Écran idle NATIF, ajouté EN DERNIER (donc au-dessus de la WebView et de la TextureView),
        // GONE par défaut. Affiché par la commande 'idle_show' quand le player n'a rien à diffuser.
        val idle = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#1C1E2A"))
            visibility = View.GONE
        }
        val logoTv = TextView(this).apply {
            text = "SignFlow"
            setTextColor(Color.parseColor("#4875B4"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 40f)
            typeface = Typeface.create(typeface, Typeface.BOLD)
            letterSpacing = 0.12f
            gravity = Gravity.CENTER   // les enfants d'un LinearLayout vertical font toute la largeur → centrer le texte
        }
        val msgTv = TextView(this).apply {
            text = "No content to display"
            setTextColor(Color.parseColor("#66778A"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            gravity = Gravity.CENTER
            setPadding(0, 24, 0, 0)
        }
        idle.addView(logoTv)
        idle.addView(msgTv)
        root.addView(idle, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT,
        ))
        idleView = idle
        idleMsgView = msgTv

        setContentView(root)

        // Re-cale la rotation quand le conteneur change de TAILLE (= changement de résolution /
        // mode d'affichage, qui redimensionne la vue de façon asynchrone). Sans ça, une rotation
        // portrait active garderait le dimensionnement de l'ancienne résolution (barre noire).
        // La transform du WebView ne change PAS la taille du parent → pas de ré-entrée en boucle.
        (webView.parent as? View)?.addOnLayoutChangeListener { _, l, t, r, b, ol, ot, oR, ob ->
            if ((r - l) != (oR - ol) || (b - t) != (ob - ot)) {
                webView.post { relayoutRotation() }
            }
        }

        webView.loadUrl("file:///android_asset/player/index.html")
    }

    private fun connectWebSocket() {
        wsClient = PlayerWebSocketClient(
            context = this,
            config = config,
            onConnected = {
                // Le serveur reprend le pilotage écran (re-assertion via reset last_power_state
                // au connect) → le pilote offline s'efface et oublie son dernier état appliqué.
                wsDownSince = null
                offlineAppliedPower = null
                bridge.dispatch("connected")
            },
            onDisconnected = {
                if (wsDownSince == null) wsDownSince = System.currentTimeMillis()
                bridge.dispatch("disconnected")
            },
            onMessage = { msg -> handleServerMessage(msg) },
            onSetupRequired = {
                Log.w(TAG, "Setup required — redirecting to SetupActivity")
                config.clear()
                runOnUiThread {
                    startActivity(Intent(this, SetupActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                    finish()
                }
            },
            storeStatus = { if (::contentStore.isInitialized) contentStore.getStorageStatus() else null },
        )
        wsClient.connect()
    }

    // Toutes les VIDÉOS du payload sont-elles en cache local ? (contentStore.verify = source de
    // vérité). Non-vidéos ignorées : le gate ne porte QUE sur les vidéos.
    private fun localVideosCached(msg: JSONObject): Boolean {
        val items = msg.optJSONArray("items") ?: return true
        for (i in 0 until items.length()) {
            val m = items.optJSONObject(i)?.optJSONObject("media") ?: continue
            if (m.optString("media_type") != "video") continue
            val ck = m.optString("cache_key").takeIf { it.isNotEmpty() } ?: return false
            var cached = contentStore.verify(contentStore.keyFor(ck))
            if (!cached) {
                m.optString("cache_key_fallback").takeIf { it.isNotEmpty() }?.let { fb ->
                    cached = contentStore.verify(contentStore.keyFor(fb))
                }
            }
            if (!cached) return false
        }
        return true
    }
    private fun downloadGateActive(msg: JSONObject): Boolean {
        val items = msg.optJSONArray("items")
        return !allowStreaming && items != null && items.length() > 0 && !localVideosCached(msg)
    }
    private fun emitSyncToRenderer(msg: JSONObject) {
        // Barrière LAN (Q1) : si l'empreinte courante n'est pas relâchée (groupe pas prêt), le
        // renderer HOLD le démarrage (le contenu en cours continue). Anti-gel = timeout côté LAN.
        val fp = currentFp
        if (lanSync != null && fp != null && !releasedFps.contains(fp)) {
            msg.put("lan_hold", true)
        }
        bridge.dispatch("sync", msg.toString())
    }

    private fun handleServerMessage(msg: JSONObject) {
        when (msg.optString("type")) {
            "player:sync" -> {
                // Store local (offline-first P0) : bascule les médias cachés sur file://
                // et met en file les manquants — AVANT de forwarder le payload au renderer.
                rewriteSyncForStore(msg)
                msg.optJSONObject("display_config")?.let { dc ->
                    saveDisplayConfig(dc)      // persiste pour le rejeu au boot offline (LAN sync, audio, écran…)
                    applyDisplayConfig(dc)
                }
                // Profil de contrôle local (token + permissions). Présent dans player:sync
                // seulement si local_control_enabled ; peut être null (JSON null) si révoqué/expiré.
                if (msg.has("local_control")) {
                    localControlProfile = msg.optJSONObject("local_control")
                }
                // Médias VOD à la demande (Feature B Phase 3) — exposés au panneau LAN-local.
                msg.optJSONArray("vod_media")?.let { lastVodMedia = it }
                // Trigger VOD multi-cible LAN (secret partagé + pairs) — pilote le contrôleur UDP 7779.
                if (msg.has("vod_lan")) {
                    lastVodLan = msg.optJSONObject("vod_lan")
                    manageVodLan()
                }
                // OTA §XXX slice 2 : directive de mise à jour (indépendante du download gate ci-dessous).
                otaUpdater.handleDirective(msg.optJSONObject("update"))
                // Download-then-play STRICT (anti-stream auto) : tant que TOUTES les vidéos du
                // nouveau contenu ne sont pas en cache local, on RETIENT le sync — le renderer garde
                // le programme courant (ou l'idle). contentStore.onReady forwarde quand tout est prêt.
                if (downloadGateActive(msg)) {
                    downloadGate = msg
                    Log.i(TAG, "[DownloadGate] nouveau contenu retenu (vidéo non cachée, no-stream) — garde le programme courant")
                    return
                }
                downloadGate = null
                emitSyncToRenderer(msg)
            }
            "player:command" -> {
                val command = msg.optString("command")
                val params = msg.optJSONObject("params") ?: JSONObject()
                handleCommand(command, params)
            }
            "player:purge_media" -> {
                // Kill-switch (§ Q5) : suppression réelle des octets du store local.
                val removed = contentStore.purgeMedia(msg.optInt("id_media"))
                Log.i(TAG, "[Purge] store: $removed fichier(s) supprimé(s) pour média ${msg.optInt("id_media")}")
            }
            "token:refresh" -> {
                // Rotation du token machine (« Option B » serveur) : token renouvelé → on le
                // persiste (EncryptedSharedPreferences). La connexion WS courante reste valide ;
                // le nouveau token sert au prochain reconnect ET aux requêtes HTTP. Aucune coupure.
                val newTok = msg.optString("token")
                if (newTok.isNotBlank() && newTok != config.playerToken) {
                    config.playerToken = newTok
                    Log.i(TAG, "[Token] renouvelé par le serveur et persisté")
                }
            }
            else -> Log.d(TAG, "Unknown message type: ${msg.optString("type")}")
        }
    }

    /**
     * Réécrit le payload player:sync pour servir depuis le store local (file://) TOUT le
     * contenu cachable déjà présent (vidéo, image ET audio des paniers §XIX), et met en file
     * ce qui manque. Non caché = URL MinIO conservée → repli streaming. L'empreinte barrière
     * LAN (currentFp) ne couvre que le VISUEL ; l'audio est épinglé mais ne bloque pas.
     */
    private val displayConfigFile get() = File(filesDir, "display_config.json")

    /** Persiste le display_config sur disque pour le rejeu au boot offline. */
    private fun saveDisplayConfig(dc: JSONObject) {
        try { displayConfigFile.writeText(dc.toString()) }
        catch (e: Exception) { Log.e(TAG, "saveDisplayConfig failed: ${e.message}") }
    }

    /** Recharge le display_config persisté (null si absent/illisible). */
    private fun loadDisplayConfig(): JSONObject? {
        return try {
            if (displayConfigFile.exists()) JSONObject(displayConfigFile.readText()) else null
        } catch (e: Exception) { null }
    }

    /**
     * Applique un display_config — live (handler player:sync) OU rejoué au boot depuis le cache
     * offline. Extrait pour que la sync LAN, le routage audio, l'écran et le Store Control Panel
     * démarrent dès le boot SANS serveur : sinon `manageLanSync` n'était appelé qu'à l'arrivée
     * d'un sync live (= retour serveur) → les players jouaient le même contenu mais ne se
     * synchronisaient pas en LAN tant que le serveur était coupé.
     */
    private fun applyDisplayConfig(dc: JSONObject) {
        lastDisplayConfig = dc  // overlay de maintenance
        // QoS download (Q3) + look-ahead (Phase 2) : plafond de bande passante, fenêtres
        // horaires de prefetch et mesure passive du débit, par player.
        val windows = ArrayList<Pair<String, String>>()
        dc.optJSONArray("download_windows")?.let { wa ->
            for (i in 0 until wa.length()) {
                val w = wa.optJSONObject(i) ?: continue
                val s = w.optString("start"); val e = w.optString("end")
                if (s.isNotEmpty() && e.isNotEmpty()) windows.add(s to e)
            }
        }
        contentStore.setPolicy(
            dc.optInt("download_bandwidth_kbps", 0),
            windows,
            dc.optBoolean("measure_bandwidth", false),
        )
        allowStreaming = dc.optBoolean("allow_streaming", false)  // download-then-play strict par défaut
        popSignEnabled = dc.optBoolean("pop_sign", false)  // P2 : active la signature Ed25519 des preuves
        dc.optString("screen_resolution").takeIf { it.isNotEmpty() }?.let { resolution ->
            config.screenResolution = resolution
            runOnUiThread { applyScreenResolution(resolution) }
        }
        dc.optString("screen_rotation").takeIf { it.isNotEmpty() }?.let { rotation ->
            runOnUiThread { applyScreenRotation(rotation) }
        }
        dc.optString("audio_basket_output").takeIf { it.isNotEmpty() }?.let { role ->
            applyAudioSink(role)
        }
        // Store Control Panel : démarre/arrête le serveur LAN selon le flag serveur.
        runOnUiThread { manageLocalControl(dc) }
        // LAN sync inter-players : démarre/arrête selon display_config (pair-à-pair, sans serveur).
        manageLanSync(dc)
    }

    private fun rewriteSyncForStore(msg: JSONObject) {
        val pinned = ArrayList<String>()   // vidéo + image + audio → épinglé (jamais évincé)
        val fpKeys = ArrayList<String>()   // barrière LAN = visuel seulement
        fallbackReady = HashSet()          // recalculé à chaque sync (repli parent → prêt)

        // Bascule une « media-like » JSON sur le store local si cachée, sinon la met en file.
        fun handle(m: JSONObject, isVisual: Boolean) {
            val cacheKey = m.optString("cache_key").ifEmpty { null } ?: return
            val url = m.optString("url").ifEmpty { null } ?: return   // URL d'origine (MinIO) = source DL
            pinned.add(cacheKey)
            if (isVisual) fpKeys.add(cacheKey)
            val filekey = contentStore.keyFor(cacheKey)
            if (contentStore.verify(filekey)) {   // garde runtime : fichier réellement présent + intègre
                m.put("url", contentStore.localUrl(filekey))
                contentStore.markUsed(filekey)
                return
            }
            // Variante servie pas (encore) en cache. Repli : si un parent de repli est caché
            // (ex. 4K d'une config antérieure), le jouer plutôt qu'un écran noir (serveur down
            // + variante non téléchargée). On met quand même la variante en file.
            val fbKey = m.optString("cache_key_fallback").ifEmpty { null }
            if (fbKey != null) {
                val fbFile = contentStore.keyFor(fbKey)
                if (contentStore.verify(fbFile)) {
                    m.put("url", contentStore.localUrl(fbFile))
                    contentStore.markUsed(fbFile)
                    fallbackReady.add(cacheKey)   // compte comme prêt pour la barrière LAN
                }
            }
            contentStore.enqueue(
                cacheKey,
                m.optString("cache_checksum").ifEmpty { null },
                m.optString("mime_type").ifEmpty { null },
                url,
                m.optInt("id_media"),
            )
        }

        // Traite le média d'un item : vidéo/image → cache direct ; feed_display → vignettes.
        fun handleItem(item: JSONObject, isVisual: Boolean) {
            val media = item.optJSONObject("media") ?: return
            val t = media.optString("media_type")
            if (t == "video" || t == "image") handle(media, isVisual)
            // Feed Display : cache offline-first des vignettes re-hébergées (image_cache_key) →
            // bascule image_url sur file:// si cachée (HORS empreinte LAN).
            else if (t == "feed_display") {
                val fitems = media.optJSONObject("feed_config")?.optJSONArray("items")
                if (fitems != null) for (j in 0 until fitems.length()) {
                    val fi = fitems.optJSONObject(j) ?: continue
                    val ick = fi.optString("image_cache_key").ifEmpty { null } ?: continue
                    val iurl = fi.optString("image_url").ifEmpty { null } ?: continue
                    val proxy = JSONObject()
                        .put("cache_key", ick).put("url", iurl)
                        .put("mime_type", "image/jpeg").put("id_media", media.optInt("id_media"))
                    handle(proxy, false)
                    fi.put("image_url", proxy.optString("url"))
                }
            }
        }

        val items = msg.optJSONArray("items")
        if (items != null) for (i in 0 until items.length()) {
            items.optJSONObject(i)?.let { handleItem(it, true) }
        }
        // §25.4 multi-zones : patcher AUSSI les items du bloc template. Après parsing JSON ce sont
        // des objets DISTINCTS de msg.items, et le renderer multi-zones lit template.zones[].items
        // (pas msg.items) → sans ça une zone vidéo déjà cachée garde l'URL MinIO et streame (écran
        // noir serveur coupé). Même cache_key que msg.items (déjà épinglé/enfilé) → isVisual=false :
        // la barrière LAN reste pilotée par msg.items, le multi-zones a son propre moteur de sync.
        val tzones = msg.optJSONObject("template")?.optJSONArray("zones")
        if (tzones != null) for (i in 0 until tzones.length()) {
            val zitems = tzones.optJSONObject(i)?.optJSONArray("items") ?: continue
            for (j in 0 until zitems.length()) zitems.optJSONObject(j)?.let { handleItem(it, false) }
        }
        val baskets = msg.optJSONArray("audio_baskets")
        if (baskets != null) for (i in 0 until baskets.length()) {
            val its = baskets.optJSONObject(i)?.optJSONArray("items") ?: continue
            for (j in 0 until its.length()) its.optJSONObject(j)?.let { handle(it, false) }
        }
        // VOD à la demande (Feature B) : pré-cache des médias VOD (variante navigateur-safe) — pin +
        // enqueue, HORS empreinte LAN → lecture instantanée locale au déclenchement cloud/LAN-local.
        val vod = msg.optJSONArray("vod_media")
        if (vod != null) for (i in 0 until vod.length()) vod.optJSONObject(i)?.let { handle(it, false) }

        contentStore.setPinned(pinned)   // épingle (vidéo+image+audio) + évince si disque tendu
        // Look-ahead (Phase 1) : pré-télécharge le contenu programmé futur (priorisé par date de
        // diffusion). Appelé APRÈS setPinned/enqueue de la playlist courante → les items courants
        // restent non-prefetch (téléchargés en priorité, hors fenêtre).
        contentStore.setPrefetch(msg.optJSONArray("prefetch"))
        pinnedKeys = fpKeys              // barrière LAN = visuel uniquement (l'audio ne bloque pas)
        currentFp = if (fpKeys.isEmpty()) null else sha1(fpKeys.sorted().joinToString("|"))
        updateLanReadiness()
    }

    /** Déclare au LAN si j'ai TOUT le contenu de l'empreinte courante en cache. */
    private fun updateLanReadiness() {
        val sync = lanSync ?: return
        val ready = pinnedKeys.all { contentStore.verify(contentStore.keyFor(it)) || fallbackReady.contains(it) }
        sync.setReadiness(currentFp, ready)
    }

    private fun sha1(s: String): String {
        val md = MessageDigest.getInstance("SHA-1")
        return md.digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    /**
     * Request a specific display mode via WindowManager.preferredDisplayModeId (API 23+).
     * Finds the first supported mode matching "WxH@Hz" (Hz optional).
     * Must be called on the UI thread.
     */
    @Suppress("DEPRECATION")
    private fun applyScreenResolution(resolution: String) {
        try {
            val atIdx = resolution.indexOf('@')
            val dims = if (atIdx >= 0) resolution.substring(0, atIdx) else resolution
            val hz = if (atIdx >= 0) resolution.substring(atIdx + 1).toFloatOrNull() else null
            val (w, h) = dims.split("x").let {
                (it.getOrNull(0)?.toIntOrNull() ?: return) to (it.getOrNull(1)?.toIntOrNull() ?: return)
            }
            val modes = windowManager.defaultDisplay.supportedModes
            // Correspondance exacte (dim + Hz) ; sinon repli sur la dimension seule (le Hz
            // demandé peut ne pas exister — ex. 4K@30 demandé alors que la box n'a que 4K@59).
            val match = modes.firstOrNull { m ->
                m.physicalWidth == w && m.physicalHeight == h &&
                    (hz == null || kotlin.math.abs(m.refreshRate - hz) < 1f)
            } ?: modes.firstOrNull { m -> m.physicalWidth == w && m.physicalHeight == h }
            if (match != null) {
                window.attributes = window.attributes.also { it.preferredDisplayModeId = match.modeId }
                Log.i(TAG, "[Resolution] $resolution applied (mode ${match.modeId})")
            } else {
                Log.w(TAG, "[Resolution] No mode for $resolution — available: ${modes.map { "${it.physicalWidth}x${it.physicalHeight}@${it.refreshRate.toInt()}" }}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "[Resolution] Error: ${e.message}")
        }
    }

    /**
     * Rotation d'écran pilotée depuis le CMS (display_config.screen_rotation).
     *
     * IMPORTANT — box Android TV : `setRequestedOrientation` est IGNORÉ par le compositeur
     * (la sortie HDMI reste verrouillée en paysage 1920x1080 par le système, validé sur le
     * MINIX : orientation changeait mais SurfaceUtils restait "rotation 0"). On rote donc la
     * VUE WebView elle-même (transform `rotation` + swap des dimensions de layout pour le
     * portrait), ce qui fonctionne quel que soit le verrou d'orientation de l'écran TV.
     * Convention serveur : normal=0°, right=90° horaire, inverted=180°, left=270° (=90° anti-horaire).
     * Doit tourner sur le thread UI.
     */
    private fun applyScreenRotation(rotation: String) {
        if (rotation !in setOf("normal", "right", "inverted", "left")) {
            Log.w(TAG, "[Rotation] valeur inconnue: $rotation")
            return
        }
        if (rotation == appliedRotation) return
        appliedRotation = rotation
        relayoutRotation()
        Log.i(TAG, "[Rotation] $rotation appliquée")
    }

    /**
     * (Re)applique la transform de rotation au WebView en se basant sur la taille COURANTE
     * du conteneur. Appelé sur changement de rotation ET sur changement de taille du parent
     * (= changement de résolution/mode d'affichage, via l'OnLayoutChangeListener) afin que la
     * rotation reste correctement dimensionnée/centrée quelle que soit la résolution.
     * Idempotent. Doit tourner sur le thread UI.
     */
    private fun relayoutRotation() {
        val angle = when (appliedRotation) {
            "right"    -> 90f
            "inverted" -> 180f
            "left"     -> 270f
            else       -> 0f   // normal / non défini
        }
        // Dimensions de la ZONE DE CONTENU réelle (le parent du WebView), pas displayMetrics
        // (qui rapportait 3840x2048 sur le MINIX = espace de vue désaligné de la surface réelle
        // 3840x2160 → barre noire sur un bord). Fallback displayMetrics si pas encore layouté.
        val parent = webView.parent as? View
        val sw = parent?.width?.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        val sh = parent?.height?.takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
        val portrait = angle == 90f || angle == 270f
        // ⚠️ LES TROIS COUCHES PLEIN ÉCRAN, pas seulement la WebView. La FrameLayout racine
        // superpose WebView (HTML) + TextureView (vidéo ExoPlayer) + écran idle natif : ne roter
        // que la première laissait la vidéo `video_renderer=exo` et le « No content to display »
        // en paysage sur un écran configuré en portrait (constat d'Ed 2026-08-14 — il pensait
        // que l'absence de rotation sous ExoPlayer était normale, elle ne l'est pas).
        // ⛔ On rote les ENFANTS et jamais la racine : l'OnLayoutChangeListener écoute la taille
        // de la racine, la roter changerait sa taille → ré-entrée en boucle.
        for (v in listOfNotNull<View>(webView, videoSurface, idleView)) {
            val lp = v.layoutParams ?: continue
            if (portrait) {
                // La vue est mise en layout "portrait" (sh × sw) puis rotée de 90°/270° pour
                // remplir l'écran paysage (sw × sh). Translation = recentrage sur le centre écran.
                lp.width = sh
                lp.height = sw
            } else {
                lp.width = ViewGroup.LayoutParams.MATCH_PARENT
                lp.height = ViewGroup.LayoutParams.MATCH_PARENT
            }
            v.layoutParams = lp
            v.rotation = angle
            v.translationX = if (portrait) (sw - sh) / 2f else 0f
            v.translationY = if (portrait) (sh - sw) / 2f else 0f
            v.requestLayout()
        }
    }

    /**
     * Routage de la sortie audio par rôle (display_config.audio_basket_output : hdmi/jack/usb).
     * Équivalent Android de applyAudioSink (wpctl/pactl) côté player-linux.
     *
     * LIMITE ANDROID assumée : avant API 31, il n'existe AUCUNE API publique pour forcer le
     * périphérique de sortie MÉDIA d'une app (le WebView lit via le stack média système, qui
     * route selon sa propre priorité : USB/jack filaire > HDMI > HP intégré dès qu'ils sont
     * branchés). Sur une box de signage (MINIX, Android 11 = API 30) le son part donc en HDMI
     * vers la TV par défaut, et brancher un jack/USB bascule automatiquement. Cette fonction
     * DÉTECTE et REMONTE l'état réel (device présent ou non pour le rôle demandé) sans prétendre
     * forcer ce que l'OS ne permet pas. Sur API 31+, on tente en plus setCommunicationDevice
     * (n'affecte toutefois que l'audio de communication, pas le média — best-effort/log).
     */
    private fun applyAudioSink(role: String) {
        if (role == "auto" || role == reportedSink) return
        try {
            val am = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val outputs = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            val wanted: (Int) -> Boolean = { type ->
                when (role) {
                    "hdmi" -> type == AudioDeviceInfo.TYPE_HDMI || type == AudioDeviceInfo.TYPE_HDMI_ARC
                    "usb"  -> type == AudioDeviceInfo.TYPE_USB_DEVICE ||
                              type == AudioDeviceInfo.TYPE_USB_HEADSET ||
                              type == AudioDeviceInfo.TYPE_USB_ACCESSORY
                    "jack" -> type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES ||
                              type == AudioDeviceInfo.TYPE_WIRED_HEADSET ||
                              type == AudioDeviceInfo.TYPE_AUX_LINE
                    else   -> false
                }
            }
            val match = outputs.firstOrNull { wanted(it.type) }
            val available = outputs.joinToString(" | ") { "${it.productName}(type=${it.type})" }
            if (match == null) {
                Log.w(TAG, "[AudioSink] aucune sortie pour role=$role (dispo: $available)")
            } else {
                Log.i(TAG, "[AudioSink] sortie role=$role présente: ${match.productName} (type=${match.type})")
                // best-effort API 31+ (n'affecte que l'audio de communication, pas le média WebView)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    try {
                        am.setCommunicationDevice(match)
                        Log.i(TAG, "[AudioSink] setCommunicationDevice tenté (API ${Build.VERSION.SDK_INT})")
                    } catch (e: Exception) {
                        Log.w(TAG, "[AudioSink] setCommunicationDevice échec: ${e.message}")
                    }
                } else {
                    Log.i(TAG, "[AudioSink] API ${Build.VERSION.SDK_INT} < 31 → routage média non forçable par l'app (l'OS priorise USB/jack > HDMI auto)")
                }
            }
            reportedSink = role
        } catch (e: Exception) {
            Log.e(TAG, "[AudioSink] erreur: ${e.message}")
        }
    }

    private fun handleCommand(command: String, params: JSONObject) {
        Log.d(TAG, "Command: $command")
        when (command) {
            "restart" -> restartApp()
            "reboot_os" -> rebootOs()
            "reset_config" -> resetConfig()
            "quit_app" -> finishAndRemoveTask()
            "maintenance" -> bridge.dispatch("maintenance", params.toString())
            "screenshot" -> captureScreenshot(params.optString("request_id").ifEmpty { null })
            "toggle_overlay" -> bridge.dispatch("overlay", buildOverlayInfo().toString())
            "play_now" -> handlePlayNow(params)
            "display_command" -> handleDisplayCommand(params)
            "set_timezone" -> handleSetTimezone(params)
            else -> Log.w(TAG, "Unknown command: $command")
        }
    }

    /** Contrôle écran via display_command. Android ne pilote pas de RS232/IP, et le CEC
     *  direct exige la permission système HDMI_CEC (réservée aux apps signées constructeur)
     *  → impossible ici. Repli « écran non pilotable » (display_config.output_power_fallback) :
     *   - power_off : veille de l'appareil (Device Owner lockNow) → la box coupe sa sortie
     *     HDMI ; un wakelock PARTIEL garde le CPU + WebSocket en vie pour recevoir le
     *     power_on. Bonus : si le CEC est activé dans les réglages de la box, la mise en
     *     veille propage souvent un standby CEC vers la TV.
     *   - power_on : réveil (wakelock ACQUIRE_CAUSES_WAKEUP + turnScreenOn + dismissKeyguard). */
    private var outputOffWakeLock: android.os.PowerManager.WakeLock? = null
    // ⚠️ Le wakelock PARTIEL garde le CPU mais PAS le réseau : constaté HW MINIX 2026-07-07,
    // le Wi-Fi s'endort avec l'écran → box injoignable pendant la coupure (WS morte, pas de
    // commandes/OTA ; le pilote offline compensait le réveil, mais avec ~2 min de retard).
    // WifiLock HIGH_PERF tenu pendant la veille → Wi-Fi actif écran éteint. Sans effet sur
    // les box Ethernet (lock inoffensif).
    @Suppress("DEPRECATION")  // WIFI_MODE_FULL_HIGH_PERF déprécié API 34, cible des box API 28+
    private var outputOffWifiLock: android.net.wifi.WifiManager.WifiLock? = null

    private fun handleDisplayCommand(params: JSONObject) {
        when (val cmd = params.optString("display_cmd")) {
            "power_off" -> runOnUiThread { videoOutputOff() }
            "power_on" -> runOnUiThread { videoOutputOn() }
            else -> Log.w(TAG, "display_command '$cmd' non supporté sur Android (pas de RS232/IP/CEC)")
        }
    }

    @Suppress("WakelockTimeout")
    private fun videoOutputOff() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
            if (outputOffWakeLock == null) {
                outputOffWakeLock = pm.newWakeLock(
                    android.os.PowerManager.PARTIAL_WAKE_LOCK, "signflow:outputOff")
            }
            if (outputOffWakeLock?.isHeld != true) outputOffWakeLock?.acquire()
            // Réseau vivant pendant la veille (cf. déclaration outputOffWifiLock).
            try {
                @Suppress("DEPRECATION")
                if (outputOffWifiLock == null) {
                    val wm = applicationContext.getSystemService(Context.WIFI_SERVICE)
                        as android.net.wifi.WifiManager
                    outputOffWifiLock = wm.createWifiLock(
                        android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF, "signflow:outputOffWifi")
                }
                if (outputOffWifiLock?.isHeld != true) outputOffWifiLock?.acquire()
            } catch (e: Exception) {
                Log.w(TAG, "[Display] WifiLock: ${e.message}")
            }
            // FLAG_KEEP_SCREEN_ON empêcherait la veille → retiré le temps de l'extinction.
            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            // ⚠️ FIX FLIP-FLOP (constaté MINIX) : videoOutputOn pose setTurnScreenOn(true) et
            // ne le retirait jamais → après lockNow, l'Activity visible RE-RÉVEILLAIT l'écran,
            // puis le timeout système (plus de KEEP_SCREEN_ON) le rendormait → cycle
            // allumé/éteint en continu. On désarme turnScreenOn/showWhenLocked AVANT la veille.
            if (Build.VERSION.SDK_INT >= 27) {
                setTurnScreenOn(false)
                setShowWhenLocked(false)
            }
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (dpm.isDeviceOwnerApp(packageName)) {
                dpm.lockNow()
                Log.i(TAG, "[Display] video output OFF (lockNow, wakelock partiel actif)")
            } else {
                Log.w(TAG, "[Display] power_off: pas Device Owner → l'écran s'éteindra au " +
                        "timeout système (FLAG_KEEP_SCREEN_ON retiré)")
            }
        } catch (e: Exception) {
            Log.e(TAG, "[Display] power_off: ${e.message}")
        }
    }

    @Suppress("DEPRECATION")
    private fun videoOutputOn() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
            // FULL_WAKE_LOCK + ACQUIRE_CAUSES_WAKEUP : déprécié mais c'est le seul réveil
            // programmable sans permission système ; relâché aussitôt (3 s), puis
            // FLAG_KEEP_SCREEN_ON reprend le maintien.
            val wl = pm.newWakeLock(
                android.os.PowerManager.FULL_WAKE_LOCK
                    or android.os.PowerManager.ACQUIRE_CAUSES_WAKEUP
                    or android.os.PowerManager.ON_AFTER_RELEASE, "signflow:outputOn")
            wl.acquire(3000)
            if (Build.VERSION.SDK_INT >= 27) {
                setTurnScreenOn(true)
                setShowWhenLocked(true)
                (getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager)
                    .requestDismissKeyguard(this, null)
            }
            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            outputOffWakeLock?.takeIf { it.isHeld }?.release()
            try { outputOffWifiLock?.takeIf { it.isHeld }?.release() } catch (_: Exception) {}
            // Reprendre le PREMIER PLAN : si une autre app (Paramètres…) était au-dessus au
            // moment de la veille, le réveil la laisse devant la vidéo (constaté HW MINIX
            // 2026-07-07). REORDER_TO_FRONT ramène le kiosk sans recréer l'Activity.
            try {
                startActivity(Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP))
            } catch (e: Exception) {
                Log.w(TAG, "[Display] bring-to-front: ${e.message}")
            }
            Log.i(TAG, "[Display] video output ON (wake)")
        } catch (e: Exception) {
            Log.e(TAG, "[Display] power_on: ${e.message}")
        }
    }

    // ── Pilote auto-power OFFLINE (autonomie sans serveur) ─────────────────────
    // Fenêtres d'allumage pré-calculées par le serveur (display_config.offline_power,
    // persisté → rejouées au boot) : si la WS est down depuis > grace, le player pilote
    // SEUL sa veille/réveil. Online, le serveur reste la source de vérité (worker
    // apply_site_power + re-assertion à la reconnexion). Le tick survit à la veille :
    // le wakelock PARTIEL posé par videoOutputOff garde le CPU (et ce Handler) vivants.
    @Volatile private var wsDownSince: Long? = System.currentTimeMillis()  // boot = « down »
    @Volatile private var offlineAppliedPower: Boolean? = null
    private val offlinePowerHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val offlinePowerRunnable = object : Runnable {
        override fun run() {
            try { offlinePowerTick() } catch (e: Exception) { Log.w(TAG, "[Power] offline tick: ${e.message}") }
            offlinePowerHandler.postDelayed(this, 60_000L)
        }
    }

    private fun offlinePowerTick() {
        if (::wsClient.isInitialized && wsClient.isConnected) return  // online = serveur seul pilote
        val down = wsDownSince ?: return
        if (System.currentTimeMillis() - down < OFFLINE_POWER_GRACE_MS) return
        val op = lastDisplayConfig?.optJSONObject("offline_power") ?: return
        val desired = offlineDesiredPower(op) ?: return
        if (desired == offlineAppliedPower) return
        val downMin = (System.currentTimeMillis() - down) / 60_000L
        Log.i(TAG, "[Power] Offline pilot: ${if (desired) "power_on" else "power_off"} (no server for $downMin min)")
        runOnUiThread { if (desired) videoOutputOn() else videoOutputOff() }
        offlineAppliedPower = desired
    }

    /** État voulu d'après offline_power = {mode, intervals:[["yyyy-MM-ddTHH:mm:ss", …]]}.
     *  Datetimes SANS timezone = heure LOCALE du device (hypothèse : TZ device = TZ site,
     *  d'où le mismatch remonté dans capabilities.timezone). Horizon serveur 14 j ; au-delà
     *  on projette le motif hebdomadaire en reculant de k×7 jours. null = ne pas piloter. */
    private fun offlineDesiredPower(op: JSONObject): Boolean? {
        when (op.optString("mode")) {
            "manual" -> return null
            "always_on" -> return true
        }
        val iv = op.optJSONArray("intervals") ?: return false
        if (iv.length() == 0) return false
        val fmt = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
        fun parse(s: String): Long? = try { fmt.parse(s)?.time } catch (_: Exception) { null }
        var t = System.currentTimeMillis()
        val lastPair = iv.optJSONArray(iv.length() - 1)
        val lastEnd = lastPair?.optString(1)?.let { parse(it) }
        if (lastEnd != null && t > lastEnd) {
            val week = 7L * 24 * 3600 * 1000
            t -= Math.ceil((t - lastEnd).toDouble() / week).toLong() * week
        }
        for (i in 0 until iv.length()) {
            val pair = iv.optJSONArray(i) ?: continue
            val a = parse(pair.optString(0)) ?: continue
            val b = parse(pair.optString(1)) ?: continue
            if (t in a until b) return true
        }
        return false
    }

    /** Change le fuseau OS (Device Owner, API 28+) puis relance l'app — les formatteurs
     *  et le wall-clock local repartent proprement sur le nouveau fuseau. */
    private fun handleSetTimezone(params: JSONObject) {
        val tz = params.optString("timezone")
        if (tz.isEmpty() || !java.util.TimeZone.getAvailableIDs().contains(tz)) {
            Log.e(TAG, "[TZ] invalid timezone: $tz"); return
        }
        try {
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (Build.VERSION.SDK_INT >= 28 && dpm.isDeviceOwnerApp(packageName)) {
                val admin = ComponentName(this, SignFlowAdminReceiver::class.java)
                // ⚠️ AUTO_TIME_ZONE actif → dpm.setTimeZone est un NO-OP qui retourne false
                // (constaté HW MINIX 2026-07-07 : auto_time_zone=1 d'usine → commande sans
                // effet visible). Device Owner → on coupe l'auto d'abord : TZ pilotée CMS.
                try {
                    dpm.setGlobalSetting(admin, android.provider.Settings.Global.AUTO_TIME_ZONE, "0")
                } catch (e: Exception) {
                    Log.w(TAG, "[TZ] disable AUTO_TIME_ZONE failed: ${e.message}")
                }
                val ok = dpm.setTimeZone(admin, tz)
                if (ok) {
                    Log.i(TAG, "[TZ] system timezone set to $tz — restarting app")
                    restartApp()
                } else {
                    Log.e(TAG, "[TZ] dpm.setTimeZone($tz) refused (auto time zone still on?)")
                }
            } else {
                Log.w(TAG, "[TZ] set_timezone requires Device Owner + API 28 (got DO=${dpm.isDeviceOwnerApp(packageName)}, API=${Build.VERSION.SDK_INT})")
            }
        } catch (e: Exception) {
            Log.e(TAG, "[TZ] set-timezone failed: ${e.message}")
        }
    }

    /** VOD à la demande (Feature B) : lecture ad-hoc takeover. Résout le src offline-first
     *  (cache local prioritaire — média pré-caché en Phase 1), repli URL signée, puis pousse
     *  au renderer WebView qui affiche l'overlay par-dessus la programmation. */
    private fun handlePlayNow(params: JSONObject) {
        val mode = params.optString("mode", "once")
        val idMedia = params.optInt("id_media", 0)
        if (mode == "stop" || idMedia == 0) {
            bridge.dispatch("play_now", JSONObject().put("mode", "stop").toString())
            return
        }
        var src: String? = params.optString("url").ifEmpty { null }
        val cacheKey = params.optString("cache_key").ifEmpty { null }
        if (::contentStore.isInitialized && cacheKey != null) {
            val filekey = contentStore.keyFor(cacheKey)
            if (contentStore.verify(filekey)) {
                src = contentStore.localUrl(filekey)   // lecture locale instantanée
            } else if (!params.optString("url").isNullOrEmpty()) {
                contentStore.enqueue(cacheKey, params.optString("cache_checksum").ifEmpty { null },
                    params.optString("mime_type").ifEmpty { null }, params.optString("url"), idMedia)
            }
        }
        if (src.isNullOrEmpty()) { Log.w(TAG, "play_now: aucun src résolu pour média $idMedia"); return }
        val out = JSONObject().apply {
            put("id_media", idMedia)
            put("media_type", params.optString("media_type", "video"))
            put("mode", if (mode == "loop") "loop" else "once")
            put("src", src)
            if (params.has("duration_ms") && !params.isNull("duration_ms")) put("duration_ms", params.optLong("duration_ms"))
            // Relayes tels quels : le defaut (`!== false`) vit dans le renderer. Un champ non
            // recopie ici serait PERDU (bug du 2026-07-19 : la case « son » restait sans effet).
            if (params.has("with_sound")) put("with_sound", params.optBoolean("with_sound", true))
            if (params.has("has_audio")) put("has_audio", params.optBoolean("has_audio", true))
        }
        bridge.dispatch("play_now", out.toString())
    }

    /** Infos device pour l'overlay de maintenance (envoyées au renderer au toggle). */
    private fun buildOverlayInfo(): JSONObject {
        val dc = lastDisplayConfig
        val lan = JSONObject().apply {
            put("enabled", dc?.optBoolean("lan_sync_enabled", false) ?: false)
            put("group", dc?.optString("lan_sync_group")?.ifEmpty { null })
            put("master", dc?.optBoolean("lan_sync_master", false) ?: false)
        }
        val device = JSONObject().apply {
            put("id_player", config.getPlayerId())
            put("hostname", Build.MODEL)
            put("os", "Android ${Build.VERSION.RELEASE}")
            put("version", BuildConfig.VERSION_NAME)
            put("ip", lanIpAddress())
            put("mac", "n/a")                  // MAC restreinte sur Android 10+ (null sans root)
            put("wan_ip", if (::wsClient.isInitialized) wsClient.lastWanIp else null)
            put("decode", "HW mediacodec")     // décodage Android = MediaCodec matériel
            put("lan", lan)
        }
        return JSONObject().put("device", device)
    }

    /** Première adresse IPv4 site-local (best-effort, sans permission spéciale). */
    private fun lanIpAddress(): String? {
        return try {
            java.net.NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
                .firstOrNull { !it.isLoopbackAddress && it is java.net.Inet4Address && it.isSiteLocalAddress }
                ?.hostAddress
        } catch (e: Exception) { null }
    }

    /**
     * Generic bridge from the WebView renderer (window.Android.nativeCall) to native Android.
     * Phase A (audio in-store) runs entirely in the WebView (Web Audio API) and does not use
     * this path. Native-backed actions (audio output routing via AudioManager, screen rotation)
     * are Phase C — handled here as they are implemented. Unknown actions are logged, never fatal.
     */
    private fun handleNativeCall(action: String, params: JSONObject) {
        when (action) {
            // Capture périodique déclenchée par le renderer (applyScreenshotSchedule).
            "screenshot" -> captureScreenshot(params.optString("request_id").ifEmpty { null })
            // État audio remonté par le renderer (~2s) → cache lu par le Store Control Panel.
            "control_status" -> lastAudioStatus = params
            // Position de lecture remontée par le renderer (~1s) → état du LAN sync leader.
            "playback_pos" -> lastPlaybackPos = params.put("reportedAt", System.currentTimeMillis())
            // Événement remonté par le renderer (ex. url_display inaccessible §XXV.2) → serveur (ou file).
            "report_event" -> { if (::wsClient.isInitialized) wsClient.reportEvent(params) }
            // Proof of Play (§XXIV) : lecture remontée par le renderer → file persistée + flush différé.
            "report_play" -> recordPlay(params)
            // Rendu vidéo HW natif (ExoPlayer) — le renderer délègue la vidéo à la surface sœur
            // quand display_config.video_renderer='exo' (HEVC + 4K@60 hors WebView).
            "exo_load" -> exo?.load(
                params.optString("url"),
                params.optLong("seekMs", 0L),
                params.optBoolean("muted", false),
                params.optBoolean("loop", false),
            )
            "exo_stop" -> exo?.stop()
            "exo_seek" -> exo?.seek(params.optLong("ms", 0L))
            "exo_rate" -> exo?.setRate(params.optDouble("rate", 1.0).toFloat())
            "exo_mute" -> exo?.setMute(params.optBoolean("muted", false))
            "exo_show" -> exo?.show()
            "exo_hide" -> {
                exo?.hide()
                // Forcer la WebView à recomposer après le retrait de la TextureView (la repeinture
                // réelle du repli est forcée côté JS via une couche de composition dédiée). invalidate
                // immédiat + différé (le temps que Chromium produise la frame).
                webView.postInvalidate()
                webView.postInvalidateDelayed(80)
            }
            // Video Wall (compensation bezel) : Matrix sur la TextureView native. transform=null = reset.
            "exo_wall" -> exo?.setWall(params.optJSONObject("transform"))
            // Écran idle NATIF (logo + message) — affiché quand le player n'a rien à diffuser.
            "idle_show" -> runOnUiThread {
                val msg = params.optString("msg", "").ifBlank { "No content to display" }
                idleMsgView?.text = msg
                idleView?.visibility = View.VISIBLE
                idleView?.bringToFront()
            }
            "idle_hide" -> runOnUiThread { idleView?.visibility = View.GONE }
            else -> Log.d(TAG, "nativeCall (unhandled): $action $params")
        }
    }

    // ── Store Control Panel LAN (§19.3) ──────────────────────────────────────────

    /**
     * Démarre/arrête le serveur de contrôle local selon display_config.local_control_enabled
     * (opt-in par player, OFF par défaut). Doit tourner sur le thread UI (dispatch WebView).
     */
    private fun manageLocalControl(dc: JSONObject) {
        val enabled = dc.optBoolean("local_control_enabled", false)
        if (enabled) {
            ensureLocalControlServer()
        } else {
            localControlServer?.stopSafe()
            localControlServer = null
        }
    }

    private fun ensureLocalControlServer() {
        if (localControlServer != null) return
        val spa = try {
            assets.open("control/control.html").bufferedReader().use { it.readText() }
        } catch (e: Exception) {
            Log.e(TAG, "[LocalControl] SPA asset introuvable: ${e.message}")
            return
        }
        localControlServer = LocalControlServer(
            port = LOCAL_CONTROL_PORT,
            spaHtml = spa,
            getPlayerName = { config.playerName },
            getProfile = { localControlProfile },
            getStatus = { lastAudioStatus },
            getVodMedia = { lastVodMedia },
            getVodPeers = { lastVodLan?.optJSONArray("peers") ?: JSONArray() },
            getSelfId = { config.getPlayerId() ?: 0 },
            onAction = { action ->
                if (action.optString("action") == "play_vod") {
                    // VOD à la demande LAN-local (Feature B Phase 3) : lecture ad-hoc takeover MULTI-CIBLE,
                    // AUTONOME (sans serveur). Pour soi = lecture locale directe ; pour les autres pairs
                    // du groupe VOD = broadcast UDP signé (le pair résout offline-first).
                    val mode = action.optString("mode", "once")
                    val id = action.optInt("id_media", 0)
                    val selfId = config.getPlayerId() ?: 0
                    val peers = lastVodLan?.optJSONArray("peers")
                    val requested = action.optJSONArray("id_players")
                    val targets = mutableListOf<Int>()
                    if (requested != null && requested.length() > 0) {
                        for (i in 0 until requested.length()) targets.add(requested.optInt(i))
                    } else if (peers != null && peers.length() > 0) {
                        for (i in 0 until peers.length()) peers.optJSONObject(i)?.let { targets.add(it.optInt("id_player")) }
                    } else {
                        targets.add(selfId)
                    }
                    for (t in targets) {
                        if (t == selfId) triggerLocalVod(id, mode)
                        else vodLan?.broadcast(t, id, mode)
                    }
                    if (::wsClient.isInitialized) {
                        wsClient.send(JSONObject(action.toString()).put("type", "local_control:action"))
                    }
                } else {
                    // Applique localement (réactif) via le renderer Web Audio.
                    runOnUiThread { bridge.dispatch("control:apply", action.toString()) }
                    // Routage de la sortie audio = niveau OS (best-effort, cf. applyAudioSink).
                    if (action.optString("action") == "set_output") {
                        action.optString("basket_output").takeIf { it.isNotEmpty() }?.let { applyAudioSink(it) }
                    }
                    // ... et transmet au backend (persistance + audit source=local_control).
                    if (::wsClient.isInitialized) {
                        val m = JSONObject(action.toString()).put("type", "local_control:action")
                        wsClient.send(m)
                    }
                }
            },
        ).also { it.startSafe() }
    }

    /**
     * Lecture VOD ad-hoc takeover LOCALE (ce player) : recompose le payload play_now depuis
     * lastVodMedia puis réutilise handlePlayNow (résolution offline-first + overlay/exo). Partagé
     * par le panneau LAN-local (cible = soi) ET la réception d'une commande UDP d'un pair.
     */
    private fun triggerLocalVod(id: Int, mode: String) {
        if (mode == "stop") {
            handlePlayNow(JSONObject().put("mode", "stop").put("id_media", -1))
            return
        }
        var entry: JSONObject? = null
        for (i in 0 until lastVodMedia.length()) {
            val m = lastVodMedia.optJSONObject(i) ?: continue
            if (m.optInt("id_media") == id) { entry = m; break }
        }
        entry?.let { e ->
            val pn = JSONObject()
                .put("id_media", id)
                .put("media_type", e.optString("media_type", "video"))
                .put("mode", mode)
                .put("cache_key", e.optString("cache_key"))
                .put("cache_checksum", e.optString("cache_checksum"))
                .put("url", e.optString("url"))
                .put("mime_type", e.optString("mime_type"))
            if (!e.isNull("duration_ms")) pn.put("duration_ms", e.optLong("duration_ms"))
            handlePlayNow(pn)
        }
    }

    /**
     * Démarre/arrête/re-clé le contrôleur UDP de trigger VOD multi-cible (port 7779) selon la
     * présence d'un bloc `vod_lan` (secret partagé) dans le sync. Actif dès que le player est dans
     * une config VOD — indépendamment du LAN sync (le trigger doit marcher hors groupe de synchro).
     */
    private fun manageVodLan() {
        val secret = lastVodLan?.optString("secret")?.takeIf { it.isNotEmpty() }
        val selfId = config.getPlayerId()
        if (secret != null && selfId != null) {
            val ctl = vodLan
            if (ctl == null) {
                vodLan = VodLanController(applicationContext, selfId, secret) { idMedia, mode ->
                    runOnUiThread { triggerLocalVod(idMedia, mode) }
                }.also { it.start() }
            } else {
                ctl.updateSecret(secret)
            }
        } else {
            vodLan?.stop()
            vodLan = null
        }
    }

    // ── LAN sync inter-players (§III.3) ──────────────────────────────────────────

    /**
     * Démarre/arrête le contrôleur LAN sync selon display_config.lan_sync_enabled.
     * Le groupe et le statut de leader désigné (lan_sync_master) viennent du serveur.
     * Recréé si le groupe ou le rôle master change (compare la conf appliquée).
     */
    private fun manageLanSync(dc: JSONObject) {
        if (!dc.optBoolean("lan_sync_enabled", false)) {
            if (lanSync != null) { lanSync?.stop(); lanSync = null; appliedLanConfig = null }
            return
        }
        val idPlayer = config.getPlayerId()
        if (idPlayer == null) {
            Log.w(TAG, "[LAN Sync] id_player inconnu (pas de JWT) — démarrage différé")
            return
        }
        val group = dc.optString("lan_sync_group").ifEmpty { "default" }
        val master = dc.optBoolean("lan_sync_master", false)
        val wanted = "$group|$master"
        // Le groupe/master sont figés au boot du contrôleur (socket UDP) → si la conf serveur
        // change, on RECRÉE le contrôleur (sinon un changement de groupe via le CMS resterait
        // ignoré jusqu'au reboot). Recrée uniquement sur changement réel (pas à chaque sync).
        if (lanSync != null && wanted == appliedLanConfig) return
        lanSync?.stop()
        appliedLanConfig = wanted
        lanSync = LanSyncController(
            context = applicationContext,
            idPlayer = idPlayer,
            groupName = group,
            isMaster = master,
            getState = { getLanSyncState() },
            onSyncReceived = { payload ->
                runOnUiThread {
                    bridge.dispatch("lan-adjust", JSONObject().apply {
                        put("id_playlist", payload.opt("id_playlist") ?: JSONObject.NULL)
                        put("start_index", payload.optInt("start_index"))
                        put("start_offset_ms", payload.optLong("start_offset_ms"))
                    }.toString())
                }
            },
            onSwitchHint = { hint ->
                runOnUiThread { bridge.dispatch("lan-switch", hint.toString()) }
            },
        ).also {
            // Barrière de readiness (Q1) : la barrière s'ouvre (groupe prêt ou timeout) →
            // le renderer démarre l'empreinte courante.
            it.setBarrierReleaseHandler { fp ->
                releasedFps.add(fp)
                if (fp == currentFp) runOnUiThread { bridge.dispatch("lan-release") }
            }
            it.start()
            updateLanReadiness()   // déclare l'état courant dès le démarrage du contrôleur
        }
    }

    /**
     * État de lecture pour le LAN sync leader : position vidéo réelle (poussée par le
     * renderer) interpolée depuis le dernier report. Null si rien ne joue.
     */
    private fun getLanSyncState(): JSONObject? {
        val p = lastPlaybackPos ?: return null
        // Borne l'interpolation : le renderer reporte toutes les 1000ms. S'il cesse de reporter
        // (vidéo finie, jank), un elapsed NON borné fait courir currentOffsetMs avec l'horloge
        // murale (65000ms pour une vidéo de 22s) → leader diffuse cette valeur folle → seeks
        // hors-borne sur les slaves = écran noir. Cap à 1500ms.
        val elapsed = (System.currentTimeMillis() - p.optLong("reportedAt")).coerceAtMost(1500L)
        return JSONObject().apply {
            put("id_playlist", p.opt("id_playlist") ?: JSONObject.NULL)
            put("currentIndex", p.optInt("currentIndex"))
            put("currentOffsetMs", p.optLong("offsetMs") + elapsed)
            put("switch_at", if (p.isNull("switchAt")) JSONObject.NULL else p.optLong("switchAt"))
            put("next_index", if (p.isNull("nextIndex")) JSONObject.NULL else p.optInt("nextIndex"))
        }
    }

    /**
     * Watchdog mémoire (F3) : logge l'état mémoire ~1×/min et relance l'app si le système
     * signale une pression critique persistante (`MemoryInfo.lowMemory`). Sur un parc mondial,
     * un player ne doit jamais rester figé/dégradé faute de RAM sans intervention.
     */
    private fun startMemoryWatchdog() {
        memHandler.postDelayed(object : Runnable {
            override fun run() {
                try {
                    val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                    val mi = ActivityManager.MemoryInfo()
                    am.getMemoryInfo(mi)
                    Log.i(TAG, "[Mem] avail=${mi.availMem / 1048576}MB/${mi.totalMem / 1048576}MB " +
                        "low=${mi.lowMemory} threshold=${mi.threshold / 1048576}MB")
                    if (mi.lowMemory) {
                        memLowTicks++
                        if (memLowTicks >= 3) {
                            Log.w(TAG, "[MemWatchdog] pression mémoire critique persistante → relance préventive")
                            memLowTicks = 0
                            restartApp()
                            return
                        }
                    } else {
                        memLowTicks = 0
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "memWatchdog: ${e.message}")
                }
                memHandler.postDelayed(this, 60_000)
            }
        }, 60_000)
    }

    private fun restartApp() {
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        )
        finish()
    }

    private fun rebootOs() {
        // 1) Device Owner (kiosk, SANS root) — chemin privilégié sur une box de signage
        //    dédiée. Provisionné via `adb shell dpm set-device-owner ...SignFlowAdminReceiver`.
        try {
            val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (dpm.isDeviceOwnerApp(packageName)) {
                dpm.reboot(ComponentName(this, SignFlowAdminReceiver::class.java))
                return
            }
        } catch (e: Exception) {
            Log.w(TAG, "reboot_os: DevicePolicyManager.reboot indisponible: ${e.message}")
        }
        // 2) Root si dispo. 3) Sinon repli = relancer l'app (mieux que rien).
        try {
            Runtime.getRuntime().exec(arrayOf("su", "-c", "reboot"))
        } catch (e: Exception) {
            Log.w(TAG, "reboot_os: ni Device Owner ni root -> relance de l'app: ${e.message}")
            restartApp()
        }
    }

    private fun resetConfig() {
        wsClient.close()
        config.clear()
        startActivity(
            Intent(this, SetupActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        )
        finish()
    }

    private fun captureScreenshot(requestId: String?) {
        runOnUiThread {
            try {
                val handler = Handler(Looper.getMainLooper())
                val surf = videoSurface
                // Mode exo : la vidéo rend sur la TextureView (texture GPU) posée au-dessus de la
                // WebView → PixelCopy(window) ne la capture pas. getBitmap() lit la frame courante
                // de la texture (contrairement à une SurfaceView = plan overlay HW non lisible).
                // Repli sur la capture fenêtre si la TextureView est cachée/indispo.
                if (surf != null && surf.visibility == View.VISIBLE && surf.isAvailable &&
                    surf.width > 0 && surf.height > 0) {
                    val tb = exo?.captureFrame()
                    if (tb != null) { uploadScreenshot(rotateForScreen(tb), requestId); return@runOnUiThread }
                    Log.w(TAG, "TextureView.getBitmap null — fallback fenêtre")
                }
                captureWindowScreenshot(requestId, handler)
            } catch (e: Exception) {
                Log.e(TAG, "Screenshot capture error: ${e.message}")
            }
        }
    }

    /**
     * Capture la FENÊTRE composée (WebView + tout contenu non-vidéo, vidéo HW <video> incluse).
     *
     * 🔴 Ne JAMAIS dériver le rect source de `webView.getLocationInWindow()` + ses dimensions de
     * layout : `getLocationInWindow` applique la matrice de transformation de la vue, alors que
     * width/height restent celles d'AVANT rotation. Dès que `screen_rotation` vaut right/inverted/
     * left, le rect obtenu sort des bornes de la fenêtre → PixelCopy refuse → repli software
     * `webView.draw()`, incapable de peindre une vidéo : Chromium y dessine son placeholder média
     * (l'icône « lecture » vue par Ed le 2026-08-14 sur les TROIS modes rotés, le mode normal
     * étant le seul où le rect coïncide avec la fenêtre). On capture donc la fenêtre entière, ce
     * qui inclut par construction les vues rotées telles qu'elles sont réellement composées.
     */
    private fun captureWindowScreenshot(requestId: String?, handler: Handler) {
        val decor = window.decorView
        val w = decor.width.coerceAtLeast(1)
        val h = decor.height.coerceAtLeast(1)
        val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        // Repli software : dessiner le DECOR (et non la seule WebView) — lui seul applique les
        // transforms de ses enfants, donc rend la rotation. La vidéo y reste non peinte.
        val softwareDraw = {
            Canvas(bitmap).also { decor.draw(it) }
            uploadScreenshot(bitmap, requestId)
        }
        try {
            PixelCopy.request(window, bitmap, { result ->
                if (result == PixelCopy.SUCCESS) {
                    uploadScreenshot(bitmap, requestId)
                } else {
                    Log.w(TAG, "PixelCopy failed ($result) — fallback software draw")
                    softwareDraw()
                }
            }, handler)
        } catch (e: Exception) {
            Log.w(TAG, "PixelCopy error (${e.message}) — fallback software draw")
            softwareDraw()
        }
    }

    /**
     * Applique la rotation d'écran courante à une capture issue de la surface vidéo. La
     * TextureView rend dans un buffer qui ignore la transform de vue → sans ça, la vignette
     * d'un écran en portrait remonterait couchée. Identité quand rotation=normal (parc existant).
     */
    private fun rotateForScreen(src: Bitmap): Bitmap {
        val angle = when (appliedRotation) {
            "right" -> 90f; "inverted" -> 180f; "left" -> 270f; else -> return src
        }
        return try {
            val m = android.graphics.Matrix().also { it.postRotate(angle) }
            val out = Bitmap.createBitmap(src, 0, 0, src.width, src.height, m, true)
            if (out !== src) src.recycle()
            out
        } catch (e: Exception) {
            Log.w(TAG, "rotateForScreen failed: ${e.message}")
            src
        }
    }

    private fun uploadScreenshot(bitmap: Bitmap, requestId: String?) {
        scope.launch {
            try {
                val baos = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.PNG, 90, baos)
                bitmap.recycle()

                val pngBytes = baos.toByteArray()
                if (pngBytes.size < 1024) {
                    Log.w(TAG, "Screenshot too small (${pngBytes.size}B) — skipping")
                    return@launch
                }

                val idPlayer = config.getPlayerId() ?: return@launch
                val body = pngBytes.toRequestBody("image/png".toMediaType())
                val req = Request.Builder()
                    .url("${config.backendUrl}/api/v1/players/$idPlayer/screenshot")
                    .post(body)
                    .header("Authorization", "Bearer ${config.playerToken}")
                    .build()

                httpClient.newCall(req).execute().use { resp ->
                    Log.i(TAG, "Screenshot uploaded: ${resp.code} (${pngBytes.size}B, request_id=$requestId)")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Screenshot upload error: ${e.message}")
            }
        }
    }

    // ── Proof of Play (§XXIV) — file PERSISTÉE (filesDir) + flush /pop/batch ────────────
    // Donnée de conformité → survit reboot/coupure (≠ events volatils). Flush best-effort ;
    // on ne retire de la file QUE si le serveur a accepté (offline → on garde).
    private val popFile by lazy { File(filesDir, "pop_queue.json") }
    private val popLock = Any()
    private val popQueue = mutableListOf<JSONObject>()
    @Volatile private var popFlushing = false
    private val POP_QUEUE_MAX = 5000
    private val POP_BATCH_MAX = 200
    // P2 — signature Ed25519 des preuves, gatée par display_config.pop_sign (rollout par player).
    @Volatile private var popSignEnabled = false
    private val popSigner by lazy { PopSigner(filesDir) }

    private fun isoNow(): String {
        val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", java.util.Locale.US)
        sdf.timeZone = java.util.TimeZone.getTimeZone("UTC")
        return sdf.format(java.util.Date())
    }

    private fun loadPopQueue() {
        try {
            if (!popFile.exists()) return
            val arr = JSONArray(popFile.readText())
            synchronized(popLock) {
                popQueue.clear()
                for (i in 0 until arr.length()) popQueue.add(arr.getJSONObject(i))
            }
        } catch (e: Exception) { Log.w(TAG, "PoP load: ${e.message}") }
    }

    private fun persistPopQueue() {
        try {
            val arr = JSONArray()
            synchronized(popLock) { for (o in popQueue) arr.put(o) }
            popFile.writeText(arr.toString())
        } catch (e: Exception) { Log.e(TAG, "PoP persist: ${e.message}") }
    }

    private fun recordPlay(params: JSONObject) {
        val idMedia = if (params.isNull("id_media")) null else params.optInt("id_media")
        val idPlaylist = if (params.isNull("id_playlist")) null else params.optInt("id_playlist")
        if (idMedia == null && idPlaylist == null) return
        val o = JSONObject()
        o.put("id_media", idMedia ?: JSONObject.NULL)
        o.put("id_playlist", idPlaylist ?: JSONObject.NULL)
        o.put("duration_ms", maxOf(0, params.optInt("duration_ms", 0)))
        o.put("played_at", params.optString("played_at").ifEmpty { isoNow() })
        // Zone recouverte par un overlay plein écran au démarrage du média (migr 0125) :
        // spot de campagne P3.6 ou takeover VOD. Le serveur conserve la preuve mais ne la
        // compte jamais comme de l'antenne. Hors du message signé.
        o.put("covered", params.optBoolean("covered", false))
        synchronized(popLock) {
            popQueue.add(o)
            while (popQueue.size > POP_QUEUE_MAX) popQueue.removeAt(0)
        }
        persistPopQueue()
    }

    private fun flushPopQueue() {
        if (popFlushing || !config.isConfigured()) return
        val batch: List<JSONObject>
        synchronized(popLock) {
            if (popQueue.isEmpty()) return
            batch = popQueue.take(POP_BATCH_MAX).toList()
        }
        popFlushing = true
        scope.launch {
            try {
                // P2 — signature Ed25519 (parité renderer web). On signe les preuves du lot non encore
                // signées (persistées dans la file → survit reboot/offline, jamais recalculées) puis on
                // joint la clé publique (TOFU). Le backend REJETTE tout le lot si une signature est
                // invalide → gate par pop_sign (rollout par player, désactivable pour récupérer).
                var pubKey: String? = null
                if (popSignEnabled) {
                    val idPlayer = config.getPlayerId()
                    if (idPlayer != null) {
                        var changed = false
                        for (o in batch) {
                            if (o.optString("signature").isEmpty()) {
                                val sig = signPopEntry(idPlayer, o)
                                if (sig != null) { o.put("signature", sig); changed = true }
                            }
                        }
                        if (changed) persistPopQueue()
                        pubKey = popSigner.publicKeyPem
                    }
                }
                val logs = JSONArray()
                for (o in batch) logs.put(o)
                val payload = JSONObject().put("logs", logs)
                if (pubKey != null) payload.put("pop_public_key", pubKey)
                val req = Request.Builder()
                    .url("${config.backendUrl}/api/v1/pop/batch")
                    .post(payload.toString().toRequestBody("application/json".toMediaType()))
                    .header("Authorization", "Bearer ${config.playerToken}")
                    .build()
                httpClient.newCall(req).execute().use { resp ->
                    if (resp.isSuccessful) {
                        synchronized(popLock) {
                            repeat(minOf(batch.size, popQueue.size)) { popQueue.removeAt(0) }
                        }
                        persistPopQueue()
                        Log.i(TAG, "PoP: ${batch.size} preuve(s) envoyée(s), ${popQueue.size} en attente")
                    } else {
                        Log.w(TAG, "PoP flush refusé HTTP ${resp.code}")
                    }
                }
            } catch (e: Exception) {
                // hors-ligne / serveur down → on garde la file
            } finally {
                popFlushing = false
            }
        }
    }

    /** Message canonique = "id_player|id_media|id_playlist|played_at_ms|duration_ms" (null → vide). */
    private fun signPopEntry(idPlayer: Int, o: JSONObject): String? {
        val idMedia = if (o.isNull("id_media")) "" else o.optInt("id_media").toString()
        val idPlaylist = if (o.isNull("id_playlist")) "" else o.optInt("id_playlist").toString()
        val ms = playedAtToMs(o.optString("played_at"))
        val dur = maxOf(0, o.optInt("duration_ms", 0))
        val msg = "$idPlayer|$idMedia|$idPlaylist|$ms|$dur"
        return popSigner.sign(msg.toByteArray(Charsets.UTF_8))
    }

    /** Epoch millis d'un played_at ISO — DOIT égaler int(dt.timestamp()*1000) côté serveur. */
    private fun playedAtToMs(s: String): Long = try {
        java.time.Instant.parse(s).toEpochMilli()
    } catch (e: Exception) {
        try {
            val sdf = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", java.util.Locale.US)
            sdf.timeZone = java.util.TimeZone.getTimeZone("UTC")
            sdf.parse(s)?.time ?: System.currentTimeMillis()
        } catch (e2: Exception) { System.currentTimeMillis() }
    }

    private fun registerWatchdog() {
        val request = PeriodicWorkRequestBuilder<WatchdogWorker>(15, TimeUnit.MINUTES).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "signflow_watchdog",
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        // Block Back and Menu — kiosk mode
        if (keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_MENU) return true
        return super.onKeyDown(keyCode, event)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) setupKioskWindow()  // Restore immersive mode after dialogs
    }

    override fun onDestroy() {
        super.onDestroy()
        memHandler.removeCallbacksAndMessages(null)
        scope.cancel()
        localControlServer?.stopSafe()
        lanSync?.stop()
        vodLan?.stop()
        // 🔴 ExoPlayer AVANT la WebView : il n'était libéré NULLE PART. `restartApp()` recrée
        // l'activité (CLEAR_TASK + finish) → une NOUVELLE instance d'ExoPlayer démarrait
        // pendant que l'ancienne gardait sa piste audio ouverte sur le même fichier ⇒ DEUX
        // sons décalés (« écho ») jusqu'au redémarrage de l'appareil. Constaté par Ed le
        // 2026-07-30 après un « Redémarrer le player », et mesuré sur l'appareil : deux flux
        // simultanés dans le MÊME processus (AudioTrack d'ExoPlayer + AAudio de la WebView).
        // Concerne TOUS les players Android en mode exo, pas seulement le stick.
        exo?.release()
        if (::wsClient.isInitialized) wsClient.close()
        if (::webView.isInitialized) webView.destroy()
    }
}
