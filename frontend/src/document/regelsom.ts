/** Regelsom-beslisboom voor de live aansluit-badge onder de boekingsregels — EXACT dezelfde boom als de
 * backend (backend/app/documenten/regelsom.py, gedeeld door de veldvoorstel-badge én de harde check
 * "Regeltelling vs totaal"). Bugfix 04-09 (Huvanco-casus): de badge telde Σ(netto + btw) op terwijl de
 * btw per regel leeg was en zette die (feitelijk exclusieve) som tegen het incl-totaal → valse afwijking.
 *
 * Volgorde:
 *  1. btw bij ÁLLE regels ingevuld én incl-totaal bekend → Σ(netto + btw) vs incl
 *  2. gelezen excl-totaal bekend                         → Σnetto vs excl (netto-vs-netto)
 *  3. gelezen factuur-btw én incl-totaal bekend          → Σnetto + factuur-btw vs incl
 *  4. anders: niet toetsbaar — nooit stil excl-vs-incl; `reden` zegt wat ontbreekt.
 *
 * Puur weergave (de backend-check is de poort); geld = code, geen afronding buiten de cent-tolerantie. */

export interface RegelsomInvoer {
  /** Per regel het netto-bedrag (null = leeg/onherkenbaar). */
  netto: (number | null)[]
  /** Per regel het btw-bedrag (null = leeg/onherkenbaar) — zelfde lengte als `netto`. */
  btw: (number | null)[]
  /** Het boekvoorstel-veld "Totaalbedrag (incl. btw)" zoals de mens het heeft staan. */
  totaalIncl: number | null
  /** Gelezen totaal excl. btw uit het veldvoorstel (AI/template/UBL). */
  totaalExcl: number | null
  /** Gelezen btw-bedrag van de factuur uit het veldvoorstel. */
  factuurBtw: number | null
}

export type RegelsomReden = 'geen_regels' | 'netto_ontbreekt' | 'btw_per_regel_ontbreekt' | 'geen_totaal'

export interface RegelsomUitkomst {
  basis: 'incl' | 'excl' | null
  som: number | null
  vergelijk: number | null
  verschil: number | null
  sluitAan: boolean | null
  reden: RegelsomReden | null
  nettoSom: number | null
  /** 1-gebaseerde regelnummers zonder btw (alleen bij reden 'btw_per_regel_ontbreekt'). */
  regelsZonderBtw: number[]
}

const TOLERANTIE = 0.01

/** Som in centen (integers) — voorkomt drijvende-komma-ruis van 0.1 + 0.2 in de weergave. */
function somCenten(bedragen: number[]): number {
  return bedragen.reduce((acc, b) => acc + Math.round(b * 100), 0) / 100
}

function nietToetsbaar(reden: RegelsomReden, nettoSom: number | null, regelsZonderBtw: number[] = []): RegelsomUitkomst {
  return { basis: null, som: null, vergelijk: null, verschil: null, sluitAan: null, reden, nettoSom, regelsZonderBtw }
}

function uitkomst(basis: 'incl' | 'excl', som: number, vergelijk: number, nettoSom: number): RegelsomUitkomst {
  const verschil = Math.abs(Math.round((som - vergelijk) * 100)) / 100
  return { basis, som, vergelijk, verschil, sluitAan: verschil <= TOLERANTIE, reden: null, nettoSom, regelsZonderBtw: [] }
}

export function toetsRegelsom({ netto, btw, totaalIncl, totaalExcl, factuurBtw }: RegelsomInvoer): RegelsomUitkomst {
  if (netto.length === 0) return nietToetsbaar('geen_regels', null)
  if (netto.some((n) => n === null)) return nietToetsbaar('netto_ontbreekt', null)
  const nettoSom = somCenten(netto as number[])
  const regelsZonderBtw = btw.flatMap((b, i) => (b === null ? [i + 1] : []))
  const btwCompleet = regelsZonderBtw.length === 0

  if (btwCompleet && totaalIncl !== null) {
    return uitkomst('incl', somCenten([nettoSom, ...(btw as number[])]), totaalIncl, nettoSom)
  }
  if (totaalExcl !== null) return uitkomst('excl', nettoSom, totaalExcl, nettoSom)
  if (factuurBtw !== null && totaalIncl !== null) {
    return uitkomst('incl', somCenten([nettoSom, factuurBtw]), totaalIncl, nettoSom)
  }
  if (totaalIncl !== null) return nietToetsbaar('btw_per_regel_ontbreekt', nettoSom, regelsZonderBtw)
  return nietToetsbaar('geen_totaal', nettoSom)
}
