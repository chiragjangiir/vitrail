'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Plus, Trash2, Upload, ClipboardPaste, Image as ImageIcon, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import { parseSerieCsv } from '@/lib/csv'
import PromoPreview, { type PromoInputs, type PromoTemplate } from './PromoPreview'

/** Une ligne de série : UNIQUEMENT ce qui varie d'un visuel à l'autre. Tout le reste — marque,
 *  mise en page, fond, mentions, calques — est commun et vient du parcours de gauche. */
export interface SerieLine {
  id: string
  slogan?: string
  price?: string
  original_price?: string
  discount_pct?: string
  productMediaId?: number | null
}

export type SerieState = 'queued' | 'sent' | 'error'

export const newSerieLine = (partial: Partial<SerieLine> = {}): SerieLine => ({
  id: `s${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
  ...partial,
})

/**
 * Le tableau du mode série — « un gabarit, N produits ».
 *
 * 🔑 LE TABLEAU **EST** LE PRODUIT : une ligne par visuel, et les colonnes sont exactement ce
 * qui change. Tout ce qui ne change pas est déclaré une seule fois dans le parcours de gauche.
 * C'est ce qui fait passer douze visuels de douze parcours complets à douze lignes.
 *
 * ⛔ Une ligne incomplète ne bloque pas la série : elle se NOMME et s'écarte. Faire échouer six
 * visuels pour un prix manquant serait le contraire de la productivité recherchée.
 */
export default function SerieTable({
  lines, onChange, template, format, inputs, backgroundUrl, fontFamilies,
  mediaThumbs, mediaNames, onPickProduct, status, busy,
}: {
  lines: SerieLine[]
  onChange: (lines: SerieLine[]) => void
  template?: PromoTemplate
  format: string
  /** Les valeurs COMMUNES : la ligne vient se superposer par-dessus pour l'aperçu. */
  inputs: PromoInputs
  backgroundUrl?: string
  fontFamilies: Record<string, string>
  mediaThumbs: Record<number, string>
  mediaNames: Record<number, string>
  onPickProduct: (lineId: string) => void
  status: Record<string, SerieState>
  busy: boolean
}) {
  const t = useTranslations()
  const fileRef = useRef<HTMLInputElement>(null)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasted, setPasted] = useState('')
  const [importNote, setImportNote] = useState<string | null>(null)

  const set = (id: string, patch: Partial<SerieLine>) =>
    onChange(lines.map((l) => (l.id === id ? { ...l, ...patch } : l)))
  const remove = (id: string) => onChange(lines.filter((l) => l.id !== id))

  /** Ajoute les lignes lues au tableau — l'import COMPLÈTE, il ne remplace pas ce qui est déjà là. */
  const ingest = (text: string) => {
    const res = parseSerieCsv(text)
    if (res.lines.length === 0) { setImportNote(t('promo.serie_import_empty')); return }
    onChange([...lines, ...res.lines.map((l) => newSerieLine(l))])
    // 🔑 Sans en-tête reconnu, les colonnes ont été lues PAR POSITION : il faut le dire, sinon
    // un fichier dont l'ordre diffère produit des prix dans le mauvais champ, en silence.
    setImportNote(res.hasHeader
      ? t('promo.serie_import_ok', { n: res.lines.length })
      : t('promo.serie_import_no_header', { n: res.lines.length }))
  }

  const th = 'px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-gray-400'
  const td = 'px-2 py-1.5 align-middle'
  const cell = 'w-full rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs focus:border-accent focus:outline-none'
  const ghost = 'inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-600 transition-sf hover:border-accent hover:text-accent'

  const complete = lines.filter((l) => (l.price ?? '').trim() !== '')
  const incomplete = lines.filter((l) => (l.price ?? '').trim() === '')

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2" data-testid="promo-serie">
      {/* Barre d'outils */}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={ghost} onClick={() => onChange([...lines, newSerieLine()])}
          data-testid="serie-add-line">
          <Plus className="h-3.5 w-3.5" />{t('promo.serie_add_line')}
        </button>
        <button type="button" className={ghost} onClick={() => fileRef.current?.click()}
          data-testid="serie-import-csv">
          <Upload className="h-3.5 w-3.5" />{t('promo.serie_import_csv')}
        </button>
        <button type="button" className={ghost} onClick={() => setPasteOpen((v) => !v)}
          data-testid="serie-paste-toggle">
          <ClipboardPaste className="h-3.5 w-3.5" />{t('promo.serie_paste')}
        </button>
        <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,text/csv" className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) f.text().then(ingest)
            e.target.value = ''
          }} />
        <span className="ml-auto text-[11px] text-gray-400" data-testid="serie-count">
          {t('promo.serie_count', { ready: complete.length, total: lines.length })}
        </span>
      </div>

      {/* Coller depuis un tableur : les colonnes arrivent séparées par des TABULATIONS,
          que le parseur reconnaît au même titre que `;` et `,`. */}
      {pasteOpen && (
        <div className="flex flex-col gap-1.5 rounded-lg border border-gray-200 p-2">
          <p className="text-[11px] text-gray-400">{t('promo.serie_paste_hint')}</p>
          <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={4}
            data-testid="serie-paste-area"
            placeholder={'Produit;Prix;Prix barré\nBrightwell V15;499,00;599,00'}
            className="w-full resize-none rounded border border-gray-200 bg-surface px-2 py-1.5 font-mono text-[11px] focus:border-accent focus:outline-none" />
          <div className="flex gap-2">
            <button type="button" className={ghost} data-testid="serie-paste-apply"
              disabled={!pasted.trim()}
              onClick={() => { ingest(pasted); setPasted(''); setPasteOpen(false) }}>
              {t('promo.serie_paste_apply')}
            </button>
          </div>
        </div>
      )}

      {importNote && (
        <p className="text-[11px] text-accent" data-testid="serie-import-note">{importNote}</p>
      )}

      {/* Le tableau */}
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-gray-200">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-gray-200">
              <th className={th} style={{ width: 58 }}></th>
              <th className={th} style={{ width: 74 }}>{t('promo.product')}</th>
              <th className={th}>{t('promo.slogan')}</th>
              <th className={th} style={{ width: 96 }}>{t('promo.price')}</th>
              <th className={th} style={{ width: 96 }}>{t('promo.original_price')}</th>
              <th className={th} style={{ width: 86 }}>{t('promo.discount')}</th>
              <th className={th} style={{ width: 92 }}>{t('promo.serie_state')}</th>
              <th className={th} style={{ width: 34 }}></th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-xs text-gray-400">
                {t('promo.serie_empty')}
              </td></tr>
            )}
            {lines.map((l) => {
              const missing = (l.price ?? '').trim() === ''
              const st = status[l.id]
              const thumb = l.productMediaId ? mediaThumbs[l.productMediaId] : undefined
              return (
                <tr key={l.id} data-testid="serie-row"
                  className={`border-b border-gray-200 last:border-0 ${missing ? 'bg-amber-500/5' : ''}`}>
                  {/* Aperçu : le gabarit commun + CETTE ligne — on voit ce qui sortira. */}
                  <td className={td}>
                    <div className="w-[46px] overflow-hidden rounded">
                      {template ? (
                        <PromoPreview template={template} format={format}
                          inputs={{ ...inputs, slogan: l.slogan, price: l.price,
                                    original_price: l.original_price, discount_pct: l.discount_pct }}
                          backgroundUrl={backgroundUrl} productUrl={thumb} fontFamilies={fontFamilies} />
                      ) : null}
                    </div>
                  </td>
                  <td className={td}>
                    <button type="button" onClick={() => onPickProduct(l.id)}
                      title={l.productMediaId ? mediaNames[l.productMediaId] : t('promo.choose_image')}
                      className="flex h-9 w-14 items-center justify-center overflow-hidden rounded border border-gray-200 transition-sf hover:border-accent">
                      {thumb
                        // eslint-disable-next-line @next/next/no-img-element
                        ? <img src={thumb} alt="" className="h-full w-full object-contain" />
                        : <ImageIcon className="h-4 w-4 text-gray-400" />}
                    </button>
                  </td>
                  <td className={td}>
                    <input value={l.slogan ?? ''} onChange={(e) => set(l.id, { slogan: e.target.value })}
                      className={cell} data-testid="serie-slogan" />
                  </td>
                  <td className={td}>
                    <input value={l.price ?? ''} onChange={(e) => set(l.id, { price: e.target.value })}
                      placeholder="4,99" className={cell} data-testid="serie-price" />
                  </td>
                  <td className={td}>
                    <input value={l.original_price ?? ''} onChange={(e) => set(l.id, { original_price: e.target.value })}
                      placeholder="6,99" className={cell} />
                  </td>
                  <td className={td}>
                    <input value={l.discount_pct ?? ''} onChange={(e) => set(l.id, { discount_pct: e.target.value })}
                      placeholder="auto" className={cell} />
                  </td>
                  <td className={td}>
                    {st === 'sent' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-green-600">
                        <CheckCircle2 className="h-3.5 w-3.5" />{t('promo.serie_st_sent')}</span>
                    ) : st === 'error' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-danger">
                        <AlertTriangle className="h-3.5 w-3.5" />{t('promo.serie_st_error')}</span>
                    ) : st === 'queued' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-accent">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />{t('promo.serie_st_queued')}</span>
                    ) : missing ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-3.5 w-3.5" />{t('promo.serie_st_incomplete')}</span>
                    ) : (
                      <span className="text-[11px] text-gray-400">{t('promo.serie_st_ready')}</span>
                    )}
                  </td>
                  <td className={td}>
                    <button type="button" onClick={() => remove(l.id)} disabled={busy}
                      aria-label={t('common.delete')}
                      className="text-gray-400 transition-sf hover:text-danger disabled:opacity-40">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ⛔ On NOMME les lignes écartées plutôt que de les taire — et la série part quand même. */}
      {incomplete.length > 0 && (
        <div data-testid="serie-incomplete"
          className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{t('promo.serie_incomplete', {
            n: incomplete.length,
            names: incomplete.map((l) => l.slogan?.trim() || t('promo.serie_unnamed')).join(', '),
          })}</span>
        </div>
      )}
    </div>
  )
}
