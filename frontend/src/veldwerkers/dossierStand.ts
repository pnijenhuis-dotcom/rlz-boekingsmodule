/** Dossier-kolom + filter "dossier onvolledig" op /veldwerkers (veldwerkers-run 14-09) — GEEN nieuwe berekening:
 * alles komt uit de bestaande `DossierSamenvattingDto` per administratie (backend `dossier.samenvatting_in_sessie`),
 * dezelfde bron als de badge in `gebruikers/DossierModal.tsx::dossierBadge` en het werkvoorraad-signaal op de klantpagina
 * (`dossier_veldwerkers_met_signaal` = ontbrekend/verlopen/verloopt binnenkort, `dossier_ter_controle`, `dossier_geblokkeerd`).
 * Een detacheerder is een bureau en heeft geen dossier (A1) → `null`. */
import type { VeldgebruikerDto } from '../meerwerk/meerwerkApi'

export type DossierStandVariant = 'ok' | 'warn' | 'danger'

export interface DossierStand {
  label: string
  variant: DossierStandVariant
  /** Telt mee in het filter "dossier onvolledig": ontbrekend/verlopen/verloopt binnenkort/ter controle/geblokkeerd. */
  onvolledig: boolean
}

export function dossierStand(info: VeldgebruikerDto): DossierStand | null {
  if (info.rol === 'detacheerder') return null
  const dossiers = info.dossiers ?? []
  if (dossiers.length === 0) return null
  const som = (kies: (d: VeldgebruikerDto['dossiers'][number]) => number) => dossiers.reduce((s, d) => s + kies(d), 0)
  const geblokkeerd = dossiers.some((d) => d.geblokkeerd)
  const ontbrekend = som((d) => d.aantal_ontbrekend)
  const verlopen = som((d) => d.aantal_verlopen)
  const binnenkort = som((d) => d.aantal_verloopt_binnenkort)
  const terControle = som((d) => d.aantal_ter_controle)
  if (geblokkeerd) return { label: 'geblokkeerd', variant: 'danger', onvolledig: true }
  if (verlopen > 0 && ontbrekend > 0) {
    return { label: `${ontbrekend} ${ontbrekend === 1 ? 'ontbreekt' : 'ontbreken'} · ${verlopen} verlopen`, variant: 'danger', onvolledig: true }
  }
  if (verlopen > 0) return { label: `${verlopen} verlopen`, variant: 'danger', onvolledig: true }
  if (ontbrekend > 0) return { label: `${ontbrekend} ${ontbrekend === 1 ? 'ontbreekt' : 'ontbreken'}`, variant: 'danger', onvolledig: true }
  if (terControle > 0) return { label: `${terControle} ter controle`, variant: 'warn', onvolledig: true }
  if (binnenkort > 0) return { label: 'verloopt binnenkort', variant: 'warn', onvolledig: true }
  return { label: 'compleet', variant: 'ok', onvolledig: false }
}

export function isDossierOnvolledig(info: VeldgebruikerDto): boolean {
  return dossierStand(info)?.onvolledig === true
}
