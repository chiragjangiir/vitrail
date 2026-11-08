package app.signflow.player

import android.util.Base64
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import java.io.File
import java.security.SecureRandom

/**
 * Signature Ed25519 des preuves Proof of Play (§XXIV, P2) — parité stricte avec le renderer web
 * (signflow.js / window.SFEd25519) et le serveur (services/pop_proof.py).
 *
 * - La clé privée = seed 32 octets persisté dans filesDir → NE QUITTE JAMAIS l'appareil.
 * - Message canonique signé (identique player/serveur, entiers robustes au formatage) :
 *     "id_player|id_media|id_playlist|played_at_ms|duration_ms"   (null → champ vide)
 * - Signature = Ed25519(msg) encodée en base64 standard (comme btoa côté JS).
 * - Clé publique = SPKI PEM Ed25519 (RFC 8410 : 12 octets de préfixe fixe + 32 octets bruts),
 *   figée côté serveur au 1er lot (TOFU). Génération déterministe = même PEM à chaque flush.
 *
 * Android < 33 n'expose pas Ed25519 dans le JCE natif → on utilise l'API bas-niveau BouncyCastle
 * (org.bouncycastle.crypto.*), sans enregistrer de provider JCE.
 */
class PopSigner(filesDir: File) {
    private val seedFile = File(filesDir, "pop_seed.txt")
    private val priv: Ed25519PrivateKeyParameters = loadOrCreate()

    /** Clé publique SPKI PEM à joindre au lot (TOFU). */
    val publicKeyPem: String = rawPubToSpkiPem(priv.generatePublicKey().encoded)

    private fun loadOrCreate(): Ed25519PrivateKeyParameters {
        val hex = runCatching { if (seedFile.exists()) seedFile.readText().trim() else "" }.getOrDefault("")
        if (hex.length == 64) {
            runCatching { return Ed25519PrivateKeyParameters(hexToBytes(hex), 0) }
        }
        val seed = ByteArray(32).also { SecureRandom().nextBytes(it) }
        runCatching { seedFile.writeText(bytesToHex(seed)) }
        return Ed25519PrivateKeyParameters(seed, 0)
    }

    /** Signature base64 du message canonique (déjà encodé UTF-8), ou null si échec. */
    fun sign(msg: ByteArray): String? = runCatching {
        val signer = Ed25519Signer()
        signer.init(true, priv)
        signer.update(msg, 0, msg.size)
        Base64.encodeToString(signer.generateSignature(), Base64.NO_WRAP)
    }.getOrNull()

    private fun rawPubToSpkiPem(raw: ByteArray): String {
        // Préfixe SPKI DER Ed25519 (RFC 8410) : SEQUENCE { AlgId { 1.3.101.112 } BIT STRING(32) }.
        val prefix = byteArrayOf(0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00)
        val der = prefix + raw
        val b64 = Base64.encodeToString(der, Base64.NO_WRAP)
        val wrapped = b64.chunked(64).joinToString("\n")
        return "-----BEGIN PUBLIC KEY-----\n$wrapped\n-----END PUBLIC KEY-----\n"
    }

    private companion object {
        fun hexToBytes(h: String) = ByteArray(h.length / 2) {
            ((h[it * 2].digitToInt(16) shl 4) or h[it * 2 + 1].digitToInt(16)).toByte()
        }
        fun bytesToHex(b: ByteArray) = b.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
    }
}
