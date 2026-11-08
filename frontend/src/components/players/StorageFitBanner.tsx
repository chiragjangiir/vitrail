'use client'

import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { AlertTriangle, HardDrive } from 'lucide-react'
import api from '@/lib/api'

/**
 * « Est-ce que ça rentre ? » — avertissement de stockage AU MOMENT DE L'AFFECTATION.
 *
 * Le 2026-08-06, une playlist de 1,85 Go affectée à un écran de 4 Go a rempli son disque à
 * 100 % et cassé Android : l'appareil n'a pu être récupéré qu'en désinstallant
 * l'application. Le frein embarqué empêche désormais la casse — mais sans cet avertissement,
 * l'écran diffuserait une playlist tronquée sans que personne ne sache pourquoi.
 *
 * 🔑 On envoie les **cibles canoniques et la playlist**, pas des listes résolues : c'est le
 * serveur qui déplie le ciblage et les sous-playlists, avec les mêmes services que la
 * diffusion. Résoudre ici donnerait un contrôle portant sur autre chose que ce qui sera
 * réellement diffusé.
 *
 * ⛔ N'affiche RIEN quand tout va bien : un bandeau permanent finit par ne plus être lu, et
 * c'est le jour où il compte qu'on ne le verra pas.
 */

type Verdict = 'ok' | 'tight' | 'insufficient' | 'unknown'

type PlayerFit = {
  id_player: number
  player_name: string
  verdict: Verdict
  reason: string
  required_bytes: number
  missing_count: number
  free_bytes: number | null
  disk_total_bytes: number | null
}

type Result = { players: PlayerFit[]; worst: Verdict; required_bytes: number }

export type StorageTarget = { target_type: string; target_id?: number | null }

function human(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  const u = ['o', 'Ko', 'Mo', 'Go', 'To']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1 }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`
}

export default function StorageFitBanner({
  targets,
  idPlaylist,
  enabled = true,
}: {
  targets: StorageTarget[]
  idPlaylist: number | null
  enabled?: boolean
}) {
  const t = useTranslations()

  const { data } = useQuery<Result>({
    queryKey: ['storage-fit', idPlaylist, targets],
    queryFn: () => api.post('/players/storage-check', {
      targets, id_playlist: idPlaylist,
    }).then((r) => r.data),
    // Rien à contrôler tant qu'il n'y a pas À LA FOIS du contenu et une cible.
    enabled: enabled && !!idPlaylist && targets.length > 0,
    staleTime: 15_000,
  })

  if (!data) return null

  // On n'alerte QUE sur ce qui est actionnable. `unknown` seul ne lève pas la bannière :
  // mesuré sur le parc réel, les BrightSign ne peuvent PAS remonter l'espace de leur carte
  // SD (leur `navigator.storage.estimate()` décrirait le quota du navigateur), et c'est
  // définitif — pas un « pas encore à jour ». Afficher un avertissement permanent pour une
  // situation que personne ne peut corriger, c'est garantir qu'on ne lira plus la bannière
  // le jour où elle dira « insuffisant ». Le serveur, lui, continue de rendre `unknown` :
  // il n'affirme jamais que ça tient — c'est l'écran qui choisit de ne pas crier.
  const actionable = data.worst === 'insufficient' || data.worst === 'tight'
  if (!actionable) return null

  const concerned = data.players.filter((p) => p.verdict === data.worst)
  const unverifiable = data.players.filter((p) => p.verdict === 'unknown')
  const insufficient = data.worst === 'insufficient'

  const tone = insufficient
    ? 'text-danger bg-danger/10'
    : 'text-amber-600 dark:text-amber-300 bg-amber-500/10 dark:bg-amber-500/15'

  const Icon = insufficient ? AlertTriangle : HardDrive

  return (
    <div
      className={`text-[11px] rounded-md px-2 py-1.5 space-y-1 ${tone}`}
      data-testid="storage-fit-banner"
      data-verdict={data.worst}
    >
      <p className="flex items-center gap-1.5 font-medium">
        <Icon className="w-3.5 h-3.5 shrink-0" />
        {insufficient
          ? t('schedules.storage_insufficient', { count: concerned.length })
          : t('schedules.storage_tight', { count: concerned.length })}
      </p>
      {/* On NOMME les écrans : « un écran est plein » sans dire lequel oblige à chercher. */}
      <ul className="space-y-0.5">
        {concerned.slice(0, 5).map((p) => (
          <li key={p.id_player}>
            {p.player_name}
            {p.free_bytes != null && (
              <> — {t('schedules.storage_needs', {
                required: human(p.required_bytes), free: human(p.free_bytes),
              })}</>
            )}
          </li>
        ))}
        {concerned.length > 5 && (
          <li>{t('schedules.storage_more', { count: concerned.length - 5 })}</li>
        )}
      </ul>
      {insufficient && <p>{t('schedules.storage_hint')}</p>}
      {/* Les écrans invérifiables ne déclenchent rien, mais tant que la bannière est là,
          autant dire qu'ils n'ont pas été contrôlés — plutôt que de laisser croire que
          tous les autres sont verts. */}
      {unverifiable.length > 0 && (
        <p className="opacity-75" data-testid="storage-fit-unverifiable">
          {t('schedules.storage_unknown', { count: unverifiable.length })}
        </p>
      )}
    </div>
  )
}
