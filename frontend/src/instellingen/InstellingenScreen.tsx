import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Checkbox, Select, Switch } from '../ui/basis'
import type { AdministratieInstellingenDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { haalIbanAccordeursOp, zetIbanAccordeurs } from '../document/ibanAccorderingApi'
import { DoorbelastingInstellingen } from '../doorbelasting/DoorbelastingInstellingen'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { AccorderingInstellingen } from './AccorderingInstellingen'
import { BevestigDialog } from './BevestigDialog'
import { BeveiligingInstellingen } from './BeveiligingInstellingen'
import { LeverancierAutoboeken } from './LeverancierAutoboeken'
import {
  haalAiKostenStatusOp,
  haalBoekenKillSwitchOp,
  haalInstellingenAdministratiesOp,
  haalIntakeAiInstellingOp,
  zetAiExtractieInstelling,
  zetAiKostenLimiet,
  zetBoekenInstelling,
  zetBoekenKillSwitch,
  zetEigenaar,
  zetIntakeAiInstelling,
  zetProjectInstelling,
  type AiKostenStatusDto,
} from './instellingenApi'

type WijzigingType =
  | 'kill_switch'
  | 'intake_ai'
  | 'boeken'
  | 'project'
  | 'ai_extractie'
  | 'eigenaar'
  | 'iban_accordeurs'
  | 'ai_kosten_limiet'

interface PendingWijziging {
  type: WijzigingType
  administratieId?: string
  naam: string
  nieuweWaarde: boolean
  /** Alleen voor type 'eigenaar' (mockup Instellingen "Eigenaar (krijgt vragen)"). */
  eigenaarId?: string | null
  eigenaarNaam?: string
  /** Alleen voor type 'iban_accordeurs': de volledige nieuwe accordeur-set + leesbare
   * omschrijving van de wijziging (vier-ogen-flow, docs/ontwerp/iban-wissel-accordering.md). */
  accordeurs?: string[]
  accordeursOmschrijving?: string
  /** Alleen voor type 'ai_kosten_limiet': de nieuwe maandlimiet in EUR (string, Decimal-precisie). */
  limietEur?: string
}

function berichtVoor(pending: PendingWijziging): string {
  switch (pending.type) {
    case 'kill_switch':
      return pending.nieuweWaarde
        ? 'Boeken wordt platformbreed weer mogelijk (nog steeds ook afhankelijk van de boeken-toggle per administratie).'
        : 'Boeken wordt voor ALLE administraties direct stopgezet, ongeacht de toggle per administratie.'
    case 'intake_ai':
      return pending.nieuweWaarde
        ? 'Nog-niet-toegewezen intake-PDF\'s (verzamelbak) gaan voortaan voor tenaamstelling en splitsingsdetectie naar de Claude API (platform-brede AVG-gate). Echte klantdocumenten pas ná DPA + EU-verwerking + verwerkersregister — zie docs/BOUWPLAN.md.'
        : 'Intake-AI wordt uitgeschakeld — élke niet-eenduidige PDF valt weer zichtbaar in de verzamelbak en wordt handmatig toegewezen.'
    case 'boeken':
      return pending.nieuweWaarde
        ? `Boeken wordt ingeschakeld voor "${pending.naam}".`
        : `Boeken wordt uitgeschakeld voor "${pending.naam}".`
    case 'project':
      return pending.nieuweWaarde
        ? `Project wordt verplicht bij boeken voor "${pending.naam}" — regels zonder project blokkeren dan het boeken.`
        : `Project is niet langer verplicht bij boeken voor "${pending.naam}".`
    case 'ai_extractie':
      return pending.nieuweWaarde
        ? `PDF's van "${pending.naam}" gaan voortaan voor extractie naar de Claude API (AVG-gate). Echte klantfacturen pas ná DPA + EU-verwerking + verwerkersregister — zie docs/BOUWPLAN.md.`
        : `AI-extractie wordt uitgeschakeld voor "${pending.naam}" — PDF's worden weer volledig handmatig ingevuld.`
    case 'eigenaar':
      return pending.eigenaarId
        ? `${pending.eigenaarNaam ?? 'Deze medewerker'} wordt eigenaar van "${pending.naam}" en krijgt nieuwe vragen standaard toegewezen.`
        : `"${pending.naam}" krijgt geen eigenaar — een vraag stellen vereist dan een expliciete toewijzing.`
    case 'iban_accordeurs':
      return `${pending.accordeursOmschrijving ?? 'De IBAN-accordeurs worden gewijzigd'} voor "${pending.naam}".${
        (pending.accordeurs?.length ?? 0) === 0
          ? ' Zonder ingestelde accordeurs vallen IBAN-wissels terug op de beheerder(s).'
          : ''
      }`
    case 'ai_kosten_limiet':
      return `De AI-kosten-maandlimiet wordt € ${pending.limietEur ?? '?'} per kalendermaand. Boven de limiet wordt AI-verwerking geblokkeerd en volgen documenten het handmatige pad.`
  }
}

async function voerWijzigingUit(pending: PendingWijziging): Promise<void> {
  // Alle paden via instellingenApi.ts/ibanAccorderingApi.ts — nooit losse fetch-paden in het
  // scherm (guard-test: instellingenApi.test.ts).
  if (pending.type === 'kill_switch') {
    await zetBoekenKillSwitch(pending.nieuweWaarde)
    return
  }
  if (pending.type === 'intake_ai') {
    await zetIntakeAiInstelling(pending.nieuweWaarde)
    return
  }
  if (pending.type === 'boeken') {
    await zetBoekenInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'ai_extractie') {
    await zetAiExtractieInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'eigenaar') {
    await zetEigenaar(pending.administratieId ?? '', pending.eigenaarId ?? null)
    return
  }
  if (pending.type === 'iban_accordeurs') {
    await zetIbanAccordeurs(pending.administratieId ?? '', pending.accordeurs ?? [])
    return
  }
  if (pending.type === 'ai_kosten_limiet') {
    await zetAiKostenLimiet(pending.limietEur ?? '')
    return
  }
  await zetProjectInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
}

interface EigenaarCellProps {
  administratie: AdministratieInstellingenDto
  onKies: (eigenaarId: string | null, eigenaarNaam: string | undefined) => void
}

/** Eigenaar-select per administratie (mockup Instellingen "Eigenaar (krijgt vragen)"): de
 * toewijsbare medewerkers komen per rij uit het scope-gecontroleerde medewerkers-endpoint. */
function EigenaarCell({ administratie, onKies }: EigenaarCellProps) {
  const { medewerkers, fout } = useMedewerkers(administratie.id)
  if (fout) return <span className="hint" style={{ margin: 0 }}>medewerkers niet te laden</span>
  return (
    <Select
      aria-label={`Eigenaar van ${administratie.naam}`}
      value={administratie.eigenaar_gebruiker_id ?? ''}
      disabled={!medewerkers}
      onChange={(e) => {
        const id = e.target.value || null
        onKies(id, medewerkers?.find((m) => m.id === id)?.naam)
      }}
    >
      <option value="">— geen eigenaar —</option>
      {(medewerkers ?? []).map((m) => (
        <option key={m.id} value={m.id}>
          {m.naam}
        </option>
      ))}
    </Select>
  )
}

interface IbanAccordeursCellProps {
  administratie: AdministratieInstellingenDto
  /** Bump na een geslaagde wijziging: de cel herlaadt dan zijn set van de backend. */
  versie: number
  onWijzig: (nieuweSet: string[], omschrijving: string) => void
}

/** Instelling "IBAN-wissel accorderen door" (vier-ogen-flow, docs/ontwerp/
 * iban-wissel-accordering.md): één of meer medewerkers binnen de scope; elke aan/uit is één
 * bevestigde wijziging (PUT met de volledige nieuwe set). Lege set → zichtbaar terugvallen op
 * de beheerder(s). */
function IbanAccordeursCell({ administratie, versie, onWijzig }: IbanAccordeursCellProps) {
  const { medewerkers, fout: medewerkersFout } = useMedewerkers(administratie.id)
  const [accordeurs, setAccordeurs] = useState<string[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    haalIbanAccordeursOp(administratie.id)
      .then((dto) => setAccordeurs(dto.accordeurs))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratie.id, versie])

  if (fout || medewerkersFout) {
    return (
      <span className="hint" style={{ margin: 0 }}>
        accordeurs niet te laden
      </span>
    )
  }
  if (accordeurs === null || !medewerkers) {
    return (
      <span className="hint" style={{ margin: 0 }}>
        Laden…
      </span>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {medewerkers.map((m) => {
        const ingesteld = accordeurs.includes(m.id)
        return (
          <label key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12.5 }}>
            <Checkbox
              checked={ingesteld}
              onChange={(e) => {
                const nieuweSet = e.target.checked
                  ? [...accordeurs, m.id]
                  : accordeurs.filter((id) => id !== m.id)
                onWijzig(
                  nieuweSet,
                  e.target.checked
                    ? `${m.naam} wordt IBAN-accordeur`
                    : `${m.naam} is niet langer IBAN-accordeur`,
                )
              }}
            />
            {m.naam}
          </label>
        )
      })}
      {accordeurs.length === 0 && (
        <span className="hint" style={{ margin: 0 }}>
          geen accordeurs ingesteld — valt terug op de beheerder(s)
        </span>
      )}
    </div>
  )
}

export function InstellingenScreen() {
  const { rol, status } = useAuth()

  const [administraties, setAdministraties] = useState<AdministratieInstellingenDto[] | null>(null)
  const [accordeursVersie, setAccordeursVersie] = useState(0)
  const [killSwitch, setKillSwitch] = useState<boolean | null>(null)
  const [intakeAi, setIntakeAi] = useState<boolean | null>(null)
  const [aiKosten, setAiKosten] = useState<AiKostenStatusDto | null>(null)
  const [limietInvoer, setLimietInvoer] = useState('')
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)

  const laadAlles = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      haalInstellingenAdministratiesOp(),
      haalBoekenKillSwitchOp(),
      haalIntakeAiInstellingOp(),
      haalAiKostenStatusOp(),
    ])
      .then(([lijst, switchDto, intakeAiDto, aiKostenDto]) => {
        setAdministraties(lijst.administraties)
        setKillSwitch(switchDto.ingeschakeld)
        setIntakeAi(intakeAiDto.ingeschakeld)
        setAiKosten(aiKostenDto)
        setLimietInvoer(aiKostenDto.limiet_eur)
      })
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [])

  useEffect(() => {
    if (rol === 'beheerder') laadAlles()
  }, [rol, laadAlles])

  // Backend dwingt dit al af op elk endpoint hieronder — dit is de UI-kant. Sinds de
  // kantoor-passkeys (besluit 0020) is Instellingen voor élke kantoor-rol bereikbaar, maar een
  // niet-Beheerder ziet uitsluitend de Beveiliging-sectie (eigen passkeys) — de beheer-secties
  // renderen niet eens (design-pass taak 3: geen kale 403 of lege tabel). Wacht op `status`
  // (niet alleen `rol`) zodat dit ook correct is los van App.tsx's status==='laden'-gate.
  if (status === 'laden') {
    return <p className="hint">Laden…</p>
  }
  const isBeheerder = rol === 'beheerder'
  if (!isBeheerder) {
    return (
      <div>
        <div className="topbar">
          <h1>Instellingen</h1>
        </div>
        <BeveiligingInstellingen isBeheerder={false} />
      </div>
    )
  }

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      await voerWijzigingUit(pending)
      if (pending.type === 'kill_switch') {
        setKillSwitch(pending.nieuweWaarde)
      } else if (pending.type === 'intake_ai') {
        setIntakeAi(pending.nieuweWaarde)
      } else if (pending.type === 'ai_kosten_limiet') {
        // Verse status ophalen: percentage/blokkade hangen van de nieuwe limiet af.
        haalAiKostenStatusOp()
          .then((dto) => {
            setAiKosten(dto)
            setLimietInvoer(dto.limiet_eur)
          })
          .catch(() => undefined)
      } else if (pending.type === 'iban_accordeurs') {
        setAccordeursVersie((v) => v + 1)
      } else {
        setAdministraties(
          (huidig) =>
            huidig?.map((a) =>
              a.id === pending.administratieId
                ? {
                    ...a,
                    ...(pending.type === 'boeken'
                      ? { boeken_ingeschakeld: pending.nieuweWaarde }
                      : pending.type === 'ai_extractie'
                        ? { ai_extractie_ingeschakeld: pending.nieuweWaarde }
                        : pending.type === 'eigenaar'
                          ? { eigenaar_gebruiker_id: pending.eigenaarId ?? null }
                          : { project_verplicht: pending.nieuweWaarde }),
                  }
                : a,
            ) ?? null,
        )
      }
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <div className="topbar">
        <h1>Instellingen</h1>
      </div>

      <BeveiligingInstellingen isBeheerder />

      {laadFout && <div className="fout">Kon instellingen niet laden: {laadFout}</div>}

      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0 }}>Boeken — globale kill switch</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Platformbrede noodstop: staat deze uit, dan kan er nergens geboekt worden, ongeacht de toggle per
              administratie hieronder.
            </p>
          </div>
          {killSwitch !== null && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
              <Switch
                aria-label="Globale kill switch"
                checked={killSwitch}
                onChange={(e) =>
                  setPending({ type: 'kill_switch', naam: 'kill switch', nieuweWaarde: e.target.checked })
                }
              />
              {killSwitch ? 'aan' : 'uit'}
            </label>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0 }}>Intake-AI (AVG-gate, platform-breed)</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Bepaalt of nog-niet-toegewezen intake-PDF&apos;s (verzamelbak) voor tenaamstelling en
              multi-factuur-splitsingsdetectie naar de Claude API mogen. Staat los van de AI-extractie
              per administratie hieronder, die pas ná toewijzing geldt.
            </p>
          </div>
          {intakeAi !== null && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
              <Switch
                aria-label="Intake-AI ingeschakeld"
                checked={intakeAi}
                onChange={(e) =>
                  setPending({ type: 'intake_ai', naam: 'intake-AI', nieuweWaarde: e.target.checked })
                }
              />
              {intakeAi ? 'aan' : 'uit'}
            </label>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
          <div>
            <h2 style={{ margin: 0 }}>AI-kosten (maandlimiet)</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Wérkelijke Anthropic-API-kosten van intake-AI deze kalendermaand, deterministisch berekend uit de
              token-usage per aanroep. Boven de limiet wordt AI-verwerking geblokkeerd en volgen documenten het
              handmatige pad (&quot;AI-limiet bereikt — handmatig verwerken&quot;).
            </p>
            {aiKosten && (
              <p style={{ marginTop: 8, marginBottom: 0 }} data-testid="ai-kosten-verbruik">
                <strong>
                  {aiKosten.maand}: € {aiKosten.verbruik_eur} van € {aiKosten.limiet_eur} ({aiKosten.percentage}%)
                </strong>
                {aiKosten.limiet_bereikt ? (
                  <span style={{ color: 'var(--red)', marginLeft: 8 }}>
                    Limiet bereikt — AI-verwerking geblokkeerd tot de nieuwe maand of een hogere limiet.
                  </span>
                ) : aiKosten.waarschuwing_80 ? (
                  <span style={{ color: 'var(--orange, #b45309)', marginLeft: 8 }}>
                    Waarschuwing: 80% van de maandlimiet bereikt.
                  </span>
                ) : null}
              </p>
            )}
          </div>
          {aiKosten && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
              €
              <input
                type="number"
                aria-label="AI-kosten maandlimiet in euro"
                min="1"
                step="1"
                style={{ width: 90 }}
                value={limietInvoer}
                onChange={(e) => setLimietInvoer(e.target.value)}
              />
              <button
                type="button"
                disabled={!limietInvoer || Number(limietInvoer) <= 0 || limietInvoer === aiKosten.limiet_eur}
                onClick={() =>
                  setPending({ type: 'ai_kosten_limiet', naam: 'AI-kosten-maandlimiet', nieuweWaarde: true, limietEur: limietInvoer })
                }
              >
                Limiet wijzigen
              </button>
            </label>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2 style={{ marginTop: 0 }}>Administraties</h2>
        {administraties === null && !laadFout && <p className="hint">Laden…</p>}
        {administraties !== null && administraties.length === 0 && (
          <p className="hint">Nog geen administraties gekoppeld.</p>
        )}
        {administraties !== null && administraties.length > 0 && (
          <table>
            <tbody>
              <tr>
                <th>Administratie</th>
                <th>Eigenaar (krijgt vragen)</th>
                <th>IBAN-wissel accorderen door</th>
                <th>Project verplicht bij boeken</th>
                <th>Boeken ingeschakeld</th>
                <th>AI-extractie (AVG-gate)</th>
              </tr>
              {administraties.map((a) => (
                <tr key={a.id}>
                  <td>{a.naam}</td>
                  <td>
                    <EigenaarCell
                      administratie={a}
                      onKies={(eigenaarId, eigenaarNaam) =>
                        setPending({
                          type: 'eigenaar',
                          administratieId: a.id,
                          naam: a.naam,
                          nieuweWaarde: eigenaarId !== null,
                          eigenaarId,
                          eigenaarNaam,
                        })
                      }
                    />
                  </td>
                  <td>
                    <IbanAccordeursCell
                      administratie={a}
                      versie={accordeursVersie}
                      onWijzig={(nieuweSet, omschrijving) =>
                        setPending({
                          type: 'iban_accordeurs',
                          administratieId: a.id,
                          naam: a.naam,
                          nieuweWaarde: nieuweSet.length > 0,
                          accordeurs: nieuweSet,
                          accordeursOmschrijving: omschrijving,
                        })
                      }
                    />
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <Switch
                        aria-label={`Project verplicht voor ${a.naam}`}
                        checked={a.project_verplicht}
                        onChange={(e) =>
                          setPending({
                            type: 'project',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.project_verplicht ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <Switch
                        aria-label={`Boeken ingeschakeld voor ${a.naam}`}
                        checked={a.boeken_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'boeken',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.boeken_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <Switch
                        aria-label={`AI-extractie voor ${a.naam}`}
                        checked={a.ai_extractie_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'ai_extractie',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.ai_extractie_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {administraties !== null && (
        <AccorderingInstellingen administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}

      {administraties !== null && (
        <LeverancierAutoboeken administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}

      {administraties !== null && (
        <DoorbelastingInstellingen administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}

      {pending && (
        <BevestigDialog
          titel="Instelling wijzigen?"
          bericht={berichtVoor(pending)}
          bezig={bezig}
          fout={wijzigenFout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setWijzigenFout(null)
            setPending(null)
          }}
        />
      )}
    </div>
  )
}
