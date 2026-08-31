// Uren & meerwerk — veldkant in de bestaande app (fase 4, mockup/uren-uitvoerder.html 1-op-1,
// BOUW GO Peter 2026-08-21). Drie rollen, rolafhankelijke functietabs:
//  - ZZP'er: mijn projecten → open weken → weekstaat (dagen: uren + optionele m²) → indienen
//    per week; "Ingediend" toont de statussen over alle projecten heen.
//  - Uitvoerder: projecten (specs, contract/offerte alleen-lezen, meerwerk melden zonder
//    prijzen) én "Te keuren" — keuring op WEEKNIVEAU: week akkoord óf week afkeuren met
//    verplichte reden (hele week terug naar de ZZP'er als "corrigeren").
//  - Detacheerder: mijn ZZP'ers → daarna exact dezelfde schermen als de ZZP'er zelf, mét
//    "· namens <ZZP'er>" in de kopregel; geen projectinhoud.
// Dit bestand hoort bij de accordeur-chunk: geen kantoor-imports (performance-budget).

import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { haalMijnAdministraties, isVoorwaardenVereist } from '../accordeur/accordeurApi'
import { PdfWeergave } from '../accordeur/PdfWeergave'
import { VoorwaardenScherm } from '../accordeur/VoorwaardenScherm'
import { useAuth } from '../auth/AuthContext'
import { UitlogIcoon } from '../accordeur/UitlogIcoon'
import {
  beantwoordMeerwerkVraag,
  datumKort,
  datumMetTijd,
  dienWeekIn,
  eenheidLabel,
  EENHEDEN,
  haalIngediend,
  haalMijnPlanning,
  haalMijnZzpers,
  haalProjectDetail,
  haalProjectDocumentBlob,
  haalTeKeuren,
  haalUitvoerderProjecten,
  haalWeekstaat,
  haalZzpProjecten,
  haalZzpWeken,
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
  zetDag,
  type DagCorrectieInvoer,
  type IngediendeWeekDto,
  type MeerwerkDto,
  type MijnPlanningDagDto,
  type ProjectDetailDto,
  type ProjectDocumentKaartDto,
  type ProjectKaartDto,
  type TeKeurenItemDto,
  type UitvoerderProjectKaartDto,
  type WeekKaartDto,
  type WeekstaatDto,
  type ZzperKaartDto,
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

interface WeekContext {
  administratieId: string
  projectId: string
  projectNaam: string | null
  jaar: number
  weeknummer: number
}

type Scherm =
  | { s: 'zzpProjecten' }
  | { s: 'zzpWeken'; project: ProjectKaartDto }
  | { s: 'weekstaat'; ctx: WeekContext; terug: Scherm }
  | { s: 'daginvoer'; ctx: WeekContext; datum: string; dagNaam: string; bestaand: WeekstaatDto['dagen'][number] | null; terug: Scherm }
  | { s: 'ingediend' }
  | { s: 'planning' }
  | { s: 'dossier'; terug: Scherm }
  | { s: 'detaZzpers' }
  | { s: 'uitvProjecten' }
  | { s: 'projectdetail'; kaart: UitvoerderProjectKaartDto }
  | { s: 'contract'; kaart: UitvoerderProjectKaartDto; doc: ProjectDocumentKaartDto }
  | { s: 'meerwerkMelden'; kaart: UitvoerderProjectKaartDto }
  | { s: 'meerwerkVraag'; kaart: UitvoerderProjectKaartDto; melding: MeerwerkDto }
  | { s: 'keurlijst' }
  | { s: 'keurdetail'; item: TeKeurenItemDto }
  | { s: 'keurafwijs'; item: TeKeurenItemDto; staat: WeekstaatDto }

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
      return { klasse: 'afgekeurd', label: 'corrigeren' }
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

export function UrenFlow({ wisselThema, uitloggen }: { wisselThema: () => void; uitloggen: () => Promise<void> }) {
  const { rol } = useAuth()
  const veldrol = rol as Veldrol
  const [scherm, setScherm] = useState<Scherm>(() =>
    veldrol === 'uitvoerder' ? { s: 'uitvProjecten' } : veldrol === 'detacheerder' ? { s: 'detaZzpers' } : { s: 'zzpProjecten' },
  )
  // Detacheerder-namens-context (besluit 21-08): ná de ZZP'er-keuze exact de ZZP-schermen,
  // elk scherm draagt "· namens <ZZP'er>" en elke invoer wordt als "X namens Y" vastgelegd.
  const [namens, setNamens] = useState<{ id: string; naam: string } | null>(null)
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
        onClick={() => setScherm({ s: 'zzpProjecten' })}
      >
        ⏱ Mijn projecten
      </button>
      <button
        className={`acc-functab${scherm.s === 'planning' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'planning' })}
      >
        📅 Planning
      </button>
      <button
        className={`acc-functab${scherm.s === 'ingediend' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'ingediend' })}
      >
        ✓ Ingediend
      </button>
    </div>
  )
  const uitvTabs = (
    <div className="acc-functabs">
      <button
        className={`acc-functab${scherm.s !== 'keurlijst' && scherm.s !== 'keurdetail' && scherm.s !== 'keurafwijs' && scherm.s !== 'planning' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'uitvProjecten' })}
      >
        🏗 Projecten
      </button>
      <button
        className={`acc-functab${scherm.s === 'planning' ? ' actief' : ''}`}
        onClick={() => setScherm({ s: 'planning' })}
      >
        📅 Planning
      </button>
      <button
        className={`acc-functab${scherm.s === 'keurlijst' || scherm.s === 'keurdetail' || scherm.s === 'keurafwijs' ? ' actief' : ''}`}
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
          <button className="acc-iconbtn" title="Uitloggen" onClick={() => void uitloggen()}>
            <UitlogIcoon />
          </button>
        </div>
      </div>

      {veldrol === 'zzper' && zzpTabs}
      {veldrol === 'uitvoerder' && uitvTabs}
      {veldrol === 'detacheerder' && detaTabs}

      <div className="acc-content">
        {scherm.s === 'zzpProjecten' && (
          <ZzpProjectenView
            namens={namens}
            vangFout={vangFout}
            terugNaarZzpers={veldrol === 'detacheerder' ? () => { setNamens(null); setScherm({ s: 'detaZzpers' }) } : null}
            openProject={(project) => setScherm({ s: 'zzpWeken', project })}
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
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={veldrol === 'detacheerder' ? () => setScherm({ s: 'zzpProjecten' }) : null}
          />
        )}
        {scherm.s === 'zzpWeken' && (
          <ZzpWekenView
            project={scherm.project}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={() => setScherm({ s: 'zzpProjecten' })}
            openWeek={(week) =>
              setScherm({
                s: 'weekstaat',
                ctx: {
                  administratieId: scherm.project.administratie_id,
                  projectId: scherm.project.project_id,
                  projectNaam: scherm.project.project_naam,
                  jaar: week.jaar,
                  weeknummer: week.weeknummer,
                },
                terug: scherm,
              })
            }
          />
        )}
        {scherm.s === 'weekstaat' && (
          <WeekstaatView
            ctx={scherm.ctx}
            namens={namens}
            namensSuffix={namensSuffix}
            vangFout={vangFout}
            terug={() => setScherm(scherm.terug)}
            openDag={(datum, dagNaam, bestaand) =>
              setScherm({ s: 'daginvoer', ctx: scherm.ctx, datum, dagNaam, bestaand, terug: scherm })
            }
            naIndienen={() => {
              toon('Week ingediend — de uitvoerder keurt de hele week.')
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
              setScherm({ s: 'zzpProjecten' })
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
            terug={() => setScherm({ s: 'projectdetail', kaart: scherm.kaart })}
            naMelden={() => {
              toon('Meerwerk gemeld — het kantoor toetst en prijst de melding.')
              setScherm({ s: 'projectdetail', kaart: scherm.kaart })
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

function ZzpProjectenView({
  namens,
  vangFout,
  terugNaarZzpers,
  openProject,
  openPlanning,
  dossierKaart,
}: {
  namens: { id: string; naam: string } | null
  vangFout: (err: unknown) => string
  terugNaarZzpers: (() => void) | null
  openProject: (project: ProjectKaartDto) => void
  /** Detacheerder-namens-flow: de planning van de gekozen ZZP'er (alleen-lezen, besluit B). */
  openPlanning: (() => void) | null
  /** ZZP-dossier (A1): statuskaart + ingang naar upload (ook namens door de detacheerder). */
  dossierKaart?: React.ReactNode
}) {
  const [projecten, setProjecten] = useState<ProjectKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalZzpProjecten(namens?.id ?? null)
      .then(setProjecten)
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
      <div className="acc-seclabel">
        {namens ? `${namens.naam} · projecten` : `Mijn projecten${projecten ? ` (${projecten.length})` : ''}`}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {projecten === null && !fout && <Leeg tekst="Laden…" />}
      {projecten !== null && projecten.length === 0 && (
        <Leeg tekst="Nog geen projecten gekoppeld — het kantoor koppelt je aan een project." />
      )}
      {(projecten ?? []).map((p) => (
        <button key={`${p.administratie_id}-${p.project_id}`} className="acc-card klik" onClick={() => openProject(p)}>
          <span>
            <span className="acc-tt">{p.project_naam ?? 'Project'}</span>
            <span className="acc-meta" style={{ display: 'block' }}>
              {p.soort_werk ?? 'steigerbouw'} · laatste invoer: {datumMetWeek(p.laatste_invoer)}
            </span>
          </span>
          {p.open_weken > 0 ? (
            <span className="acc-chip open">{p.open_weken === 1 ? '1 week open' : `${p.open_weken} weken open`}</span>
          ) : (
            <span className="acc-chip akkoord">bij</span>
          )}
        </button>
      ))}
    </div>
  )
}

function ZzpWekenView({
  project,
  namens,
  namensSuffix,
  vangFout,
  terug,
  openWeek,
}: {
  project: ProjectKaartDto
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: () => void
  openWeek: (week: WeekKaartDto) => void
}) {
  const [weken, setWeken] = useState<WeekKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalZzpWeken(project.administratie_id, project.project_id, namens?.id ?? null)
      .then(setWeken)
      .catch((err) => setFout(vangFout(err) || null))
  }, [project, namens, vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  function meta(week: WeekKaartDto): string {
    switch (week.status) {
      case 'nieuw':
        return '0 dagen ingevuld (vakantie? meld 0-uren)'
      case 'concept':
        return `${week.dagen_ingevuld} ${week.dagen_ingevuld === 1 ? 'dag' : 'dagen'} ingevuld · ${weekTotaalLabel(week.totaal_uren, week.totaal_m2)}`
      case 'ingediend':
        return `ingediend ${datumMetTijd(week.ingediend_op)} · wacht op de uitvoerder`
      case 'goedgekeurd':
        return `goedgekeurd${week.goedgekeurd_door_naam ? ` door ${week.goedgekeurd_door_naam}` : ''} · ${weekTotaalLabel(week.totaal_uren, week.totaal_m2)}`
      case 'corrigeren':
        return `week afgekeurd${week.afgekeurd_door_naam ? ` door ${week.afgekeurd_door_naam}` : ''} — tik voor toelichting`
    }
  }

  return (
    <div>
      <Terug label={namens ? `${namens.naam} · projecten` : 'Mijn projecten'} onClick={terug} />
      <div className="acc-seclabel">
        {project.project_naam ?? 'Project'} · weken{namensSuffix}
      </div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {weken === null && !fout && <Leeg tekst="Laden…" />}
      {(weken ?? []).map((week) => {
        const chip = chipVoorWeekStatus(week.status)
        return (
          <button key={`${week.jaar}-${week.weeknummer}`} className="acc-card klik" onClick={() => openWeek(week)}>
            <span>
              <span className="acc-tt">
                Week {week.weeknummer}{' '}
                <small style={{ color: 'var(--acc-muted)', fontWeight: 500 }}>
                  {datumKort(week.maandag)} – {datumKort(week.zondag)}
                </small>
              </span>
              <span className="acc-meta" style={{ display: 'block' }}>
                {meta(week)}
              </span>
            </span>
            <span className={`acc-chip ${chip.klasse}`}>{chip.label}</span>
          </button>
        )
      })}
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
  openDag: (datum: string, dagNaam: string, bestaand: WeekstaatDto['dagen'][number] | null) => void
  naIndienen: () => void
  openDossier: () => void
}) {
  const [staat, setStaat] = useState<WeekstaatDto | null | 'nieuw'>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  // Dossier-handhaving (A2): 423 = indienen geblokkeerd — melding + upload-ingang, uren blijven staan.
  const [geblokkeerd, setGeblokkeerd] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    // De weekstaat bestaat pas ná de eerste daginvoer — zoek 'm via het wekenoverzicht.
    haalZzpWeken(ctx.administratieId, ctx.projectId, namens?.id ?? null)
      .then(async (weken) => {
        const week = weken.find((w) => w.jaar === ctx.jaar && w.weeknummer === ctx.weeknummer)
        if (!week || week.weekstaat_id === null) {
          setStaat('nieuw')
          return
        }
        setStaat(await haalWeekstaat(ctx.administratieId, week.weekstaat_id))
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
      <Terug label={ctx.projectNaam ?? 'Project'} onClick={terug} />
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
        Week {ctx.weeknummer} · {datumKort(dagen[0].datum)} – {datumKort(dagen[6].datum)}
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
                    <button className="acc-plus" onClick={() => openDag(datum, naam, null)}>
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
                </span>
                <span className="acc-u">{urenLabel(dag.uren, dag.m2)}</span>
                {muteerbaar && (
                  <button className="acc-plus" onClick={() => openDag(datum, naam, dag)}>
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

function DagInvoerView({
  ctx,
  datum,
  dagNaam,
  bestaand,
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
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: () => void
  naOpslaan: () => void
}) {
  const [uren, setUren] = useState(bestaand?.uren ?? '')
  const [m2, setM2] = useState(bestaand?.m2 ?? '')
  const [opmerking, setOpmerking] = useState(bestaand?.opmerking ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

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
        m2: m2.trim() === '' ? null : m2.replace(',', '.'),
        opmerking: opmerking.trim() === '' ? null : opmerking.trim(),
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
        <div className="acc-duo">
          <label className="acc-form">
            Uren
            <input type="number" inputMode="decimal" placeholder="8,0" value={uren} onChange={(e) => setUren(e.target.value)} />
          </label>
          <label className="acc-form">
            m² gebouwd (optioneel)
            <input type="number" inputMode="decimal" placeholder="0" value={m2 ?? ''} onChange={(e) => setM2(e.target.value)} />
          </label>
        </div>
        <label className="acc-form">
          Opmerking (optioneel)
          <input type="text" placeholder="bijv. wachttijd i.v.m. levering" value={opmerking} onChange={(e) => setOpmerking(e.target.value)} />
        </label>
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
                  if (bestaand.voorstel_m2 !== null) setM2(bestaand.voorstel_m2)
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
        <button className="acc-btn groen" disabled={bezig || uren.trim() === ''} onClick={() => void opslaan()}>
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

function MijnPlanningView({
  namens,
  namensSuffix,
  vangFout,
  terug,
}: {
  namens: { id: string; naam: string } | null
  namensSuffix: React.ReactNode
  vangFout: (err: unknown) => string
  terug: (() => void) | null
}) {
  const [week, setWeek] = useState(() => isoWeekVan(new Date()))
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

function DetaZzpersView({ vangFout, kies }: { vangFout: (err: unknown) => string; kies: (zzper: ZzperKaartDto) => void }) {
  const [zzpers, setZzpers] = useState<ZzperKaartDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    setFout(null)
    haalMijnZzpers()
      .then(setZzpers)
      .catch((err) => setFout(vangFout(err) || null))
  }, [vangFout])
  useEffect(() => {
    laad()
  }, [laad])

  return (
    <div>
      <div className="acc-seclabel">Mijn ZZP'ers{zzpers ? ` (${zzpers.length})` : ''}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {zzpers === null && !fout && <Leeg tekst="Laden…" />}
      {zzpers !== null && zzpers.length === 0 && (
        <Leeg tekst="Nog geen ZZP'ers gekoppeld — het kantoor beheert de koppelingen." />
      )}
      {(zzpers ?? []).map((zzper) => (
        <button key={zzper.gebruiker_id} className="acc-card klik" onClick={() => kies(zzper)}>
          <span>
            <span className="acc-tt">{zzper.naam}</span>
            <span className="acc-meta" style={{ display: 'block' }}>
              {zzper.aantal_projecten} {zzper.aantal_projecten === 1 ? 'project' : 'projecten'} · laatste invoer{' '}
              {datumKort(zzper.laatste_invoer)}
            </span>
          </span>
          {zzper.open_weken > 0 ? (
            <span className="acc-chip open">
              {zzper.open_weken === 1 ? '1 week open' : `${zzper.open_weken} weken open`}
            </span>
          ) : (
            <span className="acc-chip akkoord">bij</span>
          )}
        </button>
      ))}
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

  return (
    <div>
      <div className="acc-seclabel">Lopende projecten{projecten ? ` (${projecten.length})` : ''}</div>
      {fout && <FoutRegel tekst={fout} onOpnieuw={laad} />}
      {projecten === null && !fout && <Leeg tekst="Laden…" />}
      {projecten !== null && projecten.length === 0 && (
        <Leeg tekst="Nog geen projecten gekoppeld — het kantoor koppelt je als uitvoerder aan projecten." />
      )}
      {(projecten ?? []).map((kaart) => (
        <button key={`${kaart.administratie_id}-${kaart.project_id}`} className="acc-card klik" onClick={() => openProject(kaart)}>
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
  kaart: UitvoerderProjectKaartDto
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
