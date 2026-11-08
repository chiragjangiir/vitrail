'use client'

import { useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { Download, Copy, Check, ChevronDown, FileUp, SlidersHorizontal } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import Collapsible from '@/components/ui/Collapsible'
import PlayerCombobox from './PlayerCombobox'
import api from '@/lib/api'

// BrightSign volontairement absent : ces players passent par le drawer dédié « BrightSign SD »
// (ZIP carte SD + ré-attache) — pas par le payload générique.
const OSES = ['android', 'linux', 'rpi', 'windows'] as const

// Résolutions proposées ('' = auto/ne pas forcer ; 'custom' = champ libre pour les LED non standard).
const RES_PRESETS = ['1280x720', '1920x1080', '3840x2160', '7680x4320'] as const
const RES_LABELS: Record<string, string> = {
  '1280x720': 'HD 1280×720', '1920x1080': 'FHD 1920×1080',
  '3840x2160': '4K 3840×2160', '7680x4320': '8K 7680×4320',
}

interface Payload {
  version: number; ref: string; os: string; backend_url: string; token: string
  network?: unknown; options?: unknown; id_key: number; id_player: number | null
}

interface Batch {
  version: number; mode: 'per_machine' | 'shared'; os: string; backend_url: string
  players: Payload[]; token?: string; count?: number; ref?: string; id_key?: number
  network?: { wifi_ssid?: string; wifi_psk?: string } | null
  options?: { resolution?: string; timezone?: string } | null
}

// Une entrée du lot per-player (état du formulaire d'une carte).
interface BatchEntry {
  ref: string; res: string; resCustom: string
  netMode: 'dhcp' | 'static'; ip: string; mask: string; gw: string; dns: string
}
const emptyEntry = (): BatchEntry =>
  ({ ref: '', res: '', resCustom: '', netMode: 'dhcp', ip: '', mask: '255.255.255.0', gw: '', dns: '' })

const effRes = (res: string, custom: string) => (res === 'custom' ? custom.trim() : res)

// Sélecteur segmenté « pill » (même idiome que les périodes des pages Rapports).
function Seg<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  return (
    <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={`flex-1 px-3 py-1.5 rounded-md text-sm font-medium transition-sf ${
            value === o.value ? 'bg-surface text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'
          }`}>{o.label}</button>
      ))}
    </div>
  )
}

// Liste déroulante de résolution (Auto / HD / FHD / 4K / 8K / Personnalisée + champ libre).
function ResolutionSelect({ res, custom, onRes, onCustom }: {
  res: string; custom: string; onRes: (v: string) => void; onCustom: (v: string) => void
}) {
  const t = useTranslations('provisioning')
  return (
    <div className="flex gap-2">
      <select value={res} onChange={(e) => onRes(e.target.value)} className={inp}>
        <option value="">{t('payload_res_auto')}</option>
        {RES_PRESETS.map((r) => <option key={r} value={r}>{RES_LABELS[r]}</option>)}
        <option value="custom">{t('payload_res_custom')}</option>
      </select>
      {res === 'custom' && (
        <input value={custom} onChange={(e) => onCustom(e.target.value)} className={inp}
          placeholder={t('payload_res_custom_ph')} />
      )}
    </div>
  )
}

// Liste IANA complète du navigateur (même source que la page Sites ; Chrome ≥ 99).
function browserTimezones(): string[] {
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    if (typeof intl.supportedValuesOf === 'function') return intl.supportedValuesOf('timeZone')
  } catch { /* navigateur ancien */ }
  return []
}

// Fuseau horaire OS posé au provisioning (clé additive "timezone" lue par sf-configure,
// timedatectl → Debian/RPi uniquement ; référence = fuseau du site CMS).
function TimezoneSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useTranslations('provisioning')
  const zones = useMemo(browserTimezones, [])
  if (!zones.length) return null
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inp}>
      <option value="">{t('payload_tz_none')}</option>
      {zones.map((z) => <option key={z} value={z}>{z}</option>)}
    </select>
  )
}

// Champ token/commande avec bouton copier (token clair, commande sombre).
function CopyField({ label, value, dark = false, copied, onCopy }: {
  label: string; value: string; dark?: boolean; copied: boolean; onCopy: () => void
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <div className="flex items-start gap-2">
        <code className={`flex-1 rounded px-2 py-1.5 ${dark
          ? 'text-[11px] bg-gray-900 text-gray-100 break-all'
          : 'text-xs bg-gray-50 border border-gray-200 truncate'}`}>
          {value}
        </code>
        <button onClick={onCopy} className="p-1.5 text-gray-400 hover:text-accent shrink-0">
          {copied ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}

export default function PayloadDrawer({
  orgId, open, onClose,
}: { orgId: number; open: boolean; onClose: () => void }) {
  const t = useTranslations('provisioning')
  const [scope, setScope] = useState<'one' | 'batch'>('one')
  const [os, setOs] = useState<string>('android')
  const [ref, setRef] = useState('')
  const [mode, setMode] = useState<'create' | 'reattach'>('create')
  const [reattachId, setReattachId] = useState<string>('')
  const [res, setRes] = useState('')
  const [resCustom, setResCustom] = useState('')
  const [tz, setTz] = useState('')            // fuseau OS (single)
  const [batchTz, setBatchTz] = useState('')  // fuseau OS commun au lot (per_machine + shared)
  const [wifiSsid, setWifiSsid] = useState('')
  const [wifiPsk, setWifiPsk] = useState('')
  const [netMode, setNetMode] = useState<'dhcp' | 'static'>('dhcp')
  const [netIp, setNetIp] = useState('')
  const [netMask, setNetMask] = useState('255.255.255.0')
  const [netGw, setNetGw] = useState('')
  const [netDns, setNetDns] = useState('')
  const [result, setResult] = useState<Payload | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  // — lot —
  const [tokenMode, setTokenMode] = useState<'per_machine' | 'shared'>('per_machine')
  const [count, setCount] = useState('2')
  const [entries, setEntries] = useState<BatchEntry[]>([emptyEntry(), emptyEntry()])
  const [csvError, setCsvError] = useState(false)
  const csvInput = useRef<HTMLInputElement>(null)
  const [sharedRef, setSharedRef] = useState('')         // shared : libellé de base
  const [sharedCount, setSharedCount] = useState('10')   // shared : nombre de players
  const [sharedRes, setSharedRes] = useState('')         // shared : réglages COMMUNS
  const [sharedResCustom, setSharedResCustom] = useState('')
  const [sharedWifiSsid, setSharedWifiSsid] = useState('')
  const [sharedWifiPsk, setSharedWifiPsk] = useState('')
  const [batchResult, setBatchResult] = useState<Batch | null>(null)

  // Le réseau (nmcli/netsh) n'est appliqué que par sf-configure Debian/RPi/Windows —
  // pas de canal réseau pour Android (provisionné par intent ADB) → sections masquées.
  const netCapable = os !== 'android'
  // Fuseau au provisioning : seul sf-configure.sh (Debian/RPi, timedatectl) l'applique.
  // Android/Windows : fuseau posé à distance après attachement (drawer player, set_timezone).
  const tzCapable = os === 'linux' || os === 'rpi'

  const backendUrl = typeof window !== 'undefined' ? window.location.origin : ''

  // Redimensionne le lot en préservant les cartes déjà saisies.
  function applyCount(v: string) {
    setCount(v)
    const n = Math.max(1, Math.min(100, Number(v) || 0))
    if (!Number(v)) return
    setEntries((prev) => {
      const next = prev.slice(0, n)
      while (next.length < n) next.push(emptyEntry())
      return next
    })
  }
  function patchEntry(i: number, patch: Partial<BatchEntry>) {
    setEntries((prev) => prev.map((e, j) => (j === i ? { ...e, ...patch } : e)))
  }

  // ── Import CSV : name;resolution;IP/prefix;gateway;DNS (1 ligne = 1 player) ──
  function importCsv(file: File) {
    setCsvError(false)
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const text = String(reader.result || '')
        const rows = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
        if (!rows.length) throw new Error('empty')
        const sep = rows[0].includes(';') ? ';' : ','
        const body = /name|nom/i.test(rows[0].split(sep)[0]) ? rows.slice(1) : rows
        const parsed = body.map((line) => {
          const c = line.split(sep).map((s) => s.trim())
          const e = emptyEntry()
          e.ref = c[0] || ''
          // Résolution : mot-clé (HD/FHD/4K/8K) ou "LxH" ; inconnu → personnalisée.
          const r = (c[1] || '').toLowerCase()
          const kw: Record<string, string> = { hd: '1280x720', fhd: '1920x1080', '4k': '3840x2160', '8k': '7680x4320' }
          if (kw[r]) e.res = kw[r]
          else if (/^\d+x\d+$/.test(r)) {
            if ((RES_PRESETS as readonly string[]).includes(r)) e.res = r
            else { e.res = 'custom'; e.resCustom = r }
          }
          if (c[2]) {
            const [ip, prefix] = c[2].split('/')
            e.netMode = 'static'; e.ip = (ip || '').trim()
            e.mask = (prefix || '24').trim(); e.gw = c[3] || ''; e.dns = c[4] || ''
          }
          return e
        }).filter((e) => e.ref)
        if (!parsed.length) throw new Error('empty')
        setEntries(parsed); setCount(String(parsed.length))
      } catch {
        setCsvError(true)
      }
    }
    reader.readAsText(file)
  }
  function downloadCsvTemplate() {
    const csv = 'name;resolution;ip/prefix;gateway;dns\n'
      + 'Store Lyon;FHD;192.168.1.50/24;192.168.1.1;8.8.8.8,1.1.1.1\n'
      + 'Store Paris;4K;;\n'
      + 'Store Nice;;;\n'
    const blob = new Blob([csv], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = 'signflow-players.csv'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href)
  }

  const gen = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = { ref: ref || 'player', os, backend_url: backendUrl }
      if (mode === 'reattach' && reattachId) body.id_player = Number(reattachId)
      const r = effRes(res, resCustom)
      const opts: Record<string, string> = {}
      if (r) opts.resolution = r
      if (tzCapable && tz) opts.timezone = tz
      if (Object.keys(opts).length) body.options = opts
      if (netCapable) {
        const net: Record<string, unknown> = { mode: netMode }
        if (netMode === 'static' && netIp) { net.ip = netIp; net.mask = netMask; net.gw = netGw; net.dns = netDns }
        if (wifiSsid) { net.wifi_ssid = wifiSsid; net.wifi_psk = wifiPsk }
        body.network = net
      }
      return (await api.post<Payload>(`/orgs/${orgId}/provisioning-payload`, body)).data
    },
    onSuccess: (d) => setResult(d),
  })

  const validEntries = useMemo(() => entries.filter((e) => e.ref.trim()), [entries])

  const genBatch = useMutation({
    mutationFn: async () => {
      // Fuseau COMMUN au lot (le fuseau est une propriété du site, pas de la machine).
      const tzv = tzCapable ? batchTz : ''
      if (tokenMode === 'per_machine') {
        const body = {
          mode: 'per_machine', os, backend_url: backendUrl,
          entries: validEntries.map((e) => {
            const r = effRes(e.res, e.resCustom)
            const opts: Record<string, string> = {}
            if (r) opts.resolution = r
            if (tzv) opts.timezone = tzv
            return {
              ref: e.ref.trim(),
              network: netCapable && e.netMode === 'static' && e.ip
                ? { mode: 'static', ip: e.ip, mask: e.mask, gw: e.gw, dns: e.dns }
                : { mode: 'dhcp' },
              ...(Object.keys(opts).length ? { options: opts } : {}),
            }
          }),
        }
        return (await api.post<Batch>(`/orgs/${orgId}/provisioning-batch`, body)).data
      }
      const r = effRes(sharedRes, sharedResCustom)
      const body: Record<string, unknown> = {
        mode: 'shared', os, backend_url: backendUrl,
        ref: sharedRef || 'player', count: Number(sharedCount) || 1,
      }
      const opts: Record<string, string> = {}
      if (r) opts.resolution = r
      if (tzv) opts.timezone = tzv
      if (Object.keys(opts).length) body.options = opts
      if (netCapable && sharedWifiSsid) {
        body.network = { mode: 'dhcp', wifi_ssid: sharedWifiSsid, wifi_psk: sharedWifiPsk }
      }
      return (await api.post<Batch>(`/orgs/${orgId}/provisioning-batch`, body)).data
    },
    onSuccess: (d) => setBatchResult(d),
  })

  const cliCmd = useMemo(() => {
    if (!result) return ''
    // Auth via clé opérateur pré-configurée (--save-config) → plus de token à passer.
    const base = `signflow-provision --payload signflow-provision.json`
    if (result.os === 'android') return `${base} --ip <IP_DEVICE> --apk app-release.apk`
    if (result.os === 'windows') return `${base} --winrm <IP> --winrm-user <user> --winrm-password <mdp>`
    return base
  }, [result])

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500)
  }
  function triggerDownload(obj: unknown, name: string) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = name
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  }
  function downloadJson() { if (result) triggerDownload(result, 'signflow-provision.json') }
  // Entrée plate (net_*/resolution) lue par sf-configure — factorisée pour single ET lot v2.
  function flatEntry(p: Payload): Record<string, unknown> {
    const n = (p.network || {}) as Record<string, string>
    const o = (p.options || {}) as Record<string, string>
    const e: Record<string, unknown> = { player_name: p.ref, token: p.token, net_mode: n.mode || 'dhcp' }
    if (n.mode === 'static') {
      e.net_ip = n.ip || ''; e.net_prefix = maskToPrefix(n.mask)
      e.net_gateway = n.gw || ''; e.net_dns = n.dns || ''
    }
    if (n.wifi_ssid) { e.net_wifi_ssid = n.wifi_ssid; e.net_wifi_psk = n.wifi_psk || '' }
    if (o.resolution) e.resolution = o.resolution
    if (o.timezone) e.timezone = o.timezone
    return e
  }
  // Bundle PLAT (1 player) lu par sf-configure.sh (Debian/RPi) / sf-configure.ps1 (Windows).
  function downloadBundle() {
    if (!result) return
    triggerDownload({ backend_url: result.backend_url, ...flatEntry(result) }, 'signflow-config.json')
  }
  // Bundle v2 (lot) : tableau de players OU token partagé (+ réglages communs). Lu par sf-configure v2.
  function downloadBundleV2() {
    if (!batchResult) return
    const b: Record<string, unknown> = {
      version: 2, mode: batchResult.mode, backend_url: batchResult.backend_url, os: batchResult.os,
    }
    if (batchResult.mode === 'per_machine') {
      b.players = batchResult.players.map(flatEntry)
    } else {
      b.token = batchResult.token; b.count = batchResult.count; b.ref = batchResult.ref
      if (batchResult.options?.resolution) b.resolution = batchResult.options.resolution
      if (batchResult.options?.timezone) b.timezone = batchResult.options.timezone
      if (batchResult.network?.wifi_ssid) {
        b.net_wifi_ssid = batchResult.network.wifi_ssid
        b.net_wifi_psk = batchResult.network.wifi_psk || ''
      }
    }
    triggerDownload(b, 'signflow-config.json')
  }
  function reset() { setResult(null); setBatchResult(null); onClose() }

  const advancedActive = !!effRes(res, resCustom) || (tzCapable && !!tz)
    || (netCapable && (netMode === 'static' || !!wifiSsid))

  return (
    <Drawer open={open} onClose={reset} title={t('payload_title')}>
      {/* Portée : un player vs lot */}
      {!result && !batchResult && (
        <div className="mb-5">
          <Seg value={scope} onChange={setScope} options={[
            { value: 'one', label: t('payload_scope_one') },
            { value: 'batch', label: t('payload_scope_batch') },
          ]} />
        </div>
      )}

      {scope === 'one' ? (
        !result ? (
          <div className="space-y-5">
            <p className="text-xs text-gray-400">{t('payload_hint')}</p>

            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('payload_os')}</label>
              <select value={os} onChange={(e) => setOs(e.target.value)} className={inp}>
                {OSES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>

            <Seg value={mode} onChange={setMode} options={[
              { value: 'create', label: t('payload_create') },
              { value: 'reattach', label: t('payload_reattach') },
            ]} />

            {mode === 'create' ? (
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('payload_ref')}</label>
                <input value={ref} onChange={(e) => setRef(e.target.value)} className={inp}
                  placeholder={t('payload_ref_ph')} />
              </div>
            ) : (
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('payload_target')}</label>
                <PlayerCombobox value={reattachId} onChange={setReattachId} enabled={open} />
              </div>
            )}

            <Collapsible title={t('payload_advanced')} icon={<SlidersHorizontal className="w-4 h-4" />}
              active={advancedActive}>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('payload_resolution')}</label>
                <ResolutionSelect res={res} custom={resCustom} onRes={setRes} onCustom={setResCustom} />
              </div>

              {tzCapable && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('payload_timezone')}</label>
                  <TimezoneSelect value={tz} onChange={setTz} />
                </div>
              )}

              {netCapable && (
                <>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('payload_network')}</label>
                    <Seg value={netMode} onChange={setNetMode} options={[
                      { value: 'dhcp', label: 'DHCP' },
                      { value: 'static', label: t('payload_net_static') },
                    ]} />
                    {netMode === 'static' && (
                      <div className="space-y-2 mt-2">
                        <input value={netIp} onChange={(e) => setNetIp(e.target.value)} className={inp} placeholder={t('payload_net_ip_ph')} />
                        <div className="grid grid-cols-2 gap-2">
                          <input value={netMask} onChange={(e) => setNetMask(e.target.value)} className={inp} placeholder={t('payload_net_mask_ph')} />
                          <input value={netGw} onChange={(e) => setNetGw(e.target.value)} className={inp} placeholder={t('payload_net_gw_ph')} />
                        </div>
                        <input value={netDns} onChange={(e) => setNetDns(e.target.value)} className={inp} placeholder={t('payload_net_dns_ph')} />
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('payload_wifi_ssid')}</label>
                      <input value={wifiSsid} onChange={(e) => setWifiSsid(e.target.value)} className={inp} />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('payload_wifi_psk')}</label>
                      <input value={wifiPsk} onChange={(e) => setWifiPsk(e.target.value)} className={inp} type="password" />
                    </div>
                  </div>
                </>
              )}
            </Collapsible>

            <Button className="w-full" loading={gen.isPending}
              disabled={mode === 'reattach' && !reattachId}
              onClick={() => gen.mutate()}>
              {t('payload_generate')}
            </Button>
            {gen.isError && <p className="text-xs text-danger">{t('payload_error')}</p>}
          </div>
        ) : (
          <div className="space-y-5">
            <div className="rounded-lg border border-success/30 bg-success/5 p-3">
              <p className="text-sm font-medium text-gray-800">
                {t('payload_ready', { ref: result.ref })}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {t('payload_player', { id: result.id_player ?? '—' })} · {result.os}
              </p>
            </div>

            <div className="flex justify-center py-2">
              {/* Fond blanc volontaire : contraste requis pour le scan du QR code. */}
              <div className="p-3 bg-white rounded-lg border border-gray-200">
                <QRCodeSVG value={JSON.stringify(result)} size={168} level="M" />
              </div>
            </div>

            <div>
              <CopyField label={t('payload_token')} value={result.token}
                copied={copied === 'tok'} onCopy={() => copy(result.token, 'tok')} />
              <p className="text-[11px] text-amber-600 mt-1">{t('payload_secret_warn')}</p>
            </div>

            <CopyField label={t('payload_cli')} value={cliCmd} dark
              copied={copied === 'cli'} onCopy={() => copy(cliCmd, 'cli')} />

            <div>
              <Button className="w-full" onClick={downloadBundle}>
                <Download className="w-4 h-4" /> {t('payload_bundle_download')}
              </Button>
              <p className="text-[11px] text-gray-400 mt-1">{t('payload_bundle_hint')}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" className="flex-1" onClick={downloadJson}>
                <Download className="w-4 h-4" /> {t('payload_download')}
              </Button>
              <Button variant="secondary" className="flex-1" onClick={reset}>{t('payload_done')}</Button>
            </div>
          </div>
        )
      ) : (
        /* ── LOT (plusieurs players) ─────────────────────────────── */
        !batchResult ? (
          <div className="space-y-5">
            <p className="text-xs text-gray-400">{t('payload_batch_hint')}</p>

            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('payload_os')}</label>
              <select value={os} onChange={(e) => setOs(e.target.value)} className={inp}>
                {OSES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('payload_token_mode')}</label>
              <Seg value={tokenMode} onChange={setTokenMode} options={[
                { value: 'per_machine', label: t('payload_token_per_machine') },
                { value: 'shared', label: t('payload_token_shared') },
              ]} />
              <p className="text-[11px] text-gray-400 mt-1">
                {tokenMode === 'per_machine' ? t('payload_token_hint_per') : t('payload_token_hint_shared')}
              </p>
            </div>

            {tokenMode === 'per_machine' ? (
              <>
                <div className="flex items-end gap-2">
                  <div className="w-32">
                    <label className="block text-xs text-gray-500 mb-1">{t('payload_shared_count')}</label>
                    <input type="number" min={1} max={100} value={count}
                      onChange={(e) => applyCount(e.target.value)} className={inp} />
                  </div>
                  <div className="flex-1" />
                  <Button size="sm" variant="secondary" onClick={() => csvInput.current?.click()}>
                    <FileUp className="w-3.5 h-3.5" /> {t('payload_csv_import')}
                  </Button>
                  <button type="button" onClick={downloadCsvTemplate}
                    className="text-xs text-accent hover:underline pb-1.5">{t('payload_csv_template')}</button>
                  <input ref={csvInput} type="file" accept=".csv,text/csv" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv(f); e.target.value = '' }} />
                </div>
                {csvError && <p className="text-xs text-danger">{t('payload_csv_error')}</p>}
                <p className="text-[11px] text-gray-400 -mt-3">{t('payload_csv_hint')}</p>

                {tzCapable && (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('payload_timezone')}</label>
                    <TimezoneSelect value={batchTz} onChange={setBatchTz} />
                    <p className="text-[11px] text-gray-400 mt-1">{t('payload_tz_hint')}</p>
                  </div>
                )}

                <div className="space-y-2">
                  {entries.map((e, i) => (
                    <PlayerCard key={i} index={i} entry={e} netCapable={netCapable}
                      defaultOpen={i === 0} onPatch={(p) => patchEntry(i, p)} />
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('payload_shared_label')}</label>
                    <input value={sharedRef} onChange={(e) => setSharedRef(e.target.value)} className={inp}
                      placeholder="Boutiques" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('payload_shared_count')}</label>
                    <input type="number" min={1} max={500} value={sharedCount}
                      onChange={(e) => setSharedCount(e.target.value)} className={inp} />
                  </div>
                </div>

                {/* Réglages COMMUNS à tout le lot (le mode partagé ne peut pas pré-assigner une
                    IP statique par player : l'assignation machine↔identité se fait sur le terrain). */}
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('payload_shared_common')}</label>
                  <div className="space-y-2 rounded-md border border-gray-200 p-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('payload_resolution')}</label>
                      <ResolutionSelect res={sharedRes} custom={sharedResCustom}
                        onRes={setSharedRes} onCustom={setSharedResCustom} />
                    </div>
                    {tzCapable && (
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">{t('payload_timezone')}</label>
                        <TimezoneSelect value={batchTz} onChange={setBatchTz} />
                      </div>
                    )}
                    {netCapable && (
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">{t('payload_wifi_ssid')}</label>
                          <input value={sharedWifiSsid} onChange={(e) => setSharedWifiSsid(e.target.value)} className={inp} />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">{t('payload_wifi_psk')}</label>
                          <input value={sharedWifiPsk} onChange={(e) => setSharedWifiPsk(e.target.value)} className={inp} type="password" />
                        </div>
                      </div>
                    )}
                    <p className="text-[11px] text-gray-400">{t('payload_shared_common_hint')}</p>
                  </div>
                </div>
              </>
            )}

            <Button className="w-full" loading={genBatch.isPending}
              disabled={tokenMode === 'per_machine' ? validEntries.length === 0 : !Number(sharedCount)}
              onClick={() => genBatch.mutate()}>
              {t('payload_batch_generate')}
              {tokenMode === 'per_machine' ? ` (${validEntries.length})` : ` (×${Number(sharedCount) || 0})`}
            </Button>
            {genBatch.isError && <p className="text-xs text-danger">{t('payload_error')}</p>}
          </div>
        ) : (
          <div className="space-y-5">
            <div className="rounded-lg border border-success/30 bg-success/5 p-3">
              <p className="text-sm font-medium text-gray-800">
                {t('payload_batch_ready')} · {batchResult.os}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {batchResult.mode === 'per_machine'
                  ? t('payload_batch_per_summary', { n: batchResult.players.length })
                  : t('payload_batch_shared_summary', { n: batchResult.count ?? 0 })}
              </p>
            </div>

            {batchResult.mode === 'per_machine' ? (
              <div className="max-h-48 overflow-auto rounded-md border border-gray-200 divide-y divide-gray-100">
                {batchResult.players.map((p) => {
                  const n = (p.network || {}) as { mode?: string; ip?: string }
                  const o = (p.options || {}) as { resolution?: string }
                  return (
                    <div key={p.id_player ?? p.id_key} className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
                      <span className="text-gray-700 truncate">{p.ref}</span>
                      <span className="shrink-0 text-[10px] text-gray-400">
                        {o.resolution ? `${o.resolution} · ` : ''}
                        {n.mode === 'static' && n.ip ? n.ip : 'DHCP'} · #{p.id_player}
                      </span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <CopyField label={t('payload_shared_token')} value={batchResult.token ?? ''}
                copied={copied === 'btok'} onCopy={() => copy(batchResult.token || '', 'btok')} />
            )}
            <p className="text-[11px] text-amber-600">{t('payload_secret_warn')}</p>

            <div>
              <Button className="w-full" onClick={downloadBundleV2}>
                <Download className="w-4 h-4" /> {t('payload_bundle_download')}
              </Button>
              <p className="text-[11px] text-gray-400 mt-1">{t('payload_batch_bundle_hint')}</p>
            </div>
            <Button variant="secondary" className="w-full" onClick={reset}>{t('payload_done')}</Button>
          </div>
        )
      )}
    </Drawer>
  )
}

// Carte repliable d'un player du lot : en-tête = « Player N » + nom + pastille réseau/résolution.
function PlayerCard({ index, entry, netCapable, defaultOpen, onPatch }: {
  index: number; entry: BatchEntry; netCapable: boolean; defaultOpen: boolean
  onPatch: (p: Partial<BatchEntry>) => void
}) {
  const t = useTranslations('provisioning')
  const [open, setOpen] = useState(defaultOpen)
  const configured = entry.netMode === 'static' || !!effRes(entry.res, entry.resCustom)
  return (
    <div className="rounded-md border border-gray-200">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left">
        <span className="text-xs font-medium text-gray-500 shrink-0">
          {t('payload_player_n', { n: index + 1 })}
        </span>
        <span className="flex-1 truncate text-sm text-gray-800">{entry.ref}</span>
        {entry.netMode === 'static' && entry.ip && (
          <span className="shrink-0 text-[10px] text-gray-400">{entry.ip}</span>
        )}
        {configured && <span className="w-2 h-2 rounded-full bg-accent shrink-0" />}
        <ChevronDown className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-gray-100 px-3 py-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('payload_ref')}</label>
            <input value={entry.ref} onChange={(e) => onPatch({ ref: e.target.value })} className={inp}
              placeholder={t('payload_ref_ph')} />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('payload_resolution')}</label>
            <ResolutionSelect res={entry.res} custom={entry.resCustom}
              onRes={(v) => onPatch({ res: v })} onCustom={(v) => onPatch({ resCustom: v })} />
          </div>
          {netCapable && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('payload_network')}</label>
              <Seg value={entry.netMode} onChange={(v) => onPatch({ netMode: v })} options={[
                { value: 'dhcp' as const, label: 'DHCP' },
                { value: 'static' as const, label: t('payload_net_static') },
              ]} />
              {entry.netMode === 'static' && (
                <div className="space-y-2 mt-2">
                  <input value={entry.ip} onChange={(e) => onPatch({ ip: e.target.value })} className={inp}
                    placeholder={t('payload_net_ip_ph')} />
                  <div className="grid grid-cols-2 gap-2">
                    <input value={entry.mask} onChange={(e) => onPatch({ mask: e.target.value })} className={inp}
                      placeholder={t('payload_net_mask_ph')} />
                    <input value={entry.gw} onChange={(e) => onPatch({ gw: e.target.value })} className={inp}
                      placeholder={t('payload_net_gw_ph')} />
                  </div>
                  <input value={entry.dns} onChange={(e) => onPatch({ dns: e.target.value })} className={inp}
                    placeholder={t('payload_net_dns_ph')} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const inp = 'w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'

// Masque réseau → préfixe CIDR (accepte aussi un préfixe déjà numérique, ex. "24").
function maskToPrefix(mask?: string): number {
  const m = (mask || '').trim()
  if (!m) return 24
  if (/^\d+$/.test(m)) return Number(m)
  const p = m.split('.').reduce((acc, o) => acc + ((parseInt(o, 10) || 0).toString(2).match(/1/g)?.length || 0), 0)
  return p || 24
}
