package app.vitrail.player

import android.content.Context
import android.util.Base64
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONObject

class PlayerConfig(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "signflow_config",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var backendUrl: String
        get() = prefs.getString("backend_url", "") ?: ""
        set(v) = prefs.edit().putString("backend_url", v).apply()

    var playerToken: String
        get() = prefs.getString("player_token", "") ?: ""
        set(v) = prefs.edit().putString("player_token", v).apply()

    var playerName: String
        get() = prefs.getString("player_name", "Android Player") ?: "Android Player"
        set(v) = prefs.edit().putString("player_name", v).apply()

    /** Last received screen_resolution from display_config (e.g. "1920x1080@60"). Restored on startup. */
    var screenResolution: String?
        get() = prefs.getString("screen_resolution", null)
        set(v) = if (v != null) prefs.edit().putString("screen_resolution", v).apply()
                 else prefs.edit().remove("screen_resolution").apply()

    fun isConfigured(): Boolean = backendUrl.isNotBlank() && playerToken.startsWith("eyJ")

    fun clear() = prefs.edit().clear().apply()

    // OTA §XXX slice 2 : compteur de tentatives par version (anti-boucle de reboot). Stocké
    // "version:count" ; réinitialisé dès qu'on atteint la version cible.
    fun otaAttemptCount(version: String): Int {
        val s = prefs.getString("ota_attempt", null) ?: return 0
        val parts = s.split(":")
        return if (parts.size == 2 && parts[0] == version) parts[1].toIntOrNull() ?: 0 else 0
    }

    fun setOtaAttempt(version: String, count: Int) =
        prefs.edit().putString("ota_attempt", "$version:$count").apply()

    fun clearOtaAttempt() = prefs.edit().remove("ota_attempt").apply()

    // OTA §XXX Slice 2c : update en attente persisté (survit aux relaunch/reboot) — pilote la
    // machine à états download→staged→install côté player (fenêtres). null = aucun.
    fun getOta(): org.json.JSONObject? {
        val s = prefs.getString("ota_pending", null) ?: return null
        return try { org.json.JSONObject(s) } catch (e: Exception) { null }
    }

    fun setOta(ota: org.json.JSONObject?) {
        if (ota == null) prefs.edit().remove("ota_pending").apply()
        else prefs.edit().putString("ota_pending", ota.toString()).apply()
    }

    fun getPlayerId(): Int? {
        return try {
            val parts = playerToken.split(".")
            if (parts.size < 2) return null
            val decoded = String(Base64.decode(parts[1], Base64.URL_SAFE or Base64.NO_PADDING))
            val json = JSONObject(decoded)
            json.optInt("sub", -1).takeIf { it >= 0 }
        } catch (e: Exception) {
            null
        }
    }
}
