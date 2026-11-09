package app.vitrail.player

import android.os.Handler
import android.os.Looper
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject

class SignFlowBridge(
    private val webView: WebView,
    private val onNativeCall: (action: String, params: JSONObject) -> Unit,
) {
    private val mainHandler = Handler(Looper.getMainLooper())

    /**
     * Push an event to window.signflow._dispatch() in the WebView.
     * payloadJson must be valid JSON or null.
     */
    fun dispatch(type: String, payloadJson: String? = null) {
        val js = if (payloadJson != null) {
            val quoted = JSONObject.quote(payloadJson)
            "window.signflow._dispatch('$type', JSON.parse($quoted))"
        } else {
            "window.signflow._dispatch('$type', null)"
        }
        mainHandler.post {
            webView.evaluateJavascript(js, null)
        }
    }

    @JavascriptInterface
    fun log(message: String) {
        Log.d("SignFlow/Player.js", message)
    }

    @JavascriptInterface
    fun nativeCall(action: String, paramsJson: String) {
        try {
            val params = JSONObject(paramsJson)
            onNativeCall(action, params)
        } catch (e: Exception) {
            Log.e("SignFlow/Bridge", "nativeCall parse error: ${e.message}")
        }
    }
}
