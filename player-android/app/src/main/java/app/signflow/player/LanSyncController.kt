package app.signflow.player

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.abs

/**
 * LanSyncController — synchronisation inter-players en réseau local (§III.3),
 * portage Kotlin du `sync_lan.js` (Node) des players Electron. Protocole IDENTIQUE
 * (un player Android et un player Electron du même groupe se synchronisent ensemble).
 *
 * Transport : UDP broadcast 255.255.255.255:7778.
 * Élection du leader : priorité (master désigné=1 > normal=0) puis plus petit id_player.
 * Le leader diffuse `sync_play` toutes les 2 s ; les slaves corrigent sur dérive > 40 ms.
 * #2b : le leader annonce `switch_at` (instant absolu de sa prochaine bascule) → les
 * slaves alignent leur bascule d'item dessus (exige NTP partagé, cf. [[project-lan-sync]]).
 *
 * Particularité Android : l'audio/vidéo joue dans le WebView. Le contrôleur tourne en
 * natif (DatagramSocket) et marshale via MainActivity :
 *   - getState()       : position de lecture poussée par le renderer (nativeCall playback_pos).
 *   - onSyncReceived() : MainActivity dispatch('lan-adjust') au WebView (seek/playbackRate).
 *   - onSwitchHint()   : MainActivity dispatch('lan-switch') au WebView.
 *
 * Réception du broadcast sur WiFi → MulticastLock (sur Ethernet GbE c'est inutile mais
 * sans effet). Le socket bloquant est fermé pour débloquer le thread de réception.
 */
class LanSyncController(
    private val context: Context,
    private val idPlayer: Int,
    groupName: String?,
    isMaster: Boolean,
    private val onSyncReceived: (JSONObject) -> Unit,
    private val onSwitchHint: (JSONObject) -> Unit,
    private val getState: () -> JSONObject?,
) {
    private val group = groupName ?: "default"
    private val masterPriority = if (isMaster) 1 else 0

    @Volatile private var socket: DatagramSocket? = null
    @Volatile private var isLeader = false
    @Volatile private var running = false
    private val peers = ConcurrentHashMap<Int, Peer>()   // id_player -> {seenAt, priority, fp, ready}
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var recvThread: Thread? = null
    private var broadcastJob: Job? = null
    private var cleanupJob: Job? = null
    private var announceJob: Job? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    // Barrière de readiness (Q1) — portage de sync_lan.js. Le mur ne démarre une nouvelle
    // empreinte de contenu (fp) que quand tous les membres qui PARLENT le protocole l'ont
    // en cache ; filet anti-gel = timeout (au pire démarrage dégradé, jamais de freeze).
    @Volatile private var myFp: String? = null            // empreinte du contenu courant
    @Volatile private var myReady: Boolean = false        // true = tout le contenu de myFp en cache
    private var onBarrierRelease: ((String) -> Unit)? = null
    private val released = ConcurrentHashMap.newKeySet<String>()   // fps déjà relâchés
    private val fpSeenAt = ConcurrentHashMap<String, Long>()       // fp -> 1re apparition (timeout)
    @Volatile private var lastLeaderMsgAt = 0L   // dernier message d'un nœud qui me surpasse (hystérésis de promotion)
    @Volatile private var startedAt = 0L         // début d'écoute (fenêtre de découverte des pairs)

    private data class Peer(val seenAt: Long, val priority: Int, val fp: String?, val ready: Boolean)

    companion object {
        private const val TAG = "SignFlow/LanSync"
        private const val BROADCAST_PORT = 7778
        private const val BROADCAST_ADDR = "255.255.255.255"
        private const val SYNC_INTERVAL_MS = 2000L
        private const val DRIFT_THRESHOLD_MS = 40
        // 20s (relevé de 10s) : aux frontières d'item, un slave chargé rate des broadcasts >10s
        // → perdait le master de ses peers → flip-flop leader/slave (oscillation). 20s tolère ce jank.
        private const val PEER_TIMEOUT_MS = 20000L
        // Hystérésis de PROMOTION (anti flip-flop, > PEER_TIMEOUT) : on ne s'auto-promeut leader
        // que si le leader LÉGITIME est resté silencieux plus longtemps que ce délai. À une coupure
        // serveur le master LAN reste vivant ; un slave chargé en frontière (ou jank de reconnexion)
        // rate ses broadcasts >PEER_TIMEOUT → cleanup retire le master → auto-promotion → re-bascule
        // (oscillation). La grâce tolère ce trou transitoire ; seul un master vraiment mort failover.
        private const val PROMOTION_GRACE_MS = 35000L
        private const val CLEANUP_INTERVAL_MS = 5000L
        // Ré-annonce périodique (< PEER_TIMEOUT) : tout nœud reste visible des autres →
        // élection de leader robuste même sans serveur / si le master tombe.
        private const val ANNOUNCE_INTERVAL_MS = 3000L
        // Fenêtre de DÉCOUVERTE avant de pouvoir conclure « je suis seul dans mon groupe ». Un
        // nœud n'apprend l'existence de ses pairs que par leur annonce périodique : il faut donc
        // avoir écouté au moins un intervalle d'annonce pour distinguer « seul » de « pas encore
        // découvert ». Deux intervalles = tolère la perte d'un datagramme (broadcast UDP, WiFi).
        private const val DISCOVERY_WINDOW_MS = 2 * ANNOUNCE_INTERVAL_MS
        private const val BARRIER_TIMEOUT_MS = 25000L
    }

    fun setBarrierReleaseHandler(fn: (String) -> Unit) { onBarrierRelease = fn }

    /** Déclaré par MainActivity : empreinte du contenu courant + si tout est en cache local. */
    fun setReadiness(fp: String?, ready: Boolean) {
        val changed = (fp != myFp) || (ready != myReady)
        if (fp != null) fpSeenAt.putIfAbsent(fp, System.currentTimeMillis())
        myFp = fp
        myReady = ready
        if (changed) {
            announce()        // re-annonce immédiate de mon état de readiness
            checkBarrier()
        }
    }

    fun start() {
        if (socket != null) return
        // Départ de la fenêtre de découverte. Posé AVANT le bind : si le bind échoue, la fenêtre
        // expire quand même et le nœud bascule en solo — mode dégradé voulu (LAN cassé ⇒ on
        // diffuse seul plutôt que de rester figé), par un chemin explicite.
        startedAt = System.currentTimeMillis()
        try {
            // MulticastLock : nécessaire pour recevoir le broadcast UDP sur WiFi.
            try {
                val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                multicastLock = wifi.createMulticastLock("signflow-lan-sync").apply {
                    setReferenceCounted(false); acquire()
                }
            } catch (e: Exception) { Log.w(TAG, "MulticastLock indisponible: ${e.message}") }

            val s = DatagramSocket(null).apply {
                reuseAddress = true
                broadcast = true
                bind(InetSocketAddress(BROADCAST_PORT))
            }
            socket = s
            running = true
            Log.i(TAG, "Listening broadcast :$BROADCAST_PORT group=\"$group\" master=${masterPriority == 1}")

            recvThread = Thread { receiveLoop(s) }.also { it.isDaemon = true; it.start() }
            cleanupJob = scope.launch {
                while (isActive) { delay(CLEANUP_INTERVAL_MS); cleanupPeers() }
            }
            // Ré-annonce périodique : garde ce nœud visible des autres (followers compris)
            // pour une élection robuste même sans serveur / si le master disparaît.
            announceJob = scope.launch {
                while (isActive) {
                    delay(ANNOUNCE_INTERVAL_MS)
                    announce()
                    // L'élection n'était déclenchée QUE par le trafic des pairs (message reçu, ou
                    // pair retiré au cleanup). Un player SEUL dans son groupe n'a ni l'un ni
                    // l'autre : il ne devenait donc JAMAIS leader, `groupReady` n'était même jamais
                    // évalué, et sa barrière ne s'ouvrait que par le filet anti-gel de
                    // BARRIER_TIMEOUT_MS (25 s) — le filet devenu chemin nominal.
                    electLeader()
                    checkBarrier()
                }
            }
            announce()
        } catch (e: Exception) {
            Log.e(TAG, "start error: ${e.message}")
            stop()
        }
    }

    private fun receiveLoop(s: DatagramSocket) {
        val buf = ByteArray(8192)
        while (running) {
            try {
                val packet = DatagramPacket(buf, buf.size)
                s.receive(packet)
                val msg = try { JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8)) } catch (e: Exception) { continue }
                if (msg.optString("group") != group) continue
                if (msg.optInt("id_player", -1) == idPlayer) continue
                handleMessage(msg)
            } catch (e: Exception) {
                if (running) Log.w(TAG, "receive error: ${e.message}")
                else break   // socket fermé sur stop()
            }
        }
    }

    private fun announce() {
        broadcastPayload(JSONObject().apply {
            put("type", "sync_announce")
            put("id_player", idPlayer)
            put("group", group)
            put("priority", masterPriority)
            put("fp", myFp ?: JSONObject.NULL)
            put("ready", myReady)
        })
    }

    /** Enregistre/rafraîchit un peer (avec son empreinte + readiness pour la barrière). */
    private fun setPeer(msg: JSONObject) {
        val fp = if (msg.isNull("fp")) null else msg.optString("fp").ifEmpty { null }
        peers[msg.optInt("id_player")] = Peer(
            System.currentTimeMillis(), msg.optInt("priority", 0), fp, msg.optBoolean("ready", false),
        )
        if (fp != null) fpSeenAt.putIfAbsent(fp, System.currentTimeMillis())
        // Liveness du leader légitime (hystérésis de promotion) : un message d'un nœud qui me
        // surpasse à l'élection prouve qu'un leader candidat est vivant → ne pas me promouvoir.
        if (outranksMe(msg)) lastLeaderMsgAt = System.currentTimeMillis()
    }

    // Le nœud émetteur me SURPASSE-t-il à l'élection (= leader légitime potentiel) ?
    private fun outranksMe(msg: JSONObject): Boolean {
        val p = msg.optInt("priority", 0)
        val id = msg.optInt("id_player")
        return p > masterPriority || (p == masterPriority && id < idPlayer)
    }

    private fun broadcastPayload(payload: JSONObject) {
        val s = socket ?: return
        try {
            val bytes = payload.toString().toByteArray(Charsets.UTF_8)
            s.send(DatagramPacket(bytes, bytes.size, InetAddress.getByName(BROADCAST_ADDR), BROADCAST_PORT))
        } catch (e: Exception) {
            Log.w(TAG, "broadcast error: ${e.message}")
        }
    }

    private fun handleMessage(msg: JSONObject) {
        when (msg.optString("type")) {
            "sync_announce" -> {
                setPeer(msg)
                electLeader()
                checkBarrier()
            }
            "barrier_release" -> {
                // Un membre (leader ou timeout) a ouvert la barrière pour cette empreinte.
                val fp = if (msg.isNull("fp")) null else msg.optString("fp").ifEmpty { null }
                if (fp != null && fp == myFp && released.add(fp)) {
                    Log.i(TAG, "Barrier OPEN fp=${fp.take(8)} (relayé par ${msg.optInt("id_player")})")
                    onBarrierRelease?.invoke(fp)
                }
            }
            "sync_play" -> {
                setPeer(msg)
                checkBarrier()
                // Anti split-brain : ne suivre QUE le leader LÉGITIME (meilleure priorité / plus
                // petit id parmi self + peers). Si un usurpateur s'est auto-élu faute de voir le
                // vrai master et diffuse aussi des sync_play, on l'ignore — sinon le slave est
                // ballotté entre les deux et se cale sur le mauvais (vu : RPi/MINIX calés sur
                // l'AOpen prio0 au lieu du NUC prio1).
                if (!isLeader && msg.optInt("id_player") == bestLeaderId()) {
                    // start_offset_ms = position DANS LA VIDÉO (currentTime), indépendante de
                    // l'horloge machine → aucun ajustement d'horloge cross-machine (cf. sync_lan.js).
                    val leaderOffset = msg.optLong("start_offset_ms")
                    val state = getState()
                    val samePl = state != null && !state.isNull("id_playlist") &&
                        state.optInt("id_playlist") == msg.optInt("id_playlist")
                    val sameItem = samePl && state!!.optInt("currentIndex") == msg.optInt("start_index")
                    val myOffset = if (sameItem && state!!.has("currentOffsetMs")) state.optLong("currentOffsetMs") else null
                    val drift = if (myOffset != null) abs(leaderOffset - myOffset) else Long.MAX_VALUE

                    if (!samePl || !sameItem || drift > DRIFT_THRESHOLD_MS || msg.optBoolean("force")) {
                        onSyncReceived(JSONObject().apply {
                            put("id_playlist", msg.opt("id_playlist"))
                            put("start_index", msg.optInt("start_index"))
                            put("start_offset_ms", leaderOffset)
                            put("source", "lan")
                        })
                    }
                    // #2b : aligne la bascule du slave sur celle du maître (switch_at absolu).
                    if (samePl && !msg.isNull("switch_at") && msg.optLong("switch_at") > 0) {
                        onSwitchHint(JSONObject().apply {
                            put("start_index", msg.optInt("start_index"))
                            put("switch_at", msg.optLong("switch_at"))
                            put("next_index", if (msg.isNull("next_index")) JSONObject.NULL else msg.optInt("next_index"))
                        })
                    }
                }
            }
            "sync_bye" -> {
                peers.remove(msg.optInt("id_player"))
                electLeader()
            }
        }
    }

    /** Leader = priorité la plus haute, puis plus petit id_player (tie-break). */
    // Id du leader LÉGITIME = meilleure priorité (puis plus petit id) parmi self + peers.
    // Sert à l'élection ET au filtrage des sync_play reçus (anti split-brain).
    private fun bestLeaderId(): Int {
        var bestPriority = masterPriority
        var bestId = idPlayer
        for ((id, info) in peers) {
            val p = info.priority
            if (p > bestPriority || (p == bestPriority && id < bestId)) {
                bestPriority = p; bestId = id
            }
        }
        return bestId
    }

    private fun shouldBeLeader(): Boolean {
        if (bestLeaderId() != idPlayer) return false
        // Je ne connais AUCUN pair : soit je suis réellement seul (groupe d'un membre — légitime :
        // on active la synchro LAN sur un écran avant d'installer les suivants), soit je viens de
        // démarrer et je ne les ai pas encore entendus. Tant que la fenêtre de découverte n'est pas
        // écoulée, je ne tranche pas. Sans ce délai, un player qui REDÉMARRE dans un groupe existant
        // se croirait seul, s'auto-promeuvrait et ouvrirait sa barrière tout seul : il partirait
        // AVANT le groupe, exactement ce que la barrière existe pour empêcher.
        if (peers.isEmpty() && (System.currentTimeMillis() - startedAt) < DISCOVERY_WINDOW_MS) {
            return false
        }
        // Si un leader légitime m'a parlé récemment (< PROMOTION_GRACE_MS), trou transitoire
        // (frontière d'item / jank de reconnexion) → je reste SLAVE (anti flip-flop). Au-delà
        // (master vraiment disparu) → auto-promotion.
        if (lastLeaderMsgAt != 0L && (System.currentTimeMillis() - lastLeaderMsgAt) < PROMOTION_GRACE_MS) {
            return false
        }
        return true
    }

    @Synchronized
    private fun electLeader() {
        val wasLeader = isLeader
        isLeader = shouldBeLeader()
        if (isLeader && !wasLeader) {
            Log.i(TAG, "Elected LEADER (priority=$masterPriority, peers=${peers.keys.joinToString(",")})")
            startBroadcast()
        } else if (!isLeader && wasLeader) {
            Log.i(TAG, "Became SLAVE")
            stopBroadcast()
        }
    }

    private fun startBroadcast() {
        if (broadcastJob?.isActive == true) return
        broadcastJob = scope.launch {
            sendSync()
            while (isActive) { delay(SYNC_INTERVAL_MS); sendSync() }
        }
    }

    private fun stopBroadcast() {
        broadcastJob?.cancel()
        broadcastJob = null
    }

    private fun sendSync() {
        if (!isLeader) return
        val state = getState() ?: return
        if (state.isNull("id_playlist") || state.optInt("id_playlist") == 0) return
        broadcastPayload(JSONObject().apply {
            put("type", "sync_play")
            put("group", group)
            put("id_player", idPlayer)
            put("priority", masterPriority)
            put("id_playlist", state.opt("id_playlist"))
            put("start_index", state.optInt("currentIndex"))
            put("start_offset_ms", state.optLong("currentOffsetMs"))
            put("switch_at", if (state.isNull("switch_at")) JSONObject.NULL else state.optLong("switch_at"))
            put("next_index", if (state.isNull("next_index")) JSONObject.NULL else state.optInt("next_index"))
            put("fp", myFp ?: JSONObject.NULL)
            put("ready", myReady)
            put("sent_at", System.currentTimeMillis())
        })
    }

    fun forceSyncNow() {
        if (isLeader) scope.launch { sendSync() }
    }

    /**
     * Barrière (Q1) : ouvre l'empreinte courante quand le groupe est prêt (leader) ou au
     * timeout (filet anti-gel, tout membre). Un peer SANS fp (ancien player / flotte mixte)
     * est NON-bloquant. Idempotent par fp.
     */
    @Synchronized
    private fun checkBarrier() {
        val fp = myFp ?: return
        if (released.contains(fp)) return
        val seenAt = fpSeenAt[fp] ?: System.currentTimeMillis()
        val timedOut = (System.currentTimeMillis() - seenAt) > BARRIER_TIMEOUT_MS
        var groupReady = false
        if (isLeader) {
            // tous les peers QUI PARLENT le protocole (fp défini) doivent être sur la même
            // empreinte ET prêts ; + moi prêt. Les peers fp=null sont ignorés (non-bloquants).
            groupReady = myReady && peers.values.all { it.fp == null || (it.fp == fp && it.ready) }
        }
        if ((isLeader && groupReady) || timedOut) {
            if (!released.add(fp)) return
            val reason = if (isLeader && groupReady) "group-ready" else "timeout"
            Log.i(TAG, "Barrier RELEASE fp=${fp.take(8)} ($reason, leader=$isLeader)")
            broadcastPayload(JSONObject().apply {
                put("type", "barrier_release"); put("id_player", idPlayer)
                put("group", group); put("fp", fp)
            })
            onBarrierRelease?.invoke(fp)
        }
    }

    private fun cleanupPeers() {
        val cutoff = System.currentTimeMillis() - PEER_TIMEOUT_MS
        var removed = false
        val it = peers.entries.iterator()
        while (it.hasNext()) {
            val e = it.next()
            if (e.value.seenAt < cutoff) {
                Log.i(TAG, "Peer ${e.key} timed out, removing")
                it.remove(); removed = true
            }
        }
        if (removed) electLeader()   // le maître a pu disparaître → réélection
        // Tick régulier de la barrière : déclenche le timeout (filet anti-gel) et ré-évalue
        // group-ready si un peer prêt n'a pas redéclenché de message depuis.
        checkBarrier()
    }

    fun stop() {
        running = false
        stopBroadcast()
        cleanupJob?.cancel(); cleanupJob = null
        announceJob?.cancel(); announceJob = null
        socket?.let { s ->
            try { broadcastPayload(JSONObject().apply { put("type", "sync_bye"); put("id_player", idPlayer); put("group", group) }) } catch (_: Exception) {}
            try { s.close() } catch (_: Exception) {}
        }
        socket = null
        recvThread = null
        try { multicastLock?.release() } catch (_: Exception) {}
        multicastLock = null
        isLeader = false
        peers.clear()
        released.clear()
        fpSeenAt.clear()
        myFp = null
        myReady = false
        scope.cancel()
        Log.i(TAG, "Stopped")
    }
}
