package app.vitrail.player

import android.app.admin.DevicePolicyManager
import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import android.util.Log

/**
 * Commandes d'administration réservées au TECHNICIEN, via adb — rien d'autre.
 *
 * Pourquoi : une fois l'appli Device Owner (mode kiosque), Android refuse de la désinstaller
 * (`adb uninstall` → « protected package ») et `dpm remove-active-admin` ne marche que pour une
 * appli de test. Sans ce geste, récupérer un boîtier imposait une réinitialisation d'usine.
 *
 *   adb shell content call --uri content://app.vitrail.player.admin --method release_device_owner
 *   adb uninstall app.vitrail.player
 *
 * Sécurité : le fournisseur est exporté (sinon adb ne pourrait pas l'appeler), donc N'IMPORTE
 * QUELLE appli du boîtier peut le joindre. Le garde est l'UID de l'appelant, lu par Binder :
 * seuls le shell adb (2000) et root (0) passent. Une appli installée a son propre UID (≥ 10000)
 * et reçoit une SecurityException. Avoir adb, c'est déjà avoir la main sur le boîtier : ce geste
 * n'ouvre rien de plus.
 */
class AdminCommandProvider : ContentProvider() {

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        val uid = Binder.getCallingUid()
        if (uid != SHELL_UID && uid != ROOT_UID) {
            Log.w(TAG, "refused '$method' from uid $uid")
            throw SecurityException("Vitrail admin commands are reserved to adb (uid $uid refused)")
        }
        val ctx = context ?: throw IllegalStateException("no context")
        return when (method) {
            "release_device_owner" -> {
                val dpm = ctx.getSystemService(DevicePolicyManager::class.java)
                val pkg = ctx.packageName
                val wasOwner = dpm.isDeviceOwnerApp(pkg)
                if (wasOwner) dpm.clearDeviceOwnerApp(pkg)
                val released = !dpm.isDeviceOwnerApp(pkg)
                Log.i(TAG, "release_device_owner: was_owner=$wasOwner released=$released")
                Bundle().apply {
                    putBoolean("was_device_owner", wasOwner)
                    putBoolean("released", released)
                }
            }
            else -> throw IllegalArgumentException("unknown method '$method' (known: release_device_owner)")
        }
    }

    override fun onCreate(): Boolean = true
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
                       selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null
    override fun getType(uri: Uri): String? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?,
                        selectionArgs: Array<out String>?): Int = 0

    private companion object {
        const val TAG = "SignFlow/Admin"
        const val SHELL_UID = 2000   // android.os.Process.SHELL_UID (masqué dans le SDK public)
        const val ROOT_UID = 0
    }
}
