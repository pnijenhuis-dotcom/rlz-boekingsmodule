import { describe, expect, it } from 'vitest'
import {
  beschikbaarheid,
  bouwDagKolommen,
  conflictWeekLabel,
  dichtstbijzijndeEerderePloeg,
  kopieVolgendeWeekItems,
  legeCelKaart,
  matrixRijen,
  plusDagen,
  vergelijkProjectnummer,
  vrijTellers,
  conflictenUniek,
  conflictenVanaf,
  conflictenVoorPaneel,
  conflictenVoorWeek,
  dagTotaalLabel,
  handvatBereik,
  laagsteStatus,
  parseKaartParam,
  perProjectRijen,
  poolStand,
  projectTegels,
  vulhandvatVoorbeeld,
  zonderAkkoord,
} from './dagEerst'
import type { PlanningKaartDto, PlanningWeekDto } from './planningApi'
import { bulkToastTekst, isOngedaanToets, maakOngedaanStand } from './planBulkOngedaan'

/** Planning v3 dag-eerst (Peter 18-09): rij-grid → dagkolommen, dagtotalen, kaartstatus = laagste van de ploeg,
 * client-side conflict-toets (dubbel/afwezig/> 5/dossier), beschikbaarheid, vulhandvat-overslaan, projectbalk-sortering,
 * per-project-leesweergave en de toast/ongedaan-tekst. */

const P_A = 'aaaaaaaa-0000-0000-0000-00000000000a'
const P_B = 'bbbbbbbb-0000-0000-0000-00000000000b'
const P_C = 'cccccccc-0000-0000-0000-00000000000c'
const G1 = '11111111-0000-0000-0000-000000000001'
const G2 = '22222222-0000-0000-0000-000000000002'
const G3 = '33333333-0000-0000-0000-000000000003'

const DAGEN = [
  { naam: 'ma', datum: '2026-09-14' },
  { naam: 'di', datum: '2026-09-15' },
  { naam: 'wo', datum: '2026-09-16' },
  { naam: 'do', datum: '2026-09-17' },
  { naam: 'vr', datum: '2026-09-18' },
]

function kaart(id: string, naam: string, extra: Partial<PlanningKaartDto> = {}): PlanningKaartDto {
  return { gebruiker_id: id, naam, rol: 'zzper', dagdeel: 'heel', ...extra }
}

function week(): PlanningWeekDto {
  return {
    jaar: 2026,
    weeknummer: 38,
    maandag: '2026-09-14',
    zondag: '2026-09-20',
    projecten: [
      {
        project_id: P_A,
        project_naam: '25026 Arnhem-Kronenburg',
        opdrachtgever: 'Pleijweg',
        soort_werk: 'montage',
        looptijd_tot: null,
        is_actief: true,
        week_man: 3,
        per_datum: {
          '2026-09-14': [kaart(G1, 'Orfan Ogur', { rol: 'uitvoerder', uren_status: 'gekeurd', uren: '8' }), kaart(G2, 'M. Sanli', { uren_status: 'ingevuld', uren: '8' })],
          '2026-09-16': [kaart(G2, 'M. Sanli')],
        },
        werkopdrachten: [{ groep_id: 'w1', van: '2026-09-01', tot_en_met: '2026-09-30', tekst: 'opbouw fase 2' }],
        werkopdracht_overrides: { '2026-09-16': [{ groep_id: 'w1', tekst: 'laatste dag', afwijkend: true }] },
        week_uren: { ingevuld_uren: '16', gekeurd_uren: '8', open_aantal: 1, zonder_uren_aantal: 1 },
      },
      {
        project_id: P_B,
        project_naam: '26031 Rijssen',
        opdrachtgever: 'Olieman',
        soort_werk: null,
        looptijd_tot: '2026-09-15',
        is_actief: true,
        week_man: 1,
        per_datum: { '2026-09-16': [kaart(G2, 'M. Sanli', { uren_status: 'vraag' }), kaart(G3, 'R. Yücetaş')] },
        werkopdrachten: [],
        werkopdracht_overrides: {},
      },
      { project_id: P_C, project_naam: '144 Breda', opdrachtgever: 'Moeskops', soort_werk: null, looptijd_tot: null, is_actief: true, week_man: 0, per_datum: {}, werkopdrachten: [], werkopdracht_overrides: {} },
    ],
    pool: [
      { gebruiker_id: G1, naam: 'Orfan Ogur', rol: 'uitvoerder', geplande_dagen: '1' },
      { gebruiker_id: G2, naam: 'M. Sanli', rol: 'zzper', geplande_dagen: '3', dossier_onvolledig: true },
      { gebruiker_id: G3, naam: 'R. Yücetaş', rol: 'zzper', geplande_dagen: '1', afwezig_tot: '2026-09-17' },
    ],
    buiten_planning: [],
    dubbele_dagen: [],
    dubbele_dag_tellers: [],
    reserveringen: [{ id: 'r1', project_id: P_C, projectnaam: '144 Breda', datum: '2026-09-17' }],
    afwezigheid: [{ id: 'a1', gebruiker_id: G3, van: '2026-09-16', tot: '2026-09-17', reden: 'verlof' }],
  }
}

describe('dagEerst — transformatie', () => {
  it('laagste status van de ploeg: vraag < geen < ingevuld < gekeurd; leeg = geen', () => {
    expect(laagsteStatus([])).toBe('geen')
    expect(laagsteStatus([{ uren_status: 'gekeurd' }, { uren_status: 'ingevuld' }])).toBe('ingevuld')
    expect(laagsteStatus([{ uren_status: 'gekeurd' }, {}])).toBe('geen')
    expect(laagsteStatus([{ uren_status: 'vraag' }, { uren_status: 'gekeurd' }])).toBe('vraag')
  })

  it('rij-grid → dagkolommen: één kaart per project × dag, reservering = lege kaart, dagtotalen', () => {
    const kolommen = bouwDagKolommen(week(), DAGEN)
    expect(kolommen.map((k) => k.kaarten.length)).toEqual([1, 0, 2, 1, 0])
    const ma = kolommen[0].kaarten[0]
    expect(ma.sleutel).toBe(`${P_A}|2026-09-14`)
    expect(ma.ploeg.map((p) => p.naam)).toEqual(['Orfan Ogur', 'M. Sanli'])
    expect(ma.status).toBe('ingevuld')
    expect(ma.werkopdracht_tekst).toBe('opbouw fase 2')
    expect(dagTotaalLabel(kolommen[0])).toBe('2 man · 1 project')
    expect(dagTotaalLabel(kolommen[1])).toBe('—')
    // wo: twee kaarten, alfabetisch op projectnaam; de dag-override wint; Rijssen ná einddatum.
    const wo = kolommen[2]
    expect(wo.kaarten.map((k) => k.project_naam)).toEqual(['25026 Arnhem-Kronenburg', '26031 Rijssen'])
    expect(wo.kaarten[0].werkopdracht_tekst).toBe('laatste dag')
    expect(wo.kaarten[0].werkopdracht_afwijkend).toBe(true)
    expect(wo.kaarten[1].na_einddatum).toBe(true)
    expect(wo.kaarten[1].status).toBe('vraag')
    expect(dagTotaalLabel(wo)).toBe('3 man · 2 projecten')
    // do: reservering zonder ploeg = gereserveerde kaart.
    const doK = kolommen[3].kaarten[0]
    expect(doK.gereserveerd).toBe(true)
    expect(doK.reservering?.id).toBe('r1')
    expect(doK.ploeg).toEqual([])
    expect(dagTotaalLabel(kolommen[3])).toBe('0 man · 1 project')
  })

  it('urenfilter werkt als kaartfilter: alleen passende ploegleden blijven, kaart zonder passende leden valt weg', () => {
    const kolommen = bouwDagKolommen(week(), DAGEN, { urenFilter: 'zonder' })
    expect(kolommen[0].kaarten).toEqual([]) // ma: beide hebben uren
    expect(kolommen[2].kaarten.map((k) => k.ploeg.map((p) => p.naam))).toEqual([['M. Sanli'], ['R. Yücetaş']])
    expect(kolommen[3].kaarten).toEqual([]) // reservering valt buiten een status-filter
  })

  it('conflicten: dubbel op één dag, afwezig, dossier — uniek voor de balk, per kaart gekoppeld', () => {
    const data = week()
    const conflicten = conflictenVoorWeek(data)
    const soorten = conflictenUniek(conflicten).map((c) => `${c.soort}:${c.datum}:${c.naam}`)
    expect(soorten).toContain(`dubbel:2026-09-16:M. Sanli`)
    expect(soorten).toContain(`afwezig:2026-09-16:R. Yücetaş`)
    // v4 (28-09): dossier-onvolledig = één rij per PERSOON per week (eerste geplande dag, alle projecten) — nooit per kaart × dag,
    // anders verdringt het dossier-signaal (Universal: 0 dossiers → iedereen) de échte planningsconflicten; kaarten kleuren er niet van.
    const dossier = conflicten.filter((c) => c.soort === 'geen_dossier')
    expect(dossier).toHaveLength(1)
    expect(dossier[0]).toMatchObject({ gebruiker_id: G2, datum: '2026-09-14', project_ids: [P_A, P_B] })
    expect(dossier[0].tekst).toContain('gepland op 2 dagen deze week')
    const wo = bouwDagKolommen(data, DAGEN, { conflicten })[2]
    expect(wo.kaarten[0].conflicten.map((c) => c.soort).sort()).toEqual(['dubbel'])
    expect(wo.kaarten[1].conflicten.map((c) => c.soort).sort()).toEqual(['afwezig', 'dubbel'])
  })

  it('21-09: paneel = alleen vanaf vandaag, gegroepeerd per dag, uniek; label "deze week" alleen voor de huidige week', () => {
    const data = week()
    const conflicten = conflictenVoorWeek(data)
    // Vandaag = di 15-9: ma 14-9 (dossier M. Sanli) is historie en valt uit het paneel; wo 16-9 blijft.
    const groepen = conflictenVoorPaneel(conflicten, '2026-09-15')
    expect(groepen.map((g) => g.label)).toEqual(['wo 16-9'])
    const soorten = groepen[0].rijen.map((c) => `${c.soort}:${c.naam}`)
    expect(soorten).toContain('dubbel:M. Sanli')
    expect(soorten).toContain('afwezig:R. Yücetaş')
    expect(soorten.filter((x) => x === 'dubbel:M. Sanli')).toHaveLength(1) // dubbel over 2 kaarten = één rij
    expect(conflictenVanaf(conflicten, '2026-09-17')).toEqual([])
    expect(conflictenUniek(conflicten).length - conflictenUniek(conflictenVanaf(conflicten, '2026-09-15')).length).toBe(1)
    expect(conflictWeekLabel({ jaar: 2026, weeknummer: 38 }, { jaar: 2026, weeknummer: 38 })).toBe('deze week')
    expect(conflictWeekLabel({ jaar: 2026, weeknummer: 37 }, { jaar: 2026, weeknummer: 39 })).toBe('week 37')
  })

  it('21-09: een akkoord verbergt het conflict alleen bij exact dezelfde planningsstand (gesorteerde project-id\'s)', () => {
    const data = week()
    const dubbel = conflictenVoorWeek(data).filter((c) => c.soort === 'dubbel' && c.gebruiker_id === G2)
    expect(dubbel.length).toBe(2)
    const akkoord = { id: 'a', gebruiker_id: G2, datum: '2026-09-16', soort: 'dubbel' as const, project_ids: [P_B, P_A], reden: 'x', aangemaakt_door: 'b', aangemaakt_op: 't' }
    expect(zonderAkkoord(dubbel, [akkoord])).toEqual([])
    // Andere stand (derde project erbij) → conflict weer zichtbaar.
    expect(zonderAkkoord(dubbel, [{ ...akkoord, project_ids: [P_A, P_B, P_C] }])).toHaveLength(2)
    // Ander soort/persoon/dag → geen effect; te_groot/geen_dossier nooit verborgen.
    expect(zonderAkkoord(dubbel, [{ ...akkoord, soort: 'afwezig' }])).toHaveLength(2)
    expect(zonderAkkoord(dubbel, [{ ...akkoord, datum: '2026-09-17' }])).toHaveLength(2)
    data.conflict_akkoorden = [akkoord]
    expect(conflictenVoorWeek(data).some((c) => c.soort === 'dubbel' && c.gebruiker_id === G2)).toBe(false)
    expect(conflictenVoorWeek(data).some((c) => c.soort === 'geen_dossier')).toBe(true)
  })

  it('> 5 op één kaart = conflict te_groot (besluit C)', () => {
    const data = week()
    data.projecten[2].per_datum['2026-09-15'] = Array.from({ length: 6 }, (_, i) => kaart(`${i}`, `P${i}`))
    expect(conflictenVoorWeek(data).some((c) => c.soort === 'te_groot' && c.project_id === P_C)).toBe(true)
  })

  it('beschikbaarheid per persoon × dag vanaf een kaart: vrij / al op ‹project› / afwezig', () => {
    const data = week()
    expect(beschikbaarheid(data, G1, '2026-09-15', P_A)).toEqual({ soort: 'vrij' })
    expect(beschikbaarheid(data, G2, '2026-09-16', P_A)).toMatchObject({ soort: 'al_op', project_naam: '26031 Rijssen' })
    expect(beschikbaarheid(data, G2, '2026-09-16', P_B)).toMatchObject({ soort: 'al_op', project_naam: '25026 Arnhem-Kronenburg' })
    expect(beschikbaarheid(data, G3, '2026-09-17', null)).toMatchObject({ soort: 'afwezig', tot: '2026-09-17', reden: 'verlof' })
    expect(poolStand(data.pool[2], DAGEN.map((d) => d.datum), data.afwezigheid)).toBe('afwezig')
    expect(poolStand({ gebruiker_id: 'x', naam: 'x', rol: 'zzper', geplande_dagen: '0' }, [], [])).toBe('vrij')
  })

  it('vulhandvat: kopieert kaart + ploeg, slaat een doeldag met een bestaande kaart van hetzelfde project over, voorspelt conflicten', () => {
    const data = week()
    const ma = bouwDagKolommen(data, DAGEN)[0].kaarten[0]
    const bereik = handvatBereik(DAGEN.map((d) => d.datum), '2026-09-14', '2026-09-18')
    expect(bereik).toHaveLength(5)
    const vb = vulhandvatVoorbeeld(data, ma, bereik)
    // wo heeft al een Arnhem-kaart → overgeslagen; di/do/vr × 2 personen = 6 items.
    expect(vb.overgeslagen_datums).toEqual(['2026-09-16'])
    expect(vb.items).toHaveLength(6)
    expect(vb.doelen.map((d) => d.items.length)).toEqual([2, 0, 2, 2])
    expect(vb.aantal_conflicten).toBe(0)
    // Kopie van de Rijssen-kaart (wo) naar do: Sanli vrij, Yücetaş afwezig do → 1 conflict.
    const woRijssen = bouwDagKolommen(data, DAGEN)[2].kaarten[1]
    const vb2 = vulhandvatVoorbeeld(data, woRijssen, ['2026-09-16', '2026-09-17'])
    expect(vb2.items.map((i) => i.conflict)).toEqual([null, 'afwezig'])
    // Weekgrens: buiten de werkdagen = leeg bereik.
    expect(handvatBereik(DAGEN.map((d) => d.datum), '2026-09-14', '2026-09-21')).toEqual([])
  })

  it('projectbalk: gepland deze week eerst (mét samenvatting), dan alfabetisch; zoeken diakriet-loos op naam/opdrachtgever', () => {
    const tegels = projectTegels(week(), DAGEN, '')
    expect(tegels.map((t) => `${t.project_naam}:${t.samenvatting}`)).toEqual([
      '144 Breda:do · 0 man',
      '25026 Arnhem-Kronenburg:ma–wo · 2 man',
      '26031 Rijssen:wo · 2 man',
    ])
    expect(projectTegels(week(), DAGEN, 'olíeman').map((t) => t.project_naam)).toEqual(['26031 Rijssen'])
  })

  it('per project (lezen): rij per project mét planning, cellen, mandagen/uren/conflicten-tekst, telling zonder planning', () => {
    const data = week()
    const kolommen = bouwDagKolommen(data, DAGEN)
    const { rijen, zonder_planning } = perProjectRijen(kolommen, data)
    expect(rijen.map((r) => r.project_naam)).toEqual(['144 Breda', '25026 Arnhem-Kronenburg', '26031 Rijssen'])
    const arnhem = rijen[1]
    expect(arnhem.cellen.map((c) => c.aantal)).toEqual([2, 0, 1, 0, 0])
    expect(arnhem.week_tekst).toBe('3 mandagen · uren 2/3 · 1 conflict') // wo dubbel (v4: dossier is geen kaartconflict)
    expect(rijen[0].week_tekst).toBe('gereserveerd — nog geen ploeg')
    expect(zonder_planning).toBe(0)
  })

  it('v4 matrix: rijen = projecten mét planning/reservering, dezelfde rij over de week; volgorde eerste dag → aantal dagen → projectnummer; urenfilter filtert rijen, niet cellen', () => {
    const data = week()
    // Extra project mét planning ma + do (2 dagen, nummer 25001) — Arnhem heeft ma + wo (2 dagen, nummer 25026).
    const P_D = 'dddddddd-0000-0000-0000-00000000000d'
    data.projecten.push({ project_id: P_D, project_naam: '25001 Zwolle', opdrachtgever: null, soort_werk: null, looptijd_tot: null, is_actief: true, week_man: 1, per_datum: { '2026-09-14': [{ gebruiker_id: G1, naam: 'O. Ogur', rol: 'zzper', dagdeel: 'heel' }], '2026-09-17': [{ gebruiker_id: G1, naam: 'O. Ogur', rol: 'zzper', dagdeel: 'heel' }] }, werkopdrachten: [], werkopdracht_overrides: {} })
    const kolommen = bouwDagKolommen(data, DAGEN)
    const rijen = matrixRijen(kolommen)
    // Eerste dag ma: Zwolle en Arnhem (beide 2 dagen) → projectnummer beslist (25001 vóór 25026); daarna Rijssen (wo), Breda (do, reservering).
    expect(rijen.map((r) => [r.project_naam, r.eerste_datum, r.aantal_dagen])).toEqual([
      ['25001 Zwolle', '2026-09-14', 2],
      ['25026 Arnhem-Kronenburg', '2026-09-14', 2],
      ['26031 Rijssen', '2026-09-16', 1],
      ['144 Breda', '2026-09-17', 1],
    ])
    // Elke rij heeft vijf cellen; een cel zonder kaart = lege plancel (null).
    const arnhem = rijen[1]
    expect(arnhem.cellen.map((c) => (c.kaart ? c.kaart.ploeg.length : null))).toEqual([2, null, 1, null, null])
    expect(arnhem.cellen.every((c) => c.kaart === null || c.kaart.project_id === P_A)).toBe(true)
    // Urenfilter 'zonder' filtert RIJEN: Arnhem blijft (Sanli wo zonder uren) mét complete kaarten; Breda (alleen reservering) valt weg.
    const gefilterd = matrixRijen(kolommen, { urenFilter: 'zonder' })
    expect(gefilterd.map((r) => r.project_naam)).toEqual(['25001 Zwolle', '25026 Arnhem-Kronenburg', '26031 Rijssen'])
    expect(gefilterd[1].cellen[0].kaart?.ploeg.length).toBe(2) // cel niet gefilterd
    expect(vergelijkProjectnummer('25001 A', '25026 B')).toBeLessThan(0)
    expect(vergelijkProjectnummer('144 Breda', '25001 A')).toBeLessThan(0) // numeriek, niet lexicografisch
  })

  it('v4 lege cel: virtuele kaart voor project × dag + voorstel = ploeg van de dichtstbijzijnde EERDERE dag (niets opgeslagen)', () => {
    const data = week()
    const werkdagen = DAGEN.map((d) => d.datum)
    const leeg = legeCelKaart(data, P_A, '2026-09-15')
    expect(leeg).toMatchObject({ sleutel: `${P_A}|2026-09-15`, project_id: P_A, datum: '2026-09-15', gereserveerd: true, leeg: true, ploeg: [] })
    expect(legeCelKaart(data, 'onbekend', '2026-09-15')).toBeNull()
    // Di: dichtstbijzijnde eerdere dag mét planning op Arnhem = ma (Ogur, Sanli); vr → wo (dichtstbijzijnd, niet ma); ma zelf → null.
    expect(dichtstbijzijndeEerderePloeg(data, P_A, '2026-09-15', werkdagen)).toEqual({ datum: '2026-09-14', gebruiker_ids: [G1, G2] })
    expect(dichtstbijzijndeEerderePloeg(data, P_A, '2026-09-18', werkdagen)?.datum).toBe('2026-09-16')
    expect(dichtstbijzijndeEerderePloeg(data, P_A, '2026-09-14', werkdagen)).toBeNull()
  })

  it('v4 kopie naar volgende week: dezelfde weekdag (+7), zelfde project, dagdeel heel; toast-tekst; vrij-tellers voor de paneelkop', () => {
    expect(plusDagen('2026-09-17', 7)).toBe('2026-09-24')
    expect(plusDagen('2026-12-31', 7)).toBe('2027-01-07')
    expect(kopieVolgendeWeekItems({ project_id: P_A, datum: '2026-09-17' }, [G1, G2])).toEqual([
      { gebruiker_id: G1, project_id: P_A, datum: '2026-09-24', dagdeel: 'heel' },
      { gebruiker_id: G2, project_id: P_A, datum: '2026-09-24', dagdeel: 'heel' },
    ])
    const r = (gebruiker_id: string, uitkomst: 'gedaan' | 'overgeslagen' | 'conflict', conflict: 'project' | 'afwezig' | null = null) => ({ gebruiker_id, project_id: P_A, datum: '2026-09-24', dagdeel: 'heel' as const, uitkomst, reden: null, conflict, conflict_projectnaam: null })
    const toast = bulkToastTekst(
      { correlatie_id: 'c', aangemaakt: [], resultaten: [r(G1, 'gedaan'), r(G2, 'conflict', 'project'), r(G3, 'overgeslagen', 'afwezig'), r('x', 'overgeslagen')] },
      { soort: 'kopie', doelDatums: ['2026-09-24'], naarWeek: { jaar: 2026, weeknummer: 39 } },
    )
    expect(toast).toBe('Gekopieerd naar do 24-9 (week 39) · 2 persoon-dagen · 1 conflict · 1 afwezig overgeslagen · 1 al gepland')
    const stand = maakOngedaanStand({ correlatie_id: 'c', aangemaakt: [], resultaten: [r(G2, 'conflict', 'project')] }, { soort: 'kopie', doelDatums: ['2026-09-24'], naarWeek: { jaar: 2026, weeknummer: 39 }, nu: 0 })
    expect(stand.naar_week).toEqual({ jaar: 2026, weeknummer: 39 })
    expect(stand.conflict_sleutel).toBeNull() // het conflict ligt in week+1 — "Naar week 39" is de handeling
    const data = week()
    // Di 15-9: niemand gepland → Ogur, Sanli, Yücetaş vrij (Yücetaş pas 16–17 afwezig); hele week vrij: niemand (Ogur 1 dg, Sanli 3 dg, Yücetaş afwezig).
    const v = vrijTellers(data, '2026-09-15', DAGEN.map((d) => d.datum))
    expect(v).toEqual({ dag: 3, week: 0, namen_week: [] })
  })

  it('deeplink ?kaart=<project>|<datum>', () => {
    expect(parseKaartParam(`${P_A}|2026-09-14`)).toBe(`${P_A}|2026-09-14`)
    expect(parseKaartParam('onzin')).toBeNull()
    expect(parseKaartParam(null)).toBeNull()
  })
})

describe('planBulkOngedaan — toast en Cmd/Ctrl-Z', () => {
  const resultaat = {
    correlatie_id: 'c-1',
    aangemaakt: [{ gebruiker_id: G1, project_id: P_A, datum: '2026-09-15' }],
    resultaten: [
      { gebruiker_id: G1, project_id: P_A, datum: '2026-09-15', dagdeel: 'heel' as const, uitkomst: 'gedaan' as const, reden: null, conflict: null, conflict_projectnaam: null },
      { gebruiker_id: G2, project_id: P_A, datum: '2026-09-15', dagdeel: 'heel' as const, uitkomst: 'conflict' as const, reden: 'al op Rijssen', conflict: 'project' as const, conflict_projectnaam: '26031 Rijssen' },
      { gebruiker_id: G2, project_id: P_A, datum: '2026-09-16', dagdeel: 'heel' as const, uitkomst: 'overgeslagen' as const, reden: 'bestaat al', conflict: null, conflict_projectnaam: null },
    ],
  }
  it('vulhandvat-tekst "Gekopieerd naar di–vr · N persoon-dagen · 1 conflict · 1 overgeslagen"', () => {
    expect(bulkToastTekst(resultaat, { soort: 'vulhandvat', doelDatums: ['2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18'] })).toBe(
      'Gekopieerd naar di–vr · 2 persoon-dagen · 1 conflict · 1 overgeslagen',
    )
    expect(bulkToastTekst(resultaat, { soort: 'ploeg', verwijderd: 1 })).toBe('Ploeg opgeslagen · 2 toegevoegd · 1 verwijderd · 1 conflict · 1 overgeslagen')
    const stand = maakOngedaanStand(resultaat, { soort: 'vulhandvat', doelDatums: ['2026-09-15'], nu: 1000 })
    expect(stand.aangemaakt).toEqual(resultaat.aangemaakt)
    expect(stand.conflict_sleutel).toBe(`${P_A}|2026-09-15`)
    expect(stand.verloopt_op).toBe(11000)
  })
  it('Cmd/Ctrl-Z alleen buiten invoervelden en zonder shift', () => {
    const buiten = { key: 'z', metaKey: true, ctrlKey: false, shiftKey: false, target: null }
    expect(isOngedaanToets(buiten)).toBe(true)
    expect(isOngedaanToets({ ...buiten, shiftKey: true })).toBe(false)
    expect(isOngedaanToets({ ...buiten, metaKey: false })).toBe(false)
    const input = document.createElement('input')
    expect(isOngedaanToets({ ...buiten, target: input })).toBe(false)
  })
})
