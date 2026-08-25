import { describe, expect, it } from 'vitest'
import type { VeldgebruikerDto } from '../meerwerk/meerwerkApi'
import { dossierBadge } from './DossierModal'

/* Dossier-badge op het veldwerkers-paneel (steigerbouw-run A1, mockup meerwerk-kantoor
 * "📁 dossier 4/6" / "📁 dossier compleet"): prioriteit geblokkeerd > ontbrekend/verlopen >
 * ter controle > verloopt binnenkort > compleet; zonder dossier-rijen géén badge. */

function veldwerker(dossiers: VeldgebruikerDto['dossiers']): VeldgebruikerDto {
  return {
    gebruiker_id: 'g1', naam: 'Milan K.', e_mail: 'm@x', rol: 'zzper', status: 'actief',
    projecten: [], zzpers: [], crediteuren: [], uren_afwijking_aantal: 0, uren_afwijking_som: '0', dossiers,
  }
}

const basis = {
  administratie_id: 'a1', administratie_naam: 'Universal', aantal_verplicht: 6, aantal_aanwezig: 4,
  aantal_ontbrekend: 0, aantal_verlopen: 0, aantal_verloopt_binnenkort: 0, aantal_ter_controle: 0,
  herinneringen_teller: 0, geblokkeerd: false, compleet: false,
}

describe('dossierBadge', () => {
  it('geen dossier-rijen → geen badge (rol zonder dossier / geen scope)', () => {
    expect(dossierBadge(undefined)).toBeNull()
    expect(dossierBadge(veldwerker([]))).toBeNull()
    expect(dossierBadge({ ...veldwerker([]), dossiers: undefined as never })).toBeNull()
  })
  it('ontbrekend of verlopen → rood met teller "4/6"', () => {
    expect(dossierBadge(veldwerker([{ ...basis, aantal_ontbrekend: 2 }]))).toEqual({ variant: 'danger', label: '📁 dossier 4/6' })
    expect(dossierBadge(veldwerker([{ ...basis, aantal_verlopen: 1, aantal_aanwezig: 5 }]))?.variant).toBe('danger')
  })
  it('geblokkeerd wint van alles', () => {
    expect(dossierBadge(veldwerker([{ ...basis, aantal_ontbrekend: 1, geblokkeerd: true, herinneringen_teller: 3 }]))?.label).toContain('geblokkeerd')
  })
  it('ter controle → oranje; verloopt binnenkort → oranje; compleet → groen', () => {
    expect(dossierBadge(veldwerker([{ ...basis, aantal_ter_controle: 2 }]))).toEqual({ variant: 'warn', label: '📁 dossier 4/6 · 2 ter controle' })
    expect(dossierBadge(veldwerker([{ ...basis, aantal_aanwezig: 6, aantal_verloopt_binnenkort: 1 }]))?.variant).toBe('warn')
    expect(dossierBadge(veldwerker([{ ...basis, aantal_aanwezig: 6, compleet: true }]))).toEqual({ variant: 'ok', label: '📁 dossier compleet' })
  })
})
