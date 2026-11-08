package app.signflow.player

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.math.abs

/**
 * VodLanController — déclenchement VOD multi-cible AUTONOME en réseau local (Feature B, Phase 3).
 * Portage Kotlin du `vod_lan.js` (Node) des players Electron, protocole IDENTIQUE (un panneau
 * Electron peut déclencher une vidéo sur un player Android et inversement).
 *
 * Permet au panneau de contrôle local (§19.3) de lancer une vidéo sur N'IMPORTE QUEL player du
 * groupe VOD, SANS serveur (survit à une coupure internet — exigence §XIX).
 *
 * Transport : UDP broadcast 255.255.255.255:7779 (port DÉDIÉ, séparé du LAN sync 7778).
 * Sécurité : commandes signées HMAC-SHA256 avec le secret partagé par site (livré dans le sync
 * `vod_lan.secret`, caché offline). Anti-rejeu = fraîcheur ts (≤30s) + set de nonces.
 */
class VodLanController(
    private val context: Context,
    private val idPlayer: Int,
    @Volatile private var secret: String?,
    private val onCommand: (idMedia: Int, mode: String) -> Unit,
) {
    @Volatile private var socket: DatagramSocket? = null
    @Volatile private var running = false
    private var recvThread: Thread? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private val seen = ConcurrentHashMap<String, Long>()   // nonce -> seenAt (anti-rejeu)
    private val rng = SecureRandom()

    companion object {
        private const val TAG = "SignFlow/VodLan"
        private const val VOD_LAN_PORT = 7779
        private const val BROADCAST_ADDR = "255.255.255.255"
        private const val FRESH_MS = 30000L
        private const val NONCE_TTL_MS = 60000L
    }

    /** Re-clé sans redémarrer le socket (le secret peut changer à un re-sync). */
    fun updateSecret(s: String?) { secret = s }

    private fun canonical(m: JSONObject): String =
        "vod_play|${m.optInt("id_player")}|${m.optInt("id_media")}|${m.optString("mode")}|${m.optLong("ts")}|${m.optString("nonce")}"

    private fun sign(data: String, key: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal(data.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }

    fun start() {
        if (socket != null) return
        try {
            try {
                val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                multicastLock = wifi.createMulticastLock("signflow-vod-lan").apply {
                    setReferenceCounted(false); acquire()
                }
            } catch (e: Exception) { Log.w(TAG, "MulticastLock indisponible: ${e.message}") }

            val s = DatagramSocket(null).apply {
                reuseAddress = true
                broadcast = true
                bind(InetSocketAddress(VOD_LAN_PORT))
            }
            socket = s
            running = true
            recvThread = Thread { receiveLoop(s) }.also { it.isDaemon = true; it.start() }
            Log.i(TAG, "Listening VOD trigger broadcast :$VOD_LAN_PORT self=$idPlayer")
        } catch (e: Exception) {
            Log.e(TAG, "start error: ${e.message}")
            stop()
        }
    }

    fun stop() {
        running = false
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        try { recvThread?.interrupt() } catch (_: Exception) {}
        recvThread = null
        try { multicastLock?.release() } catch (_: Exception) {}
        multicastLock = null
        seen.clear()
    }

    /** Diffuse une commande de lecture VOD vers un player cible (signée). */
    fun broadcast(idTarget: Int, idMedia: Int, mode: String) {
        val s = socket ?: return
        val key = secret ?: return
        val norm = when (mode) { "loop" -> "loop"; "stop" -> "stop"; else -> "once" }
        val nonce = ByteArray(8).also { rng.nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val m = JSONObject()
            .put("cmd", "vod_play")
            .put("id_player", idTarget)
            .put("id_media", idMedia)
            .put("mode", norm)
            .put("ts", System.currentTimeMillis())
            .put("nonce", nonce)
        m.put("sig", sign(canonical(m), key))
        try {
            val bytes = m.toString().toByteArray(Charsets.UTF_8)
            s.send(DatagramPacket(bytes, bytes.size, InetAddress.getByName(BROADCAST_ADDR), VOD_LAN_PORT))
        } catch (e: Exception) { Log.w(TAG, "broadcast error: ${e.message}") }
    }

    private fun receiveLoop(s: DatagramSocket) {
        val buf = ByteArray(4096)
        while (running) {
            try {
                val packet = DatagramPacket(buf, buf.size)
                s.receive(packet)
                val m = try { JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8)) } catch (e: Exception) { continue }
                handleMessage(m)
            } catch (e: Exception) {
                if (running) Log.w(TAG, "receive error: ${e.message}") else break
            }
        }
    }

    private fun handleMessage(m: JSONObject) {
        val key = secret ?: return
        if (m.optString("cmd") != "vod_play") return
        if (m.optInt("id_player", -1) != idPlayer) return              // ne joue que ce qui ME cible
        val ts = m.optLong("ts", 0)
        if (ts == 0L || abs(System.currentTimeMillis() - ts) > FRESH_MS) return  // fraîcheur
        val nonce = m.optString("nonce")
        if (nonce.isEmpty() || seen.containsKey(nonce)) return         // anti-rejeu
        val expected = sign(canonical(m), key)
        val sig = m.optString("sig")
        if (sig.length != expected.length || !constantTimeEquals(sig, expected)) return
        seen[nonce] = System.currentTimeMillis()
        sweepNonces()
        try { onCommand(m.optInt("id_media"), m.optString("mode")) } catch (e: Exception) { Log.w(TAG, "onCommand: ${e.message}") }
    }

    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var r = 0
        for (i in a.indices) r = r or (a[i].code xor b[i].code)
        return r == 0
    }

    private fun sweepNonces() {
        val cutoff = System.currentTimeMillis() - NONCE_TTL_MS
        val it = seen.entries.iterator()
        while (it.hasNext()) if (it.next().value < cutoff) it.remove()
    }
}
