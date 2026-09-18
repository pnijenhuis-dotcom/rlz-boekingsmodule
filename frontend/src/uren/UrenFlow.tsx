// Uren & meerwerk — veldkant in de bestaande app (fase 4, mockup/uren-uitvoerder.html 1-op-1,
// BOUW GO Peter 2026-08-21). Drie rollen, rolafhankelijke functietabs:
//  - ZZP'er (sinds 04-09 planning-gestuurd, opdracht Peter blok A): mijn weken (alleen weken mét
//    planning + deze week) → projecten in die week (sinds 18-09 ÁLLE actieve projecten, gepland bovenaan,
//    doorzoekbaar — de aparte stap "+ ander project" is vervallen) → weekstaat (dagen: uren + optionele m² +
//    keuze Doorfactureren/Niet doorfactureren per regel) → indienen per week; "Ingediend" toont de statussen
//    over alle projecten heen.
//  - Uitvoerder: projecten (ÁLLE actieve projecten sinds 18-09, gekoppeld bovenaan; specs, contract/offerte
//    alleen-lezen, meerwerk melden zonder prijzen), "Mijn uren" (sinds 18-09: eigen weekstaten — "soort
//    urenstaat achteraf", zelfde flow als de ZZP'er, nooit zelf keuren) én "Te keuren" — keuring op
//    WEEKNIVEAU: week akkoord óf week afkeuren met verplichte reden (hele week terug als "corrigeren").
//    Géén planningstab meer (feedback uitvoerder via Peter 18-09 blok D, allowlist auth/rollen.ts).
//  - Detacheerder: mijn ZZP'ers (werklijst = alleen wie nog iets te doen heeft; niets = "✓ Alles is
//    bij") → daarna exact dezelfde schermen als de ZZP'er zelf, mét "· namens <ZZP'er>" in de
//    kopregel; geen projectinhoud.
// Dit bestand hoort bij de accordeur-chunk: geen kantoor-imports (performance-budget).

import { Fragment, useCallback, useEffect, useState, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { haalMijnAdministraties, isVoorwaardenVereist } from '../accordeur/accordeurApi'
import { PdfWeergave } from '../accordeur/PdfWeergave'
import { VoorwaardenScherm } from '../accordeur/VoorwaardenScherm'
import { useAuth } from '../auth/AuthContext'
import { toontPlanningTab } from '../auth/rollen'
import { ACC_TERUG_EVENT } from '../accordeur/androidTerug'
import { UitlogIcoon } from '../accordeur/UitlogIcoon'
import {
  beantwoordMeerwerkVraag,
  datumKort,
  datumMetTijd,
  dienWeekIn,
  doorfacturerenLabel,
  eenheidLabel,
  EENHEDEN,
  haalIngediend,
  haalMijnPlanning,
  haalMijnZzpers,
  haalProjectDetail,
  haalProjectDocumentBlob,
  haalTeKeuren,
  haalUitvoerderProjecten,
  haalWeekProjecten,
  haalWeekstaat,
  haalZzpWekenOverzicht,
  heeftVoorstel,
  isoWeekVan,
  keurWeekAf,
  keurWeekGoed,
  meldMeerwerk,
  schuifWeek,
  urenLabel,
  voorstelLabel,
  weekDagen,
  weekTotaalLabel,
  weekKaarten,
  standaardDag,
  dagTotaal,
  haalOmschrijvingChips,
  STANDAARD_OMSCHRIJVING_CHIPS,
  OVERIG_CHIP,
  UREN_TIKKEUZES,
  stapHalfUur,
  vergetenDagen,
  indienSamenvatting,
  isM2Project,
  zetDag,
  type DagCorrectieInvoer,
  type IngediendeWeekDto,
  type MeerwerkDto,
  type MijnPlanningDagDto,
  type ProjectDetailDto,
  type ProjectDocumentKaartDto,
  type TeKeurenItemDto,
  type UitvoerderProjectKaartDto,
  type WeekKaartDto,
  type WeekOverzichtKaartDto,
  type WeekProjectKaartDto,
  type WeekstaatDto,
  type ZzperKaartDto,
  zoekWeekstaat,
  dossierStatusLabel,
  haalMijnDossier,
  isDossierGeblokkeerd,
  uploadDossierDocument,
  type DossierDto,
  datumMetWeek,
  gestempeldLabel,
  haalEigenStempels,
  stempelTijd,
  stempelToets,
  type StempelDto,
} from './urenApi'

type Veldrol = 'zzper' | 'uitvoerder' | 'detacheerder'

/** Schermen van de uren-flow (weken → projecten → weekstaat → dag) — voor de "Mijn uren"-tab van de uitvoerder. */
const UREN_SCHERMEN: ReadonlySet<Scherm['s']> = new Set(['zzpWeken', 'weekProjecten', 'projectToevoegen', 'weekstaat', 'daginvoer', 'ingediend'])
const KEUR_SCHERMEN: ReadonlySet<Scherm['s']> = new Set(['keurlijst', 'keurdetail', 'keurafwijs'])

interface WeekContext {
  administratieId: string
  projectId: string
  projectNaam: string | null
  jaar: number
  weeknummer: number
  /** Label van de terugknop boven de weekstaat (week N / Ingediend). */
  terugLabel: string
}

type Scherm =
  | { s: 'zzpWeken' }
  | { s: 'weekProjecten'; week: WeekOverzichtKaartDto }
  /** "+ Ander project toevoegen aan mijn week" (project-eerst, Peter 18-09): alle actieve projecten, gepland bovenaan. */
  | { s: 'projectToevoegen'; week: WeekOverzichtKaartDto }
  | { s: 'weekstaat'; ctx: WeekContext; terug: Scherm }
  | {
      s: 'daginvoer'
      ctx: WeekContext
      datum: string
      dagNaam: string
      bestaand: WeekstaatDto['dagen'][number] | null
      /** Projectdefault voor de doorfactureren-dropdown (18-09 blok B). */
      doorfacturerenStandaard: boolean
      /** Run A (18-09): omschrijving-chips van de administratie en het contract-m² van het project (m²-project?). */
      chips: string[]
      contractM2: string | null
      terug: Scherm
    }
  | { s: 'ingediend' }
  | { s: 'planning' }
  | { s: 'dossier'; terug: Scherm }
  | { s: 'detaZzpers' }
  | { s: 'uitvProjecten' }
  | { s: 'projectdetail'; kaart: UitvoerderProjectKaartDto }
  | { s: 'contract'; kaart: UitvoerderProjectKaartDto; doc: ProjectDocumentKaartDto }
  | { s: 'meerwerkMelden'; kaart: UitvoerderProjectKaartDto; terug?: undefined }
  /** Meerwerk melden vanaf een projectkaart in de week (project-eerst): project al ingevuld, terug naar die week. */
  | { s: 'meerwerkMelden'; kaart: MeerwerkDoel; terug: Scherm }
  | { s: 'meerwerkVraag'; kaart: UitvoerderProjectKaartDto; melding: MeerwerkDto }
  | { s: 'keurlijst' }
  | { s: 'keurdetail'; item: TeKeurenItemDto }
  | { s: 'keurafwijs'; item: TeKeurenItemDto; staat: WeekstaatDto }

/** Het minimum dat "Meerwerk melden" nodig heeft — een projectkaart uit de week óf een uitvoerder-projectkaart. */
type MeerwerkDoel = Pick<UitvoerderProjectKaartDto, 'administratie_id' | 'project_id' | 'project_naam'>

function weekSleutel(week: { jaar: number; weeknummer: number }): string {
  return `${week.jaar}-W${week.weeknummer}`
}

/** Android-terugknop in de web-flow (SPOED 18-09, event `acc-terug`): één scherm terug binnen de flow i.p.v. de app
 * verlaten. Schermen mét `terug` gebruiken die; de rest volgt de vaste ouder; een beginscherm blijft staan (null). */
export function terugVan(scherm: Scherm, veldrol: Veldrol): Scherm | null {
  if ('terug' in scherm && scherm.terug !== undefined) return scherm.terug
  switch (scherm.s) {
    case 'weekProjecten':
      return { s: 'zzpWeken' }
    case 'projectToevoegen':
      return { s: 'weekProjecten', week: scherm.week }
    case 'projectdetail':
      return { s: 'uitvProjecten' }
    case 'contract':
    case 'meerwerkVraag':
      return { s: 'projectdetail', kaart: scherm.kaart }
    case 'meerwerkMelden':
      return { s: 'projectdetail', kaart: scherm.kaart as UitvoerderProjectKaartDto }
    case 'keurdetail':
      return { s: 'keurlijst' }
    case 'keurafwijs':
      return { s: 'keurdetail', item: scherm.item }
    case 'ingediend':
    case 'planning':
      return { s: 'zzpWeken' }
    case 'keurlijst':
      return { s: 'uitvProjecten' }
    case 'zzpWeken':
      return veldrol === 'uitvoerder' ? { s: 'uitvProjecten' } : veldrol === 'detacheerder' ? { s: 'detaZzpers' } : null
    case 'uitvProjecten':
    case 'detaZzpers':
      return null
  }
}

function chipVoorWeekStatus(status: WeekKaartDto['status']): { klasse: string; label: string } {
  switch (status) {
    case 'nieuw':
    case 'concept':
      return { klasse: 'open', label: 'nog invullen' }
    case 'ingediend':
      return { klasse: 'ingediend', label: 'ingediend' }
    case 'goedgekeurd':
      return { klasse: 'akkoord', label: 'goedgekeurd' }
    case 'corrigeren':
      return { klasse: 'afgekeurd', label: 'afgekeurd — aanpassen' }
  }
}

function meerwerkChip(m: MeerwerkDto): { klasse: string; label: string } {
  switch (m.status) {
    case 'gemeld':
      return { klasse: 'meerwerk', label: 'gemeld' }
    case 'goedgekeurd':
      return { klasse: 'ingediend', label: 'nog doorbelasten' }
    case 'doorbelast':
      return { klasse: 'akkoord', label: 'doorbelast' }
    case 'afgewezen':
      return { klasse: 'afgekeurd', label: 'eigen rekening' }
  }
}

export function UrenFlow({
  wisselThema,
  uitloggen,
  openToegang,
}: {
  wisselThema: () => void
  uitloggen: () => Promise<void>
  /** App-lock-instellingen (native, 31-08) — undefined buiten de native schil. */
  openToegang?: () => void
}) {
  const { rol } = useAuth()
  const veldrol = rol as Veldrol
  const [scherm, setScherm] = useState<Scherm>(() =>
    veldrol === 'uitvoerder' ? { s: 'uitvProjecten' } : veldrol === 'detacheerder' ? { s: 'detaZzpers' } : { s: 'zzpWeken' },
  )
  // Detacheerder-namens-context (besluit 21-08): ná de ZZP'er-keuze exact de ZZP-schermen,
  // elk scherm draagt "· namens <ZZP'er>" en elke invoer wordt als "X namens Y" vastgelegd.
  const [namens, setNamens] = useState<{ id: string; naam: string } | null>(null)
  // Project-eerst (Peter 18-09): projecten die de gebruiker deze week zelf aan zijn week toevoegde (nog zonder regels);
  // per week bewaard zolang de app open is — een kaart zonder regels verdwijnt bij weekwissel.
  const [extraKaarten, setExtraKaarten] = useState<Record<string, WeekProjectKaartDto[]>>({})
  // Run A punt 3: omschrijving-chips per administratie (één keer ophalen per app-sessie).
  const chipsCache = useRef<Record<string, string[]>>({})
  const [voorwaardenNodig, setVoorwaardenNodig] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [administratieNamen, setAdministratieNamen] = useState<string[]>([])
  const [administraties, setAdministraties] = useState<{ id: string; naam: string }[]>([])
  const location = useLocation()
  const [teKeurenTeller, setTeKeurenTeller] = useState<number | null>(null)

  const toon = useCallback((tekst: string) => {
    setToast(tekst)
    window.setTimeout(() => setToast(null), 3600)
  }, [])

  const vangFout = useCallback((err: unknown): string => {
    if (isVoorwaardenVereist(err)) {
      setVoorwaardenNodig(true)
      return ''
    }
    return err instanceof Error ? err.message : 'Er ging iets mis — probeer het opnieuw.'
  }, [])

  /** "+ Uren" op een projectkaart: project én dag staan al vast — alleen de bestaande regel van die dag ophalen
   * (prefill + projectdefault doorfactureren) en direct het invoerscherm openen. */
  const plusUren = useCallback(
    async (week: WeekOverzichtKaartDto, project: WeekProjectKaartDto, datum: string, dagNaam: string) => {
      const ctx: WeekContext = {
        administratieId: project.administratie_id,
        projectId: project.project_id,
        projectNaam: project.project_naam,
        jaar: week.jaar,
        weeknummer: week.weeknummer,
        terugLabel: `Week ${week.weeknummer}`,
      }
      try {
        const gevonden = await zoekWeekstaat({
          administratieId: ctx.administratieId,
          projectId: ctx.projectId,
          jaar: ctx.jaar,
          weeknummer: ctx.weeknummer,
          namens: namens?.id ?? null,
        })
        const bestaand = gevonden.weekstaat?.dagen.find((d) => d.datum === datum) ?? null
        const chips = chipsCache.current[project.administratie_id] ?? (await haalOmschrijvingChips(project.administratie_id))
        chipsCache.current[project.administratie_id] = chips
        setScherm({
          s: 'daginvoer',
          ctx,
          datum,
          dagNaam,
          bestaand,
          doorfacturerenStandaard: gevonden.doorfactureren_standaard,
          chips,
          contractM2: project.contract_m2 ?? null,
          terug: { s: 'weekProjecten', week },
        })
      } catch (err) {
        const tekst = vangFout(err)
        if (tekst) toon(tekst)
      }
    },
    [namens, vangFout, toon],
  )

  /** "Zelfde als gisteren" (run A punt 1): de laatste regel op dit project (ook uit een vorige week) naar de gekozen dag —
   * uren, m², omschrijving én doorfactureren; één tik, direct opgeslagen, audit bron=kopie. */
  const kopieerLaatsteRegel = useCallback(
    async (week: WeekOverzichtKaartDto, project: WeekProjectKaartDto, datum: string): Promise<boolean> => {
      const bron = project.laatste_regel
      if (!bron) return false
      try {
        await zetDag({
          bron: 'kopie',
          administratie_id: project.administratie_id,
          project_id: project.project_id,
          jaar: week.jaar,
          weeknummer: week.weeknummer,
          datum,
          uren: bron.uren,
          m2: bron.m2,
          doorfactureren: bron.doorfactureren,
          opmerking: bron.opmerking,
          namens_zzper_id: namens?.id ?? null,
        })
        toon(`Gekopieerd van ${datumKort(bron.datum)}: ${urenLabel(bron.uren, bron.m2)}${bron.opmerking ? ` · ${bron.opmerking}` : ''}.`)
        return true
      } catch (err) {
        const tekst = vangFout(err)
        if (tekst) toon(tekst)
        return false
      }
    },
    [namens, vangFout, toon],
  )

  // Android-terugknop (web, SPOED 18-09): één scherm terug binnen de flow; op een beginscherm gebeurt niets.
  useEffect(() => {
    const op = () =>
      setScherm((huidig) => {
        const doel = terugVan(huidig, veldrol)
        if (doel?.s === 'detaZzpers') setNamens(null)
        return doel ?? huidig
      })
    window.addEventListener(ACC_TERUG_EVENT, op)
    return () => window.removeEventListener(ACC_TERUG_EVENT, op)
  }, [veldrol])

  useEffect(() => {
    haalMijnAdministraties()
      .then((data) => {
        setAdministratieNamen(data.administraties.map((a) => a.naam))
        setAdministraties(data.administraties)
      })
      .catch(() => undefined)
  }, [])

  // Deep-link uit de dossier-herinnering (push/mail: /accordeur?dossier=1) → direct het dossier.
  useEffect(() => {
    if (new URLSearchParams(location.search).get('dossier') === '1' && veldrol !== 'detacheerder') {
      setScherm((huidig) => (huidig.s === 'dossier' ? huidig : { s: 'dossier', terug: huidig }))
    }
    // 15-09: deep-link uit de bundelmelding "planning week N aangepast" (/accordeur?planning=JJJJ-Wnn) → de
    // planningweergave van die week.
    // 18-09 blok D: de uitvoerder heeft geen planningstab meer — de melding blijft, de deep-link landt op zijn uren.
    if (planningWeekUitZoekdeel(location.search)) setScherm(toontPlanningTab(veldrol) ? { s: 'planning' } : { s: 'zzpWeken' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search])

  const laadTeKeurenTeller = useCallback(() => {
    if (veldrol !== 'uitvoerder') return
    haalTeKeuren()
      .then((items) => setTeKeurenTeller(items.length))
      .catch((err) => {
        vangFout(err)
      })
  }, [veldrol, vangFout])

  useEffect(() => {
    laadTeKeurenTeller()
  }, [laadTeKeurenTeller])


  if (voorwaardenNodig) {
    // Zelfde fail-closed voorwaarden-/privacypoort als de accordeur (één app, één akkoord).
    return (
      <>
        <VoorwaardenScherm naAkkoord={() => setVoorwaardenNodig(false)} uitloggen={uitloggen} />
        {toast && <div className="acc-toast">{toast}</div>}
      </>
    )
  }

  const kopnaam =
    veldrol === 'zzper' ? (
      <b>
        Uren — <span>Boekingsmodule</span>
      </b>
    ) : veldrol === 'uitvoerder' ? (
      <b>
        Projecten — <span>Boekingsmodule</span>
      </b>
    ) : (
      <b>
        Uren namens — <span>Boekingsmodule</span>
      </b>
    )

  const zzpTabs = (
    <div className="acc-functabs">
      <button
        className={`acc-functab${scherm.s !== 'ingediend' && scherm.s !== 'planning' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'zzpWeken' })}
      >
        ⏱ Mijn weken
      </button>
      {toontPlanningTab(veldrol) && (
        <button
          className={`acc-functab${scherm.s === 'planning' ? ' actief' : ''}`}
          onClick={() => setScherm({ s: 'planning' })}
        >
          📅 Planning
        </button>
      )}
      <button
        className={`acc-functab${scherm.s === 'ingediend' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'ingediend' })}
      >
        ✓ Ingediend
      </button>
    </div>
  )
  // Uitvoerder (18-09): Projecten · Mijn uren · Te keuren — géén planningstab (blok D, allowlist toontPlanningTab).
  const uitvTabs = (
    <div className="acc-functabs">
      <button
        className={`acc-functab${!KEUR_SCHERMEN.has(scherm.s) && !UREN_SCHERMEN.has(scherm.s) ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'uitvProjecten' })}
      >
        🏗 Projecten
      </button>
      <button
        className={`acc-functab${UREN_SCHERMEN.has(scherm.s) ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'zzpWeken' })}
        data-testid="tab-mijn-uren"
      >
        ⏱ Mijn uren
      </button>
      <button
        className={`acc-functab${KEUR_SCHERMEN.has(scherm.s) ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'keurlijst' })}
      >
        ✓ Te keuren{teKeurenTeller !== null && teKeurenTeller > 0 && <span className="acc-badge">{teKeurenTeller}</span>}
      </button>
    </div>
  )
  const detaTabs = (
    <div className="acc-functabs">
      <button className="acc-functab actief" onClick={() => { setNamens(null); setScherm({ s: 'detaZzpers' }) }}>
        👥 Mijn ZZP'ers
      </button>
    </div>
  )

  const namensSuffix = namens ? <span className="acc-namens"> · namens {namens.naam}</span> : null

  return (
    <>
      <div className="acc-apphead">
        <div className="acc-who">
          Nijenhuis{administratieNamen.length > 0 ? ` · ${administratieNamen.join(' · ')}` : ''}
          {kopnaam}
        </div>
        <div className="acc-headbtns">
          <button className="acc-iconbtn" title="Thema wisselen" onClick={wisselThema}>
            ◐
          </button>
          {openToegang && (
            <button className="acc-iconbtn" title="Toegang tot de app" onClick={openToegang}>
              ⚙
            </button>
          )}
          <button className="acc-iconbtn" title="Vergrendelen" aria-label="Vergrendelen" onClick={() => void uitloggen()}>
            <UitlogIcoon />
          </button>
        </div>
      </div>

      {veldrol === 'zzper' && zzpTabs}
      {veldrol === 'uitvoerder' && uitvTabs}
      {veldrol === 'detacheerder' && detaTabs}

      <div className="acc-content acc-veld">
        {scherm.s === 'zzpWeken' && (
          <WekenOverzichtView
            namens={namens}
            vangFout={vangFout}
            terugNaarZzpers={veldrol === 'detacheerder' ? () => { setNamens(null); setScherm({ s: 'detaZzpers' }) } : null}
            openWeek={(week) => setScherm({ s: 'weekProjecten', week })}
            openPlanning={veldrol === 'detacheerder' ? () => setScherm({ s: 'planning' }) : null}
            dossierKaart={
              <DossierKaart
                administratieId={administraties[0]?.id ?? null}
                namens={namens}
                vangFout={vangFout}
                open={() => setScherm({ s: 'dossier', terug: scherm })}
              />
            }
          />
        )}
        {scherm.s === 'weekProjecten' && (
          <WeekProjectenView
            week={scherm.week}
            namens={namens}
            namensSuffix={namensSuffix}
            extra={extraKaarten[weekSleutel(scherm.week)] ?? []}
            vangFout={vangFout}
            toon={toon}
            terug={() => setScherm({ s: 'zzpWeken' })}
            openWeekstaat={(project) =>
              setScherm({
                s: 'weekstaat',
                ctx: {
                  administratieId: project.administratie_id,
                  projectId: project.project_id,
                  projectNaam: project.project_naam,
                  jaar: scherm.week.jaar,
                  weeknummer: scherm.week.weeknummer,
                  terugLabel: `Week ${scherm.week.weeknummer}`,
                },
                terug: scherm,
              })
            }
            plusUren={(project, datum, dagNaam) => void plusUren(scherm.week, project, datum, dagNaam)}
            kopieer={(project, datum) => kopieerLaatsteRegel(scherm.week, project, datum)}
            // Alleen een uitvoerder meldt meerwerk (backend: `meld_meerwerk`); nooit namens.
            meldMeerwerk={
              veldrol === 'uitvoerder' && !namens
                ? (project) =>
                    setScherm({
                      s: 'meerwerkMelden',
                      kaart: { administratie_id: project.administratie_id, project_id: project.project_id, project_naam: project.project_naam },
                      terug: scherm,
                    })
                : null
            }
            voegProjectToe={() => setScherm({ s: 'projectToevoegen', week: scherm.week })}
            naIndienen={(aantal) =>
              toon(
                aantal === 1
                  ? veldrol === 'uitvoerder'
                    ? 'Week ingediend — een andere uitvoerder op dit project keurt de hele week.'
                    : 'Week ingediend — de uitvoerder keurt de hele week.'
                  : `${aantal} weekstaten ingediend — ${veldrol === 'uitvoerder' ? 'een andere uitvoerder' : 'de uitvoerder'} keurt per project de hele week.`,
              )
            }
          />
        )}
        {scherm.s === 'projectToevoegen' && (
          <ProjectToevoegenView
            week={scherm.week}
            namens={namens}
            namensSuffix={namensSuffix}
            alInWeek={extraKaarten[weekSleutel(scherm.week)] ?? []}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'weekProjecten', week: scherm.week })}
            kies={(project) => {
              const sleutel = weekSleutel(scherm.week)
              setExtraKaarten((huidig) => ({ ...huidig, [sleutel]: weekKaarten(huidig[sleutel] ?? [], [project]) }))
              setScherm({ s: 'weekProjecten', week: scherm.week })
            }}
          />
        )}
        {scherm.s === 'dossier' && (
          <DossierView
            administraties={administraties}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={() => setScherm(scherm.terug)}
            toon={toon}
          />
        )}
        {scherm.s === 'planning' && (
          <MijnPlanningView
            startWeek={planningWeekUitZoekdeel(location.search)}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={veldrol === 'detacheerder' ? () => setScherm({ s: 'zzpWeken' }) : null}
          />
        )}
        {scherm.s === 'weekstaat' && (
          <WeekstaatView
            ctx={scherm.ctx}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={() => setScherm(scherm.terug)}
            openDag={(datum, dagNaam, bestaand, doorfacturerenStandaard) =>
              setScherm({
                s: 'daginvoer',
                ctx: scherm.ctx,
                datum,
                dagNaam,
                bestaand,
                doorfacturerenStandaard,
                chips: chipsCache.current[scherm.ctx.administratieId] ?? STANDAARD_OMSCHRIJVING_CHIPS,
                contractM2: null,
                terug: scherm,
              })
            }
            naIndienen={() => {
              toon(
                veldrol === 'uitvoerder'
                  ? 'Week ingediend — een andere uitvoerder op dit project keurt de hele week.'
                  : 'Week ingediend — de uitvoerder keurt de hele week.',
              )
              setScherm(veldrol === 'detacheerder' ? scherm.terug : { s: 'ingediend' })
            }}
            openDossier={() => setScherm({ s: 'dossier', terug: scherm })}
          />
        )}
        {scherm.s === 'daginvoer' && (
          <DagInvoerView
            ctx={scherm.ctx}
            datum={scherm.datum}
            dagNaam={scherm.dagNaam}
            bestaand={scherm.bestaand}
            doorfacturerenStandaard={scherm.doorfacturerenStandaard}
            chips={scherm.chips}
            contractM2={scherm.contractM2}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={() => setScherm(scherm.terug)}
            naOpslaan={() => setScherm(scherm.terug)}
          />
        )}
        {scherm.s === 'ingediend' && (
          <IngediendView
            namens={namens}
            vangFout={vangFout}
            openWeek={(item) =>
              setScherm({
                s: 'weekstaat',
                ctx: {
                  administratieId: item.administratie_id,
                  projectId: item.project_id,
                  projectNaam: item.project_naam,
                  jaar: item.jaar,
                  weeknummer: item.weeknummer,
                  terugLabel: 'Ingediend',
                },
                terug: { s: 'ingediend' },
              })
            }
          />
        )}
        {scherm.s === 'detaZzpers' && (
          <DetaZzpersView
            vangFout={vangFout}
            kies={(zzper) => {
              setNamens({ id: zzper.gebruiker_id, naam: zzper.naam })
              setScherm({ s: 'zzpWeken' })
            }}
          />
        )}
        {scherm.s === 'uitvProjecten' && (
          <>
            <DossierKaart
              administratieId={administraties[0]?.id ?? null}
              namens={null}
              vangFout={vangFout}
              open={() => setScherm({ s: 'dossier', terug: scherm })}
            />
            <UitvProjectenView vangFout={vangFout} openProject={(kaart) => setScherm({ s: 'projectdetail', kaart })} />
          </>
        )}
        {scherm.s === 'projectdetail' && (
          <ProjectDetailView
            kaart={scherm.kaart}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'uitvProjecten' })}
            openDocument={(doc) => setScherm({ s: 'contract', kaart: scherm.kaart, doc })}
            meldMeerwerk={() => setScherm({ s: 'meerwerkMelden', kaart: scherm.kaart })}
            beantwoordVraag={(melding) => setScherm({ s: 'meerwerkVraag', kaart: scherm.kaart, melding })}
          />
        )}
        {scherm.s === 'contract' && (
          <ContractView kaart={scherm.kaart} doc={scherm.doc} vangFout={vangFout} terug={() => setScherm({ s: 'projectdetail', kaart: scherm.kaart })} />
        )}
        {scherm.s === 'meerwerkMelden' && (
          <MeerwerkMeldenView
            kaart={scherm.kaart}
            vangFout={vangFout}
            terug={() => setScherm(scherm.terug !== undefined ? scherm.terug : { s: 'projectdetail', kaart: scherm.kaart })}
            naMelden={() => {
              toon('Meerwerk gemeld — het kantoor toetst en prijst de melding.')
              setScherm(scherm.terug !== undefined ? scherm.terug : { s: 'projectdetail', kaart: scherm.kaart })
            }}
          />
        )}
        {scherm.s === 'meerwerkVraag' && (
          <MeerwerkVraagView
            kaart={scherm.kaart}
            melding={scherm.melding}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'projectdetail', kaart: scherm.kaart })}
            naAntwoord={() => {
              toon('Antwoord verstuurd naar het kantoor.')
              setScherm({ s: 'projectdetail', kaart: scherm.kaart })
            }}
          />
        )}
        {scherm.s === 'keurlijst' && (
          <KeurLijstView vangFout={vangFout} openItem={(item) => setScherm({ s: 'keurdetail', item })} />
        )}
        {scherm.s === 'keurdetail' && (
          <KeurDetailView
            item={scherm.item}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'keurlijst' })}
            naarAfwijzen={(staat) => setScherm({ s: 'keurafwijs', item: scherm.item, staat })}
            naAkkoord={() => {
              toon('Week goedgekeurd — dit is nu de getekende urenstaat.')
              laadTeKeurenTeller()
              setScherm({ s: 'keurlijst' })
            }}
          />
        )}
        {scherm.s === 'keurafwijs' && (
          <KeurAfwijsView
            item={scherm.item}
            staat={scherm.staat}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'keurdetail', item: scherm.item })}
            naAfkeuren={() => {
              toon(`Week afgekeurd en teruggestuurd naar ${scherm.item.zzper_naam ?? "de ZZP'er"}.`)
              laadTeKeurenTeller()
              setScherm({ s: 'keurlijst' })
            }}
          />
        )}
      </div>
      {toast && <div className="acc-toast">{toast}</div>}
    </>
  )
}

/* ============ ZZP-dossier (A1/A2, 25-08 — kantoor-mockup "Dossier", veldkant) ============ */

function DossierKaart({
  administratieId,
  namens,
  vangFout,
  open,
}: {
  administratieId: string | null
  namens: { id: string; naam: string } | null
  vangFout: (err: unknown) => string
  open: () => void
}) {
  const [dossier, setDossier] = useState<DossierDto | null>(null)
  useEffect(() => {
    if (!administratieId) return
    haalMijnDossier(administratieId, namens?.id ?? null)
      .then(setDossier)
      .catch((err) => {
        vangFout(err)
      })
  }, [administratieId, namens, vangFout])
  if (!dossier) return null
  const ontbrekend = dossier.aantal_ontbrekend + dossier.aantal_verlopen
  const chip = dossier.geblokkeerd
    ? { klasse: 'afgekeurd', label: 'geblokkeerd' }
    : ontbrekend > 0
      ? { klasse: 'afgekeurd', label: `${ontbrekend} ontbreekt` }
      : dossier.aantal_ter_controle > 0
        ? { klasse: 'ingediend', label: `${dossier.aantal_ter_controle} ter controle` }
        : dossier.aantal_verloopt_binnenkort > 0
          ? { klasse: 'open', label: 'verloopt binnenkort' }
          : { klasse: 'akkoord', label: 'compleet' }
  return (
    <button className="acc-card klik" onClick={open}>
      <span>
        <span className="acc-tt">📁 {namens ? `Dossier van ${namens.naam}` : 'Mijn dossier'}</span>
        <span className="acc-meta" style={{ display: 'block' }}>
          {dossier.geblokkeerd
            ? 'weekstaten indienen is geblokkeerd tot het dossier compleet is — upload hier'
            : dossier.herinneringen_teller > 0
              ? `herinnering ${dossier.herinneringen_teller} van ${dossier.herinneringen_max} · ${dossier.aantal_aanwezig}/${dossier.aantal_verplicht} verplichte documenten`
              : `${dossier.aantal_aanwezig}/${dossier.aantal_verplicht} verplichte documenten aanwezig`}
        </span>
      </span>
      <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
    </button>
  )
}

function DossierView({
  administraties,
  namens,
  namensSuffix,
  vangFout,
  terug,
  toon,
}: {
  administraties: { id: string; naam: string }[]
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: () => void
  toon: (tekst: string) => void
}) {
  const [administratieId, setAdministratieId] = useState<string | null>(administraties[0]?.id ?? null)
  const [dossier, setDossier] = useState<DossierDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState<string | null>(null)
  const [geldigTot, setGeldigTot] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!administratieId && administraties[0]) setAdministratieId(administraties[0].id)
  }, [administraties, administratieId])

  const laad = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalMijnDossier(administratieId, namens?.id ?? null)
      .then(setDossier)
      .catch((err) => setFout(vangFout(err) || null))
  }, [administratieId, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  async function upload(code: string, bestand: File) {
    if (!administratieId) return
    setBezig(code)
    setFout(null)
    try {
      const nieuw = await uploadDossierDocument({
        administratie_id: administratieId,
        type_code: code,
        geldig_tot: geldigTot[code] || null,
        namens: namens?.id ?? null,
        bestand,
      })
      setDossier(nieuw)
      toon('Document geüpload — het kantoor controleert het.')
    } catch (err) {
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(null)
    }
  }

  return (
    <div>
      <Terug label="Terug" onClick={terug} />
      <div className="acc-seclabel">
        📁 {namens ? `Dossier van ${namens.naam}` : 'Mijn dossier'}
        {namensSuffix}
      </div>
      {administraties.length > 1 && (
        <label className="acc-form">
          Administratie
          <select value={administratieId ?? ''} onChange={(e) => setAdministratieId(e.target.value)}>
            {administraties.map((a) => (
              <option key={a.id} value={a.id}>
                {a.naam}
              </option>
            ))}
          </select>
        </label>
      )}
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {dossier === null && !fout && <Leeg tekst="Laden…" />}
      {dossier?.geblokkeerd && (
        <div className="acc-afwijs">
          <b>🔒 Weekstaten indienen is geblokkeerd.</b> Na {dossier.herinneringen_max} herinneringen is het dossier nog niet
          compleet. Upload de ontbrekende documenten hieronder — zodra alles geüpload is kun je je weken weer indienen; je uren
          blijven bewaard.
        </div>
      )}
      {dossier && !dossier.geblokkeerd && dossier.herinneringen_teller > 0 && (
        <div className="acc-notitie waarschuw">
          <span>🔔</span>
          <span>
            Herinnering {dossier.herinneringen_teller} van {dossier.herinneringen_max} ontvangen. Na de {dossier.herinneringen_max}e herinnering kun
            je geen weekstaten meer indienen tot het dossier compleet is.
          </span>
        </div>
      )}
      {dossier?.documenten.map((d) => {
        const chip = dossierStatusLabel(d)
        const kanUploaden = d.status !== 'ter_controle'
        return (
          <div key={d.code} className="acc-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ flex: 1 }}>
                <span className="acc-tt">{d.naam}</span>
                <span className="acc-meta" style={{ display: 'block' }}>
                  {d.status === 'ontbreekt' && (d.verplicht ? 'verplicht — nog niet geüpload' : 'niet verplicht')}
                  {d.status === 'ter_controle' && `geüpload ${datumKort(d.geupload_op)} — het kantoor controleert`}
                  {d.status === 'afgewezen' && `afgewezen: ${d.afwijs_reden ?? '—'} — upload een nieuw document`}
                  {(d.status === 'goedgekeurd' || d.status === 'verloopt_binnenkort') && `geldig tot ${datumKort(d.geldig_tot)}`}
                  {d.status === 'verlopen' && `verlopen op ${datumKort(d.geldig_tot)} — upload een nieuw document`}
                </span>
              </span>
              <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
            </div>
            {kanUploaden && (
              <div className="acc-duo" style={{ marginTop: 8 }}>
                {d.geldig_tot_vereist && (
                  <label className="acc-form">
                    Geldig tot
                    <input type="date" value={geldigTot[d.code] ?? ''} onChange={(e) => setGeldigTot({ ...geldigTot, [d.code]: e.target.value })} />
                  </label>
                )}
                <label className="acc-form">
                  {d.document_id ? 'Nieuw bestand' : 'Bestand (foto of PDF)'}
                  <BestandKnop
                    label={d.document_id ? 'Nieuw bestand kiezen' : 'Bestand kiezen (foto of PDF)'}
                    bestandsnaam={null}
                    accept="application/pdf,image/jpeg,image/png"
                    disabled={bezig === d.code || (d.geldig_tot_vereist && !geldigTot[d.code])}
                    onKies={(f) => void upload(d.code, f)}
                  />
                </label>
              </div>
            )}
            {kanUploaden && d.geldig_tot_vereist && !geldigTot[d.code] && (
              <small className="acc-meta">Vul eerst de geldig-tot-datum in, dan kun je het bestand kiezen.</small>
            )}
          </div>
        )
      })}
      {dossier && (
        <div className="acc-notitie">
          <span>ℹ️</span>
          <span>
            Kopie ID: alleen het kantoor kan dit document (gemaskeerd) inzien — je BSN wordt nergens gelezen of opgeslagen buiten het bestand zelf.
          </span>
        </div>
      )}
    </div>
  )
}

/* ============ gedeelde bouwstenen ============ */

/** Uploadveld als eigen knop (overlap-bug iPad 30-08): een kale native file-input rendert als
 * OS-widget en viel op het tablet-breakpoint over andere velden heen. Daarom overal een eigen
 * knop (.acc-bestandknop, patroon oude .acc-fotoknop) mét de verborgen input erín en de gekozen
 * bestandsnaam mét ellipsis. Hoort binnen een <label> te staan (klik op de knop activeert de
 * input via het label), zoals de bestaande formulieren. */
function BestandKnop({
  label,
  bestandsnaam,
  accept,
  capture,
  disabled,
  onKies,
  icoon = '📎',
}: {
  /** Knoptekst zolang er geen bestand gekozen is. */
  label: string
  bestandsnaam: string | null
  accept: string
  capture?: 'environment' | 'user'
  disabled?: boolean
  onKies: (file: File) => void
  icoon?: string
}) {
  return (
    <span className="acc-bestandknop" role="button" aria-disabled={disabled ? 'true' : undefined}>
      <span aria-hidden>{icoon}</span>
      {bestandsnaam ? <span className="acc-bestandknop-naam">{bestandsnaam}</span> : label}
      <input
        type="file"
        accept={accept}
        capture={capture}
        disabled={disabled}
        style={{ position: 'absolute', opacity: 0, width: 1, height: 1 }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onKies(f)
          e.target.value = ''
        }}
      />
    </span>
  )
}

function Terug({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="acc-tekstlink" style={{ marginBottom: 8 }} onClick={onClick}>
      ‹ {label}
    </button>
  )
}

function Leeg({ tekst }: { tekst: string }) {
  return <p className="acc-qcount">{tekst}</p>
}

function FoutRegel({ tekst, onOpnieuw }: { tekst: string; onOpnieuw?: () => void }) {
  return (
    <div className="acc-afwijs">
      {tekst}{' '}
      {onOpnieuw && (
        <button className="acc-tekstlink" onClick={onOpnieuw}>
          Opnieuw proberen
        </button>
      )}
    </div>
  )
}

/* ============ ZZP (en detacheerder-namens) ============ */

function weekOverzichtMeta(week: WeekOverzichtKaartDto): string {
  const delen: string[] = []
  if (week.geplande_projecten > 0) {
    delen.push(`${week.geplande_projecten} ${week.geplande_projecten === 1 ? 'project' : 'projecten'} gepland`)
  }
  if (week.te_doen > 0) delen.push(`${week.te_doen} nog invullen`)
  if (Number(week.totaal_uren) > 0) delen.push(weekTotaalLabel(week.totaal_uren, week.totaal_m2))
  if (delen.length === 0) return 'geen planning deze week — uren via + ander project'
  return delen.join(' · ')
}

function weekOverzichtChip(week: WeekOverzichtKaartDto): { klasse: string; label: string } {
  if (week.te_doen > 0) return { klasse: 'open', label: week.te_doen === 1 ? 'nog invullen' : `${week.te_doen} nog invullen` }
  switch (week.status) {
    case 'ingediend':
      return { klasse: 'ingediend', label: 'ingediend' }
    case 'goedgekeurd':
      return { klasse: 'akkoord', label: 'goedgekeurd' }
    default:
      return { klasse: 'wacht', label: 'geen planning' }
  }
}

/** Beginscherm ZZP'er / detacheerder-namens (planning-gestuurd, 04-09 A2): alleen weken mét planning
 * plus deze week; een oudere week mét een staat in concept/corrigeren blijft staan tot hij is afgehandeld. */
function WekenOverzichtView({
  namens,
  vangFout,
  terugNaarZzpers,
  openWeek,
  openPlanning,
  dossierKaart,
}: {
  namens: { id: string; naam: string } | null
  vangFout: (err: unknown) => string
  terugNaarZzpers: (() => void) | null
  openWeek: (week: WeekOverzichtKaartDto) => void
  /** Detacheerder-namens-flow: de planning van de gekozen ZZP'er (alleen-lezen, besluit B). */
  openPlanning: (() => void) | null
  /** ZZP-dossier (A1): statuskaart + ingang naar upload (ook namens door de detacheerder). */
  dossierKaart?: React.ReactNode
}) {
  const [weken, setWeken] = useState<WeekOverzichtKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalZzpWekenOverzicht(namens?.id ?? null)
      .then(setWeken)
      .catch((err) => setFout(vangFout(err) || null))
  }, [namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  return (
    <div>
      {terugNaarZzpers && <Terug label="Mijn ZZP'ers" onClick={terugNaarZzpers} />}
      {namens && (
        <div className="acc-notitie" style={{ margin: '0 0 12px' }}>
          <span>✍️</span>
          <span>
            Je werkt nu <b>namens {namens.naam}</b> — elke invoer wordt zo vastgelegd (zichtbaar bij de keuring).
          </span>
        </div>
      )}
      {namens && openPlanning && (
        <button className="acc-card klik" onClick={openPlanning}>
          <span>
            <span className="acc-tt">📅 Planning van {namens.naam}</span>
            <span className="acc-meta" style={{ display: 'block' }}>
              waar moet {namens.naam.split(' ')[0]} deze week heen — alleen-lezen, plannen doet het kantoor
            </span>
          </span>
          <span className="acc-arrow">›</span>
        </button>
      )}
      {dossierKaart}
      <div className="acc-seclabel">{namens ? `${namens.naam} · weken` : 'Mijn weken'}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {weken === null && !fout && <Leeg tekst="Laden…" />}
      {(weken ?? []).map((week) => {
        const chip = weekOverzichtChip(week)
        return (
          <button key={`${week.jaar}-${week.weeknummer}`} className="acc-card klik" onClick={() => openWeek(week)}>
            <span>
              <span className="acc-tt">
                Week {week.weeknummer}{' '}
                <small style={{ color: 'var(--acc-muted)', fontWeight: 500 }}>
                  {datumKort(week.maandag)} – {datumKort(week.zondag)}
                  {week.is_huidige ? ' · deze week' : ''}
                </small>
              </span>
              <span className="acc-meta" style={{ display: 'block' }}>
                {weekOverzichtMeta(week)}
              </span>
            </span>
            <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
          </button>
        )
      })}
      {weken !== null && (
        <div className="acc-notitie">
          <span>📅</span>
          <span>
            Je ziet de weken waarin {namens ? namens.naam.split(' ')[0] : 'je'} <b>ingepland</b> {namens ? 'is' : 'bent'} (plus deze
            week). Open een week: geplande projecten staan bovenaan, daaronder <b>alle andere projecten</b> — uren schrijven kan
            op elk project.
          </span>
        </div>
      )}
    </div>
  )
}

/** Projecten in één week (04-09 A1, herzien 18-09 blok C): ÁLLE actieve projecten — de geplande projecten (en projecten
 * mét een staat) bovenaan onder "Gepland deze week", de rest doorzoekbaar onder "Andere projecten" mét chip "niet
 * gepland" (informatief, geen blokkade). De aparte stap "+ ander project" is vervallen. */
/** Weekweergave PROJECT-EERST (Peter 18-09: "eerst het project selecteren en dan de uren-/meerwerkknop"; bouwnorm
 * `mockup/uren-uitvoerder-v2.html` scherm ①): een lijst PROJECTKAARTEN — geplande projecten van de week (chip "gepland"),
 * projecten waar deze week al uren of meerwerk op staan (chip "niet gepland" als ze niet gepland zijn) en de projecten die de
 * gebruiker zelf toevoegde. Per kaart: dagtotaal van de gekozen dag, weektotaal, laatste omschrijving, doorfactureren-chip en
 * de knoppen "+ Uren" en "Meerwerk melden" — beide starten mét het project al ingevuld. Onderaan "+ Ander project toevoegen
 * aan mijn week" en "Week indienen" (alle concept-staten mét uren, per project = per weekstaat). */
function WeekProjectenView({
  week,
  namens,
  namensSuffix,
  extra,
  vangFout,
  toon,
  terug,
  openWeekstaat,
  plusUren,
  kopieer,
  meldMeerwerk,
  voegProjectToe,
  naIndienen,
}: {
  week: WeekOverzichtKaartDto
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  /** Door de gebruiker deze week toegevoegde projecten zonder regels (UrenFlow-state per week). */
  extra: WeekProjectKaartDto[]
  vangFout: (err: unknown) => string
  toon: (tekst: string) => void
  terug: () => void
  openWeekstaat: (project: WeekProjectKaartDto) => void
  plusUren: (project: WeekProjectKaartDto, datum: string, dagNaam: string) => void
  /** Run A punt 1: "Zelfde als gisteren" — laatste regel op dit project naar de gekozen dag; true = opgeslagen. */
  kopieer: (project: WeekProjectKaartDto, datum: string) => Promise<boolean>
  /** null = deze rol/context meldt geen meerwerk (alleen een uitvoerder, nooit namens). */
  meldMeerwerk: ((project: WeekProjectKaartDto) => void) | null
  voegProjectToe: () => void
  naIndienen: (aantal: number) => void
}) {
  const [kaarten, setKaarten] = useState<WeekProjectKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [samenvatting, setSamenvatting] = useState(false)
  const dagen = weekDagen(week.jaar, week.weeknummer)
  const [dag, setDag] = useState(() => standaardDag(dagen))
  const vandaag = standaardDag(dagen).datum
  const laad = useCallback(() => {
    setFout(null)
    haalWeekProjecten(week.jaar, week.weeknummer, namens?.id ?? null)
      .then(setKaarten)
      .catch((err) => setFout(vangFout(err) || null))
  }, [week, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const alle = kaarten === null ? null : weekKaarten(kaarten, extra)
  const muteerbaar = (k: WeekProjectKaartDto) => k.status === 'nieuw' || k.status === 'concept' || k.status === 'corrigeren'
  const indienbaar = (alle ?? []).filter((k) => (k.status === 'concept' || k.status === 'corrigeren') && Number(k.totaal_uren) > 0)
  const weekUren = (alle ?? []).reduce((som, k) => som + Number(k.totaal_uren), 0)
  // Run A punt 9: werkdagen vóór vandaag zonder uren = oranje rand (alleen als vandaag in deze week valt of erna).
  const vergeten = new Set(alle ? vergetenDagen(alle, dagen, vandaag) : [])
  const overzicht = alle ? indienSamenvatting(indienbaar, dagen) : null

  async function indienen() {
    setBezig(true)
    setFout(null)
    let gelukt = 0
    try {
      for (const k of indienbaar) {
        await dienWeekIn({
          administratie_id: k.administratie_id,
          project_id: k.project_id,
          jaar: week.jaar,
          weeknummer: week.weeknummer,
          namens_zzper_id: namens?.id ?? null,
        })
        gelukt += 1
      }
      naIndienen(gelukt)
    } catch (err) {
      if (isDossierGeblokkeerd(err)) {
        toon('Indienen is geblokkeerd: dossier incompleet — open Mijn dossier en upload de documenten.')
      } else {
        const tekst = vangFout(err)
        if (tekst) setFout(tekst)
      }
      if (gelukt > 0) naIndienen(gelukt)
    } finally {
      setBezig(false)
      laad()
    }
  }

  function kaartMeta(k: WeekProjectKaartDto): string {
    const dagUren = k.dag_uren?.[dag.datum]
    const delen = [
      dagUren !== undefined ? `${dag.naam}: ${urenLabel(dagUren, null)}` : `${dag.naam}: nog geen uren`,
      Number(k.totaal_uren) > 0 ? `week ${weekTotaalLabel(k.totaal_uren, k.totaal_m2)}` : null,
      k.laatste_omschrijving ?? null,
    ]
    return delen.filter(Boolean).join(' · ')
  }

  function kaart(k: WeekProjectKaartDto) {
    const chip = chipVoorWeekStatus(k.status)
    const nietDoorf = k.dagen_niet_doorfactureren ?? 0
    return (
      <div key={`${k.administratie_id}-${k.project_id}`} className="acc-card acc-projectkaart" data-testid="projectkaart">
        <button className="acc-kaartkop" onClick={() => openWeekstaat(k)} aria-label={`Weekstaat ${k.project_naam ?? 'project'}`}>
          <span className="acc-tt">
            {k.project_naam ?? 'Project'}{' '}
            {k.gepland ? (
              <span className="acc-chip ingediend" data-testid="chip-gepland">
                gepland
              </span>
            ) : (
              <span className="acc-chip wacht" data-testid="chip-niet-gepland">
                niet gepland
              </span>
            )}
          </span>
          <span className="acc-meta" style={{ display: 'block' }}>
            {kaartMeta(k)}
            {k.administratie_naam ? ` · ${k.administratie_naam}` : ''}
          </span>
          <span className="acc-meta acc-kaartchips" style={{ display: 'block' }}>
            {k.status !== 'nieuw' && <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>}
            {nietDoorf > 0 ? (
              <span className="acc-chip wacht" data-testid="chip-niet-doorfactureren">
                {nietDoorf} {nietDoorf === 1 ? 'dag' : 'dagen'} niet doorfactureren
              </span>
            ) : (
              <span className="acc-chip">{doorfacturerenLabel(k.doorfactureren_standaard ?? true).toLowerCase()}</span>
            )}
            {(k.meerwerk_aantal ?? 0) > 0 && <span className="acc-chip meerwerk">{k.meerwerk_aantal} meerwerk</span>}
          </span>
          {/* Run A punt 10: terugkoppeling van kantoor/uitvoerder per week op de kaart. */}
          {k.status === 'goedgekeurd' && (
            <span className="acc-meta" style={{ display: 'block', marginTop: 4 }} data-testid="terugkoppeling-goed">
              ✓ Goedgekeurd{k.goedgekeurd_door_naam ? ` door ${k.goedgekeurd_door_naam}` : ''} — getekende urenstaat.
            </span>
          )}
          {k.status === 'corrigeren' && (
            <span className="acc-meta" style={{ display: 'block', marginTop: 4, color: 'var(--acc-orange)' }} data-testid="terugkoppeling-afgekeurd">
              Afgekeurd{k.afgekeurd_door_naam ? ` door ${k.afgekeurd_door_naam}` : ''}
              {k.afkeur_reden ? `: "${k.afkeur_reden}"` : ''} — tik op Aanpassen, corrigeer en dien de week opnieuw in.
            </span>
          )}
        </button>
        {/* Run A punt 6 (KP7): één primaire knop per kaart; de rest als tekstlinks eronder. */}
        <div className="acc-kaartknoppen">
          {k.status === 'corrigeren' ? (
            <button className="acc-btn primair" data-testid="aanpassen" onClick={() => openWeekstaat(k)}>
              Aanpassen
            </button>
          ) : (
            <button
              className="acc-btn primair"
              data-testid="plus-uren"
              disabled={!muteerbaar(k)}
              title={muteerbaar(k) ? undefined : 'Deze week is ingediend of goedgekeurd — wijzigen kan alleen via een afkeuring.'}
              onClick={() => plusUren(k, dag.datum, dag.naam)}
            >
              + Uren
            </button>
          )}
        </div>
        <div className="acc-kaartlinks">
          {k.laatste_regel && muteerbaar(k) ? (
            <button
              type="button"
              className="acc-tekstlink"
              data-testid="zelfde-als-gisteren"
              title={`Laatste regel: ${datumKort(k.laatste_regel.datum)} · ${urenLabel(k.laatste_regel.uren, k.laatste_regel.m2)}${k.laatste_regel.opmerking ? ` · ${k.laatste_regel.opmerking}` : ''}`}
              onClick={() => void kopieer(k, dag.datum).then((ok) => ok && laad())}
            >
              ⟲ Zelfde als gisteren
            </button>
          ) : (
            <span />
          )}
          {meldMeerwerk && (
            <button type="button" className="acc-tekstlink paars" data-testid="meerwerk-melden" onClick={() => meldMeerwerk(k)}>
              Meerwerk melden
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div>
      <Terug label={namens ? `${namens.naam} · weken` : 'Mijn weken'} onClick={terug} />
      <div className="acc-seclabel">
        Week {week.weeknummer} · {datumKort(week.maandag)} – {datumKort(week.zondag)}
        {namensSuffix}
      </div>
      {/* Dagbalk: kies de dag waarop "+ Uren" landt; teller = uren op die dag over alle projecten. */}
      <div className="acc-dagbalk" role="tablist" aria-label="Dag">
        {dagen.map((d) => {
          const uren = alle ? dagTotaal(alle, d.datum) : 0
          return (
            <button
              key={d.datum}
              role="tab"
              aria-selected={d.datum === dag.datum}
              className={`acc-dagknop${d.datum === dag.datum ? ' on' : ''}${vergeten.has(d.datum) ? ' vergeten' : ''}`}
              onClick={() => setDag(d)}
              data-testid={`dag-${d.naam}`}
              title={vergeten.has(d.datum) ? 'Nog geen uren op deze werkdag' : undefined}
            >
              {d.naam}
              <small>{uren > 0 ? `${uren.toLocaleString('nl-NL')} u` : '—'}</small>
            </button>
          )
        })}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {alle === null && !fout && <Leeg tekst="Laden…" />}
      {alle !== null && alle.length === 0 && (
        <Leeg tekst="Nog geen projecten in deze week — voeg hieronder een project toe en tik dan op + Uren." />
      )}
      {alle !== null && alle.map(kaart)}
      <div className="acc-kaartknoppen" style={{ padding: '4px 0 0' }}>
        <button className="acc-btn secundair" data-testid="ander-project" onClick={voegProjectToe}>
          + Ander project toevoegen aan mijn week
        </button>
      </div>
      {vergeten.size > 0 && (
        <div className="acc-notitie waarschuw" data-testid="vergeten-dagen">
          <span>⚠️</span>
          <span>
            Nog geen uren op {Array.from(vergeten).map((d) => dagen.find((x) => x.datum === d)?.naam ?? d).join(', ')} — vergeten? Tik de dag aan en dan + Uren.
          </span>
        </div>
      )}
      {indienbaar.length > 0 && (
        <div className="acc-actionbar">
          <button className="acc-btn primair" disabled={bezig} data-testid="week-indienen" onClick={() => setSamenvatting(true)}>
            {bezig ? 'Bezig…' : `Week indienen (${weekUren.toLocaleString('nl-NL')} u${indienbaar.length > 1 ? ` · ${indienbaar.length} projecten` : ''})`}
          </button>
        </div>
      )}
      {/* Run A punt 8: samenvatting + bevestigen; ontbrekende werkdag = waarschuwing, niet blokkerend. */}
      {samenvatting && overzicht && (
        <>
          <div className="acc-sheet-achter" onClick={() => setSamenvatting(false)} />
          <div className="acc-sheet" role="dialog" aria-label={`Week ${week.weeknummer} indienen`} data-testid="indien-samenvatting">
            <b style={{ fontSize: 17 }}>Week {week.weeknummer} indienen?</b>
            <div data-testid="indien-regel">
              {overzicht.dagen} {overzicht.dagen === 1 ? 'dag' : 'dagen'} · {overzicht.uren.toLocaleString('nl-NL')} u · {overzicht.projecten}{' '}
              {overzicht.projecten === 1 ? 'project' : 'projecten'}
              {overzicht.zonderM2 > 0 ? ` · ${overzicht.zonderM2} ${overzicht.zonderM2 === 1 ? 'regel' : 'regels'} zonder m²` : ''}
              {overzicht.nietDoorfactureren > 0 ? ` · ${overzicht.nietDoorfactureren} niet doorfactureren` : ''}
            </div>
            {overzicht.ontbrekendeWerkdagen.length > 0 && (
              <div style={{ color: 'var(--acc-orange)' }} data-testid="indien-waarschuwing">
                ⚠ Geen uren op {overzicht.ontbrekendeWerkdagen.map((d) => `${d.naam} ${datumKort(d.datum)}`).join(', ')} — klopt dat? (waarschuwing, je kunt gewoon indienen)
              </div>
            )}
            <div className="acc-kaartknoppen" style={{ marginTop: 12 }}>
              <button className="acc-btn primair" disabled={bezig} data-testid="indien-bevestig" onClick={() => { setSamenvatting(false); void indienen() }}>
                Ja, indienen
              </button>
            </div>
            <div className="acc-kaartknoppen" style={{ marginTop: 8 }}>
              <button className="acc-btn secundair" onClick={() => setSamenvatting(false)}>
                Nog even nakijken
              </button>
            </div>
          </div>
        </>
      )}
      <div className="acc-notitie">
        <span>ℹ️</span>
        <span>
          Kies eerst het project, dan <b>+ Uren</b> of <b>Meerwerk melden</b>. Uren op een niet-gepland project mogen — bij de
          keuring krijgen die dagen de markering <b>buiten planning</b> (oranje, geen blokkade).
        </span>
      </div>
    </div>
  )
}

/** "+ Ander project toevoegen aan mijn week" (mockup v2 scherm ③): alle actieve projecten in de scope, gepland bovenaan,
 * doorzoekbaar; projecten die al als kaart in de week staan blijven weg. Kiezen = kaart erbij (zonder uren). */
function ProjectToevoegenView({
  week,
  namens,
  namensSuffix,
  alInWeek,
  vangFout,
  terug,
  kies,
}: {
  week: WeekOverzichtKaartDto
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  alInWeek: WeekProjectKaartDto[]
  vangFout: (err: unknown) => string
  terug: () => void
  kies: (project: WeekProjectKaartDto) => void
}) {
  const [projecten, setProjecten] = useState<WeekProjectKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [zoek, setZoek] = useState('')
  const laad = useCallback(() => {
    setFout(null)
    haalWeekProjecten(week.jaar, week.weeknummer, namens?.id ?? null, true)
      .then(setProjecten)
      .catch((err) => setFout(vangFout(err) || null))
  }, [week, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const term = zoek.trim().toLowerCase()
  const extraSleutels = new Set(alInWeek.map((p) => `${p.administratie_id}-${p.project_id}`))
  const past = (p: WeekProjectKaartDto) =>
    term === '' ||
    (p.project_naam ?? '').toLowerCase().includes(term) ||
    (p.administratie_naam ?? '').toLowerCase().includes(term) ||
    (p.soort_werk ?? '').toLowerCase().includes(term)
  // Al een kaart in de week (gepland, mét regels, mét meerwerk of zelf toegevoegd) = niet nog eens aanbieden.
  const kandidaten = (projecten ?? []).filter(
    (p) => !p.gepland && p.weekstaat_id === null && (p.meerwerk_aantal ?? 0) === 0 && !extraSleutels.has(`${p.administratie_id}-${p.project_id}`),
  )
  const zichtbaar = kandidaten.filter(past)

  return (
    <div>
      <Terug label={`Week ${week.weeknummer}`} onClick={terug} />
      <div className="acc-seclabel">
        Project toevoegen aan week {week.weeknummer}
        {namensSuffix}
        {projecten ? ` · ${projecten.length} actieve projecten` : ''}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {projecten === null && !fout && <Leeg tekst="Laden…" />}
      {projecten !== null && (
        <>
          <div className="acc-card">
            <label className="acc-form">
              Zoek project
              <input
                type="search"
                placeholder="nummer, plaats of opdrachtgever"
                value={zoek}
                onChange={(e) => setZoek(e.target.value)}
                aria-label="Zoek project"
                autoFocus
              />
            </label>
          </div>
          <div className="acc-seclabel">Alle projecten</div>
          {zichtbaar.length === 0 && (
            <Leeg tekst={term ? 'Geen project gevonden.' : 'Alle actieve projecten staan al in je week.'} />
          )}
          {zichtbaar.map((p) => (
            <button key={`${p.administratie_id}-${p.project_id}`} className="acc-card klik" onClick={() => kies(p)}>
              <span>
                <span className="acc-tt">{p.project_naam ?? 'Project'}</span>
                <span className="acc-meta" style={{ display: 'block' }}>
                  {[p.soort_werk, p.administratie_naam].filter(Boolean).join(' · ') || 'projectgegevens volgen'}
                </span>
              </span>
              <span className="acc-arrow">›</span>
            </button>
          ))}
        </>
      )}
      <div className="acc-notitie">
        <span>ℹ️</span>
        <span>
          Na kiezen staat het project als kaart in je week; daar kies je <b>+ Uren</b> of <b>Meerwerk melden</b>. Een kaart zonder
          uren verdwijnt weer bij weekwissel.
        </span>
      </div>
    </div>
  )
}

function WeekstaatView({
  ctx,
  namens,
  namensSuffix,
  vangFout,
  terug,
  openDag,
  naIndienen,
  openDossier,
}: {
  ctx: WeekContext
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: () => void
  openDag: (datum: string, dagNaam: string, bestaand: WeekstaatDto['dagen'][number] | null, doorfacturerenStandaard: boolean) => void
  naIndienen: () => void
  openDossier: () => void
}) {
  const [staat, setStaat] = useState<WeekstaatDto | null | 'nieuw'>(null)
  // Projectdefault voor de doorfactureren-dropdown (18-09 blok B) — reist mee met de lookup, ook zonder staat.
  const [standaard, setStandaard] = useState(true)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  // Dossier-handhaving (A2): 423 = indienen geblokkeerd — melding + upload-ingang, uren blijven staan.
  const [geblokkeerd, setGeblokkeerd] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    // De weekstaat bestaat pas ná de eerste daginvoer — de lookup vereist geen koppeling (die
    // ontstaat bij "+ ander project" pas mét de eerste dagregel, addendum 04-09).
    zoekWeekstaat({
      administratieId: ctx.administratieId,
      projectId: ctx.projectId,
      jaar: ctx.jaar,
      weeknummer: ctx.weeknummer,
      namens: namens?.id ?? null,
    })
      .then((gevonden) => {
        setStandaard(gevonden.doorfactureren_standaard)
        setStaat(gevonden.weekstaat ?? 'nieuw')
      })
      .catch((err) => setFout(vangFout(err) || null))
  }, [ctx, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const dagen = weekDagen(ctx.jaar, ctx.weeknummer)
  const echteStaat = staat !== null && staat !== 'nieuw' ? staat : null
  const dagPer = new Map((echteStaat?.dagen ?? []).map((d) => [d.datum, d]))
  const muteerbaar = staat === 'nieuw' || echteStaat?.status === 'concept' || echteStaat?.status === 'corrigeren'

  async function indienen() {
    setBezig(true)
    setFout(null)
    try {
      await dienWeekIn({
        administratie_id: ctx.administratieId,
        project_id: ctx.projectId,
        jaar: ctx.jaar,
        weeknummer: ctx.weeknummer,
        namens_zzper_id: namens?.id ?? null,
      })
      naIndienen()
    } catch (err) {
      if (isDossierGeblokkeerd(err)) {
        setGeblokkeerd(err instanceof Error ? err.message : 'Indienen is geblokkeerd: dossier incompleet.')
        return
      }
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <Terug label={ctx.terugLabel} onClick={terug} />
      {geblokkeerd && (
        <div className="acc-afwijs">
          <b>🔒 Indienen geblokkeerd — dossier incompleet.</b> {geblokkeerd}
          <div style={{ marginTop: 8 }}>
            <button className="acc-btn klein" onClick={openDossier}>
              📁 Naar {namens ? `dossier van ${namens.naam}` : 'mijn dossier'} — documenten uploaden
            </button>
          </div>
          <small style={{ display: 'block', marginTop: 6 }}>Je uren blijven bewaard; zodra alle verplichte documenten geüpload zijn kun je de week alsnog indienen.</small>
        </div>
      )}
      <div className="acc-seclabel">
        {ctx.projectNaam ?? 'Project'} · week {ctx.weeknummer} · {datumKort(dagen[0].datum)} – {datumKort(dagen[6].datum)}
        {namensSuffix}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {staat === null && !fout && <Leeg tekst="Laden…" />}
      {staat !== null && (
        <div className="acc-card">
          {dagen.map(({ naam, datum }) => {
            const dag = dagPer.get(datum) ?? null
            if (dag === null) {
              return (
                <div key={datum} className="acc-dagrij">
                  <span className="acc-dag">{naam}</span>
                  <span className="acc-leegdag">nog niet ingevuld</span>
                  {muteerbaar && (
                    <button className="acc-plus" onClick={() => openDag(datum, naam, null, standaard)}>
                      + invullen
                    </button>
                  )}
                </div>
              )
            }
            const toonVoorstel = echteStaat?.status === 'corrigeren' && heeftVoorstel(dag)
            return (
              <div key={datum} className="acc-dagrij">
                <span className="acc-dag">{naam}</span>
                <span className="acc-proj">
                  {dag.opmerking ?? '—'}
                  {dag.namens && <small>ingevuld door {dag.ingevuld_door_naam ?? 'detacheerder'}</small>}
                  {toonVoorstel && <small className="acc-voorstel">voorstel keurder: {voorstelLabel(dag)}</small>}
                  {dag.boven_dagmax && <small style={{ color: 'var(--acc-orange)' }}>⚠ {Number(dag.dag_totaal_uren).toLocaleString('nl-NL')} u op deze dag (alle projecten) — boven {Number(dag.dagmax_uren ?? 0).toLocaleString('nl-NL')} u</small>}
                  {/* 18-09 blok B/C: keuze per regel + planning-dekking, informatief. */}
                  {dag.doorfactureren === false && <small className="acc-chip wacht" data-testid="chip-niet-doorfactureren">niet doorfactureren</small>}
                  {dag.buiten_planning && <small className="acc-chip wacht">niet gepland</small>}
                </span>
                <span className="acc-u">{urenLabel(dag.uren, dag.m2)}</span>
                {muteerbaar && (
                  <button className="acc-plus" onClick={() => openDag(datum, naam, dag, standaard)}>
                    wijzig
                  </button>
                )}
              </div>
            )
          })}
          {echteStaat && (
            <div className="acc-totbalk">
              <span className="acc-k">Totaal week {ctx.weeknummer} op dit project</span>
              <span>{weekTotaalLabel(echteStaat.totaal_uren, echteStaat.totaal_m2)}</span>
            </div>
          )}
          {echteStaat && Number(echteStaat.totaal_uren_niet_doorfactureren ?? 0) > 0 && (
            <div className="acc-totbalk" data-testid="totaal-niet-doorfactureren">
              <span className="acc-k">waarvan niet doorfactureren</span>
              <span>{weekTotaalLabel(echteStaat.totaal_uren_niet_doorfactureren ?? '0', echteStaat.totaal_m2_niet_doorfactureren ?? '0')}</span>
            </div>
          )}
          {echteStaat?.status === 'corrigeren' && echteStaat.afkeur_reden && (
            <div className="acc-afwijs">
              <b>Week afgekeurd{echteStaat.afgekeurd_door_naam ? ` door ${echteStaat.afgekeurd_door_naam}` : ''}:</b>{' '}
              "{echteStaat.afkeur_reden}" — corrigeer en dien de <b>week</b> opnieuw in.
              {echteStaat.dagen.some(heeftVoorstel) && (
                <>
                  {' '}
                  De keurder deed per dag een <b>voorstel</b> (paars) — jij beslist: overnemen of zelf aanpassen.
                </>
              )}
            </div>
          )}
          {echteStaat?.status === 'goedgekeurd' && (
            <div className="acc-notitie">
              <span>🔒</span>
              <span>
                Goedgekeurd{echteStaat.goedgekeurd_door_naam ? ` door ${echteStaat.goedgekeurd_door_naam}` : ''} — de{' '}
                <b>getekende urenstaat</b>; wijzigen kan alleen via een nieuwe afkeuring.
              </span>
            </div>
          )}
          {echteStaat?.status === 'ingediend' && (
            <div className="acc-notitie">
              <span>⏳</span>
              <span>
                Ingediend {datumMetTijd(echteStaat.ingediend_op)}
                {echteStaat.ingediend_namens && echteStaat.ingediend_door_naam
                  ? ` door ${echteStaat.ingediend_door_naam} (namens)`
                  : ''}{' '}
                — wacht op de uitvoerder.
              </span>
            </div>
          )}
        </div>
      )}
      {muteerbaar && (
        <div className="acc-notitie">
          <span>ℹ️</span>
          <span>
            Indienen kan t/m <b>maandag 09:00</b> · lege dag telt als 0 uur.
          </span>
        </div>
      )}
      {muteerbaar && (
        <div className="acc-actionbar">
          <button className="acc-btn groen" disabled={bezig} onClick={() => void indienen()}>
            {bezig ? 'Bezig…' : 'Week indienen'}
          </button>
        </div>
      )}
    </div>
  )
}

/** Daginvoer (run A 12 UX-punten, mockup uren-uitvoerder-v3.html scherm ②): uren als tikknoppen 4·6·8·10 + −/+ per half
 * uur ("ander aantal…" pas een toetsenbord), omschrijving als chips (per administratie instelbaar; "overig" = vrij veld),
 * doorfactureren ingeklapt (chip + wijzigen), m² en vrije omschrijving onder "meer" als het project geen m²-project is. */
function DagInvoerView({
  ctx,
  datum,
  dagNaam,
  bestaand,
  doorfacturerenStandaard,
  chips,
  contractM2,
  namens,
  namensSuffix,
  vangFout,
  terug,
  naOpslaan,
}: {
  ctx: WeekContext
  datum: string
  dagNaam: string
  bestaand: WeekstaatDto['dagen'][number] | null
  /** Projectdefault (18-09 blok B): verrekenbaar volgens de contract-ontleding → Doorfactureren, anders Niet. */
  doorfacturerenStandaard: boolean
  chips: string[]
  contractM2: string | null
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: () => void
  naOpslaan: () => void
}) {
  const [uren, setUren] = useState(bestaand?.uren ?? '')
  const [anderAantal, setAnderAantal] = useState(false)
  const [m2, setM2] = useState(bestaand?.m2 ?? '')
  const chipLijst = chips.length > 0 ? chips : STANDAARD_OMSCHRIJVING_CHIPS
  const bestaandeChip = bestaand?.opmerking && chipLijst.includes(bestaand.opmerking) ? bestaand.opmerking : null
  const [chip, setChip] = useState<string | null>(bestaandeChip ?? (bestaand?.opmerking ? OVERIG_CHIP : null))
  const [vrijeTekst, setVrijeTekst] = useState(bestaandeChip ? '' : (bestaand?.opmerking ?? ''))
  // 18-09 blok B: bestaande regel = zijn eigen stand; nieuwe regel = projectdefault (chip "standaard"); mens wint.
  const [doorfactureren, setDoorfactureren] = useState<boolean>(bestaand?.doorfactureren ?? doorfacturerenStandaard)
  const [doorfWijzigen, setDoorfWijzigen] = useState(false)
  const m2Project = isM2Project({ contract_m2: contractM2 })
  const [meer, setMeer] = useState(m2Project || Boolean(bestaand?.m2))
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const omschrijving = chip === OVERIG_CHIP || chip === null ? vrijeTekst.trim() : chip
  const urenGetal = Number(uren.replace(',', '.'))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      await zetDag({
        administratie_id: ctx.administratieId,
        project_id: ctx.projectId,
        jaar: ctx.jaar,
        weeknummer: ctx.weeknummer,
        datum,
        uren: uren.replace(',', '.'),
        // m² optioneel (18-09 blok A): leeg blijft null — nooit 0 invullen.
        m2: m2.trim() === '' ? null : m2.replace(',', '.'),
        doorfactureren,
        opmerking: omschrijving === '' ? null : omschrijving,
        namens_zzper_id: namens?.id ?? null,
      })
      naOpslaan()
    } catch (err) {
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(false)
    }
  }

  const datumLabel = new Date(datum).toLocaleDateString('nl-NL', { weekday: 'long', day: 'numeric', month: 'short' })

  return (
    <div>
      <Terug label={`Week ${ctx.weeknummer}`} onClick={terug} />
      <div className="acc-seclabel">
        {datumLabel} · {ctx.projectNaam ?? 'project'}
        {namensSuffix}
      </div>
      <div className="acc-card">
        {/* Punt 2: uren als tikknoppen; toetsenbord alleen via "ander aantal…". */}
        <div className="acc-form">
          <span style={{ fontWeight: 600 }}>Uren</span>
          <div className="acc-tikrij" role="group" aria-label="Uren">
            {UREN_TIKKEUZES.map((keuze) => (
              <button
                key={keuze}
                type="button"
                className={`acc-tik${uren.replace(',', '.') === keuze ? ' on' : ''}`}
                data-testid={`tik-${keuze}`}
                onClick={() => {
                  setUren(keuze)
                  setAnderAantal(false)
                }}
              >
                {keuze}
              </button>
            ))}
          </div>
          <div className="acc-pm">
            <button type="button" className="acc-tik" aria-label="Half uur minder" onClick={() => setUren(stapHalfUur(uren, -1))}>
              −
            </button>
            <b data-testid="uren-stand">{uren === '' ? '—' : `${urenGetal.toLocaleString('nl-NL')} u`}</b>
            <button type="button" className="acc-tik" aria-label="Half uur meer" onClick={() => setUren(stapHalfUur(uren, 1))}>
              +
            </button>
          </div>
          {anderAantal ? (
            <input
              type="number"
              inputMode="decimal"
              step={0.5}
              min={0}
              max={24}
              autoFocus
              aria-label="Uren (ander aantal)"
              placeholder="bijv. 7,5"
              value={uren}
              onChange={(e) => setUren(e.target.value)}
            />
          ) : (
            <button type="button" className="acc-tekstlink" style={{ alignSelf: 'flex-start' }} onClick={() => setAnderAantal(true)}>
              ander aantal…
            </button>
          )}
        </div>

        {/* Punt 3: omschrijving als chips (per administratie instelbaar); "overig" opent een tekstveld. */}
        <div className="acc-form">
          <span style={{ fontWeight: 600 }}>Wat heb je gedaan?</span>
          <div className="acc-chipkeuze" role="group" aria-label="Omschrijving">
            {chipLijst.map((c) => (
              <button
                key={c}
                type="button"
                className={`acc-tik${chip === c ? ' on' : ''}`}
                data-testid={`chip-${c}`}
                onClick={() => setChip(chip === c ? null : c)}
              >
                {c}
              </button>
            ))}
            {!chipLijst.includes(OVERIG_CHIP) && (
              <button type="button" className={`acc-tik${chip === OVERIG_CHIP ? ' on' : ''}`} data-testid="chip-overig" onClick={() => setChip(OVERIG_CHIP)}>
                {OVERIG_CHIP}
              </button>
            )}
          </div>
          {(chip === OVERIG_CHIP || (meer && chip === null)) && (
            <input
              type="text"
              aria-label="Omschrijving (vrij)"
              placeholder="bijv. wachttijd i.v.m. levering"
              value={vrijeTekst}
              onChange={(e) => setVrijeTekst(e.target.value)}
            />
          )}
        </div>

        {/* Punt 11: doorfactureren ingeklapt — chip + wijzigen; dropdown pas ná tikken. */}
        <div className="acc-form">
          <span style={{ fontWeight: 600 }}>Doorfactureren</span>
          {doorfWijzigen ? (
            <select
              value={doorfactureren ? 'ja' : 'nee'}
              onChange={(e) => setDoorfactureren(e.target.value === 'ja')}
              aria-label="Doorfactureren"
              data-testid="doorfactureren"
              autoFocus
            >
              <option value="ja">{doorfacturerenLabel(true)}</option>
              <option value="nee">{doorfacturerenLabel(false)}</option>
            </select>
          ) : (
            <div className="acc-ingeklapt" data-testid="doorfactureren-ingeklapt">
              <span>
                <span className={`acc-chip${doorfactureren ? '' : ' wacht'}`}>{doorfacturerenLabel(doorfactureren).toLowerCase()}</span>
                <small style={{ color: 'var(--acc-muted)', marginLeft: 6 }}>
                  {doorfactureren === doorfacturerenStandaard ? 'standaard voor dit project' : `standaard: ${doorfacturerenLabel(doorfacturerenStandaard).toLowerCase()}`}
                </small>
              </span>
              <button type="button" className="acc-tekstlink" data-testid="doorfactureren-wijzigen" onClick={() => setDoorfWijzigen(true)}>
                wijzigen
              </button>
            </div>
          )}
        </div>

        {/* Punt 12: m² (en vrije omschrijving zonder chip) alleen direct zichtbaar op een m²-project; anders onder "meer". */}
        {!meer ? (
          <button type="button" className="acc-tekstlink" data-testid="meer" style={{ alignSelf: 'flex-start' }} onClick={() => setMeer(true)}>
            ▸ meer (m², omschrijving)
          </button>
        ) : (
          <label className="acc-form">
            m² gebouwd (optioneel)
            <input type="number" inputMode="decimal" placeholder="leeg = niet ingevuld" value={m2 ?? ''} onChange={(e) => setM2(e.target.value)} aria-label="m² gebouwd (optioneel)" />
          </label>
        )}

        {bestaand && heeftVoorstel(bestaand) && (
          <div className="acc-notitie">
            <span>✏️</span>
            <span>
              Voorstel van de keurder: <b className="acc-voorstel-inline">{voorstelLabel(bestaand)}</b> — jij beslist.{' '}
              <button
                type="button"
                className="acc-plus"
                onClick={() => {
                  if (bestaand.voorstel_uren !== null) setUren(bestaand.voorstel_uren)
                  if (bestaand.voorstel_m2 !== null) {
                    setMeer(true)
                    setM2(bestaand.voorstel_m2)
                  }
                }}
              >
                overnemen
              </button>
            </span>
          </div>
        )}
        <div className="acc-notitie">
          <span>➕</span>
          <span>
            {dagNaam === 'za' || dagNaam === 'zo'
              ? 'Weekenddag — alleen invullen als er echt gewerkt is.'
              : 'Zelfde dag op een ander project gewerkt? Vul die uren dáár in.'}
          </span>
        </div>
        {fout && <FoutRegel tekst={fout} />}
      </div>
      <div className="acc-actionbar">
        <button className="acc-btn primair" disabled={bezig || uren.trim() === '' || Number.isNaN(urenGetal)} onClick={() => void opslaan()}>
          {bezig ? 'Bezig…' : 'Opslaan'}
        </button>
      </div>
    </div>
  )
}

function IngediendView({
  namens,
  vangFout,
  openWeek,
}: {
  namens: { id: string; naam: string } | null
  vangFout: (err: unknown) => string
  openWeek: (item: IngediendeWeekDto) => void
}) {
  const [items, setItems] = useState<IngediendeWeekDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalIngediend(namens?.id ?? null)
      .then(setItems)
      .catch((err) => setFout(vangFout(err) || null))
  }, [namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  return (
    <div>
      <div className="acc-seclabel">Ingediende weken (alle projecten)</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {items === null && !fout && <Leeg tekst="Laden…" />}
      {items !== null && items.length === 0 && <Leeg tekst="Nog geen ingediende weken." />}
      {(items ?? []).map((item) => {
        const chip = chipVoorWeekStatus(item.status as WeekKaartDto['status'])
        const meta =
          item.status === 'goedgekeurd'
            ? `goedgekeurd${item.goedgekeurd_door_naam ? ` door ${item.goedgekeurd_door_naam}` : ''}`
            : item.status === 'corrigeren'
              ? 'week afgekeurd — tik voor toelichting'
              : `ingediend ${datumMetTijd(item.ingediend_op)}${item.ingediend_namens ? ' (namens)' : ''}`
        return (
          <button key={item.weekstaat_id} className="acc-card klik" onClick={() => openWeek(item)}>
            <span>
              <span className="acc-tt">
                Wk {item.weeknummer} · {item.project_naam ?? 'project'} · {weekTotaalLabel(item.totaal_uren, item.totaal_m2)}
              </span>
              <span className="acc-meta" style={{ display: 'block' }}>
                {meta}
              </span>
            </span>
            <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
          </button>
        )
      })}
      {items !== null && items.length > 0 && (
        <div className="acc-notitie">
          <span>🔒</span>
          <span>
            Een goedgekeurde week is de <b>getekende urenstaat</b> — de basis voor de factuurcontrole.
          </span>
        </div>
      )}
    </div>
  )
}

/* ============ planning (alleen-lezen, besluit B 22-08) ============ */

/** `?planning=2026-W37` (bundelmelding "planning week N aangepast", 15-09): de week uit de deep-link, anders null. */
export function planningWeekUitZoekdeel(zoekdeel: string): { jaar: number; weeknummer: number } | null {
  const m = /^(\d{4})-W(\d{1,2})$/.exec(new URLSearchParams(zoekdeel).get('planning') ?? '')
  if (!m) return null
  const jaar = Number(m[1])
  const weeknummer = Number(m[2])
  return weeknummer >= 1 && weeknummer <= 53 ? { jaar, weeknummer } : null
}

function MijnPlanningView({
  namens,
  namensSuffix,
  vangFout,
  terug,
  startWeek = null,
}: {
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: (() => void) | null
  /** Deep-link `/accordeur?planning=JJJJ-Wnn` (15-09): open direct die week. */
  startWeek?: { jaar: number; weeknummer: number } | null
}) {
  const [week, setWeek] = useState(() => startWeek ?? isoWeekVan(new Date()))
  const [dagen, setDagen] = useState<MijnPlanningDagDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    setDagen(null)
    haalMijnPlanning(week.jaar, week.weeknummer, namens?.id ?? null)
      .then(setDagen)
      .catch((err) => setFout(vangFout(err) || null))
  }, [week, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const weekdagen = weekDagen(week.jaar, week.weeknummer)
  const perDatum = new Map<string, MijnPlanningDagDto[]>()
  for (const dag of dagen ?? []) {
    perDatum.set(dag.datum, [...(perDatum.get(dag.datum) ?? []), dag])
  }
  const huidige = isoWeekVan(new Date())
  const isHuidigeWeek = week.jaar === huidige.jaar && week.weeknummer === huidige.weeknummer

  return (
    <div>
      {terug && <Terug label={namens ? `${namens.naam} · projecten` : 'Terug'} onClick={terug} />}
      {/* Blok C 28-08 (mockup §1 "Vandaag"): eigen stempels — alleen de veldwerker zelf, nooit namens. */}
      {namens === null && isHuidigeWeek && <StempelsVandaag vangFout={vangFout} />}
      <div className="acc-seclabel" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>
          Planning · week {week.weeknummer}
          {namensSuffix}
        </span>
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
          <button className="acc-iconbtn" aria-label="Vorige week" onClick={() => setWeek(schuifWeek(week.jaar, week.weeknummer, -1))}>
            ‹
          </button>
          {!isHuidigeWeek && (
            <button className="acc-tekstlink" onClick={() => setWeek(huidige)}>
              vandaag
            </button>
          )}
          <button className="acc-iconbtn" aria-label="Volgende week" onClick={() => setWeek(schuifWeek(week.jaar, week.weeknummer, 1))}>
            ›
          </button>
        </span>
      </div>
      {/* 15-09 (Peter/Haci, planning met terugwerkende kracht): de twee voorgaande weken staan één tik weg — het kantoor
          kan achteraf plannen; gekeurde uren blijven alleen-lezen zoals altijd. */}
      <div className="acc-chips" data-testid="planning-weekchips" style={{ display: 'flex', gap: 6, margin: '6px 0 8px', flexWrap: 'wrap' }}>
        {[-2, -1, 0].map((delta) => {
          const w = schuifWeek(huidige.jaar, huidige.weeknummer, delta)
          const actief = w.jaar === week.jaar && w.weeknummer === week.weeknummer
          return (
            <button
              key={delta}
              type="button"
              className={`acc-chip${actief ? ' actief' : ''}`}
              aria-pressed={actief}
              onClick={() => setWeek(w)}
            >
              {delta === 0 ? 'deze week' : `week ${w.weeknummer}`}
            </button>
          )
        })}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {dagen === null && !fout && <Leeg tekst="Laden…" />}
      {dagen !== null && (
        <div className="acc-card">
          {weekdagen.map(({ naam, datum }) => {
            const items = perDatum.get(datum) ?? []
            if (items.length === 0 && (naam === 'za' || naam === 'zo')) return null // weekend alleen tonen mét planning
            return (
              <div key={datum} className="acc-dagrij">
                <span className="acc-dag">{naam}</span>
                {items.length === 0 ? (
                  <span className="acc-leegdag">vrij / niet gepland</span>
                ) : (
                  <span className="acc-proj">
                    {items.map((item) => (
                      <span key={`${item.administratie_id}-${item.project_id}`} style={{ display: 'block' }}>
                        <b>{item.project_naam ?? 'project'}</b>
                        {item.dagdeel === 'half' ? ' · ½ dag' : ''}
                        {/* Werkopdracht(en) bij de geplande dag (31-08, alleen-lezen): de
                            dag-override wint en toont "afwijkend" (mockup veld-app-paneel). */}
                        {(item.werkopdrachten ?? []).map((wo) => (
                          <span key={wo.groep_id} className="acc-werkopdracht">
                            📋 {wo.afwijkend && <b>{naam} afwijkend: </b>}
                            {wo.tekst}
                          </span>
                        ))}
                      </span>
                    ))}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
      <div className="acc-notitie">
        <span>🔒</span>
        <span>
          Alleen-lezen: plannen doet het kantoor. Sta je ergens anders op de bouw dan gepland? Vul je uren gewoon
          in op het juiste project — dat kleurt bij de keuring als "buiten planning", nooit een blokkade.
        </span>
      </div>
    </div>
  )
}

/** Eigen werkstempels van vandaag (blok C 28-08, mockup geofence-stempels.html §1): transparantie
 * voor de veldwerker — per project de in-/uit-tijden; geen stempels = "Geen stempels vandaag".
 * De registratie komt uit de latere native OS-geofence (eigen release-ronde); deze weergave en het
 * intake-endpoint staan er al voor. */
function StempelsVandaag({ vangFout }: { vangFout: (err: unknown) => string }) {
  const [stempels, setStempels] = useState<StempelDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const vandaag = new Date()
  const datum = `${vandaag.getFullYear()}-${String(vandaag.getMonth() + 1).padStart(2, '0')}-${String(vandaag.getDate()).padStart(2, '0')}`
  useEffect(() => {
    let actief = true
    haalEigenStempels(datum)
      .then((s) => actief && setStempels(s))
      .catch((err) => actief && setFout(vangFout(err) || null))
    return () => {
      actief = false
    }
  }, [datum, vangFout])
  if (fout) return null // stempels zijn een extra; een leesfout mag de planning nooit hinderen
  const perProject = new Map<string, StempelDto[]>()
  for (const s of stempels ?? []) perProject.set(s.project_id, [...(perProject.get(s.project_id) ?? []), s])
  return (
    <div className="acc-card" data-testid="stempels-vandaag" style={{ marginBottom: 10 }}>
      <div className="acc-seclabel" style={{ marginTop: 0 }}>
        📍 Vandaag · werkstempels
      </div>
      {stempels === null && <Leeg tekst="Laden…" />}
      {stempels !== null && perProject.size === 0 && <Leeg tekst="Geen stempels vandaag" />}
      {[...perProject.entries()].map(([projectId, lijst]) => (
        <div key={projectId} className="acc-dagrij">
          <span className="acc-proj">
            <b>{lijst[0].project_naam ?? 'project'}</b>
            {lijst.map((s) => (
              <span key={s.id} style={{ display: 'block' }}>
                {stempelTijd(s.tijdstip)} {s.soort === 'in' ? 'aangekomen' : 'vertrokken'}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ============ detacheerder ============ */

function zzperKaart(zzper: ZzperKaartDto, kies: (zzper: ZzperKaartDto) => void) {
  return (
    <button key={zzper.gebruiker_id} className="acc-card klik" onClick={() => kies(zzper)}>
      <span>
        <span className="acc-tt">{zzper.naam}</span>
        <span className="acc-meta" style={{ display: 'block' }}>
          {zzper.aantal_projecten} {zzper.aantal_projecten === 1 ? 'project' : 'projecten'} · laatste invoer{' '}
          {datumKort(zzper.laatste_invoer)}
        </span>
      </span>
      {zzper.te_doen > 0 ? (
        <span className="acc-chip open">
          {zzper.open_weken === 1 ? '1 week open' : `${zzper.open_weken} weken open`}
        </span>
      ) : (
        <span className="acc-chip akkoord">bij</span>
      )}
    </button>
  )
}

/** Werklijst detacheerder (04-09 A3): alleen ZZP'ers met een handeling (gepland zonder staat, of een staat
 * die op correctie wacht); niets te doen voor niemand = "✓ Alles is bij" mét verversknop (accordeur-patroon).
 * Wie niets te doen heeft blijft bereikbaar onder "Ook zonder werk" — uren buiten planning blijven invoerbaar. */
function DetaZzpersView({ vangFout, kies }: { vangFout: (err: unknown) => string; kies: (zzper: ZzperKaartDto) => void }) {
  const [zzpers, setZzpers] = useState<ZzperKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [toonZonderWerk, setToonZonderWerk] = useState(false)
  const laad = useCallback(() => {
    setFout(null)
    haalMijnZzpers()
      .then(setZzpers)
      .catch((err) => setFout(vangFout(err) || null))
  }, [vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const metWerk = (zzpers ?? []).filter((z) => z.te_doen > 0)
  const zonderWerk = (zzpers ?? []).filter((z) => z.te_doen === 0)

  return (
    <div>
      <div className="acc-seclabel">Mijn ZZP'ers{zzpers ? ` · ${metWerk.length} met werk` : ''}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {zzpers === null && !fout && <Leeg tekst="Laden…" />}
      {zzpers !== null && zzpers.length === 0 && (
        <Leeg tekst="Nog geen ZZP'ers gekoppeld — het kantoor beheert de koppelingen." />
      )}
      {metWerk.map((zzper) => zzperKaart(zzper, kies))}
      {zzpers !== null && zzpers.length > 0 && metWerk.length === 0 && (
        <div className="acc-leeg" data-testid="alles-bij">
          <div className="acc-big">✓</div>
          <b>Alles is bij</b>
          Alle geplande weken zijn ingevuld of ingediend en er wacht geen afgekeurde staat — of ververs hier.
          <div style={{ marginTop: 16 }}>
            <button className="acc-btn klein secundair" onClick={laad}>
              ↻ Verversen
            </button>
          </div>
        </div>
      )}
      {zonderWerk.length > 0 && (
        <>
          <button
            className="acc-card klik"
            onClick={() => setToonZonderWerk((v) => !v)}
            aria-expanded={toonZonderWerk}
            data-testid="ook-zonder-werk"
          >
            <span>
              <span className="acc-tt">Ook zonder werk</span>
              <span className="acc-meta" style={{ display: 'block' }}>
                {zonderWerk.length} {zonderWerk.length === 1 ? "ZZP'er" : "ZZP'ers"} · alles bij — uren buiten de planning invullen kan
                hier
              </span>
            </span>
            <span className="acc-arrow">{toonZonderWerk ? '▾' : '›'}</span>
          </button>
          {toonZonderWerk && zonderWerk.map((zzper) => zzperKaart(zzper, kies))}
        </>
      )}
      <div className="acc-notitie">
        <span>🔒</span>
        <span>
          Je vult weekstaten in <b>namens</b> gekoppelde ZZP'ers; projectinhoud blijft onzichtbaar.
        </span>
      </div>
    </div>
  )
}

/* ============ uitvoerder ============ */

function UitvProjectenView({
  vangFout,
  openProject,
}: {
  vangFout: (err: unknown) => string
  openProject: (kaart: UitvoerderProjectKaartDto) => void
}) {
  const [projecten, setProjecten] = useState<UitvoerderProjectKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalUitvoerderProjecten()
      .then(setProjecten)
      .catch((err) => setFout(vangFout(err) || null))
  }, [vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  function voortgang(kaart: UitvoerderProjectKaartDto): string | null {
    if (kaart.contract_m2 === null || Number(kaart.contract_m2) === 0) return null
    return `${Math.round((Number(kaart.gebouwd_m2) / Number(kaart.contract_m2)) * 100)}% gebouwd`
  }

  // 18-09 (feedback uitvoerder punt 3): álle actieve projecten; gekoppeld (planning/uren) bovenaan, chip op de rest.
  const gekoppeld = (projecten ?? []).filter((k) => k.gekoppeld !== false)
  const overige = (projecten ?? []).filter((k) => k.gekoppeld === false)

  return (
    <div>
      <div className="acc-seclabel">Lopende projecten{projecten ? ` (${projecten.length})` : ''}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {projecten === null && !fout && <Leeg tekst="Laden…" />}
      {projecten !== null && projecten.length === 0 && (
        <Leeg tekst="Geen actieve projecten in je administratie(s) — het kantoor maakt projecten aan." />
      )}
      {projecten !== null && overige.length > 0 && gekoppeld.length > 0 && <div className="acc-seclabel">Mijn projecten</div>}
      {[...gekoppeld, ...overige].map((kaart, i) => (
        <Fragment key={`${kaart.administratie_id}-${kaart.project_id}`}>
          {i === gekoppeld.length && gekoppeld.length > 0 && overige.length > 0 && (
            <div className="acc-seclabel" data-testid="kop-andere-projecten">
              Andere projecten
            </div>
          )}
        <button className="acc-card klik" onClick={() => openProject(kaart)}>
          <span>
            <span className="acc-tt">{kaart.project_naam ?? 'Project'}</span>
            <span className="acc-meta" style={{ display: 'block' }}>
              {[
                kaart.soort_werk,
                kaart.contract_m2 !== null ? `${Number(kaart.contract_m2).toLocaleString('nl-NL')} m² contract` : null,
                kaart.looptijd_tot ? `t/m ${datumMetWeek(kaart.looptijd_tot)}` : null,
              ]
                .filter(Boolean)
                .join(' · ') || 'projectgegevens volgen'}
            </span>
          </span>
          <span style={{ textAlign: 'right' }}>
            {kaart.meerwerk_gemeld > 0 && <span className="acc-chip meerwerk">{kaart.meerwerk_gemeld} meerwerk</span>}
            {voortgang(kaart) && (
              <span className="acc-meta" style={{ display: 'block' }}>
                {voortgang(kaart)}
              </span>
            )}
          </span>
        </button>
        </Fragment>
      ))}
    </div>
  )
}

function ProjectDetailView({
  kaart,
  vangFout,
  terug,
  openDocument,
  meldMeerwerk: naarMelden,
  beantwoordVraag,
}: {
  kaart: UitvoerderProjectKaartDto
  vangFout: (err: unknown) => string
  terug: () => void
  openDocument: (doc: ProjectDocumentKaartDto) => void
  meldMeerwerk: () => void
  beantwoordVraag: (melding: MeerwerkDto) => void
}) {
  const [detail, setDetail] = useState<ProjectDetailDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalProjectDetail(kaart.administratie_id, kaart.project_id)
      .then(setDetail)
      .catch((err) => setFout(vangFout(err) || null))
  }, [kaart, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  const pct =
    detail && detail.contract_m2 !== null && Number(detail.contract_m2) > 0
      ? ` (${Math.round((Number(detail.gebouwd_m2) / Number(detail.contract_m2)) * 100)}%)`
      : ''

  return (
    <div>
      <Terug label="Projecten" onClick={terug} />
      <div className="acc-seclabel">{kaart.project_naam ?? 'Project'}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {detail === null && !fout && <Leeg tekst="Laden…" />}
      {detail !== null && (
        <>
          <div className="acc-card acc-infolijst">
            {detail.opdrachtgever && (
              <div className="acc-rij">
                <span className="acc-k">Opdrachtgever</span>
                <b>{detail.opdrachtgever}</b>
              </div>
            )}
            {detail.werknummer_opdrachtgever && (
              <div className="acc-rij">
                <span className="acc-k">Werknummer opdrachtgever</span>
                <b>{detail.werknummer_opdrachtgever}</b>
              </div>
            )}
            {detail.contract_m2 !== null && (
              <div className="acc-rij">
                <span className="acc-k">Contract m²</span>
                <b>{Number(detail.contract_m2).toLocaleString('nl-NL')} m²</b>
              </div>
            )}
            <div className="acc-rij">
              <span className="acc-k">Gebouwd (goedgekeurde staten)</span>
              <b>
                {Number(detail.gebouwd_m2).toLocaleString('nl-NL')} m²{pct}
              </b>
            </div>
            {(detail.looptijd_van || detail.looptijd_tot) && (
              <div className="acc-rij">
                <span className="acc-k">Looptijd</span>
                <b>
                  {datumMetWeek(detail.looptijd_van)} – {datumMetWeek(detail.looptijd_tot)}
                </b>
              </div>
            )}
            {detail.huurtijd_omschrijving && (
              <div className="acc-rij">
                <span className="acc-k">Huurtijd in contract</span>
                <b>{detail.huurtijd_omschrijving}</b>
              </div>
            )}
            {detail.doorlopende_huur_omschrijving && (
              <div className="acc-rij">
                <span className="acc-k">Doorlopende huur</span>
                <b className="acc-chip ingediend">{detail.doorlopende_huur_omschrijving}</b>
              </div>
            )}
          </div>

          {detail.documenten.length > 0 && <div className="acc-seclabel">Documenten</div>}
          {detail.documenten.map((doc) => (
            <button key={doc.id} className="acc-doclink" onClick={() => openDocument(doc)}>
              <span className="acc-ic">📄</span>
              <span>
                {doc.titel}
                {doc.versie_omschrijving && <small>{doc.versie_omschrijving}</small>}
              </span>
            </button>
          ))}

          <div className="acc-seclabel">Meerwerk ({detail.meerwerk.length})</div>
          {detail.meerwerk.length === 0 && <Leeg tekst="Nog geen meerwerk gemeld op dit project." />}
          {detail.meerwerk.length > 0 && (
            <div className="acc-card">
              {detail.meerwerk.map((m) => {
                const chip = meerwerkChip(m)
                const openVraag = m.vraag_tekst !== null && m.vraag_antwoord === null
                return (
                  <div key={m.id} className="acc-mwrij">
                    <span className="acc-oms">
                      {m.omschrijving}
                      <small>
                        gemeld {datumMetWeek(m.gemeld_op)} · {m.aantal} {eenheidLabel(m.eenheid)}
                        {m.heeft_foto ? ' · foto ✓' : ''}
                      </small>
                      {openVraag && (
                        <button className="acc-tekstlink" onClick={() => beantwoordVraag(m)}>
                          ❓ Vraag van het kantoor — beantwoorden
                        </button>
                      )}
                    </span>
                    <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
                  </div>
                )
              })}
            </div>
          )}

          <div className="acc-actionbar">
            <button className="acc-btn groen" onClick={naarMelden}>
              + Meerwerk melden
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function ContractView({
  kaart,
  doc,
  vangFout,
  terug,
}: {
  kaart: UitvoerderProjectKaartDto
  doc: ProjectDocumentKaartDto
  vangFout: (err: unknown) => string
  terug: () => void
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => {
    let url: string | null = null
    haalProjectDocumentBlob(kaart.administratie_id, doc.id)
      .then((geladen) => {
        url = geladen
        setBlobUrl(geladen)
      })
      .catch((err) => setFout(vangFout(err) || null))
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [kaart, doc, vangFout])

  return (
    <div>
      <Terug label={kaart.project_naam ?? 'Project'} onClick={terug} />
      <div className="acc-seclabel">{doc.titel} — alleen lezen</div>
      {fout && <FoutRegel tekst={fout} />}
      <PdfWeergave blobUrl={blobUrl} laden={blobUrl === null && !fout} fout={null} />
    </div>
  )
}

function MeerwerkMeldenView({
  kaart,
  vangFout,
  terug,
  naMelden,
}: {
  kaart: MeerwerkDoel
  vangFout: (err: unknown) => string
  terug: () => void
  naMelden: () => void
}) {
  const [omschrijving, setOmschrijving] = useState('')
  const [aantal, setAantal] = useState('')
  const [eenheid, setEenheid] = useState('m2')
  const [datum, setDatum] = useState(() => new Date().toISOString().slice(0, 10))
  const [inOpdrachtVan, setInOpdrachtVan] = useState('')
  const [foto, setFoto] = useState<File | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  async function melden() {
    setBezig(true)
    setFout(null)
    try {
      await meldMeerwerk({
        administratie_id: kaart.administratie_id,
        project_id: kaart.project_id,
        omschrijving: omschrijving.trim(),
        aantal: aantal.replace(',', '.'),
        eenheid,
        datum_uitgevoerd: datum,
        in_opdracht_van: inOpdrachtVan,
        foto,
      })
      naMelden()
    } catch (err) {
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <Terug label={kaart.project_naam ?? 'Project'} onClick={terug} />
      <div className="acc-seclabel">Meerwerk melden</div>
      <div className="acc-card">
        <label className="acc-form">
          Omschrijving
          <textarea
            rows={4}
            style={{ resize: 'vertical', minHeight: 96, lineHeight: 1.5 }}
            placeholder="Beschrijf het meerwerk voluit — wat, waar en waarom. Alle tekst blijft volledig zichtbaar, ook in de kantoorlijst."
            value={omschrijving}
            onChange={(e) => setOmschrijving(e.target.value)}
          />
        </label>
        <div className="acc-duo">
          <label className="acc-form">
            Aantal
            <input type="number" inputMode="decimal" placeholder="0" value={aantal} onChange={(e) => setAantal(e.target.value)} />
          </label>
          <label className="acc-form">
            Eenheid
            <select value={eenheid} onChange={(e) => setEenheid(e.target.value)}>
              {EENHEDEN.map((e) => (
                <option key={e.waarde} value={e.waarde}>
                  {e.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="acc-form">
          Datum uitgevoerd
          <input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} />
        </label>
        <label className="acc-form">
          In opdracht van (naam op de bouw)
          <input type="text" placeholder="bijv. J. Timmers (BAM)" value={inOpdrachtVan} onChange={(e) => setInOpdrachtVan(e.target.value)} />
        </label>
        <label className="acc-form">
          Foto (optioneel, sterk aangeraden)
          <BestandKnop
            icoon="📷"
            label="Maak of kies een foto"
            bestandsnaam={foto?.name ?? null}
            accept="image/*"
            capture="environment"
            onKies={setFoto}
          />
        </label>
        <div className="acc-notitie waarschuw">
          <span>⚠️</span>
          <span>
            Meerwerk zonder melding = niet doorbelast. Het kantoor toetst elke melding tegen offerte- en
            verrekenafspraken en zet 'm door naar facturatie.
          </span>
        </div>
        {fout && <FoutRegel tekst={fout} />}
      </div>
      <div className="acc-actionbar">
        <button
          className="acc-btn groen"
          disabled={bezig || omschrijving.trim() === '' || aantal.trim() === ''}
          onClick={() => void melden()}
        >
          {bezig ? 'Bezig…' : 'Melden'}
        </button>
      </div>
    </div>
  )
}

function MeerwerkVraagView({
  kaart,
  melding,
  vangFout,
  terug,
  naAntwoord,
}: {
  kaart: UitvoerderProjectKaartDto
  melding: MeerwerkDto
  vangFout: (err: unknown) => string
  terug: () => void
  naAntwoord: () => void
}) {
  const [tekst, setTekst] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  async function versturen() {
    setBezig(true)
    setFout(null)
    try {
      await beantwoordMeerwerkVraag(kaart.administratie_id, melding.id, tekst.trim())
      naAntwoord()
    } catch (err) {
      const foutTekst = vangFout(err)
      if (foutTekst) setFout(foutTekst)
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <Terug label={kaart.project_naam ?? 'Project'} onClick={terug} />
      <div className="acc-seclabel">Vraag van het kantoor</div>
      <div className="acc-card">
        <div className="acc-notitie" style={{ margin: '0 0 10px' }}>
          <span>❓</span>
          <span>
            Over "{melding.omschrijving}": <b>{melding.vraag_tekst}</b>
          </span>
        </div>
        <label className="acc-form">
          Jouw antwoord
          <textarea
            rows={4}
            style={{ resize: 'vertical', minHeight: 96, lineHeight: 1.5 }}
            value={tekst}
            onChange={(e) => setTekst(e.target.value)}
          />
        </label>
        {fout && <FoutRegel tekst={fout} />}
      </div>
      <div className="acc-actionbar">
        <button className="acc-btn groen" disabled={bezig || tekst.trim() === ''} onClick={() => void versturen()}>
          {bezig ? 'Bezig…' : 'Antwoord versturen'}
        </button>
      </div>
    </div>
  )
}

/* ============ uitvoerder: keuren (WEEKNIVEAU) ============ */

function KeurLijstView({
  vangFout,
  openItem,
}: {
  vangFout: (err: unknown) => string
  openItem: (item: TeKeurenItemDto) => void
}) {
  const [items, setItems] = useState<TeKeurenItemDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalTeKeuren()
      .then(setItems)
      .catch((err) => setFout(vangFout(err) || null))
  }, [vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  return (
    <div>
      <div className="acc-seclabel">Te keuren urenstaten{items ? ` (${items.length})` : ''}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {items === null && !fout && <Leeg tekst="Laden…" />}
      {items !== null && items.length === 0 && <Leeg tekst="Niets te keuren — ingediende weken verschijnen hier." />}
      {(items ?? []).map((item) => (
        <button key={item.weekstaat_id} className="acc-card klik" onClick={() => openItem(item)}>
          <span>
            <span className="acc-tt">
              {item.zzper_naam ?? "ZZP'er"} · wk {item.weeknummer} · {item.project_naam ?? 'project'}
            </span>
            <span className="acc-meta" style={{ display: 'block' }}>
              {weekTotaalLabel(item.totaal_uren, item.totaal_m2)} · ingediend {datumMetTijd(item.ingediend_op)}
              {item.ingediend_namens && item.ingediend_door_naam ? ` · door ${item.ingediend_door_naam} (namens)` : ''}
            </span>
          </span>
          <span className="acc-arrow">›</span>
        </button>
      ))}
      {items !== null && items.length > 0 && (
        <div className="acc-notitie">
          <span>🔑</span>
          <span>
            Na jouw akkoord is de staat de <b>getekende urenstaat</b>.
          </span>
        </div>
      )}
    </div>
  )
}

function KeurDetailView({
  item,
  vangFout,
  terug,
  naarAfwijzen,
  naAkkoord,
}: {
  item: TeKeurenItemDto
  vangFout: (err: unknown) => string
  terug: () => void
  naarAfwijzen: (staat: WeekstaatDto) => void
  naAkkoord: () => void
}) {
  const [staat, setStaat] = useState<WeekstaatDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const laad = useCallback(() => {
    setFout(null)
    haalWeekstaat(item.administratie_id, item.weekstaat_id)
      .then(setStaat)
      .catch((err) => setFout(vangFout(err) || null))
  }, [item, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  async function akkoord() {
    setBezig(true)
    setFout(null)
    try {
      await keurWeekGoed(item.administratie_id, item.weekstaat_id)
      naAkkoord()
    } catch (err) {
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(false)
    }
  }

  const dagen = weekDagen(item.jaar, item.weeknummer)
  const dagPer = new Map((staat?.dagen ?? []).map((d) => [d.datum, d]))

  return (
    <div>
      <Terug label="Te keuren" onClick={terug} />
      <div className="acc-seclabel">
        {item.zzper_naam ?? "ZZP'er"} · week {item.weeknummer} · {item.project_naam ?? 'project'}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {staat === null && !fout && <Leeg tekst="Laden…" />}
      {staat !== null && (
        <div className="acc-card">
          {dagen
            .filter(({ datum }) => dagPer.has(datum))
            .map(({ naam, datum }) => {
              const dag = dagPer.get(datum)!
              return (
                <div key={datum} className="acc-dagrij">
                  <span className="acc-dag">{naam}</span>
                  <span className="acc-proj">
                    {dag.opmerking ?? '—'}
                    {dag.namens && <small>ingevuld door {dag.ingevuld_door_naam ?? 'detacheerder'} (namens)</small>}
                    {/* Planning-toetsbron (besluit 22-08): oranje signaal, nooit een blokkade. */}
                    {dag.buiten_planning && <small style={{ color: 'var(--acc-warn, #e5a04c)' }}>⚠ buiten planning</small>}
                    {/* 18-09 blok B: de keurder ziet de doorfactureren-keuze per regel. */}
                    {dag.doorfactureren === false && <small className="acc-chip wacht">niet doorfactureren</small>}
                    {/* Geofence-stempels (blok C 28-08, mockup §3): gestempelde aanwezigheid + toets —
                        oranje vlag bij > 1,0 u afwijking, "onvolledig paar" gemarkeerd; geen stempels =
                        de toets zwijgt (net als een dag zonder planning). Nooit een korting. */}
                    {(() => {
                      const label = gestempeldLabel(dag)
                      const toets = stempelToets(dag)
                      if (label === null) {
                        return <small style={{ color: 'var(--acc-muted)' }}>📍 {toets.tekst}</small>
                      }
                      return (
                        <small
                          data-testid={`stempel-${dag.datum}`}
                          style={{ color: toets.soort === 'vlag' ? 'var(--acc-orange)' : 'var(--acc-muted)' }}
                        >
                          📍 {label} · {toets.soort === 'ok' ? '✓' : '⚑'} {toets.tekst}
                        </small>
                      )
                    })()}
                    {/* A6 (25-08): >N uur per dag over álle weekstaten — signaal, geen blokkade. */}
                    {dag.boven_dagmax && (
                      <small style={{ color: 'var(--acc-orange)' }}>
                        ⚠ {Number(dag.dag_totaal_uren).toLocaleString('nl-NL')} u op deze dag over alle projecten (&gt; {Number(dag.dagmax_uren ?? 0).toLocaleString('nl-NL')} u)
                      </small>
                    )}
                  </span>
                  <span className="acc-u">{urenLabel(dag.uren, dag.m2)}</span>
                </div>
              )
            })}
          {staat.dagen.length === 0 && <Leeg tekst="Lege week ingediend — telt als 0 uur op dit project." />}
          <div className="acc-totbalk">
            <span className="acc-k">Totaal</span>
            <span>{weekTotaalLabel(staat.totaal_uren, staat.totaal_m2)}</span>
          </div>
          {Number(staat.totaal_uren_niet_doorfactureren ?? 0) > 0 && (
            <div className="acc-totbalk">
              <span className="acc-k">waarvan niet doorfactureren</span>
              <span>{weekTotaalLabel(staat.totaal_uren_niet_doorfactureren ?? '0', staat.totaal_m2_niet_doorfactureren ?? '0')}</span>
            </div>
          )}
        </div>
      )}
      {staat !== null && staat.meer_gebouwd_dan_geleverd && (
        <div className="acc-notitie waarschuw">
          <span>📦</span>
          <span>
            <b>Meer gebouwd dan geleverd</b>: op dit project is {Number(staat.m2_gebouwd_project ?? 0).toLocaleString('nl-NL')} m² gebouwd
            (incl. deze week) tegenover {Number(staat.m2_geleverd_project ?? 0).toLocaleString('nl-NL')} m² geleverd materiaal — controleer de
            m²; een signaal, geen blokkade.
          </span>
        </div>
      )}
      {staat !== null && staat.dagen.some((d) => d.boven_dagmax) && (
        <div className="acc-notitie waarschuw">
          <span>⚠️</span>
          <span>
            Dagen met meer dan {Number(staat.dagen.find((d) => d.boven_dagmax)?.dagmax_uren ?? 12).toLocaleString('nl-NL')} uur
            (over álle projecten samen) — controleer of dit klopt; een signaal, geen blokkade.
          </span>
        </div>
      )}
      {staat !== null && staat.dagen.some((d) => d.buiten_planning) && (
        <div className="acc-notitie waarschuw">
          <span>⚠️</span>
          <span>
            Dagen met <b>buiten planning</b>: uren op een dag/project waar het kantoor deze persoon niet gepland
            had — een signaal, geen blokkade (invallen en omplannen mag).
          </span>
        </div>
      )}
      {staat !== null && staat.dagen.some((d) => d.stempel_afwijking) && (
        <div className="acc-notitie waarschuw" data-testid="stempel-notitie">
          <span>📍</span>
          <span>
            Dagen waar de opgegeven uren méér dan 1 uur afwijken van de <b>gestempelde aanwezigheid</b> — informatie
            voor het gesprek of het correctievoorstel, nooit een automatische korting. Geen stempels ≠ verdacht.
          </span>
        </div>
      )}
      <div className="acc-notitie">
        <span>ℹ️</span>
        <span>
          Keuren gaat per <b>week</b> — dagen alleen ter controle; afkeuren = hele week terug met reden.
        </span>
      </div>
      <div className="acc-actionbar">
        <button className="acc-btn afwijs" disabled={bezig || staat === null} onClick={() => staat && naarAfwijzen(staat)}>
          Week afkeuren…
        </button>
        <button className="acc-btn groen" disabled={bezig || staat === null} onClick={() => void akkoord()}>
          {bezig ? 'Bezig…' : 'Week akkoord'}
        </button>
      </div>
    </div>
  )
}

/** Invoerstaat van één correctievoorstel-rij in het afkeurscherm (hybride keuring, 22-08). */
interface CorrectieInvoer {
  uren: string
  m2: string
  opmerking: string
}

function KeurAfwijsView({
  item,
  staat,
  vangFout,
  terug,
  naAfkeuren,
}: {
  item: TeKeurenItemDto
  staat: WeekstaatDto
  vangFout: (err: unknown) => string
  terug: () => void
  naAfkeuren: () => void
}) {
  const [reden, setReden] = useState('')
  const [correcties, setCorrecties] = useState<Record<string, CorrectieInvoer>>({})
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  // Alleen bestaande dagregels kunnen een voorstel dragen (backend-regel), in ma–zo-volgorde.
  const dagen = weekDagen(item.jaar, item.weeknummer)
    .map((d) => ({ ...d, dag: staat.dagen.find((x) => x.datum === d.datum) ?? null }))
    .filter((d): d is typeof d & { dag: NonNullable<(typeof d)['dag']> } => d.dag !== null)

  function zetCorrectie(datum: string, deel: Partial<CorrectieInvoer>) {
    setCorrecties((huidig) => {
      const basis = huidig[datum] ?? { uren: '', m2: '', opmerking: '' }
      return { ...huidig, [datum]: { ...basis, ...deel } }
    })
  }

  function alsPayload(): DagCorrectieInvoer[] {
    return Object.entries(correcties)
      .map(([datum, c]) => ({
        datum,
        uren: c.uren.trim() === '' ? null : c.uren.replace(',', '.'),
        m2: c.m2.trim() === '' ? null : c.m2.replace(',', '.'),
        opmerking: c.opmerking.trim() === '' ? null : c.opmerking.trim(),
      }))
      .filter((c) => c.uren !== null || c.m2 !== null || c.opmerking !== null)
  }

  async function afkeuren() {
    setBezig(true)
    setFout(null)
    try {
      await keurWeekAf(item.administratie_id, item.weekstaat_id, reden.trim(), alsPayload())
      naAfkeuren()
    } catch (err) {
      const tekst = vangFout(err)
      if (tekst) setFout(tekst)
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <Terug label="Urenstaat" onClick={terug} />
      <div className="acc-seclabel">Week {item.weeknummer} afkeuren — reden verplicht</div>
      <div className="acc-card">
        <label className="acc-form">
          Reden (verplicht — gaat naar {item.zzper_naam ?? "de ZZP'er"})
          <textarea
            rows={4}
            style={{ resize: 'vertical', minHeight: 96, lineHeight: 1.5 }}
            placeholder="bijv. wachttijd wo niet akkoord — vooraf melden"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
          />
        </label>
        <div className="acc-notitie">
          <span>↩️</span>
          <span>
            De hele week gaat terug naar {item.zzper_naam ?? "de ZZP'er"} als "corrigeren"; hij dient zelf opnieuw in.
          </span>
        </div>
        {fout && <FoutRegel tekst={fout} />}
      </div>
      {dagen.length > 0 && (
        <div className="acc-card">
          <div className="acc-seclabel" style={{ margin: '0 0 6px' }}>
            Correctievoorstel per dag (optioneel)
          </div>
          {dagen.map(({ naam, datum, dag }) => (
            <div key={datum} className="acc-dagrij acc-correctierij">
              <span className="acc-dag">{naam}</span>
              <span className="acc-proj">
                <small>ingediend: {urenLabel(dag.uren, dag.m2)}</small>
              </span>
              <input
                type="number"
                inputMode="decimal"
                className="acc-correctie-input"
                placeholder="uren"
                aria-label={`Voorstel uren ${naam}`}
                value={correcties[datum]?.uren ?? ''}
                onChange={(e) => zetCorrectie(datum, { uren: e.target.value })}
              />
              <input
                type="number"
                inputMode="decimal"
                className="acc-correctie-input"
                placeholder="m²"
                aria-label={`Voorstel m² ${naam}`}
                value={correcties[datum]?.m2 ?? ''}
                onChange={(e) => zetCorrectie(datum, { m2: e.target.value })}
              />
              <input
                type="text"
                className="acc-correctie-opmerking"
                placeholder="opmerking"
                aria-label={`Voorstel opmerking ${naam}`}
                value={correcties[datum]?.opmerking ?? ''}
                onChange={(e) => zetCorrectie(datum, { opmerking: e.target.value })}
              />
            </div>
          ))}
          <div className="acc-notitie">
            <span>✏️</span>
            <span>
              Jouw voorstel wijzigt níéts zelf — {item.zzper_naam ?? "de ZZP'er"} ziet het letterlijk in zijn
              corrigeer-scherm en dient zelf opnieuw in.
            </span>
          </div>
        </div>
      )}
      <div className="acc-actionbar">
        <button className="acc-btn afwijs" disabled={bezig || reden.trim() === ''} onClick={() => void afkeuren()}>
          {bezig ? 'Bezig…' : 'Week afkeuren en terugsturen'}
        </button>
      </div>
    </div>
  )
}
