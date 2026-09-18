import { describe, expect, it } from 'vitest'
import {
  beschikbaarheid,
  bouwDagKolommen,
  conflictenUniek,
  conflictenVoorWeek,
  dagTotaalLabel,
  handvatBereik,
  laagsteStatus,
  parseKaartParam,
  perProjectRijen,
  poolStand,
  projectTegels,
  vulhandvatVoorbeeld,
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
    expect(soorten.filter((s) => s.startsWith('geen_dossier')).length).toBe(3) // M. Sanli op ma, wo (2 kaarten)
    const wo = bouwDagKolommen(data, DAGEN, { conflicten })[2]
    expect(wo.kaarten[0].conflicten.map((c) => c.soort).sort()).toEqual(['dubbel', 'geen_dossier'])
    expect(wo.kaarten[1].conflicten.map((c) => c.soort).sort()).toEqual(['afwezig', 'dubbel', 'geen_dossier'])
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
    expect(arnhem.week_tekst).toBe('3 mandagen · uren 2/3 · 3 conflicten') // ma dossier + wo dubbel + wo dossier
    expect(rijen[0].week_tekst).toBe('gereserveerd — nog geen ploeg')
    expect(zonder_planning).toBe(0)
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
