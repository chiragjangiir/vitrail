package app.vitrail.player

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageInstaller
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.Calendar

/**
 * OTA §XXX Slice 2 + 2c (Android) — MAJ pilotée par le player avec fenêtres + install programmée.
 * Machine à états : (1) DOWNLOAD de l'APK dans `download_window` (repris via HTTP Range si
 * interrompu — survit aux coupures/liens lents), (2) vérif sha256 → `staged`, (3) INSTALL
 * (PackageInstaller : silencieux si Device Owner, sinon via une confirmation à l'écran — cf.
 * STATUS_PENDING_USER_ACTION dans `installApk`) UNIQUEMENT dans `install_window` (évite un reboot
 * en pleine journée), puis reboot fiable via AlarmManager (survit à la mort du process → écran
 * propre). `force` = ignorer les fenêtres. État persisté dans `config` (survit aux relaunch/reboot).
 * Timer 60s pour ré-évaluer les fenêtres. Anti-boucle install (max 2 tentatives/version).
 */
class OtaUpdater(
    private val context: Context,
    private val config: PlayerConfig,
    private val sendStatus: (JSONObject) -> Unit,
) {
    private val http = OkHttpClient()
    private val handler = Handler(Looper.getMainLooper())

    @Volatile
    private var inProgress = false
    private var tickScheduled = false

    private fun partFile() = File(context.filesDir, "ota_download.part")
    private fun stagedFile() = File(context.filesDir, "ota_staged.apk")

    private fun cleanup() {
        try { partFile().delete() } catch (_: Exception) {}
        try { stagedFile().delete() } catch (_: Exception) {}
    }

    fun handleDirective(update: JSONObject?) {
        if (!tickScheduled) { tickScheduled = true; scheduleTick() }
        if (update == null || update.optInt("id_deployment", 0) == 0 || update.optString("version").isBlank()) {
            // Plus de directive = déploiement terminé/annulé → abandonne l'update en attente.
            if (config.getOta() != null) { cleanup(); config.setOta(null); config.clearOtaAttempt() }
            return
        }
        val version = update.optString("version")
        if (semverGte(BuildConfig.VERSION_NAME, version)) {
            if (config.getOta() != null) { cleanup(); config.setOta(null); config.clearOtaAttempt() }
            return
        }
        // Persiste/rafraîchit l'update en attente (préserve `staged` si version inchangée).
        val prev = config.getOta()
        val staged = prev != null && prev.optString("version") == version &&
            prev.optBoolean("staged") && stagedFile().exists()
        val ota = JSONObject()
            .put("id_deployment", update.optInt("id_deployment"))
            .put("version", version)
            .put("url", update.optString("download_url"))
            .put("sha256", update.optString("sha256"))
            .put("download_window", update.optString("download_window", ""))
            .put("install_window", update.optString("install_window", ""))
            .put("force", update.optBoolean("force"))
            .put("staged", staged)
        config.setOta(ota)
        tick()
    }

    private fun scheduleTick() {
        handler.postDelayed({ try { tick() } catch (_: Exception) {}; scheduleTick() }, 60_000)
    }

    private fun tick() {
        val ota = config.getOta() ?: return
        val version = ota.optString("version")
        if (semverGte(BuildConfig.VERSION_NAME, version)) {
            cleanup(); config.setOta(null); config.clearOtaAttempt(); return
        }
        if (inProgress) return
        val staged = ota.optBoolean("staged") && stagedFile().exists()
        val force = ota.optBoolean("force")
        if (staged) {
            if (force || inWindow(ota.optString("install_window"))) doInstall(ota)
        } else if (force || inWindow(ota.optString("download_window"))) {
            doDownload(ota)
        }
    }

    private fun doDownload(ota: JSONObject) {
        inProgress = true
        val idDep = ota.optInt("id_deployment")
        report(idDep, "downloading", null)
        Thread {
            try {
                val part = partFile()
                val offset = if (part.exists()) part.length() else 0L
                // URL RELATIVE (ex "/api/v1/updates/bundles/android/2.5.14") = artefact servi par
                // LE serveur du player -> a resoudre contre son backend_url, comme le font les
                // players Electron. Sans ca, seule une URL absolue pre-signee marchait, avec une
                // expiration a 7 jours et des identifiants MinIO stockes en base (2026-07-19).
                val rawUrl = ota.optString("url")
                val url = if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) rawUrl
                          else config.backendUrl.trimEnd('/') + rawUrl
                val reqB = Request.Builder().url(url)
                // Endpoint authentifie par token machine (ignore par MinIO sur une URL pre-signee).
                if (config.playerToken.isNotBlank()) {
                    reqB.header("Authorization", "Bearer " + config.playerToken)
                }
                if (offset > 0) reqB.header("Range", "bytes=$offset-")
                var stopped = false
                http.newCall(reqB.build()).execute().use { resp ->
                    if (resp.code != 200 && resp.code != 206) {
                        part.delete(); fail(idDep, "download HTTP ${resp.code}"); return@Thread
                    }
                    val append = resp.code == 206 && offset > 0
                    if (!append && offset > 0) part.delete()
                    val body = resp.body ?: run { fail(idDep, "download vide"); return@Thread }
                    FileOutputStream(part, append).use { out ->
                        body.byteStream().use { input ->
                            val buf = ByteArray(65536)
                            var lastCheck = System.currentTimeMillis()
                            while (true) {
                                val n = input.read(buf); if (n < 0) break
                                out.write(buf, 0, n)
                                if (!ota.optBoolean("force") && System.currentTimeMillis() - lastCheck > 3000) {
                                    lastCheck = System.currentTimeMillis()
                                    if (!inWindow(ota.optString("download_window"))) { stopped = true; break }
                                }
                            }
                        }
                    }
                }
                if (stopped) { inProgress = false; Log.i(TAG, "download hors fenêtre → pause (reprise en fenêtre)"); return@Thread }
                val sha = ota.optString("sha256")
                if (sha.isNotBlank() && !sha256(part).equals(sha, ignoreCase = true)) {
                    fail(idDep, "sha256 invalide", part); return@Thread
                }
                stagedFile().delete(); part.renameTo(stagedFile())
                ota.put("staged", true); config.setOta(ota)
                report(idDep, "staged", null)
                Log.i(TAG, "téléchargé + vérifié → staged (v${ota.optString("version")})")
                inProgress = false
                handler.post { try { tick() } catch (_: Exception) {} }
            } catch (e: Exception) {
                Log.e(TAG, "download err (reprise au tick)", e); inProgress = false
            }
        }.start()
    }

    private fun doInstall(ota: JSONObject) {
        inProgress = true
        val idDep = ota.optInt("id_deployment")
        val version = ota.optString("version")
        val prev = config.otaAttemptCount(version)
        if (prev >= 2) {
            report(idDep, "failed", "version $version non atteinte après $prev tentatives")
            inProgress = false; return
        }
        config.setOtaAttempt(version, prev + 1)
        report(idDep, "installing", null)
        Log.i(TAG, "install v$version (deployment $idDep) — tentative ${prev + 1}")
        installApk(stagedFile(), idDep)
    }

    // Install silencieux (Device Owner) + reboot FIABLE via AlarmManager (l'install tue le process →
    // le receiver dynamique meurt ; le receiver manifeste tenu par AlarmManager survit → reboot au
    // succès → écran propre). En échec, le receiver dynamique annule le reboot + report.
    private fun installApk(apk: File, idDep: Int) {
        val pi = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        val sessionId = pi.createSession(params)
        val alarmMgr = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val rebootPi = PendingIntent.getBroadcast(
            context, 0,
            Intent(context, OtaRebootReceiver::class.java).setAction(OtaRebootReceiver.ACTION),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        pi.openSession(sessionId).use { session ->
            apk.inputStream().use { input ->
                session.openWrite("apk", 0, apk.length()).use { out -> input.copyTo(out); session.fsync(out) }
            }
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(c: Context, i: Intent) {
                    // ⚠️ Défaut par MIN_VALUE et non -1 : -1 EST la valeur de
                    // STATUS_PENDING_USER_ACTION. Avec -1 en défaut, un message sans
                    // l'extra serait lu comme « confirmation en attente » et on
                    // tenterait de lancer une intention inexistante.
                    val status = i.getIntExtra(PackageInstaller.EXTRA_STATUS, Int.MIN_VALUE)

                    // Sans Device Owner, Android ne peut pas installer en silence : il
                    // répond STATUS_PENDING_USER_ACTION *en fournissant l'intention à
                    // lancer* (EXTRA_INTENT). Ce n'est pas un échec, c'est une ÉTAPE.
                    // La traiter comme un échec est ce qui bloquait tout player Android
                    // non provisionné : téléchargement et empreinte réussis, install en
                    // échec immédiat, et AUCUNE boîte de dialogue (mesuré le 2026-07-30).
                    if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                        val confirm = confirmIntentOf(i)
                        if (confirm == null) {
                            abort(this, alarmMgr, rebootPi, idDep,
                                "confirmation demandée sans intention à lancer")
                            return
                        }
                        // ⚠️ On NE se désabonne PAS : la session émettra un SECOND
                        // message portant le résultat définitif (confirmé ou refusé).
                        // Se désabonner ici rendrait un refus invisible et laisserait
                        // l'alarme rebooter sans que rien n'ait été installé.
                        //
                        // L'alarme de reboot est REPROGRAMMÉE (10 min au lieu de 40 s),
                        // ni gardée ni annulée.
                        //
                        // ⚠️ MESURÉ le 2026-08-06, et ça corrige la raison qu'on croyait
                        // avoir : sur l'appareil qui reçoit ce statut, l'alarme ne peut
                        // de toute façon PAS rebooter — `OtaRebootReceiver` est gardé par
                        // `isDeviceOwnerApp`, et ce statut n'arrive JUSTEMENT que sans
                        // Device Owner. Les deux conditions s'excluent.
                        // On la reprogramme quand même, par prudence et à coût nul, pour
                        // le seul cas théorique où un Device Owner recevrait ce statut :
                        // là, 40 s redémarreraient l'écran pendant que le dialogue est
                        // affiché, et annuler serait pire (après confirmation l'install
                        // tue ce process, plus personne ne pourrait armer l'alarme).
                        //
                        // Sans Device Owner, la reprise se fait autrement : l'install tue
                        // l'app, Android revient à l'accueil — qui EST l'app en mode
                        // kiosque — et elle repart. Hors kiosque, elle ne revient pas.
                        alarmMgr.setAndAllowWhileIdle(
                            AlarmManager.RTC_WAKEUP,
                            System.currentTimeMillis() + USER_CONFIRM_REBOOT_MS, rebootPi)
                        confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        try {
                            context.startActivity(confirm)
                            // Le statut reste `installing` : le serveur n'accepte que
                            // downloading|staged|installing|success|failed et jette en
                            // silence tout autre valeur (vérifié dans ws.py).
                            Log.i(TAG, "install: confirmation utilisateur demandée (pas de Device Owner)")
                        } catch (e: Exception) {
                            // ⚠️ Android restreint le lancement d'activité depuis
                            // l'arrière-plan : le dialogue suppose que le player est au
                            // premier plan. C'est le cas d'un kiosque allumé, pas
                            // forcément d'un device en veille dans sa fenêtre de nuit.
                            abort(this, alarmMgr, rebootPi, idDep,
                                "dialogue de confirmation non affichable: ${e.message}")
                        }
                        return
                    }

                    try { context.unregisterReceiver(this) } catch (_: Exception) {}
                    if (status != PackageInstaller.STATUS_SUCCESS) {
                        try { alarmMgr.cancel(rebootPi) } catch (_: Exception) {}
                        val m = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "status $status"
                        report(idDep, "failed", "install: $m"); inProgress = false
                    }
                    // Succès : le process est tué par l'install ; l'alarme reboote.
                }
            }
            val filter = IntentFilter(OTA_RESULT_ACTION)
            if (Build.VERSION.SDK_INT >= 33) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                context.registerReceiver(receiver, filter)
            }
            val pending = PendingIntent.getBroadcast(
                context, sessionId, Intent(OTA_RESULT_ACTION).setPackage(context.packageName),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
            )
            alarmMgr.setAndAllowWhileIdle(
                AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + 40_000L, rebootPi)
            session.commit(pending.intentSender)
        }
    }

    /**
     * L'intention de confirmation fournie par le système avec
     * STATUS_PENDING_USER_ACTION. `getParcelableExtra(String)` est déprécié depuis
     * l'API 33 au profit de la surcharge typée.
     */
    private fun confirmIntentOf(i: Intent): Intent? =
        if (Build.VERSION.SDK_INT >= 33) {
            i.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            i.getParcelableExtra(Intent.EXTRA_INTENT)
        }

    /** Abandon d'un install en attente de confirmation : on désarme tout et on le dit. */
    private fun abort(
        receiver: BroadcastReceiver,
        alarmMgr: AlarmManager,
        rebootPi: PendingIntent,
        idDep: Int,
        msg: String,
    ) {
        try { context.unregisterReceiver(receiver) } catch (_: Exception) {}
        try { alarmMgr.cancel(rebootPi) } catch (_: Exception) {}
        report(idDep, "failed", "install: $msg")
        inProgress = false
    }

    private fun fail(idDep: Int, msg: String, f: File? = null) {
        f?.delete()
        Log.e(TAG, "OTA échec: $msg")
        report(idDep, "failed", msg)
        inProgress = false
    }

    private fun sha256(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { s ->
            val buf = ByteArray(65536)
            while (true) { val n = s.read(buf); if (n < 0) break; md.update(buf, 0, n) }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    private fun report(idDep: Int, status: String, error: String?) {
        val j = JSONObject().put("type", "update:status").put("id_deployment", idDep)
            .put("status", status).put("version", BuildConfig.VERSION_NAME)
        if (error != null) j.put("error", error)
        try { sendStatus(j) } catch (_: Exception) {}
    }

    // Fenêtre "HH:MM-HH:MM" en HEURE LOCALE (= horloge du device au site). null/vide = toujours.
    // Gère le passage minuit (start > end).
    private fun inWindow(win: String?): Boolean {
        if (win.isNullOrBlank()) return true
        val m = Regex("""^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$""").find(win) ?: return true
        val c = Calendar.getInstance()
        val cur = c.get(Calendar.HOUR_OF_DAY) * 60 + c.get(Calendar.MINUTE)
        val s = m.groupValues[1].toInt() * 60 + m.groupValues[2].toInt()
        val e = m.groupValues[3].toInt() * 60 + m.groupValues[4].toInt()
        return if (s <= e) cur in s until e else (cur >= s || cur < e)
    }

    private fun semverGte(a: String, b: String): Boolean {
        val pa = parse(a); val pb = parse(b)
        for (i in 0..2) { if (pa[i] != pb[i]) return pa[i] > pb[i] }
        return true
    }

    private fun parse(v: String?): IntArray {
        val m = Regex("""(\d+)\.(\d+)\.(\d+)""").find(v ?: "")
        return if (m != null) {
            intArrayOf(m.groupValues[1].toInt(), m.groupValues[2].toInt(), m.groupValues[3].toInt())
        } else intArrayOf(0, 0, 0)
    }

    companion object {
        private const val TAG = "SFOta"
        private const val OTA_RESULT_ACTION = "app.vitrail.player.OTA_RESULT"

        /**
         * Délai avant reboot quand l'install attend une confirmation humaine. Les 40 s
         * du chemin silencieux laisseraient l'écran redémarrer pendant que le dialogue
         * est affiché. Si personne ne confirme, le reboot finit par tomber sans install :
         * l'anti-boucle (2 tentatives par version) borne la récidive.
         */
        private const val USER_CONFIRM_REBOOT_MS = 10 * 60 * 1000L
    }
}
