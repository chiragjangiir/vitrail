package app.vitrail.player

import android.app.admin.DevicePolicyManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * OTA §XXX slice 2 — reboot fiable APRÈS une auto-install d'APK. L'install remplace l'app et TUE
 * son process (donc un receiver dynamique meurt avant le résultat) → `OtaUpdater` planifie ce
 * receiver **manifeste** via AlarmManager juste avant le commit : l'alarme est tenue par le service
 * système et survit à la mort du process. Au réveil, on reboote (Device Owner) → BootReceiver relance
 * la nouvelle version, écran propre (la notification système « app installée » est effacée).
 */
class OtaRebootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        try {
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            if (dpm.isDeviceOwnerApp(context.packageName)) {
                Log.i("SFOta", "reboot planifié post-install → reboot")
                dpm.reboot(ComponentName(context, SignFlowAdminReceiver::class.java))
            }
        } catch (e: Exception) {
            Log.e("SFOta", "reboot planifié KO: ${e.message}")
        }
    }

    companion object {
        const val ACTION = "app.vitrail.player.OTA_REBOOT"
    }
}
