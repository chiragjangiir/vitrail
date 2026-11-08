package app.signflow.player

import android.util.Log
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.math.max
import kotlin.math.min

/**
 * LocalControlServer — Store Control Panel LAN (§19.3), portage Kotlin du
 * `local_control_server.js` (Node) des players Electron.
 *
 * Mini-serveur HTTP embarqué dans le player Android (NanoHTTPD), accessible
 * uniquement sur le LAN. L'opérateur magasin scanne un QR code (généré par le CMS)
 * → ouvre la SPA (asset `control/control.html`, IDENTIQUE à celle des Electron) sur
 * son téléphone → pilote l'audio in-store (paniers, ratio, volume, annonce).
 *
 * Particularité Android vs Electron : l'audio tourne dans le WebView (audio_player.js),
 * pas dans le process natif. Donc :
 *   - getStatus()  = dernier état audio poussé par le renderer (nativeCall control_status),
 *                    caché côté MainActivity — lu de façon synchrone ici.
 *   - onAction(a)  = MainActivity applique localement (dispatch 'control:apply' au WebView)
 *                    ET transmet au backend (WS local_control:action, persistance + audit).
 *   - getProfile() = profil reçu dans player:sync (msg.local_control).
 *
 * Sécurité (identique au Node) : LAN-only (IP privées/loopback), token QR → session
 * HMAC locale 4h, rate-limit 10 req/min/IP sur l'auth (anti-bruteforce).
 */
class LocalControlServer(
    port: Int,
    private val spaHtml: String,
    private val getPlayerName: () -> String,
    private val getProfile: () -> JSONObject?,
    private val getStatus: () -> JSONObject,
    private val getVodMedia: () -> JSONArray = { JSONArray() },   // VOD à la demande (Feature B Phase 3)
    private val getVodPeers: () -> JSONArray = { JSONArray() },   // pairs ciblables (trigger multi-cible LAN)
    private val getSelfId: () -> Int = { 0 },                     // id_player de CE player
    private val onAction: (JSONObject) -> Unit,
) : NanoHTTPD(port) {

    private val secret = ByteArray(32).also { SecureRandom().nextBytes(it) }  // régénéré à chaque boot
    private val rate = ConcurrentHashMap<String, MutableList<Long>>()         // ip -> timestamps

    companion object {
        private const val TAG = "SignFlow/LocalCtrl"
        private const val SESSION_TTL_MS = 4L * 60 * 60 * 1000   // 4h (§19.3)
        private const val RATE_LIMIT = 10                         // requêtes
        private const val RATE_WINDOW_MS = 60_000L               // par minute

        // 429 absent de l'enum NanoHTTPD → status custom.
        private val TOO_MANY = object : Response.IStatus {
            override fun getDescription() = "429 Too Many Requests"
            override fun getRequestStatus() = 429
        }

        fun isPrivateAddr(addrRaw: String?): Boolean {
            if (addrRaw.isNullOrEmpty()) return false
            val ip = addrRaw.removePrefix("::ffff:")
            if (ip == "127.0.0.1" || ip == "::1" || ip == "localhost") return true
            if (ip.startsWith("10.")) return true
            if (ip.startsWith("192.168.")) return true
            if (ip.startsWith("169.254.")) return true   // link-local
            if (ip.startsWith("fe80:")) return true
            Regex("^172\\.(\\d+)\\.").find(ip)?.let {
                val o = it.groupValues[1].toIntOrNull() ?: return@let
                if (o in 16..31) return true
            }
            return false
        }
    }

    fun startSafe() {
        try {
            start(SOCKET_READ_TIMEOUT, true)   // thread daemon (défaut NanoHTTPD)
            Log.i(TAG, "Listening on :$listeningPort")
        } catch (e: Exception) {
            Log.e(TAG, "start error: ${e.message}")
        }
    }

    fun stopSafe() {
        try { stop() } catch (_: Exception) {}
        Log.i(TAG, "Stopped")
    }

    // ── Session HMAC ─────────────────────────────────────────────────────────────

    private fun b64url(bytes: ByteArray): String =
        Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)

    private fun hmac(payload: String): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret, "HmacSHA256"))
        return mac.doFinal(payload.toByteArray(Charsets.UTF_8))
    }

    private fun issueSession(): String {
        val payload = b64url(JSONObject().put("exp", System.currentTimeMillis() + SESSION_TTL_MS)
            .toString().toByteArray(Charsets.UTF_8))
        return "$payload.${b64url(hmac(payload))}"
    }

    private fun verifySession(token: String?): Boolean {
        if (token.isNullOrEmpty()) return false
        val parts = token.split(".")
        if (parts.size != 2) return false
        val (payload, sig) = parts
        val expected = b64url(hmac(payload))
        if (sig.length != expected.length) return false
        if (!MessageDigest.isEqual(sig.toByteArray(), expected.toByteArray())) return false
        return try {
            val data = JSONObject(String(Base64.getUrlDecoder().decode(payload), Charsets.UTF_8))
            val exp = data.optLong("exp", 0)
            exp > System.currentTimeMillis()
        } catch (e: Exception) { false }
    }

    // ── Rate limit ───────────────────────────────────────────────────────────────

    private fun rateOk(ip: String): Boolean {
        val now = System.currentTimeMillis()
        val hits = rate.getOrPut(ip) { mutableListOf() }
        synchronized(hits) {
            hits.removeAll { now - it >= RATE_WINDOW_MS }
            hits.add(now)
            return hits.size <= RATE_LIMIT
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    private fun json(status: Response.IStatus, obj: JSONObject): Response {
        val r = newFixedLengthResponse(status, "application/json", obj.toString())
        r.addHeader("Cache-Control", "no-store")
        return r
    }

    private fun jsonOk(obj: JSONObject) = json(Response.Status.OK, obj)
    private fun err(status: Response.IStatus, code: String) = json(status, JSONObject().put("error", code))

    private fun readBody(session: IHTTPSession): JSONObject {
        return try {
            val files = HashMap<String, String>()
            session.parseBody(files)
            val data = files["postData"]
            if (data.isNullOrBlank()) JSONObject() else JSONObject(data)
        } catch (e: Exception) { JSONObject() }
    }

    private fun authed(session: IHTTPSession): Boolean {
        val h = session.headers["authorization"] ?: return false
        val m = Regex("^Bearer\\s+(.+)$").find(h) ?: return false
        return verifySession(m.groupValues[1])
    }

    private fun basketAllowed(profile: JSONObject, id: Int): Boolean {
        val allow = profile.optJSONArray("allowed_basket_ids") ?: return true
        for (i in 0 until allow.length()) if (allow.optInt(i) == id) return true
        return false
    }

    private fun clampPct(v: Int) = max(0, min(100, v))

    // ── Routeur ──────────────────────────────────────────────────────────────────

    override fun serve(session: IHTTPSession): Response {
        return try { route(session) }
        catch (e: Exception) { Log.e(TAG, "serve error: ${e.message}"); err(Response.Status.INTERNAL_ERROR, "server_error") }
    }

    private fun route(session: IHTTPSession): Response {
        val ip = session.remoteIpAddress
        if (!isPrivateAddr(ip)) {
            return newFixedLengthResponse(Response.Status.FORBIDDEN, MIME_PLAINTEXT, "Forbidden (LAN only)")
        }

        val method = session.method
        var path = session.uri.trimEnd('/')
        if (path.isEmpty()) path = "/control"

        // SPA (shell, sans auth)
        if (method == Method.GET && (path == "/control" || path == "/")) {
            val r = newFixedLengthResponse(Response.Status.OK, "text/html; charset=utf-8", spaHtml)
            r.addHeader("Cache-Control", "no-store")
            return r
        }

        val profile = getProfile() ?: return err(Response.Status.SERVICE_UNAVAILABLE, "control_unavailable")

        // Auth : échange token QR → session (seule route rate-limitée — anti-bruteforce)
        if (method == Method.POST && path == "/control/auth") {
            if (!rateOk(ip)) return err(TOO_MANY, "rate_limited")
            val body = readBody(session)
            val given = body.optString("token")
            val expected = profile.optString("token")
            val ok = given.isNotEmpty() && expected.isNotEmpty() &&
                given.length == expected.length &&
                MessageDigest.isEqual(given.toByteArray(), expected.toByteArray())
            if (!ok) return err(Response.Status.UNAUTHORIZED, "invalid_token")
            return jsonOk(JSONObject().apply {
                put("session", issueSession())
                put("player_name", getPlayerName())
                put("permissions", JSONObject().apply {
                    put("role", profile.optString("role"))
                    put("can_edit_ratio", profile.optBoolean("can_edit_ratio"))
                    put("can_set_volume", profile.optBoolean("can_set_volume"))
                    put("can_trigger_event", profile.optBoolean("can_trigger_event"))
                })
            })
        }

        // Routes protégées par session
        if (!authed(session)) return err(Response.Status.UNAUTHORIZED, "unauthorized")

        if (method == Method.GET && path == "/control/status") {
            val st = getStatus()
            return jsonOk(JSONObject().apply {
                put("running", st.optBoolean("running"))
                put("volume", st.optInt("volume", 100))
                put("music_volume", st.optInt("music_volume", 100))
                put("ambiance_volume", st.optInt("ambiance_volume", 100))
                put("families_present", st.optBoolean("families_present"))
                put("now_playing", st.opt("now_playing") ?: JSONObject.NULL)
                put("now_playing_ambiance", st.opt("now_playing_ambiance") ?: JSONObject.NULL)
                put("has_emergency", st.optBoolean("has_emergency"))
                put("emergency_playing", st.optBoolean("emergency_playing"))
                put("triggers", st.optJSONArray("triggers") ?: JSONArray())
                put("triggered_id", if (st.isNull("triggered_id")) JSONObject.NULL else (st.opt("triggered_id") ?: JSONObject.NULL))
                put("basket_output", st.optString("basket_output", "auto"))
                put("content_sound", st.optString("content_sound", "on"))
            })
        }

        if (method == Method.GET && path == "/control/baskets") {
            val st = getStatus()
            val src = st.optJSONArray("baskets") ?: JSONArray()
            val out = JSONArray()
            for (i in 0 until src.length()) {
                val b = src.optJSONObject(i) ?: continue
                if (basketAllowed(profile, b.optInt("id_basket"))) out.put(b)
            }
            return jsonOk(JSONObject().put("baskets", out))
        }

        // /control/baskets/{id}/toggle  &  /control/baskets/{id}/ratio
        Regex("^/control/baskets/(\\d+)/(toggle|ratio)$").find(path)?.let { m ->
            val id = m.groupValues[1].toInt()
            val kind = m.groupValues[2]
            if (!basketAllowed(profile, id)) return err(Response.Status.FORBIDDEN, "basket_forbidden")
            val body = readBody(session)
            if (kind == "toggle" && method == Method.POST) {
                onAction(JSONObject().put("action", "toggle_basket").put("id_basket", id)
                    .put("is_active", body.optBoolean("is_active")))
                return jsonOk(JSONObject().put("ok", true))
            }
            if (kind == "ratio" && method == Method.PUT) {
                if (!profile.optBoolean("can_edit_ratio")) return err(Response.Status.FORBIDDEN, "ratio_forbidden")
                val ratio = clampPct(body.optInt("mix_ratio", 0))
                onAction(JSONObject().put("action", "set_ratio").put("id_basket", id).put("mix_ratio", ratio))
                return jsonOk(JSONObject().put("ok", true).put("mix_ratio", ratio))
            }
        }

        // Batch ratios (auto-équilibrage)
        if (method == Method.PUT && path == "/control/baskets/ratios") {
            if (!profile.optBoolean("can_edit_ratio")) return err(Response.Status.FORBIDDEN, "ratio_forbidden")
            val body = readBody(session)
            val src = body.optJSONArray("ratios") ?: JSONArray()
            val ratios = JSONArray()
            for (i in 0 until src.length()) {
                val r = src.optJSONObject(i) ?: continue
                val id = r.optInt("id_basket")
                if (!basketAllowed(profile, id)) continue
                ratios.put(JSONObject().put("id_basket", id).put("mix_ratio", clampPct(r.optInt("mix_ratio", 0))))
            }
            onAction(JSONObject().put("action", "set_ratios").put("ratios", ratios))
            return jsonOk(JSONObject().put("ok", true).put("ratios", ratios))
        }

        // Rappel des réglages serveur (efface les overrides opérateur)
        if (method == Method.POST && path == "/control/reset-defaults") {
            if (!profile.optBoolean("can_edit_ratio")) return err(Response.Status.FORBIDDEN, "ratio_forbidden")
            onAction(JSONObject().put("action", "reset_overrides"))
            return jsonOk(JSONObject().put("ok", true))
        }

        // Sortie audio (paniers) + son des contenus
        if (method == Method.POST && path == "/control/output") {
            if (!profile.optBoolean("can_set_volume")) return err(Response.Status.FORBIDDEN, "output_forbidden")
            val body = readBody(session)
            val out = JSONObject().put("action", "set_output")
            // Le contrôle local pilote l'audio (paniers) → sortie Jack/USB, jamais HDMI (§XIX).
            body.optString("basket_output").takeIf { it in setOf("auto", "jack", "usb") }?.let { out.put("basket_output", it) }
            body.optString("content_sound").takeIf { it in setOf("on", "muted") }?.let { out.put("content_sound", it) }
            onAction(out)
            return jsonOk(JSONObject().put("ok", true))
        }

        if (method == Method.POST && path == "/control/volume") {
            if (!profile.optBoolean("can_set_volume")) return err(Response.Status.FORBIDDEN, "volume_forbidden")
            val body = readBody(session)
            val volume = clampPct(body.optInt("volume", 0))
            onAction(JSONObject().put("action", "set_volume").put("volume", volume))
            return jsonOk(JSONObject().put("ok", true).put("volume", volume))
        }

        if (method == Method.POST && path == "/control/family-volume") {
            if (!profile.optBoolean("can_set_volume")) return err(Response.Status.FORBIDDEN, "volume_forbidden")
            val body = readBody(session)
            val family = when (body.optString("family")) {
                "ambiance" -> "ambiance"
                "music" -> "music"
                else -> return err(Response.Status.BAD_REQUEST, "bad_family")
            }
            val volume = clampPct(body.optInt("volume", 0))
            onAction(JSONObject().put("action", "set_family_volume").put("family", family).put("volume", volume))
            return jsonOk(JSONObject().put("ok", true).put("family", family).put("volume", volume))
        }

        if (method == Method.POST && path == "/control/event") {
            if (!profile.optBoolean("can_trigger_event")) return err(Response.Status.FORBIDDEN, "event_forbidden")
            val body = readBody(session)
            val rawId = body.opt("id_basket")
            val idBasket: Any = if (rawId == null || rawId == JSONObject.NULL) JSONObject.NULL else rawId
            onAction(JSONObject().put("action", "trigger_event").put("id_basket", idBasket))
            return jsonOk(JSONObject().put("ok", true))
        }

        // VOD à la demande LAN-local (Feature B Phase 3) — gated can_trigger_event
        if (method == Method.GET && path == "/control/vod") {
            if (!profile.optBoolean("can_trigger_event")) return err(Response.Status.FORBIDDEN, "vod_forbidden")
            val src = getVodMedia()
            val media = JSONArray()
            for (i in 0 until src.length()) {
                val m = src.optJSONObject(i) ?: continue
                media.put(JSONObject()
                    .put("id_media", m.optInt("id_media"))
                    .put("media_name", m.optString("media_name"))
                    .put("media_type", m.optString("media_type")))
            }
            // Pairs ciblables (trigger multi-cible LAN) + id de CE player → picker de cibles.
            val peers = JSONArray()
            val ps = getVodPeers()
            for (i in 0 until ps.length()) {
                val p = ps.optJSONObject(i) ?: continue
                peers.put(JSONObject().put("id_player", p.optInt("id_player")).put("name", p.optString("name")))
            }
            return jsonOk(JSONObject().put("media", media).put("peers", peers).put("self_id", getSelfId()))
        }
        if (method == Method.POST && path == "/control/vod/play") {
            if (!profile.optBoolean("can_trigger_event")) return err(Response.Status.FORBIDDEN, "vod_forbidden")
            val body = readBody(session)
            val mode = when (body.optString("mode")) { "loop" -> "loop"; "stop" -> "stop"; else -> "once" }
            val idMedia = body.optInt("id_media", 0)
            if (mode != "stop" && idMedia == 0) return err(Response.Status.BAD_REQUEST, "bad_media")
            // id_players = sous-ensemble de cibles (absent/vide → tous les pairs, géré côté MainActivity).
            val idPlayers = body.optJSONArray("id_players") ?: JSONArray()
            onAction(JSONObject().put("action", "play_vod").put("id_media", idMedia).put("mode", mode)
                .put("id_players", idPlayers))
            return jsonOk(JSONObject().put("ok", true).put("mode", mode))
        }

        return err(Response.Status.NOT_FOUND, "not_found")
    }
}
