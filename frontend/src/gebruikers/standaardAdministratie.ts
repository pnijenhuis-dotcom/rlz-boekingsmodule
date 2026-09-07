/** Standaard-administratie voor de veldwerker-dialogen (dossier, crediteur koppelen) — fixrun
 * 07-09 blok C3. Kernprincipe 7: administratie is een FILTER, nooit een poort — een dialoog
 * opent dus altijd voorgeselecteerd, de picker blijft als wissel-filter staan. Volgorde:
 *   (1) precies één administratie in scope → die;
 *   (2) anders de administratie van de recentste planning / crediteur-koppeling van deze
 *       veldwerker (server-hints, `voorkeur` bepaalt welke van de twee eerst telt);
 *   (3) anders de administratie mét uren-&-meerwerk-opt-in — precies één → die; meerdere → de
 *       eerste alfabetisch (de picker toont dan de wissel).
 * Nooit een hardcoded administratie (in de praktijk is dit Universal Steigerbouw, maar dat volgt
 * uit de opt-in-vlag, niet uit code). Zonder kandidaat: null — de dialoog valt dan terug op de
 * eerste keuze uit de lijst zoals vóór 07-09. */

export type StandaardReden =
  | 'enige_in_scope'
  | 'recentste_planning'
  | 'recentste_koppeling'
  | 'enige_met_opt_in'
  | 'eerste_met_opt_in'

export interface StandaardKeuze {
  id: string
  reden: StandaardReden
}

export interface StandaardHints {
  recentstePlanning?: string | null
  recentsteKoppeling?: string | null
  /** Welke recency eerst telt — het dossier volgt de planning, de crediteur-koppeling de koppeling. */
  voorkeur?: 'planning' | 'koppeling'
}

export interface StandaardOptIns {
  /** Administratie-id's mét `uren_meerwerk_ingeschakeld`. */
  urenMeerwerk: ReadonlyArray<string>
}

export function kiesStandaardAdministratie(
  scope: ReadonlyArray<{ id: string; naam: string }>,
  hints: StandaardHints = {},
  optIns: StandaardOptIns = { urenMeerwerk: [] },
): StandaardKeuze | null {
  if (scope.length === 0) return null
  if (scope.length === 1) return { id: scope[0].id, reden: 'enige_in_scope' }

  const inScope = (id: string | null | undefined): id is string => !!id && scope.some((a) => a.id === id)
  const volgorde: Array<[string | null | undefined, StandaardReden]> =
    hints.voorkeur === 'koppeling'
      ? [
          [hints.recentsteKoppeling, 'recentste_koppeling'],
          [hints.recentstePlanning, 'recentste_planning'],
        ]
      : [
          [hints.recentstePlanning, 'recentste_planning'],
          [hints.recentsteKoppeling, 'recentste_koppeling'],
        ]
  for (const [id, reden] of volgorde) {
    if (inScope(id)) return { id, reden }
  }

  const metOptIn = scope
    .filter((a) => optIns.urenMeerwerk.includes(a.id))
    .sort((a, b) => a.naam.localeCompare(b.naam, 'nl'))
  if (metOptIn.length === 1) return { id: metOptIn[0].id, reden: 'enige_met_opt_in' }
  if (metOptIn.length > 1) return { id: metOptIn[0].id, reden: 'eerste_met_opt_in' }
  return null
}

/** Opt-in-lijst uit de administratie-DTO's (veld optioneel: oudere mocks/antwoorden missen 'm). */
export function urenMeerwerkOptIns(administraties: ReadonlyArray<{ id: string; uren_meerwerk_ingeschakeld?: boolean }>): string[] {
  return administraties.filter((a) => a.uren_meerwerk_ingeschakeld === true).map((a) => a.id)
}

/** Korte uitleg onder de picker — alleen als de keuze níet triviaal is (meerdere in scope). */
export function standaardRedenLabel(reden: StandaardReden): string | null {
  switch (reden) {
    case 'recentste_planning':
      return 'voorgeselecteerd: administratie van de recentste planning'
    case 'recentste_koppeling':
      return 'voorgeselecteerd: administratie van de recentste crediteur-koppeling'
    case 'enige_met_opt_in':
      return 'voorgeselecteerd: de administratie met uren & meerwerk'
    case 'eerste_met_opt_in':
      return 'voorgeselecteerd: eerste administratie met uren & meerwerk — wissel hierboven'
    case 'enige_in_scope':
      return null
  }
}
