'use client'

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation } from '@tanstack/react-query'
import { MapPinOff, X } from 'lucide-react'
import Button from '@/components/ui/Button'
import MarqueeText from '@/components/ui/MarqueeText'
import SiteMapSelector, { type MapSite, type MapSiteGroup } from '@/components/maps/SiteMapSelector'
import api from '@/lib/api'
import type { GovernanceAssignment, PlayerRead, Site, SiteGroupRead } from '@/types/api'

/**
 * Sélection du périmètre d'un nœud sur CARTE — « Carte 1 », tranchée par Ed le 2026-07-26 :
 * carte pleine largeur, panier à droite, création de groupe depuis le panier.
 *
 * 🔑 `SiteMapSelector` existe déjà (drawer campagne + portail) et sert tel quel : marqueurs,
 * clic = bascule, recherche + recentrage. Ce composant n'apporte que le panier, la création
 * de groupe et la mise en page pleine page.
 *
 * ⚠️ **Faiblesse assumée de la Carte 1, à ne pas laisser filer** : les sites SANS coordonnées
 * n'apparaissent pas sur une carte. La Carte 2 les traitait par construction ; la Carte 1 les
 * traite par ajout — d'où le compartiment dédié ci-dessous, **visible et compté**. Sans lui on
 * croirait un magasin gouverné alors qu'il ne l'est pas.
 */
export default function PerimeterMapModal({
  nodeId, assignments, onClose, onChanged,
}: {
  nodeId: number
  assignments: GovernanceAssignment[]
  onClose: () => void
  onChanged: () => void
}) {
  const t = useTranslations('governance')
  const [groupName, setGroupName] = useState('')
  const [error, setError] = useState<string | null>(null)
  // `document` n'existe pas au rendu serveur : on ne portalise qu'après montage.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const { data: sites = [] } = useQuery<Site[]>({
    queryKey: ['sites'], queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'], queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  // Tous les groupes de l'org, pas seulement ceux déjà rattachés : on ne pouvait ni les
  // voir ni les choisir depuis la carte (retour Ed 2026-07-26).
  const { data: allGroups = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })

  // Sites déjà rattachés au nœud = contenu initial du panier.
  const selected = useMemo(
    () => new Set(assignments.filter((a) => a.target_type === 'site').map((a) => a.target_id)),
    [assignments],
  )
  const groupAssignments = useMemo(
    () => assignments.filter((a) => a.target_type === 'site_group'), [assignments],
  )
  const attachedGroupIds = useMemo(
    () => new Set(groupAssignments.map((a) => a.target_id)), [groupAssignments],
  )
  // Sites couverts INDIRECTEMENT par un groupe rattaché : ils sont gouvernés sans être
  // cochés un par un. Les taire ferait croire à un magasin oublié.
  const coveredSiteIds = useMemo(() => {
    const out = new Set<number>()
    for (const g of allGroups) {
      if (attachedGroupIds.has(g.id_site_group)) (g.site_ids ?? []).forEach((id) => out.add(id))
    }
    return out
  }, [allGroups, attachedGroupIds])
  const mapGroups: MapSiteGroup[] = useMemo(
    () => allGroups.map((g) => ({
      id: g.id_site_group, name: g.group_name, site_ids: g.site_ids ?? [],
    })),
    [allGroups],
  )

  const screensBySite = useMemo(() => {
    const m = new Map<number, number>()
    for (const p of players) {
      if (p.id_site == null) continue
      m.set(p.id_site, (m.get(p.id_site) ?? 0) + 1)
    }
    return m
  }, [players])

  const mapSites: MapSite[] = useMemo(
    () => sites.map((s) => ({
      id_site: s.id_site,
      site_name: s.site_name,
      latitude: s.latitude,
      longitude: s.longitude,
      screen_count: screensBySite.get(s.id_site) ?? 0,
    })),
    [sites, screensBySite],
  )

  const unplaced = useMemo(
    () => sites.filter((s) => s.latitude == null || s.longitude == null), [sites],
  )
  const selectedSites = useMemo(
    () => sites.filter((s) => selected.has(s.id_site)), [sites, selected],
  )
  const selectedScreens = selectedSites.reduce(
    (n, s) => n + (screensBySite.get(s.id_site) ?? 0), 0,
  )
  const unplacedSelected = selectedSites.filter((s) => s.latitude == null || s.longitude == null)

  const fail = (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(typeof msg === 'string' && msg ? msg : t('perimeter_error'))
  }

  const toggle = useMutation({
    mutationFn: async (id_site: number) => {
      const body = { target_type: 'site', target_id: id_site }
      if (selected.has(id_site)) {
        await api.request({ method: 'DELETE', url: `/governance/nodes/${nodeId}/assignments`, data: body })
      } else {
        await api.post(`/governance/nodes/${nodeId}/assignments`, body)
      }
    },
    onSuccess: () => { setError(null); onChanged() },
    onError: fail,
  })

  // Création d'un groupe de SITES depuis le panier, puis rattachement du groupe au nœud.
  // Les sites individuels sont ensuite détachés : garder les deux ferait doublon, et surtout
  // le groupe deviendrait un décor — un site ajouté au groupe plus tard n'aurait rien changé.
  const makeGroup = useMutation({
    mutationFn: async () => {
      // `POST /site-groups/` ne prend que le nom : les membres s'ajoutent un par un
      // (endpoint existant, pas de nouvelle route pour ce chantier).
      const grp = (await api.post<SiteGroupRead>('/site-groups/', {
        group_name: groupName.trim(),
      })).data
      for (const id of selected) {
        await api.post(`/site-groups/${grp.id_site_group}/sites`, { id_site: id })
      }
      await api.post(`/governance/nodes/${nodeId}/assignments`, {
        target_type: 'site_group', target_id: grp.id_site_group,
      })
      for (const id of selected) {
        await api.request({
          method: 'DELETE', url: `/governance/nodes/${nodeId}/assignments`,
          data: { target_type: 'site', target_id: id },
        })
      }
    },
    onSuccess: () => { setError(null); setGroupName(''); onChanged() },
    onError: fail,
  })

  const toggleGroup = useMutation({
    mutationFn: async (id: number) => {
      const body = { target_type: 'site_group', target_id: id }
      if (attachedGroupIds.has(id)) {
        await api.request({ method: 'DELETE', url: `/governance/nodes/${nodeId}/assignments`, data: body })
      } else {
        await api.post(`/governance/nodes/${nodeId}/assignments`, body)
      }
    },
    onSuccess: () => { setError(null); onChanged() },
    onError: fail,
  })

  // 🔑 PORTAIL obligatoire, et pas un simple `z-50` : `DashboardShell` enferme tout le
  // contenu dans un `relative z-10`, sous la sidebar (`relative z-20`). Un enfant de ce
  // conteneur ne peut PAS passer devant la sidebar, quel que soit son `z-index` — c'est la
  // règle des contextes d'empilement. Vu à l'écran : la sidebar mangeait les 240 px de
  // gauche du plein écran, et la bulle d'aide (`z-30`, posée hors de ce conteneur) passait
  // par-dessus le pied de page. Les drawers existants ne le voyaient pas : `inset-y-0
  // right-0` ne touche jamais la sidebar.
  if (!mounted) return null

  return createPortal(
    <div className="fixed inset-0 z-[100] bg-canvas flex flex-col" data-testid="gov-perimeter">
      <header className="shrink-0 flex items-center gap-3 px-5 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-800">{t('perimeter_title')}</h2>
        <p className="text-[11px] text-gray-400 flex-1 truncate">{t('perimeter_hint')}</p>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label={t('close')}>
          <X className="w-5 h-5" />
        </button>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Carte pleine largeur (Carte 1) */}
        <div className="flex-1 min-w-0 p-4">
          <SiteMapSelector
            sites={mapSites}
            selected={selected}
            onToggle={(id) => toggle.mutate(id)}
            heightClass="h-full"
            searchable
            searchPlaceholder={t('perimeter_search')}
            covered={coveredSiteIds}
            groups={mapGroups}
            onPickGroup={(id) => toggleGroup.mutate(id)}
          />
        </div>

        {/* Panier */}
        <aside className="w-[360px] shrink-0 border-l border-gray-100 flex flex-col min-h-0">
          <div className="shrink-0 px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {t('basket_title')}
            </p>
            <p className="text-[11px] text-gray-400 mt-0.5">
              {t('basket_count', { sites: selectedSites.length, screens: selectedScreens })}
            </p>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
            {mapGroups.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
                  {t('basket_groups')}
                </p>
                <p className="text-[11px] text-gray-400">{t('basket_groups_hint')}</p>
                {mapGroups.map((g) => (
                  <label key={g.id} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={attachedGroupIds.has(g.id)}
                      onChange={() => toggleGroup.mutate(g.id)}
                      className="accent-accent"
                    />
                    <MarqueeText text={g.name} className="flex-1 min-w-0" />
                    <span className="text-[11px] text-gray-400 shrink-0">{g.site_ids.length}</span>
                  </label>
                ))}
              </div>
            )}

            {selectedSites.length === 0 ? (
              <p className="text-xs text-gray-400">{t('basket_empty')}</p>
            ) : (
              <div className="space-y-1">
                {selectedSites.map((s) => (
                  <div key={s.id_site} className="flex items-center gap-2 text-sm text-gray-700">
                    {(s.latitude == null || s.longitude == null) && (
                      <span title={t('basket_unplaced_badge')} className="shrink-0">
                        <MapPinOff className="w-3.5 h-3.5 text-amber-500" />
                      </span>
                    )}
                    <MarqueeText text={s.site_name} className="flex-1 min-w-0" />
                    <span className="text-[11px] text-gray-400 shrink-0">
                      {screensBySite.get(s.id_site) ?? 0}
                    </span>
                    <button onClick={() => toggle.mutate(s.id_site)}
                            className="text-gray-400 hover:text-danger">×</button>
                  </div>
                ))}
              </div>
            )}

            {/* Compartiment des sites SANS coordonnées : visible et COMPTÉ. La carte ne peut
                pas les montrer ; les taire ferait croire le périmètre complet. */}
            {unplaced.length > 0 && (
              <div className="rounded-md border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 px-3 py-2 space-y-1">
                <p className="text-[11px] text-amber-700 dark:text-amber-300">
                  {t('unplaced_notice', {
                    total: unplaced.length, selected: unplacedSelected.length,
                  })}
                </p>
                {unplaced.map((s) => (
                  <label key={s.id_site} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id_site)}
                      onChange={() => toggle.mutate(s.id_site)}
                      className="accent-accent"
                    />
                    <MarqueeText text={s.site_name} className="flex-1 min-w-0" />
                    <span className="text-[11px] text-gray-400 shrink-0">
                      {screensBySite.get(s.id_site) ?? 0}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-gray-100 px-4 py-3 space-y-2">
            <p className="text-[11px] text-gray-400">{t('make_group_hint')}</p>
            <div className="flex gap-2">
              <input
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder={t('make_group_placeholder')}
                className="flex-1 min-w-0 border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-surface"
              />
              <Button
                size="sm"
                disabled={!groupName.trim() || selectedSites.length === 0}
                loading={makeGroup.isPending}
                onClick={() => makeGroup.mutate()}
              >
                {t('make_group')}
              </Button>
            </div>
            {error && <p className="text-[11px] text-danger">{error}</p>}
          </div>
        </aside>
      </div>
    </div>,
    document.body,
  )
}
