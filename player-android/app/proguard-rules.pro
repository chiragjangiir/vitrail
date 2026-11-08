-keep class app.signflow.player.** { *; }
-keepattributes JavascriptInterface
-keepattributes *Annotation*
-keep public class * extends android.webkit.WebViewClient
-keep public class * extends android.webkit.WebChromeClient
# Proof of Play — signature Ed25519 via l'API bas-niveau BouncyCastle (crypto/math/util).
-keep class org.bouncycastle.crypto.** { *; }
-keep class org.bouncycastle.math.** { *; }
-dontwarn org.bouncycastle.**
-dontwarn javax.naming.**
