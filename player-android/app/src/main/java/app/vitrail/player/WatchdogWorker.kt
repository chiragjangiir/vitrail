package app.vitrail.player

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters

private const val TAG = "SignFlow/Watchdog"

class WatchdogWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val config = PlayerConfig(applicationContext)
        if (!config.isConfigured()) {
            Log.d(TAG, "Not configured — skipping watchdog")
            return Result.success()
        }

        if (!isAppInForeground()) {
            Log.w(TAG, "App not in foreground — restarting")
            applicationContext.startActivity(
                Intent(applicationContext, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } else {
            Log.d(TAG, "App running — OK")
        }
        return Result.success()
    }

    private fun isAppInForeground(): Boolean {
        val actManager = applicationContext.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val tasks = actManager.getRunningTasks(1)
        return tasks.isNotEmpty() &&
            tasks[0].topActivity?.packageName == applicationContext.packageName
    }
}
