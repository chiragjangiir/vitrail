package app.vitrail.player

import android.app.ActivityManager
import android.content.Context
import android.media.MediaCodecList
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.StatFs
import android.util.Log
import android.view.WindowManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

private const val TAG = "SignFlow/WS"
private const val HEARTBEAT_INTERVAL_MS = 10_000L
// Watchdog de liveness : re-vérification périodique de la connexion sur le main looper
// (résilient à une veille qui gèle le scope IO / le delay() du reconnect OkHttp).
private const val WATCHDOG_INTERVAL_MS = 15_000L
private const val PLAYER_VERSION = BuildConfig.VERSION_NAME

class PlayerWebSocketClient(
    private val context: Context,
    private val config: PlayerConfig,
    private val onConnected: () -> Unit,
    private val onDisconnected: () -> Unit,
    private val onMessage: (JSONObject) -> Unit,
    private val onSetupRequired: () -> Unit,
    private val storeStatus: () -> JSONObject? = { null },
) {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val httpClient = OkHttpClient.Builder()
        .pingInterval(25, TimeUnit.SECONDS)
        .build()

    private var ws: WebSocket? = null
    private var heartbeatJob: Job? = null
    private var reconnectJob: Job? = null
    private var reconnectAttempts = 0
    // Fenêtre d'étalement de la TOUTE PREMIÈRE connexion après le démarrage (P3.12).
    private val STARTUP_SPREAD_MS = 5_000
    private var startupSpreadDone = false
    // Liveness : état réel de la connexion + watchdog résilient (main looper). Le reconnect
    // OkHttp (onFailure→scheduleReconnect) peut ne JAMAIS repartir après une veille (signal de
    // coupure non émis, ou delay() du reconnect gelé puis non repris) → le player restait
    // déconnecté indéfiniment sans tenter quoi que ce soit. Le watchdog relance alors connect().
    @Volatile private var connected = false
    /** État réel de la connexion — consommé par le pilote auto-power offline (MainActivity). */
    val isConnected: Boolean get() = connected
    private var watchdogStarted = false
    private val watchdogHandler = Handler(Looper.getMainLooper())
    private val watchdogRunnable = object : Runnable {
        override fun run() {
            try { watchdogTick() } catch (e: Exception) { Log.w(TAG, "watchdog: ${e.message}") }
            watchdogHandler.postDelayed(this, WATCHDOG_INTERVAL_MS)
        }
    }

    private var lastCpuTotal = 0L
    private var lastCpuIdle = 0L
    private var cachedWanIp: String? = null
    private var wanIpFetchedAt = 0L
    val lastWanIp: String? get() = cachedWanIp   // IP WAN cachée (overlay maintenance)
    private var baseCaps: JSONObject? = null   // display_modes + décodage (calculés 1×, coûteux)

    fun connect() {
        if (!config.isConfigured()) {
            onSetupRequired()
            return
        }
        // Étalement d'entrée : une seule fois, au premier appel après le démarrage. Le
        // jitter du backoff ne joue que si le serveur est injoignable ; quand un site
        // retrouve le courant et que le serveur, lui, n'a jamais bougé, la première
        // connexion réussit du premier coup et les écrans arrivent GROUPÉS — d'autant plus
        // qu'un parc homogène boote en même temps. On tire ici un retard par écran.
        // Coût assumé : quelques secondes avant le retour à l'antenne d'un écran redémarré
        // seul. Les reconnexions suivantes passent par reconnectDelayMs(), qui a son
        // propre jitter.
        if (!startupSpreadDone) {
            startupSpreadDone = true
            val spread = (Math.random() * STARTUP_SPREAD_MS).toLong()
            if (spread > 0) {
                Log.i(TAG, "Startup spread: ${spread}ms")
                reconnectJob = scope.launch {
                    delay(spread)
                    if (isActive) connect()
                }
                return
            }
        }
        startWatchdog()   // filet de secours indépendant du reconnect OkHttp (cf. watchdogTick)
        val wsUrl = config.backendUrl
            .replace("https://", "wss://")
            .replace("http://", "ws://")
            .trimEnd('/') + "/api/v1/ws/player?token=${config.playerToken}"

        val request = Request.Builder().url(wsUrl).build()
        ws = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "Connected")
                connected = true
                reconnectAttempts = 0
                reconnectJob?.cancel()
                reconnectJob = null
                baseCaps = null   // re-remonter les modes/décodage après chaque (re)connexion
                onConnected()
                startHeartbeat()
                flushEventQueue()   // rejoue les alertes (ex. url_display inaccessible) accumulées offline
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    onMessage(JSONObject(text))
                } catch (e: Exception) {
                    Log.e(TAG, "Invalid message: ${e.message}")
                }
            }

            // Défensif : certains messages serveur peuvent arriver en trame BINAIRE
            // (ex. forward d'un message redis en bytes). On les traite comme du texte.
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                try {
                    onMessage(JSONObject(bytes.utf8()))
                } catch (e: Exception) {
                    Log.e(TAG, "Invalid binary message: ${e.message}")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.w(TAG, "Closed ($code): $reason")
                connected = false
                stopHeartbeat()
                onDisconnected()
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "Failure: ${t.message}")
                connected = false
                stopHeartbeat()
                onDisconnected()
                scheduleReconnect()
            }
        })
    }

    fun send(json: JSONObject) {
        ws?.send(json.toString())
    }

    // File d'événements sortants (player → serveur), ex. alerte url_display inaccessible (§XXV.2).
    // Envoi immédiat si le WS est ouvert, sinon file bornée rejouée à la reconnexion.
    private val eventQueue = java.util.Collections.synchronizedList(mutableListOf<JSONObject>())

    fun reportEvent(ev: JSONObject) {
        ev.put("type", "player:event")
        if (connected) {
            try { ws?.send(ev.toString()); return } catch (e: Exception) { /* close suivra → on file */ }
        }
        synchronized(eventQueue) {
            eventQueue.add(ev)
            while (eventQueue.size > 100) eventQueue.removeAt(0)
        }
    }

    private fun flushEventQueue() {
        val pending: List<JSONObject>
        synchronized(eventQueue) { pending = ArrayList(eventQueue); eventQueue.clear() }
        for (ev in pending) { try { ws?.send(ev.toString()) } catch (e: Exception) { /* ignore */ } }
    }

    fun close() {
        watchdogStarted = false
        watchdogHandler.removeCallbacks(watchdogRunnable)
        reconnectJob?.cancel()
        heartbeatJob?.cancel()
        connected = false
        ws?.close(1000, "Client shutdown")
        scope.cancel()
    }

    private fun startWatchdog() {
        if (watchdogStarted) return
        watchdogStarted = true
        watchdogHandler.postDelayed(watchdogRunnable, WATCHDOG_INTERVAL_MS)
    }

    /**
     * Filet de secours de connexion, sur le main looper (donc résilient à une veille qui
     * gèle le scope IO ou le `delay()` du reconnect). Si on est déconnecté ET qu'aucune
     * reconnexion OkHttp n'est en cours (le loop a pu mourir : signal de coupure non émis,
     * ou coroutine de reconnect gelée puis non reprise au réveil), on relance connect()
     * nous-mêmes. Sans faux positif : on ne touche à rien tant qu'on est connecté.
     */
    private fun watchdogTick() {
        if (!connected && reconnectJob?.isActive != true) {
            Log.w(TAG, "Watchdog: déconnecté sans reconnexion en cours → reconnect")
            forceReconnect()
        }
    }

    private fun forceReconnect() {
        reconnectJob?.cancel(); reconnectJob = null
        reconnectAttempts = 0
        try { ws?.cancel() } catch (_: Exception) {}
        ws = null
        connect()
    }

    /**
     * Délai avant la prochaine tentative : backoff exponentiel 2s/4s/8s/16s/30s, tiré au
     * hasard dans la MOITIÉ HAUTE de sa borne (« equal jitter »).
     *
     * Sans ce tirage, le backoff est entièrement déterministe : après une coupure de
     * courant ou un redémarrage serveur, tous les écrans repartent au même instant,
     * échouent au même instant, et retentent à exactement 2s, 4s, 8s… Leurs tentatives
     * restent EN PHASE, et la rafale se rejoue à chaque palier au lieu de se disperser.
     *
     * La moitié basse est écartée volontairement : un jitter « plein » (0 à la borne)
     * peut rendre un délai quasi nul et faire marteler un serveur qui vient de repartir.
     */
    internal fun reconnectDelayMs(attempts: Int): Long {
        val ceiling = min(30_000L, (2_000L * 2.0.pow(attempts.toDouble())).toLong())
        return ceiling / 2 + (Math.random() * (ceiling / 2)).toLong()
    }

    private fun scheduleReconnect() {
        if (reconnectJob?.isActive == true) return
        val delay = reconnectDelayMs(reconnectAttempts)
        reconnectAttempts++
        Log.i(TAG, "Reconnect in ${delay}ms (attempt $reconnectAttempts)")
        reconnectJob = scope.launch {
            delay(delay)
            if (isActive) connect()
        }
    }

    private fun startHeartbeat() {
        stopHeartbeat()
        heartbeatJob = scope.launch {
            while (isActive) {
                delay(HEARTBEAT_INTERVAL_MS)
                sendHeartbeat()
            }
        }
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }

    private suspend fun sendHeartbeat() {
        try {
            val actManager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val memInfo = ActivityManager.MemoryInfo()
            actManager.getMemoryInfo(memInfo)
            val ramPct = if (memInfo.totalMem > 0)
                ((memInfo.totalMem - memInfo.availMem) * 100.0 / memInfo.totalMem).roundToInt()
            else 0

            val statFs = StatFs(Environment.getDataDirectory().path)
            val diskPct = if (statFs.totalBytes > 0)
                ((statFs.totalBytes - statFs.availableBytes) * 100L / statFs.totalBytes).toInt()
            else 0

            val payload = JSONObject().apply {
                put("type", "player:status")
                put("status", "online")
                // Champ OMIS si la mesure est indisponible : le serveur fait `msg.get("cpu")`
                // → None → colonne NULL. Un `0` s'afficherait comme une vraie valeur.
                getCpuUsage()?.let { put("cpu", it) }
                put("ram", ramPct)
                put("disk", diskPct)
                put("ip_address", getLanIp())
                put("mac_address", getMacAddress())
                put("wan_ip", getWanIp())
                put("player_version", PLAYER_VERSION)
                put("player_os", "android-${Build.SUPPORTED_ABIS.firstOrNull() ?: "arm64"}")
            }
            // Capacités du player (une fois par connexion) → persistées telles quelles dans le
            // JSONB capabilities (le handler player:status REMPLACE le dict) : on envoie donc
            // modes d'affichage ET décodage matériel ENSEMBLE dans le MÊME objet.
            //   - display_modes : modes "WxH@Hz" réels → le drawer CMS propose ces modes-là.
            //   - décodage HW (MediaCodec) : équivalent Android de detect-capabilities.sh
            //     (vaapi/v4l2/d3d11) → la matrice de conformité (player_capabilities.decode_health)
            //     classe le player en "hardware" et lève/efface les alertes 4K/60fps.
            // Le handler player:status REMPLACE le dict capabilities → on renvoie l'objet
            // COMPLET à chaque heartbeat (display_modes + décodage cachés une fois car
            // coûteux ; store recalculé à chaque fois car il change → inventaire Q4 à jour).
            if (baseCaps == null) {
                val base = JSONObject()
                val modes = getDisplayModes()
                if (modes.isNotEmpty()) base.put("display_modes", JSONArray(modes))
                mergeDecodeCapabilities(base)
                baseCaps = base
            }
            val caps = JSONObject(baseCaps.toString())   // clone (ne pas muter le cache)
            storeStatus()?.let { caps.put("store", it) }
            // Fuseau horaire OS réel (drawer CMS : détection de mismatch avec le site — le
            // pilotage offline auto-power compare ses fenêtres locales à CETTE horloge).
            caps.put("timezone", java.util.TimeZone.getDefault().id)
            if (caps.length() > 0) payload.put("capabilities", caps)
            // send() == false ⇒ le WebSocket est en fermeture/fermé : on marque déconnecté
            // pour que le watchdog relance la connexion (le heartbeat envoyait jusque-là dans
            // le vide sur un socket mort, sans que rien ne le détecte).
            val ok = ws?.send(payload.toString()) ?: false
            if (!ok) connected = false
        } catch (e: Exception) {
            Log.e(TAG, "Heartbeat error: ${e.message}")
        }
    }

    /**
     * Décodage vidéo matériel via MediaCodec → bloc capabilities compatible avec
     * `backend/app/services/player_capabilities.py` (hw_decode/hw_decode_active/codecs/…).
     *
     * Sur une box de signage Android, le décodage des codecs principaux (H.264/HEVC/VP9/AV1)
     * est assuré par des décodeurs MATÉRIELS (le WebView/MediaCodec les utilise par défaut) —
     * contrairement à Electron/Intel-Linux où la VA-API ne se déclenche pas (cf. EVOLUTIONS).
     * On énumère les décodeurs, on garde les accélérés matériellement (API 29+ :
     * `isHardwareAccelerated` ; pré-29 : heuristique sur le préfixe du nom — les décodeurs
     * logiciels d'Android sont `OMX.google.*` / `c2.android.*`).
     */
    private fun mergeDecodeCapabilities(caps: JSONObject) {
        try {
            val mimeToCodec = mapOf(
                "video/avc" to "h264",
                "video/hevc" to "hevc",
                "video/x-vnd.on2.vp9" to "vp9",
                "video/vp8" to "vp8",
                "video/av01" to "av1",
            )
            val codecs = linkedSetOf<String>()
            val list = MediaCodecList(MediaCodecList.REGULAR_CODECS)
            for (info in list.codecInfos) {
                if (info.isEncoder) continue
                val isHw = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    info.isHardwareAccelerated
                } else {
                    val n = info.name.lowercase()
                    !n.startsWith("omx.google.") && !n.startsWith("c2.android.")
                }
                if (!isHw) continue
                for (type in info.supportedTypes) {
                    mimeToCodec[type.lowercase()]?.let { codecs.add(it) }
                }
            }
            caps.put("hw_decode", "mediacodec")
            caps.put("hw_decode_active", codecs.isNotEmpty())
            caps.put("sf_hw_decode", "auto")
            caps.put("codecs", JSONArray(codecs.toList()))
            caps.put("gpu_vendor", Build.MANUFACTURER.lowercase())
            caps.put("gpu_model", Build.MODEL)
            caps.put("detection_source", "runtime")
            Log.i(TAG, "[Decode] mediacodec hw codecs=${codecs.joinToString(",").ifEmpty { "-" }}")
        } catch (e: Exception) {
            Log.w(TAG, "mergeDecodeCapabilities error: ${e.message}")
        }
    }

    /** Modes d'affichage supportés au format "WxH@Hz" (ex. "3840x2160@59"). */
    private fun getDisplayModes(): List<String> {
        return try {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            @Suppress("DEPRECATION")
            wm.defaultDisplay.supportedModes
                .map { "${it.physicalWidth}x${it.physicalHeight}@${it.refreshRate.roundToInt()}" }
                .distinct()
        } catch (e: Exception) {
            Log.w(TAG, "getDisplayModes error: ${e.message}")
            emptyList()
        }
    }

    /**
     * Charge CPU **DU PLAYER**, en % d'une machine entière (0-100, tous cœurs confondus).
     *
     * 🔴 L'implémentation précédente lisait `/proc/stat` (charge SYSTÈME). Ce fichier est
     * **interdit aux applications depuis Android 8** : la lecture échouait, le `catch`
     * renvoyait `0.0`, et le CMS affichait « 0 % » sans que rien ne signale l'échec — un
     * levier inerte. Constaté par Ed le 2026-07-30 : Xiaomi Stick (Android 14) à 0, quand le
     * MINIX (Android 9), qui a encore l'accès, remontait 20,7 %.
     *
     * `/proc/self/stat` reste lisible par le processus lui-même, quelle que soit la version.
     * On mesure donc la consommation de SignFlow plutôt que celle du système — décision d'Ed :
     * c'est l'information utile pour de la signalétique (« mon player sature-t-il ? »), sans
     * le bruit des services Google. ⚠️ Sémantique différente des autres plateformes, où
     * `cpu_usage` reste la charge système.
     *
     * Renvoie **null** si même cette lecture échoue : l'appelant omet alors le champ et le
     * serveur enregistre NULL. Jamais de `0` trompeur — mieux vaut « inconnu » que « faux ».
     */
    private fun getCpuUsage(): Double? {
        return try {
            // Le champ `comm` (2ᵉ) peut contenir espaces et parenthèses : on repart de la
            // DERNIÈRE `)`. Après elle, les jetons sont les champs 3..N — donc utime (14ᵉ)
            // est à l'indice 11 et stime (15ᵉ) à l'indice 12.
            val raw = File("/proc/self/stat").readText()
            val after = raw.substring(raw.lastIndexOf(')') + 1).trim().split(" ")
            val utime = after.getOrNull(11)?.toLongOrNull() ?: return null
            val stime = after.getOrNull(12)?.toLongOrNull() ?: return null
            val ticks = utime + stime
            val now = android.os.SystemClock.elapsedRealtime()

            val prevTicks = lastCpuTotal
            val prevAt = lastCpuIdle          // réutilisé : instant de la mesure précédente (ms)
            lastCpuTotal = ticks
            lastCpuIdle = now
            if (prevAt == 0L) return null     // 1re mesure : aucun intervalle, donc rien à dire

            val elapsedMs = now - prevAt
            if (elapsedMs <= 0L) return null
            val hz = android.system.Os.sysconf(android.system.OsConstants._SC_CLK_TCK)
                .takeIf { it > 0 } ?: 100L
            val cores = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
            val pct = (ticks - prevTicks) * 1000.0 / hz / elapsedMs * 100.0 / cores
            (pct.coerceIn(0.0, 100.0) * 10).roundToInt() / 10.0
        } catch (e: Exception) {
            Log.w(TAG, "CPU indisponible: ${e.message}")
            null
        }
    }

    private fun getLanIp(): String? {
        return try {
            NetworkInterface.getNetworkInterfaces()?.asSequence()
                ?.flatMap { it.inetAddresses.asSequence() }
                ?.firstOrNull { !it.isLoopbackAddress && it is Inet4Address }
                ?.hostAddress
        } catch (e: Exception) { null }
    }

    private fun getMacAddress(): String? {
        // Returns null on Android 10+ without root (privacy restriction)
        return try {
            NetworkInterface.getNetworkInterfaces()?.asSequence()
                ?.firstOrNull { iface ->
                    !iface.isLoopback &&
                        iface.hardwareAddress != null &&
                        iface.inetAddresses.asSequence().any { !it.isLoopbackAddress && it is Inet4Address }
                }
                ?.hardwareAddress
                ?.joinToString(":") { "%02x".format(it) }
        } catch (e: Exception) { null }
    }

    private suspend fun getWanIp(): String? {
        val now = System.currentTimeMillis()
        if (cachedWanIp != null && now - wanIpFetchedAt < 5 * 60 * 1000) return cachedWanIp
        return try {
            val req = Request.Builder().url("https://api.ipify.org?format=json").build()
            val body = withContext(Dispatchers.IO) {
                httpClient.newCall(req).execute().use { it.body?.string() }
            }
            cachedWanIp = body?.let { JSONObject(it).optString("ip") }
            wanIpFetchedAt = now
            cachedWanIp
        } catch (e: Exception) { cachedWanIp }
    }
}
