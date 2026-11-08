'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { KeyRound, Download, RefreshCw } from 'lucide-react'

import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import PlayerCombobox from './PlayerCombobox'
import api from '@/lib/api'
import { isDemoBlocked } from '@/lib/demo'
import type { ProvisioningTokenRead } from '@/types/api'

/** Fichiers du renderer servis par le frontend → recopiés sur la SD en `sf_rnd_*` (offline 1er boot). */
const RENDERER_FILES: Array<[string, string]> = [
  ['/player-chromeos/ed25519.js', 'sf_rnd_ed25519.js'],
  ['/player-chromeos/signflow.js', 'sf_rnd_signflow.js'],
  ['/player-chromeos/audio_player.js', 'sf_rnd_audio_player.js'],
  ['/player-chromeos/player.js', 'sf_rnd_player.js'],
  ['/player-chromeos/style.css', 'sf_rnd_style.css'],
]

const RES_PRESETS: Record<string, { w: number; h: number; mode: string }> = {
  'fhd60': { w: 1920, h: 1080, mode: '1920x1080x60p' },
  'fhd30': { w: 1920, h: 1080, mode: '1920x1080x30p' },
  '4k30': { w: 3840, h: 2160, mode: '3840x2160x30p' },
  '4k60': { w: 3840, h: 2160, mode: '3840x2160x60p' },
  'portrait': { w: 1080, h: 1920, mode: '1920x1080x60p' },
}

async function fetchText(url: string): Promise<string> {
  const r = await fetch(url, { cache: 'no-store' })
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`)
  return r.text()
}

/** Fuseaux BrightSign (noms abrégés acceptés par roSystemTime.SetTimeZone) — P2.9. */
const TIMEZONES = ['CET', 'WET', 'EET', 'GMT', 'UTC', 'EST', 'CST', 'MST', 'PST', 'GST', 'IST', 'JST', 'AEST']

interface PinnedFirmware {
  model_family: string | null
  version: string
  original_filename: string | null
  file_size: number | null
  download_url: string
}

export default function BrightSignSdDrawer({
  orgId, open, onClose,
}: { orgId: number; open: boolean; onClose: () => void }) {
  const t = useTranslations()
  const [backendUrl, setBackendUrl] = useState(typeof window !== 'undefined' ? window.location.origin : '')
  const [token, setToken] = useState('')
  const [reattachId, setReattachId] = useState('')   // optionnel : lie le token à un player existant
  const [resPreset, setResPreset] = useState('fhd60')
  const [timezone, setTimezone] = useState('')   // P2.9 : fuseau device (vide = inchangé/défaut OS)
  const [dws, setDws] = useState(true)
  const [autoUpdate, setAutoUpdate] = useState(true)
  const [debug, setDebug] = useState(false)
  // Firmware validé à bundler (P2.2) : liste des firmwares ÉPINGLÉS par famille (signés).
  const [pinnedFw, setPinnedFw] = useState<PinnedFirmware[]>([])
  const [includeFw, setIncludeFw] = useState(false)
  const [fwFamily, setFwFamily] = useState('')
  // Réseau
  const [netMode, setNetMode] = useState<'dhcp' | 'static'>('dhcp')
  const [ip, setIp] = useState('')
  const [netmask, setNetmask] = useState('255.255.255.0')
  const [gateway, setGateway] = useState('')
  const [dns, setDns] = useState('')
  const [wifiEnabled, setWifiEnabled] = useState(false)
  const [wifiSsid, setWifiSsid] = useState('')
  const [wifiPass, setWifiPass] = useState('')

  const [busy, setBusy] = useState(false)
  const [genTokenBusy, setGenTokenBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Charge les firmwares ÉPINGLÉS (validés) à l'ouverture → bundlables dans le ZIP (P2.2).
  useEffect(() => {
    if (!open) return
    api.get<PinnedFirmware[]>('/firmware/pinned')
      .then((r) => {
        setPinnedFw(r.data)
        if (r.data.length) setFwFamily((f) => f || r.data[0].model_family || '')
      })
      .catch(() => setPinnedFw([]))
  }, [open])

  async function generateToken() {
    setGenTokenBusy(true); setError(null)
    try {
      if (reattachId) {
        // Ré-attache : token lié au player cible (provision_target_player) → la box reprend
        // son identité à l'enregistrement, zéro doublon.
        const r = await api.post<{ token: string }>(`/orgs/${orgId}/provisioning-payload`, {
          ref: 'BrightSign SD', os: 'brightsign', backend_url: backendUrl,
          id_player: Number(reattachId),
        })
        setToken(r.data.token || '')
      } else {
        const r = await api.post<ProvisioningTokenRead>(`/orgs/${orgId}/provisioning-tokens`, {
          label: 'BrightSign SD', max_uses: 1,
        })
        setToken(r.data.token_value || '')
      }
    } catch {
      setError(t('brightsign_sd.token_error'))
    } finally {
      setGenTokenBusy(false)
    }
  }

  function buildConfig() {
    const preset = RES_PRESETS[resPreset]
    const cfg: Record<string, unknown> = {
      backend_url: backendUrl.trim().replace(/\/$/, ''),
      token: token.trim(),
      width: preset.w, height: preset.h, video_mode: preset.mode,
      dws, autorun_autoupdate: autoUpdate,
    }
    if (timezone) cfg.timezone = timezone   // P2.9 : l'autorun pose la TZ device au boot
    if (debug) cfg.debug = true
    const wifiOn = wifiEnabled && wifiSsid.trim() !== ''
    if (netMode === 'static' || wifiOn) {
      const net: Record<string, unknown> = { mode: netMode }
      if (netMode === 'static') {
        net.ip = ip.trim(); net.netmask = netmask.trim(); net.gateway = gateway.trim()
        const dnsArr = dns.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
        if (dnsArr.length) net.dns = dnsArr
      }
      if (wifiOn) net.wifi = { ssid: wifiSsid.trim(), passphrase: wifiPass }
      cfg.network = net
    }
    return cfg
  }

  async function generateZip() {
    if (!token.trim()) { setError(t('brightsign_sd.need_token')); return }
    if (netMode === 'static' && (!ip.trim() || !gateway.trim())) { setError(t('brightsign_sd.need_static')); return }
    setBusy(true); setError(null)
    try {
      const JSZip = (await import('jszip')).default
      const zip = new JSZip()
      // Assets servis par le frontend (même origine) → on les met sur la SD.
      const [autorun, bootstrap] = await Promise.all([
        fetchText('/player-chromeos/brightsign/autorun.brs'),
        fetchText('/player-chromeos/brightsign/bootstrap.html'),
      ])
      zip.file('autorun.brs', autorun)
      zip.file('bootstrap.html', bootstrap)
      zip.file('config.json', JSON.stringify(buildConfig(), null, 2) + '\n')
      zip.file('ss_body.json', JSON.stringify({ width: 1280, height: 720 }))
      // Renderers (offline au 1er boot ; sinon EnsureRenderer les retéléchargerait).
      const renderers = await Promise.all(RENDERER_FILES.map(([url]) => fetchText(url)))
      RENDERER_FILES.forEach(([, dest], i) => zip.file(dest, renderers[i]))

      // Firmware validé (P2.2) : le .bsfw épinglé de la famille à la RACINE → le bootloader BrightSign
      // l'applique au 1er boot d'un player neuf (auto-upgrade vers la version validée). ~200 Mo.
      if (includeFw && fwFamily) {
        const fw = pinnedFw.find((f) => (f.model_family || '') === fwFamily)
        if (!fw) throw new Error(t('brightsign_sd.fw_none'))
        const resp = await fetch(fw.download_url)
        if (!resp.ok) throw new Error(`${fw.original_filename} → HTTP ${resp.status}`)
        zip.file(fw.original_filename || `${fw.version}.bsfw`, await resp.arrayBuffer())
      }

      const blob = await zip.generateAsync({ type: 'blob' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'signflow-brightsign-sd.zip'
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 4000)
    } catch (e) {
      if (isDemoBlocked(e)) return  // toast global démo → pas de message dans le drawer
      setError((e as Error)?.message || t('brightsign_sd.zip_error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title={t('brightsign_sd.title')} width="w-[460px]">
      <div className="space-y-5">
        <p className="text-xs text-gray-500">{t('brightsign_sd.intro')}</p>

        {/* Ré-attache optionnelle : cibler un player BrightSign existant avant de générer le token */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.reattach')}</label>
          <PlayerCombobox value={reattachId} onChange={setReattachId} osFilter="brightsign" enabled={open} />
          <p className="text-[11px] text-gray-400">{t('brightsign_sd.reattach_hint')}</p>
        </div>

        {/* Token */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.token')}</label>
          <div className="flex items-center gap-2">
            <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="sfp_…" className="flex-1 font-mono text-xs" />
            <Button variant="secondary" size="sm" onClick={generateToken} disabled={genTokenBusy}>
              {genTokenBusy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <KeyRound className="w-4 h-4" />}
              {t('brightsign_sd.generate_token')}
            </Button>
          </div>
        </div>

        {/* Backend + résolution */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.backend_url')}</label>
          <Input value={backendUrl} onChange={(e) => setBackendUrl(e.target.value)} className="text-xs" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.resolution')}</label>
            <select value={resPreset} onChange={(e) => setResPreset(e.target.value)}
              className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-accent/40 bg-surface">
              <option value="fhd60">FHD 1080p · 60Hz</option>
              <option value="fhd30">FHD 1080p · 30Hz</option>
              <option value="4k30">4K 2160p · 30Hz</option>
              <option value="4k60">4K 2160p · 60Hz</option>
              <option value="portrait">Portrait 1080×1920</option>
            </select>
          </div>
          <div className="space-y-1.5 pt-5 text-xs text-gray-600 flex flex-col gap-1">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={dws} onChange={(e) => setDws(e.target.checked)} /> {t('brightsign_sd.opt_dws')}</label>
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={autoUpdate} onChange={(e) => setAutoUpdate(e.target.checked)} /> {t('brightsign_sd.opt_autoupdate')}</label>
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} /> {t('brightsign_sd.opt_debug')}</label>
          </div>
        </div>

        {/* Fuseau horaire (P2.9) — l'autorun pose la TZ device au boot (roSystemTime.SetTimeZone) */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.timezone')}</label>
          <select value={timezone} onChange={(e) => setTimezone(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-accent/40 bg-surface">
            <option value="">{t('brightsign_sd.tz_unchanged')}</option>
            {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
          </select>
        </div>

        {/* Réseau */}
        <div className="space-y-2 pt-2 border-t border-gray-100">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('brightsign_sd.network')}</label>
          <div className="flex items-center gap-4 text-sm">
            <label className="inline-flex items-center gap-1.5"><input type="radio" checked={netMode === 'dhcp'} onChange={() => setNetMode('dhcp')} /> DHCP</label>
            <label className="inline-flex items-center gap-1.5"><input type="radio" checked={netMode === 'static'} onChange={() => setNetMode('static')} /> {t('brightsign_sd.static')}</label>
          </div>
          {netMode === 'static' && (
            <div className="grid grid-cols-2 gap-2">
              <Input value={ip} onChange={(e) => setIp(e.target.value)} placeholder={t('brightsign_sd.ip')} className="text-xs" />
              <Input value={netmask} onChange={(e) => setNetmask(e.target.value)} placeholder={t('brightsign_sd.netmask')} className="text-xs" />
              <Input value={gateway} onChange={(e) => setGateway(e.target.value)} placeholder={t('brightsign_sd.gateway')} className="text-xs" />
              <Input value={dns} onChange={(e) => setDns(e.target.value)} placeholder={t('brightsign_sd.dns')} className="text-xs" />
            </div>
          )}
          <label className="inline-flex items-center gap-2 text-sm pt-1">
            <input type="checkbox" checked={wifiEnabled} onChange={(e) => setWifiEnabled(e.target.checked)} />
            {t('brightsign_sd.wifi')}
          </label>
          {wifiEnabled && (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="block text-xs text-gray-500">{t('brightsign_sd.wifi_ssid')}</label>
                <Input value={wifiSsid} onChange={(e) => setWifiSsid(e.target.value)} placeholder="SSID" className="text-xs" />
              </div>
              <div className="space-y-1">
                <label className="block text-xs text-gray-500">{t('brightsign_sd.wifi_pass')}</label>
                <Input value={wifiPass} onChange={(e) => setWifiPass(e.target.value)} placeholder="Password" type="password" className="text-xs" />
              </div>
            </div>
          )}
        </div>

        {/* Firmware validé (P2.2) — .bsfw épinglé bundlé à la racine, appliqué au 1er boot d'un player neuf */}
        {pinnedFw.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-gray-100">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={includeFw} onChange={(e) => setIncludeFw(e.target.checked)} />
              {t('brightsign_sd.include_fw')}
            </label>
            {includeFw && (
              <div className="space-y-1.5">
                <select value={fwFamily} onChange={(e) => setFwFamily(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-accent/40 bg-surface">
                  {pinnedFw.map((f) => (
                    <option key={f.model_family || ''} value={f.model_family || ''}>
                      {(f.model_family || '?')} · {f.version}{f.file_size ? ` · ${Math.round(f.file_size / 1048576)} Mo` : ''}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-gray-400">{t('brightsign_sd.fw_hint')}</p>
              </div>
            )}
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <Button onClick={generateZip} disabled={busy} className="w-full">
          {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
          {busy ? t('brightsign_sd.generating') : t('brightsign_sd.generate_zip')}
        </Button>
        <p className="text-[11px] text-gray-400">{t('brightsign_sd.howto')}</p>
      </div>
    </Drawer>
  )
}
