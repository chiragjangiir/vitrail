package app.vitrail.player

import android.os.StatFs
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.Calendar
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * ContentStore — store local offline-first / download-then-play (épopée P0→P3),
 * portage Kotlin du `content_store.js` (Node) des players Electron. Télécharge les
 * octets des médias (vidéo/image/audio) sur disque et les sert au WebView via des URLs
 * `file://` (le media stack Android lit le fichier directement → seek natif complet,
 * indispensable au nudge LAN ; contrairement à un schéma custom intercepté que le
 * WebView ne sait pas servir en Range). Tant qu'un octet n'est pas en cache, le
 * renderer continue de streamer l'URL MinIO → repli gracieux (P0 ne régresse jamais).
 *
 * Clé du store = `cache_key` (le storage_key RÉELLEMENT servi : parent ou rendition),
 * pas le checksum du payload. Nom de fichier = sha1(cache_key). Garde d'intégrité =
 * taille annoncée (Content-Length) + atomicité .part→rename (le checksum du payload
 * = upload, pas l'objet transcodé/rendition servi → on ne le vérifie pas).
 *
 * Look-ahead (prefetch) : le serveur joint au sync une liste `prefetch` du contenu
 * programmé sur les prochaines semaines, chaque entrée avec une `priority` (= date de
 * diffusion ; plus petit = plus tôt). Le store télécharge à l'avance (file triée par
 * priorité) DANS LA LIMITE DU DISQUE, et sous pression évince d'abord le contenu non
 * programmé (stale), puis le plus lointain — jamais la playlist courante (épinglée).
 * Les downloads de prefetch ne s'effectuent que dans les fenêtres horaires autorisées
 * (Phase 2) ; la playlist courante (non-prefetch) télécharge toujours.
 *
 * Q2 éviction : épinglé (= playlist courante) jamais évincé ; non-épinglé évincé sous
 * pression — stale (LRU) d'abord, puis programmé lointain. Q3 QoS : plafond de bande
 * passante (pacing par sleep) + reprise HTTP Range des .part + plafond appliqué À CHAUD
 * (interrompt + reprend le download en cours quand le plafond change). Q4 :
 * getStorageStatus pour le heartbeat. Q5 : purgeMedia (kill-switch).
 */
class ContentStore(baseDir: File, private val log: (String) -> Unit) {

    private data class Entry(
        val cacheKey: String, val mime: String, val size: Long,
        val idMedia: Int, var lastUsed: Long, var priority: Long = 0L,
    )

    private data class DlJob(
        val filekey: String, val cacheKey: String, val cacheChecksum: String?,
        val mime: String?, val url: String, val idMedia: Int,
        val priority: Long = 0L, val isPrefetch: Boolean = false,
    )

    private val dir = File(baseDir, "content_store").also { it.mkdirs() }
    private val indexFile = File(dir, "index.json")
    private val index = HashMap<String, Entry>()         // filekey -> Entry
    private val inflight = HashSet<String>()             // filekeys en cours de download
    private val downloading = HashSet<Int>()            // id_media en file/en cours (inventaire UI)
    private val queue = ArrayList<DlJob>()               // file d'attente (triée par priorité)
    private var active = false
    private val pinned = HashSet<String>()               // filekeys épinglés (playlist courante)
    private val prefetchKeys = HashMap<String, Long>()   // filekey -> priorité (programmé voulu, évinçable par lointain)
    @Volatile private var pressure = false               // épinglé ne tient pas → alerte serveur
    private val blocked = HashSet<Int>()                 // id_media renonces faute de place → serveur
    @Volatile private var blockedLogged = false          // n'inonde pas le journal tant que ca dure
    @Volatile private var bandwidthKbps = 0              // Q3 : plafond download (0 = illimité)
    @Volatile private var measureBandwidth = false       // mesure passive du débit réel (opt-in)
    @Volatile private var measuredKbps = 0.0             // EWMA du débit mesuré (kbit/s) → heartbeat
    private var windows: List<Pair<Int, Int>>? = null    // fenêtres horaires (prefetch only), null = toujours
    private var activeCall: Call? = null                 // call HTTP du download en cours (interruption à chaud)
    private var requeueActive = false                    // remettre le download courant en file (plafond changé)
    private var recheckScheduled = false                 // un re-essai de fenêtre est déjà planifié

    /** Callback(cacheKey, fileUrl) quand un média vient d'arriver en cache. */
    var onReady: ((cacheKey: String, url: String) -> Unit)? = null

    private val lock = Any()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.SECONDS)   // pas de plafond global (gros fichiers + throttle)
        .build()

    companion object {
        private const val HIGH_WATERMARK = 0.85
        private const val LOW_WATERMARK = 0.70
        // Frein de stockage (2026-08-06) : plancher ABSOLU d'espace libre.
        // Les watermarks ci-dessus sont des RATIOS et ne peuvent RIEN quand tout le cache est
        // epingle (= playlist courante) : l'eviction n'a alors rien a liberer, elle leve
        // `pressure` pour prevenir le serveur... et le telechargement continuait quand meme.
        // Mesure sur CE modele d'appareil (stick Android TV 4 Go) : disque a 100 %, 0 octet
        // libre, et c'est ANDROID qui casse (SQLITE_FULL, keystore en echec, ENOSPC), pas
        // seulement notre app. L'appareil n'a pu etre recupere qu'en DESINSTALLANT SignFlow,
        // donc par un deplacement sur site. On prefere renoncer a un media plutot que rendre
        // la machine inutilisable : un ecran qui diffuse une playlist partielle reste
        // reparable a distance, un ecran dont l'OS est mort ne l'est plus.
        private const val MIN_FREE_BYTES = 512L * 1024 * 1024       // 512 Mo laisses a l'OS
        private const val FREE_CHECK_EVERY_BYTES = 8L * 1024 * 1024 // re-mesure pendant l'ecriture
        private const val WINDOW_RECHECK_MS = 60_000L  // re-tente le prefetch quand une fenêtre peut s'ouvrir
        private const val MIN_MEASURE_BYTES = 1_048_576L  // mesure de débit : ignorer les fichiers < 1 Mo (bruit)
    }

    init { load() }

    /**
     * Q3 + fenêtres look-ahead (Phase 2) : politique de download, pilotée par display_config.
     * `windows` = plages "HH:MM"→"HH:MM" autorisées pour le PREFETCH (la playlist courante
     * télécharge hors fenêtre aussi) ; vide/null = toujours autorisé. Plafond changé EN COURS
     * de download → on interrompt + reprend (le .part est repris via Range) pour appliquer le
     * nouveau throttle tout de suite, sans reboot (vu sur fifi 2026-06-08).
     */
    fun setPolicy(bandwidthKbps: Int, windows: List<Pair<String, String>>?, measureBandwidth: Boolean) {
        val prev = this.bandwidthKbps
        this.bandwidthKbps = if (bandwidthKbps > 0) bandwidthKbps else 0
        this.measureBandwidth = measureBandwidth
        val parsed = windows
            ?.mapNotNull { (s, e) -> val a = hm(s); val b = hm(e); if (a != null && b != null) a to b else null }
            ?.takeIf { it.isNotEmpty() }
        this.windows = parsed
        if (this.bandwidthKbps != prev) interruptActiveForPolicy()
        pump()  // une fenêtre qui s'ouvre (ou un débit relevé) peut débloquer le prefetch
    }

    /** "HH:MM" → minutes depuis minuit (null si invalide). */
    private fun hm(str: String?): Int? {
        val m = Regex("^(\\d{1,2}):(\\d{2})$").find((str ?: "").trim()) ?: return null
        val h = m.groupValues[1].toInt(); val mi = m.groupValues[2].toInt()
        if (h > 23 || mi > 59) return null
        return h * 60 + mi
    }

    // Interrompt le download en cours pour le remettre en file → le nouveau plafond s'applique
    // au prochain pump. No-op s'il n'y a pas de download actif. Reprise gratuite : le .part déjà
    // écrit est repris via Range, rien n'est re-téléchargé.
    private fun interruptActiveForPolicy() {
        val call = synchronized(lock) {
            if (!active || activeCall == null) return
            requeueActive = true
            activeCall
        }
        log("débit: plafond changé en cours de download → interruption + reprise")
        try { call?.cancel() } catch (_: Exception) {}
    }

    // True si le prefetch a le droit de télécharger maintenant (selon les fenêtres). Gère l'overnight.
    private fun downloadAllowed(): Boolean {
        val w = windows ?: return true
        val cal = Calendar.getInstance()
        val cur = cal.get(Calendar.HOUR_OF_DAY) * 60 + cal.get(Calendar.MINUTE)
        return w.any { (s, e) -> if (s <= e) (cur in s..e) else (cur >= s || cur <= e) }
    }

    /** sha1 du cache_key → nom de fichier sûr et stable. */
    fun keyFor(cacheKey: String): String {
        val md = MessageDigest.getInstance("SHA-1")
        return md.digest(cacheKey.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    private fun fileFor(filekey: String) = File(dir, filekey)

    fun has(filekey: String): Boolean = synchronized(lock) { index.containsKey(filekey) }

    /**
     * Garde d'intégrité RUNTIME : l'entrée est-elle réellement servable (fichier présent +
     * taille cohérente avec l'index) ? Le `load` ne purge qu'au démarrage ; ici on couvre une
     * disparition / troncature à chaud (disque qui se remplit, suppression externe). En cas
     * d'échec on OUBLIE l'entrée → le rewrite gardera l'URL MinIO (repli streaming) et re-mettra
     * le téléchargement en file. Utilisé au rewrite + readiness LAN.
     */
    fun verify(filekey: String): Boolean {
        synchronized(lock) {
            val e = index[filekey] ?: return false
            val f = fileFor(filekey)
            val size = if (f.exists()) f.length() else -1L
            if (size < 0 || size != e.size) {
                index.remove(filekey)
                saveIndex()
                log("verify: ${filekey.take(12)} invalide (taille $size/${e.size}) → oublié, repli stream")
                return false
            }
            return true
        }
    }

    /** URL `file://` servie au WebView (lecture directe → seek natif). */
    fun localUrl(filekey: String): String = "file://" + fileFor(filekey).absolutePath

    /** Marque un média comme récemment utilisé (LRU) — appelé quand on le sert en local. */
    fun markUsed(filekey: String) {
        synchronized(lock) { index[filekey]?.lastUsed = System.currentTimeMillis() }
    }

    private fun mimeFromKey(cacheKey: String): String? {
        val ext = Regex("\\.([a-z0-9]+)$").find(cacheKey.lowercase())?.groupValues?.get(1) ?: return null
        return mapOf(
            "mp4" to "video/mp4", "m4v" to "video/mp4", "webm" to "video/webm",
            "mkv" to "video/x-matroska", "mov" to "video/quicktime", "ogv" to "video/ogg",
            "jpg" to "image/jpeg", "jpeg" to "image/jpeg", "png" to "image/png",
            "gif" to "image/gif", "webp" to "image/webp", "svg" to "image/svg+xml",
            // Audio (offline-first §XIX) : l'audio ré-encodé est en .ogg.
            "ogg" to "audio/ogg", "opus" to "audio/ogg", "mp3" to "audio/mpeg",
            "m4a" to "audio/mp4", "aac" to "audio/aac", "wav" to "audio/wav", "flac" to "audio/flac",
            "pdf" to "application/pdf",
        )[ext]
    }

    private fun load() {
        try {
            val raw = if (indexFile.exists()) indexFile.readText() else "{}"
            val obj = JSONObject(raw)
            for (k in obj.keys()) {
                val e = obj.getJSONObject(k)
                index[k] = Entry(
                    e.optString("cache_key"), e.optString("mime", "application/octet-stream"),
                    e.optLong("size"), e.optInt("id_media"), e.optLong("last_used"),
                    e.optLong("priority"),
                )
            }
        } catch (e: Exception) { index.clear() }
        // Purge les entrées dont le fichier a disparu (cohérence index↔disque).
        var pruned = 0
        val it = index.keys.iterator()
        while (it.hasNext()) {
            val k = it.next()
            if (!fileFor(k).exists()) { it.remove(); pruned++ }
        }
        if (pruned > 0) saveIndex()
        log("store: ${index.size} média(s) en cache ($pruned purgé[s])")
    }

    private fun saveIndex() {
        try {
            val obj = JSONObject()
            for ((k, e) in index) {
                obj.put(k, JSONObject().apply {
                    put("cache_key", e.cacheKey); put("mime", e.mime); put("size", e.size)
                    put("id_media", e.idMedia); put("last_used", e.lastUsed); put("priority", e.priority)
                })
            }
            val tmp = File(dir, "index.json.tmp")
            tmp.writeText(obj.toString())
            tmp.renameTo(indexFile)
        } catch (e: Exception) { log("index save failed: ${e.message}") }
    }

    private fun sortQueue() {
        // Plus petite priorité d'abord = diffusion la plus proche téléchargée en premier.
        queue.sortBy { it.priority }
    }

    /**
     * Met un média en file d'attente (no-op si déjà présent / en vol). priority = date de
     * diffusion (epoch s) ; isPrefetch=true → soumis aux fenêtres horaires. Un même filekey
     * déjà en file conserve la priorité la plus haute (la + petite) et perd isPrefetch si une
     * demande non-prefetch (playlist courante) arrive.
     */
    fun enqueue(
        cacheKey: String?, cacheChecksum: String?, mime: String?, url: String?, idMedia: Int,
        priority: Long = 0L, isPrefetch: Boolean = false,
    ) {
        if (cacheKey.isNullOrEmpty() || url.isNullOrEmpty()) return
        val filekey = keyFor(cacheKey)
        synchronized(lock) {
            if (index.containsKey(filekey) || inflight.contains(filekey)) return
            val i = queue.indexOfFirst { it.filekey == filekey }
            if (i >= 0) {
                val ex = queue[i]
                val newPrio = minOf(ex.priority, priority)
                val newPrefetch = ex.isPrefetch && isPrefetch
                if (newPrio != ex.priority || newPrefetch != ex.isPrefetch) {
                    queue[i] = ex.copy(priority = newPrio, isPrefetch = newPrefetch)
                    sortQueue()
                }
                return
            }
            if (idMedia != 0) downloading.add(idMedia)   // inventaire UI
            queue.add(DlJob(filekey, cacheKey, cacheChecksum, mime, url, idMedia, priority, isPrefetch))
            sortQueue()
        }
        pump()
    }

    private fun pump() {
        val job: DlJob
        synchronized(lock) {
            if (active) return
            // 1er job exécutable : la playlist courante (non-prefetch) toujours ; le prefetch
            // seulement dans une fenêtre autorisée.
            val idx = queue.indexOfFirst { !it.isPrefetch || downloadAllowed() }
            if (idx < 0) {
                if (queue.isNotEmpty()) scheduleRecheck()  // que du prefetch hors fenêtre → on réessaiera
                return
            }
            // FREIN : on libere d'abord ce qui est liberable, puis on refuse de DEMARRER si le
            // plancher n'est pas tenu. Le job reste EN FILE (jamais jete) : il repartira des
            // qu'une eviction ou une desaffectation aura rendu de la place.
            enforceQuota()
            if (freeBytes() < MIN_FREE_BYTES) {
                val j = queue[idx]
                if (j.idMedia != 0) blocked.add(j.idMedia)
                pressure = true
                if (!blockedLogged) {
                    log("FREIN STOCKAGE: ${freeBytes() / 1048576} MB libres < plancher " +
                        "${MIN_FREE_BYTES / 1048576} MB - telechargements suspendus, " +
                        "le contenu deja en cache continue de diffuser")
                    blockedLogged = true
                }
                scheduleRecheck()
                return
            }
            // La place est revenue : sinon un media resterait signale « bloque » a vie.
            if (blocked.isNotEmpty()) blocked.clear()
            blockedLogged = false

            job = queue.removeAt(idx)
            active = true
            inflight.add(job.filekey)
            requeueActive = false
        }
        scope.launch {
            try {
                download(job)
                onReady?.invoke(job.cacheKey, localUrl(job.filekey))
                enforceQuota()   // un nouvel octet peut avoir poussé le disque au-dessus du seuil
            } catch (e: Exception) {
                log("download ${job.filekey.take(12)} failed: ${e.message}")
            } finally {
                val requeue: Boolean
                synchronized(lock) {
                    inflight.remove(job.filekey); downloading.remove(job.idMedia)
                    active = false; activeCall = null
                    requeue = requeueActive
                    requeueActive = false
                }
                // Plafond de débit changé pendant ce download → on le remet en file pour reprendre
                // sous le nouveau throttle (no-op s'il a fini entre-temps : enqueue voit has()=true).
                if (requeue) enqueue(
                    job.cacheKey, job.cacheChecksum, job.mime, job.url, job.idMedia,
                    job.priority, job.isPrefetch,
                )
                pump()
            }
        }
    }

    private fun scheduleRecheck() {
        if (recheckScheduled) return
        recheckScheduled = true
        scope.launch {
            delay(WINDOW_RECHECK_MS)
            synchronized(lock) { recheckScheduled = false }
            pump()
        }
    }

    private fun download(job: DlJob) {
        val fp = fileFor(job.filekey)
        val tmp = File(dir, job.filekey + ".part")
        // Reprise (Q3) : si un .part existe (download interrompu), on reprend via Range.
        val startByte = if (tmp.exists()) tmp.length() else 0L
        val reqB = Request.Builder().url(job.url)
        if (startByte > 0) reqB.header("Range", "bytes=$startByte-")

        val tStart = System.currentTimeMillis()   // mesure passive du débit (opt-in)
        val call = http.newCall(reqB.build())
        synchronized(lock) { activeCall = call }   // exposé pour interruption à chaud (plafond changé)

        call.execute().use { resp ->
            val code = resp.code
            if (code != 200 && code != 206) throw IOException("HTTP $code")
            val resuming = code == 206 && startByte > 0
            val base = if (resuming) startByte else 0L
            val body = resp.body ?: throw IOException("no body")
            val contentLen = body.contentLength()
            val expected = if (contentLen >= 0) base + contentLen else 0L

            val out = RandomAccessFile(tmp, "rw")
            if (resuming) out.seek(startByte) else out.setLength(0)
            // Plafond de bande passante (Q3) : pacing par sleep → préserve la ligne du client.
            val bytesPerSec = if (bandwidthKbps > 0) bandwidthKbps * 125L else 0L
            val buf = ByteArray(64 * 1024)
            var sent = 0L
            val t0 = System.currentTimeMillis()
            // FREIN EN COURS D'ECRITURE. Indispensable : la taille du fichier n'est PAS connue
            // avant de commencer (le serveur ne l'envoie pas au player), donc le controle
            // d'avant-demarrage ne suffit pas - un seul media peut a lui seul saturer le disque.
            var insufficient = false
            var sinceCheck = 0L
            try {
                body.byteStream().use { input ->
                    while (true) {
                        val nb = input.read(buf)
                        if (nb < 0) break
                        out.write(buf, 0, nb)
                        sinceCheck += nb
                        if (sinceCheck >= FREE_CHECK_EVERY_BYTES) {
                            sinceCheck = 0L
                            if (freeBytes() < MIN_FREE_BYTES) { insufficient = true; break }
                        }
                        if (bytesPerSec > 0) {
                            sent += nb
                            val allowedMs = sent * 1000L / bytesPerSec
                            val waitMs = allowedMs - (System.currentTimeMillis() - t0)
                            if (waitMs > 0) Thread.sleep(waitMs)
                        }
                    }
                }
            } finally { try { out.close() } catch (_: Exception) {} }
            if (insufficient) {
                // On ABANDONNE le .part au lieu de le garder pour reprise : le conserver
                // immobiliserait precisement l'espace qui manque.
                tmp.delete()
                synchronized(lock) {
                    if (job.idMedia != 0) blocked.add(job.idMedia)
                    pressure = true
                }
                log("FREIN STOCKAGE en cours d'ecriture: ${job.filekey.take(12)} abandonne, " +
                    "${freeBytes() / 1048576} MB libres - la machine reste utilisable")
                throw IOException("insufficient-space")
            }

            val size = tmp.length()
            // Garde anti-troncature = taille annoncée. .part conservé sur incomplet → reprise.
            if (expected > 0 && size != expected) {
                if (size > expected) { tmp.delete(); throw IOException("oversized ($size>$expected)") }
                throw IOException("incomplete ($size/$expected) — .part gardé pour reprise")
            }
            if (!tmp.renameTo(fp)) throw IOException("rename failed")
            val mime = mimeFromKey(job.cacheKey) ?: job.mime ?: "application/octet-stream"
            synchronized(lock) {
                index[job.filekey] = Entry(job.cacheKey, mime, size, job.idMedia, System.currentTimeMillis(), job.priority)
                saveIndex()
            }
            // Mesure passive du débit (opt-in) : seulement les downloads COMPLETS, NON bridés
            // (sinon on mesurerait le throttle, pas la ligne) et assez gros pour être fiables.
            if (measureBandwidth && bandwidthKbps == 0 && !resuming && size >= MIN_MEASURE_BYTES) {
                val sec = (System.currentTimeMillis() - tStart) / 1000.0
                if (sec > 0.05) {
                    val kbps = size * 8 / 1000.0 / sec
                    measuredKbps = if (measuredKbps > 0) 0.6 * measuredKbps + 0.4 * kbps else kbps
                }
            }
            log("stored ${job.filekey.take(12)} (${"%.1f".format(size / 1048576.0)} MB${if (resuming) ", repris" else ""})")
        }
    }

    /** Purge tous les octets d'un id_media (kill-switch Q5 → vraie suppression fichier). */
    fun purgeMedia(idMedia: Int): Int {
        var removed = 0
        synchronized(lock) {
            val it = index.entries.iterator()
            while (it.hasNext()) {
                val (k, e) = it.next()
                if (e.idMedia == idMedia) {
                    try { fileFor(k).delete() } catch (_: Exception) {}
                    it.remove(); removed++
                }
            }
            if (removed > 0) saveIndex()
        }
        return removed
    }

    // ── Éviction (Q2) ────────────────────────────────────────────────────────────
    /** Épingle l'ensemble SERVI à ce player (= playlist courante). Le programmé n'est jamais évincé. */
    fun setPinned(cacheKeys: List<String>) {
        synchronized(lock) {
            pinned.clear()
            cacheKeys.forEach { pinned.add(keyFor(it)) }
        }
        enforceQuota()   // une nouvelle playlist libère l'ancien contenu
    }

    /**
     * Look-ahead : enregistre l'ensemble du contenu programmé futur (priorité = date de
     * diffusion) et met en file ce qui manque (téléchargé en fond, sous fenêtres). Met aussi à
     * jour la priorité des entrées déjà en cache → ranking d'éviction correct. Le contenu en
     * cache qui n'est NI épinglé NI dans ce set devient « stale » (évincé en premier).
     */
    fun setPrefetch(list: JSONArray?) {
        synchronized(lock) { prefetchKeys.clear() }
        if (list != null) for (i in 0 until list.length()) {
            val o = list.optJSONObject(i) ?: continue
            val ck = o.optString("cache_key").ifEmpty { null } ?: continue
            val fk = keyFor(ck)
            val prio = o.optLong("priority", 0L)
            synchronized(lock) {
                prefetchKeys[fk] = prio
                index[fk]?.priority = prio   // re-rank une entrée déjà en cache
            }
            enqueue(
                ck, o.optString("cache_checksum").ifEmpty { null },
                o.optString("mime_type").ifEmpty { null }, o.optString("url").ifEmpty { null },
                o.optInt("id_media"), prio, isPrefetch = true,
            )
        }
        enforceQuota()
    }

    /** Fraction du disque ENTIER utilisée (0..1). 0 si StatFs indisponible (→ pas d'éviction). */
    /**
     * Octets reellement libres. `Long.MAX_VALUE` si la mesure echoue => AUCUN frein : on ne
     * bloque jamais la diffusion sur une metrique qu'on ne sait pas prendre (meme regle que
     * `diskUsedRatio`, qui rend 0.0 pour desactiver l'eviction).
     */
    private fun freeBytes(): Long = try {
        StatFs(dir.path).availableBytes
    } catch (e: Exception) { Long.MAX_VALUE }

    /** Capacite totale, en octets. null si indisponible (le serveur s'abstiendra alors). */
    private fun diskTotalBytes(): Long? = try {
        val t = StatFs(dir.path).totalBytes
        if (t > 0L) t else null
    } catch (e: Exception) { null }

    private fun diskUsedRatio(): Double {
        return try {
            val sf = StatFs(dir.path)
            val total = sf.blockCountLong
            if (total <= 0L) 0.0 else 1.0 - (sf.availableBlocksLong.toDouble() / total.toDouble())
        } catch (e: Exception) { 0.0 }
    }

    /**
     * Évince le NON-épinglé tant que le disque dépasse HIGH, jusqu'à repasser sous LOW. Ordre :
     * (1) le « stale » (ni épinglé ni programmé) en premier, le plus ancien d'abord ; (2) puis le
     * programmé (prefetch) le plus LOINTAIN d'abord (priorité la + haute = date la + tardive). Le
     * programmé proche et la playlist courante (épinglée) sont les derniers servis. Si l'épinglé
     * seul ne tient pas → pression (alerte serveur), JAMAIS de drop.
     */
    fun enforceQuota() {
        synchronized(lock) {
            if (diskUsedRatio() < HIGH_WATERMARK) { pressure = false; return }
            val evictable = index.entries.filter { !pinned.contains(it.key) }.toMutableList()
            evictable.sortWith(Comparator { a, b ->
                val wa = prefetchKeys.containsKey(a.key); val wb = prefetchKeys.containsKey(b.key)
                if (wa != wb) return@Comparator if (wa) 1 else -1                 // stale (non voulu) évincé d'abord
                if (!wa) return@Comparator a.value.lastUsed.compareTo(b.value.lastUsed)  // stale : LRU (vieux d'abord)
                (prefetchKeys[b.key] ?: 0L).compareTo(prefetchKeys[a.key] ?: 0L)  // voulu : lointain d'abord
            })
            var freed = 0L
            for (entry in evictable) {
                if (diskUsedRatio() < LOW_WATERMARK) break
                val cat = if (prefetchKeys.containsKey(entry.key)) "far-future" else "stale"
                try { fileFor(entry.key).delete() } catch (_: Exception) {}
                index.remove(entry.key)
                freed += entry.value.size
                log("evicted ${entry.key.take(12)} (${"%.1f".format(entry.value.size / 1048576.0)} MB, $cat)")
            }
            if (freed > 0) saveIndex()
            pressure = diskUsedRatio() >= HIGH_WATERMARK
            if (pressure) {
                log("STORAGE PRESSURE: disque ${(diskUsedRatio() * 100).toInt()}% après éviction du non-épinglé — l'ensemble épinglé ne tient pas")
            } else if (freed > 0) {
                log("éviction: ${(freed / 1048576)} MB libérés, disque ${(diskUsedRatio() * 100).toInt()}%")
            }
        }
    }

    /** État de stockage pour le heartbeat (Q4 inventaire + alerte disque + débit mesuré). */
    fun getStorageStatus(): JSONObject = JSONObject().apply {
        val cachedIds = synchronized(lock) { index.values.map { it.idMedia }.filter { it != 0 }.distinct() }
        val dlIds = synchronized(lock) { downloading.toList() }
        put("disk_used_ratio", Math.round(diskUsedRatio() * 100) / 100.0)
        put("storage_pressure", pressure)
        put("cached_count", cachedIds.size)
        put("cached_ids", JSONArray(cachedIds))
        put("downloading_ids", JSONArray(dlIds))
        // Medias auxquels on a RENONCE faute de place, octets libres et capacite absolue.
        // Sans ces champs le frein serait muet cote serveur : l'ecran diffuserait une playlist
        // tronquee sans que personne ne sache pourquoi, et le controle a l'affectation serait
        // impossible (un ratio ne dit pas « 1,85 Go ne rentrent pas »).
        put("blocked_ids", JSONArray(synchronized(lock) { blocked.toList() }))
        put("free_bytes", freeBytes().let { if (it == Long.MAX_VALUE) JSONObject.NULL else it })
        put("disk_total_bytes", diskTotalBytes() ?: JSONObject.NULL)
        // Débit mesuré (opt-in) → nourrit l'ETA de readiness côté serveur (repli du plafond manuel).
        if (measureBandwidth && measuredKbps > 0) put("throughput_kbps", Math.round(measuredKbps))
    }
}
