package app.signflow.player

import android.app.admin.DeviceAdminReceiver

/**
 * Device Admin / Device Owner receiver. Permet, une fois l'app provisionnée Device
 * Owner (adb : dpm set-device-owner app.signflow.player[.debug]/.SignFlowAdminReceiver),
 * d'utiliser DevicePolicyManager.reboot() SANS root — indispensable pour rebooter
 * une box de signage non-rootée à distance depuis le CMS (§XXX). Aucune politique
 * particulière n'est requise pour reboot ; le fichier res/xml/device_admin.xml fournit
 * les métadonnées obligatoires du receiver.
 */
class SignFlowAdminReceiver : DeviceAdminReceiver()
