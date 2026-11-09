package app.vitrail.player

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import android.os.Build

private const val TAG = "SignFlow/Setup"

class SetupActivity : AppCompatActivity() {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val httpClient = OkHttpClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )

        val etUrl = findViewById<EditText>(R.id.etServerUrl)
        val etToken = findViewById<EditText>(R.id.etToken)
        val btnConnect = findViewById<Button>(R.id.btnConnect)
        val tvStatus = findViewById<TextView>(R.id.tvStatus)

        // Pre-fill server URL if already saved (re-registration)
        val config = PlayerConfig(this)
        if (config.backendUrl.isNotBlank()) etUrl.setText(config.backendUrl)

        btnConnect.setOnClickListener {
            val url = etUrl.text.toString().trim().trimEnd('/')
            val token = etToken.text.toString().trim()

            if (url.isEmpty() || token.isEmpty()) {
                tvStatus.setTextColor(getColor(R.color.error))
                tvStatus.text = "Please fill in all fields."
                return@setOnClickListener
            }
            if (!token.startsWith("sfp_")) {
                tvStatus.setTextColor(getColor(R.color.error))
                tvStatus.text = "Invalid token format — must start with sfp_"
                return@setOnClickListener
            }

            btnConnect.isEnabled = false
            tvStatus.setTextColor(getColor(R.color.text_secondary))
            tvStatus.text = "Connecting..."

            registerPlayer(url, token, config, tvStatus, btnConnect)
        }

        // Provisioning par intent (installeur terrain §XXIX) : l'outil CLI ADB injecte la config
        // sans piloter l'UI clavier virtuel :
        //   adb shell am start -n app.vitrail.player/.SetupActivity \
        //     -e backend_url https://cms.example.com -e token sfp_…
        // Auto-remplit + auto-enregistre. Le token sfp_ reste requis (secret d'enregistrement).
        val extraUrl = intent.getStringExtra("backend_url")?.trim()?.trimEnd('/')
        val extraToken = intent.getStringExtra("token")?.trim()
        if (!extraUrl.isNullOrEmpty() && !extraToken.isNullOrEmpty()
            && extraToken.startsWith("sfp_")) {
            etUrl.setText(extraUrl)
            etToken.setText(extraToken)
            btnConnect.isEnabled = false
            tvStatus.setTextColor(getColor(R.color.text_secondary))
            tvStatus.text = "Provisioning..."
            registerPlayer(extraUrl, extraToken, config, tvStatus, btnConnect)
        }
    }

    private fun registerPlayer(
        serverUrl: String,
        orgToken: String,
        config: PlayerConfig,
        tvStatus: TextView,
        btnConnect: Button,
    ) {
        scope.launch {
            try {
                val body = JSONObject().apply {
                    put("player_name", "Android Player")
                    put("player_os", "android-${Build.SUPPORTED_ABIS.firstOrNull() ?: "arm64"}")
                    put("player_version", BuildConfig.VERSION_NAME)
                    put("org_token", orgToken)
                }.toString()

                val request = Request.Builder()
                    .url("$serverUrl/api/v1/players/register")
                    .post(body.toRequestBody("application/json".toMediaType()))
                    .build()

                httpClient.newCall(request).execute().use { response ->
                    val responseBody = response.body?.string() ?: ""
                    if (!response.isSuccessful) {
                        val detail = try {
                            JSONObject(responseBody).optString("detail", "HTTP ${response.code}")
                        } catch (e: Exception) {
                            "HTTP ${response.code}"
                        }
                        withContext(Dispatchers.Main) {
                            tvStatus.setTextColor(getColor(R.color.error))
                            tvStatus.text = "Registration failed: $detail"
                            btnConnect.isEnabled = true
                        }
                        return@use
                    }

                    val json = JSONObject(responseBody)
                    val playerToken = json.getString("player_token")

                    config.backendUrl = serverUrl
                    config.playerToken = playerToken

                    withContext(Dispatchers.Main) {
                        tvStatus.setTextColor(getColor(R.color.accent))
                        tvStatus.text = "Connected! Starting player..."
                        startActivity(
                            Intent(this@SetupActivity, MainActivity::class.java)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                        )
                        finish()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    tvStatus.setTextColor(getColor(R.color.error))
                    tvStatus.text = "Error: ${e.message}"
                    btnConnect.isEnabled = true
                }
            }
        }
    }
}
