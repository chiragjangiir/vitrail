'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { MapPinOff, MonitorSmartphone, X } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import SiteMapSelector, { type MapSite } from '@/components/maps/SiteMapSelector'

/**
 * Choisir ses écrans SUR UNE CARTE — brique partagée (demande d'Ed, audit du 2026-07-29).
 *
 * « La recherche de cible est trop simple : ça suffit pour 8 écrans, pas pour 200, 500 ou
 * 1000. » Mesuré : la page Événements chargeait **tout le parc** à l'ouverture (1,9 Ko par
 * écran, soit ~1,8 Mo à 1000 écrans) pour l'afficher dans une liste à cases à cocher, et sa
 * recherche filtrait **dans le navigateur**. À cette échelle, on ne cherche plus un écran
 * par son nom : on le désigne par son emplacement.
 *
 * 🔑 Aucune carte n'est réécrite : `SiteMapSelector` existe déjà et sert les campagnes, le
 * portail annonceur et la carte de gouvernance. Il est purement contrôlé (aucun appel
 * réseau), donc réutilisable tel quel. Ce tiroir n'ajoute que la traduction entre la carte
 * (qui parle de SITES) et la cible demandée (des sites, ou des écrans).
 *
 * ⚠️ Les sites sans coordonnées n'apparaissent pas sur la carte — faiblesse assumée du
 * composant. Ils restent trouvables par sa recherche, et leur nombre est AFFICHÉ ici :
 * un site invisible et non compté serait un écran qu'on croit avoir ciblé.
 */

export interface MapPlayer {
  id_player: number
  player_name: string
  id_site: number | null
}

interface Props {
  open: boolean
  onClose: () => void
  /** `site` = la cible est une liste de sites · `player` = une liste d'écrans. */
  mode: 'site' | 'player'
  sites: MapSite[]
  players: MapPlayer[]
  /** Sélection courante (identifiants de site ou d'écran selon `mode`). */
  value: number[]
  onApply: (ids: number[]) => void
  /** Contrainte du module appelant.
   *
   * 🔑 C'est ce qui permet d'harmoniser la PRÉSENTATION sans relâcher la SÉMANTIQUE. La VOD
   * exige que tous ses écrans partagent le même site — ce n'est pas une coquetterie :
   * `id_site` est la clé du domaine de confiance du déclenchement LAN (secret partagé PAR
   * SITE) et la portée du panneau de contrôle magasin. Une carte qui laisserait cocher deux
   * sites produirait une configuration refusée par le serveur… après coup.
   *   · `single`      — un seul site ;
   *   · `single-site` — des écrans, mais tous d'un même site.
   */
  constraint?: 'single' | 'single-site'
}

export default function TargetMapDrawer({
  open, onClose, mode, sites, players, value, onApply, constraint,
}: Props) {
  const t = useTranslations()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [focusedSite, setFocusedSite] = useState<number | null>(null)

  // Réouverture = on repart de la sélection réelle du formulaire (aller-retour sans perte).
  useEffect(() => {
    if (open) { setSelected(new Set(value)); setFocusedSite(null) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  /** Sites à colorer sur la carte : en mode écran, ceux dont AU MOINS un écran est retenu. */
  const siteSelection = useMemo(() => {
    if (mode === 'site') return selected
    const out = new Set<number>()
    players.forEach((p) => {
      if (p.id_site != null && selected.has(p.id_player)) out.add(p.id_site)
    })
    return out
  }, [mode, selected, players])

  const unplaced = sites.filter((s) => s.latitude == null || s.longitude == null).length
  const focusedPlayers = players.filter((p) => p.id_site === focusedSite)

  /** La sélection courante appartient-elle déjà au site `id` ? (contrainte `single-site`) */
  function sameSiteAs(sel: Set<number>, id: number | null): boolean {
    const s0 = new Set(players.filter((p) => sel.has(p.id_player)).map((p) => p.id_site))
    return s0.size === 0 || (s0.size === 1 && s0.has(id))
  }

  /** Écran cochable ? Sous `single-site`, seuls ceux du site déjà retenu le sont. */
  function playerAllowed(pid: number, siteId: number | null): boolean {
    if (constraint !== 'single-site') return true
    return selected.has(pid) || sameSiteAs(selected, siteId)
  }

  function toggleSite(id: number) {
    if (mode === 'site') {
      setSelected((prev) => {
        if (constraint === 'single') return prev.has(id) ? new Set<number>() : new Set([id])
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      return
    }
    // Mode écran : cliquer un site prend (ou rend) TOUS ses écrans — le geste rapide.
    const ids = players.filter((p) => p.id_site === id).map((p) => p.id_player)
    setSelected((prev) => {
      // Changer de site sous `single-site` : la sélection précédente ne peut pas tenir, on
      // repart de zéro plutôt que de fabriquer une config que le serveur refusera.
      const next = constraint === 'single-site' && !sameSiteAs(prev, id)
        ? new Set<number>()
        : new Set(prev)
      const allIn = ids.length > 0 && ids.every((i) => next.has(i))
      ids.forEach((i) => (allIn ? next.delete(i) : next.add(i)))
      return next
    })
    setFocusedSite(id)
  }

  return (
    <Drawer open={open} onClose={onClose} title={t('target_map.title')} width="w-[720px]">
      {open && (
        <div className="flex flex-col h-full min-h-0 gap-3" data-testid="target-map">
          <p className="text-xs text-gray-400 shrink-0">
            {t(mode === 'site' ? 'target_map.hint_site' : 'target_map.hint_player')}
            {constraint === 'single-site' && <> {t('target_map.hint_single_site')}</>}
          </p>

          <div className="shrink-0">
            <SiteMapSelector
              sites={sites}
              selected={siteSelection}
              onToggle={toggleSite}
              onFocusSite={(id) => setFocusedSite(id)}
              searchable
              searchPlaceholder={t('target_map.search')}
              heightClass="h-[300px]"
            />
          </div>

          {/* 🔴 Le site RECENTRÉ est sélectionnable ICI, et pas seulement en cliquant son
              marqueur. Sans ce panneau, un site SANS COORDONNÉES — qui n'apparaît pas sur
              la carte mais que la recherche trouve — serait impossible à cibler : le tiroir
              annoncerait « trouvable par la recherche » en le rendant inutilisable.
              Défaut trouvé en écrivant le test, pas en relisant le code. */}
          {mode === 'site' && focusedSite !== null && (
            <div className="shrink-0 border border-gray-200 rounded-lg px-3 py-2 flex items-center justify-between gap-3">
              <span className="text-xs text-gray-700 truncate">
                {sites.find((s) => s.id_site === focusedSite)?.site_name}
              </span>
              <Button size="sm" variant={selected.has(focusedSite) ? 'secondary' : 'primary'}
                      data-testid="target-map-toggle-focused"
                      onClick={() => toggleSite(focusedSite)}>
                {t(selected.has(focusedSite) ? 'target_map.remove' : 'target_map.add')}
              </Button>
            </div>
          )}

          {/* Mode écran : le site recentré s'ouvre en liste d'écrans — c'est ainsi qu'on
              cible « les 2 vitrines de ce magasin » sans dérouler tout le parc. */}
          {mode === 'player' && focusedSite !== null && (
            <div className="shrink-0 border border-gray-200 rounded-lg p-2 max-h-40 overflow-y-auto">
              <p className="text-xs font-medium text-gray-600 px-1 pb-1">
                {sites.find((s) => s.id_site === focusedSite)?.site_name}
              </p>
              {focusedPlayers.length === 0 && (
                <p className="text-xs text-gray-400 px-1 py-2">{t('target_map.no_screens')}</p>
              )}
              {focusedPlayers.map((p) => (
                <label key={p.id_player}
                       className="flex items-center gap-2 px-1 py-1 text-xs cursor-pointer hover:bg-gray-50 rounded">
                  <input
                    type="checkbox"
                    className="accent-accent w-3.5 h-3.5"
                    disabled={!playerAllowed(p.id_player, p.id_site)}
                    checked={selected.has(p.id_player)}
                    onChange={() => setSelected((prev) => {
                      const next = new Set(prev)
                      if (next.has(p.id_player)) next.delete(p.id_player)
                      else next.add(p.id_player)
                      return next
                    })}
                  />
                  <MonitorSmartphone className="w-3.5 h-3.5 text-gray-400" />
                  <span className="truncate">{p.player_name}</span>
                </label>
              ))}
            </div>
          )}

          {/* Récapitulatif : ce qu'on emporte, nommé — jamais un simple compteur. */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            <div className="flex flex-wrap gap-1.5">
              {mode === 'site'
                ? sites.filter((s) => selected.has(s.id_site)).map((s) => (
                    <span key={s.id_site}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-accent/10 text-accent rounded">
                      {s.site_name}
                      <button type="button" onClick={() => toggleSite(s.id_site)}
                              className="hover:text-danger"><X className="w-3 h-3" /></button>
                    </span>
                  ))
                : players.filter((p) => selected.has(p.id_player)).map((p) => (
                    <span key={p.id_player}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-accent/10 text-accent rounded">
                      {p.player_name}
                      <button type="button"
                              onClick={() => setSelected((prev) => {
                                const next = new Set(prev); next.delete(p.id_player); return next
                              })}
                              className="hover:text-danger"><X className="w-3 h-3" /></button>
                    </span>
                  ))}
              {selected.size === 0 && (
                <span className="text-xs text-gray-400">{t('target_map.none')}</span>
              )}
            </div>
            {unplaced > 0 && (
              <p className="text-[11px] text-gray-400 mt-2 flex items-center gap-1">
                <MapPinOff className="w-3 h-3" />
                {t('target_map.unplaced', { count: unplaced })}
              </p>
            )}
          </div>

          <div className="shrink-0 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
            <span className="text-xs text-gray-500">
              {t('target_map.selected', { count: selected.size })}
            </span>
            <Button size="sm" data-testid="target-map-apply"
                    onClick={() => { onApply(Array.from(selected)); onClose() }}>
              {t('target_map.apply')}
            </Button>
          </div>
        </div>
      )}
    </Drawer>
  )
}
