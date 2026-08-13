import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type {
  DoorbelastingInstellingDto,
  DoorbelastingInstellingInputDto,
  DoorbelastingMappingDto,
  DoorbelastingMappingWijzigingDto,
} from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { FoutMelding } from '../ui/FoutMelding'
import {
  haalDoorbelastingInstellingOp,
  haalDoorbelastingMappingsOp,
  haalDoorbelastingToggleOp,
  wijzigDoorbelastingMapping,
  zetDoorbelastingInstelling,
  zetDoorbelastingToggle,
} from './doorbelastingApi'
import { formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'

type PendingWijziging =
  | { type: 'toggle'; nieuweWaarde: boolean }
  | { type: 'instelling'; invoer: DoorbelastingInstellingInputDto }
  | {
      type: 'mapping'
      mappingId: string
      wijziging: DoorbelastingMappingWijzigingDto
      omschrijving: string
    }

/** Instellingen-sectie "Doorbelasting" (Kempen, blok 3 — patroon LeverancierAutoboeken):
 * toggle per administratie, bron-configuratie (provisie-%, vlak btw-tarief, omzet-GB's) en de
 * mapping-whitelist. Beheerder-only: de sectie leeft binnen de rol-gate van InstellingenScreen
 * en de backend geeft 403 voor andere rollen; elke wijziging vraagt bevestiging
 * (BevestigDialog) en staat in het audit log. */
export function DoorbelastingInstellingen({
  administraties,
}: {
  administraties: { id: string; naam: string }[]
}) {
  const [administratieId, setAdministratieId] = useState('')

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Doorbelasting (Kempen)</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Doorbelasten van geboekte inkoopfacturen aan groepsentiteiten: toggle per bron-administratie
        (default uit), provisie-instellingen en de server-side afgedwongen whitelist van
        doelentiteiten. Kies eerst een administratie.
      </p>
      <select
        aria-label="Administratie voor doorbelasting"
        style={{ width: 'auto' }}
        value={administratieId}
        onChange={(e) => setAdministratieId(e.target.value)}
      >
        <option value="">— kies administratie —</option>
        {administraties.map((a) => (
          <option key={a.id} value={a.id}>
            {a.naam}
          </option>
        ))}
      </select>
      {administratieId && (
        <DoorbelastingAdministratie
          key={administratieId}
          administratieId={administratieId}
          naam={administraties.find((a) => a.id === administratieId)?.naam ?? administratieId}
        />
      )}
    </div>
  )
}

function berichtVoor(pending: PendingWijziging, naam: string): string {
  switch (pending.type) {
    case 'toggle':
      return pending.nieuweWaarde
        ? `Doorbelasting wordt ingeschakeld voor "${naam}" — op geboekte inkoopfacturen verschijnt dan de actie "Doorbelasten…".`
        : `Doorbelasting wordt uitgeschakeld voor "${naam}" — bestaande boekingen blijven staan, nieuwe doorbelastingen kunnen niet meer gestart worden.`
    case 'instelling':
      return (
        `De doorbelasting-instellingen van "${naam}" worden gewijzigd (provisie ` +
        `${formatPercentage(pending.invoer.provisie_percentage)}%). Deze configuratie stuurt de ` +
        'provisieregel en de btw op elke volgende doorbelasting.'
      )
    case 'mapping':
      return `${pending.omschrijving} — wijzigingen aan de whitelist staan in het audit log.`
  }
}

function DoorbelastingAdministratie({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [ingeschakeld, setIngeschakeld] = useState<boolean | null>(null)
  const [instelling, setInstelling] = useState<DoorbelastingInstellingDto | null>(null)
  const [mappings, setMappings] = useState<DoorbelastingMappingDto[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [laadVersie, setLaadVersie] = useState(0)

  // Bewerkbare instelling-velden (bron-configuratie).
  const [provisiePct, setProvisiePct] = useState('')
  const [btwTaxrateId, setBtwTaxrateId] = useState<string | null>(null)
  const [omzetLedgerId, setOmzetLedgerId] = useState<string | null>(null)
  const [provisieOmzetLedgerId, setProvisieOmzetLedgerId] = useState<string | null>(null)

  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)

  const grootboek = useGrootboekOpties(administratieId)
  const btwCodes = useTaxrateOpties(administratieId)
  const doelGrootboek = useDoelGrootboek(
    useMemo(() => (mappings ?? []).map((m) => m.doel_administratie_id), [mappings]),
  )

  useEffect(() => {
    let actief = true
    setLaadFout(null)
    Promise.all([
      haalDoorbelastingToggleOp(administratieId),
      haalDoorbelastingInstellingOp(administratieId),
      haalDoorbelastingMappingsOp(administratieId),
    ])
      .then(([toggle, instellingDto, mappingLijst]) => {
        if (!actief) return
        setIngeschakeld(toggle.ingeschakeld)
        setInstelling(instellingDto)
        setProvisiePct(formatPercentage(instellingDto.provisie_percentage))
        setBtwTaxrateId(instellingDto.btw_taxrate_id)
        setOmzetLedgerId(instellingDto.omzet_ledger_id)
        setProvisieOmzetLedgerId(instellingDto.provisie_omzet_ledger_id)
        setMappings(mappingLijst)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, laadVersie])

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      if (pending.type === 'toggle') {
        const dto = await zetDoorbelastingToggle(administratieId, pending.nieuweWaarde)
        setIngeschakeld(dto.ingeschakeld)
      } else if (pending.type === 'instelling') {
        const dto = await zetDoorbelastingInstelling(administratieId, pending.invoer)
        setInstelling(dto)
        setProvisiePct(formatPercentage(dto.provisie_percentage))
        setBtwTaxrateId(dto.btw_taxrate_id)
        setOmzetLedgerId(dto.omzet_ledger_id)
        setProvisieOmzetLedgerId(dto.provisie_omzet_ledger_id)
      } else {
        const dto = await wijzigDoorbelastingMapping(administratieId, pending.mappingId, pending.wijziging)
        setMappings((huidig) => huidig?.map((m) => (m.id === dto.id ? dto : m)) ?? null)
      }
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const provisieGeldig = (() => {
    const pct = bedragAlsGetal(provisiePct)
    return pct !== null && pct >= 0 && pct <= 100
  })()

  if (laadFout) {
    return (
      <div style={{ marginTop: 10 }}>
        <FoutMelding
          melding="De doorbelasting-instellingen konden niet geladen worden."
          detail={laadFout}
          onOpnieuw={() => setLaadVersie((v) => v + 1)}
        />
      </div>
    )
  }
  if (ingeschakeld === null || instelling === null || mappings === null) {
    return <p className="hint">Laden…</p>
  }

  return (
    <div style={{ marginTop: 12 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '0 0 12px' }}>
        <input
          type="checkbox"
          aria-label={`Doorbelasting ingeschakeld voor ${naam}`}
          style={{ width: 'auto' }}
          checked={ingeschakeld}
          onChange={(e) => setPending({ type: 'toggle', nieuweWaarde: e.target.checked })}
        />
        Doorbelasting {ingeschakeld ? 'aan' : 'uit'} voor <b>{naam}</b>
      </label>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(150px, 1fr))', gap: 10 }}>
        <div>
          <label htmlFor="doorbelasting-provisie">Provisie-opslag (%)</label>
          <input
            id="doorbelasting-provisie"
            inputMode="decimal"
            style={{ textAlign: 'right' }}
            value={provisiePct}
            onChange={(e) => setProvisiePct(e.target.value)}
          />
          {!provisieGeldig && (
            <div className="hint" style={{ margin: '4px 0 0', color: 'var(--orange)' }}>
              Vul een percentage tussen 0 en 100 in.
            </div>
          )}
        </div>
        <SearchableCombobox
          label="Btw op doorbelasting (vlak tarief)"
          opties={btwCodes.opties}
          waarde={btwTaxrateId}
          onWijzig={setBtwTaxrateId}
          placeholder="Kies btw-code…"
          vereist
        />
        <SearchableCombobox
          label="Omzet-GB doorbelasting (bron)"
          opties={grootboek.opties}
          waarde={omzetLedgerId}
          onWijzig={setOmzetLedgerId}
          placeholder="Kies omzetrekening…"
          vereist
        />
        <SearchableCombobox
          label="Omzet-GB provisie (bron)"
          opties={grootboek.opties}
          waarde={provisieOmzetLedgerId}
          onWijzig={setProvisieOmzetLedgerId}
          placeholder="Kies omzetrekening…"
        />
      </div>
      <div className="actions">
        <button
          type="button"
          className="btn secondary"
          disabled={!provisieGeldig}
          onClick={() =>
            setPending({
              type: 'instelling',
              invoer: {
                provisie_percentage: normaliseerBedrag(provisiePct),
                btw_taxrate_id: btwTaxrateId,
                omzet_ledger_id: omzetLedgerId,
                provisie_omzet_ledger_id: provisieOmzetLedgerId,
              },
            })
          }
        >
          Instellingen opslaan
        </button>
      </div>
      <p className="hint">
        Zonder btw-tarief en omzet-GB blokkeren de harde checks elke doorbelasting — configuratie,
        nooit hardcoded.
      </p>

      <h3 style={{ margin: '14px 0 6px', fontSize: 14 }}>Doelentiteiten (whitelist)</h3>
      {mappings.length === 0 && (
        <p className="hint">
          Nog geen doelentiteiten — de whitelist wordt geseed vanaf de server
          (make doorbelasting-seed-kempen).
        </p>
      )}
      {mappings.length > 0 && (
        <div className="tabel-scroll">
          <table className="lines">
            <tbody>
              <tr>
                <th>Doelentiteit</th>
                <th>Onboarded</th>
                <th>Intercompany (RC)</th>
                <th>Provisie-GB (doel)</th>
                <th>Actief</th>
              </tr>
              {mappings.map((m) => {
                const schema = m.doel_administratie_id ? doelGrootboek[m.doel_administratie_id] : undefined
                return (
                  <tr key={m.id}>
                    <td>
                      <b>{m.doelentiteit_naam}</b>
                    </td>
                    <td>
                      {m.doel_administratie_id ? (
                        <span className="chip ok">onboarded</span>
                      ) : (
                        <span
                          className="chip vraag"
                          title="Nog geen eigen administratie in het platform — de spiegel-inkoopfactuur wordt een open taak"
                        >
                          niet onboarded
                        </span>
                      )}
                    </td>
                    <td>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                        <input
                          type="checkbox"
                          aria-label={`Intercompany voor ${m.doelentiteit_naam}`}
                          style={{ width: 'auto' }}
                          checked={m.intercompany}
                          onChange={(e) =>
                            setPending({
                              type: 'mapping',
                              mappingId: m.id,
                              wijziging: { intercompany: e.target.checked },
                              omschrijving: e.target.checked
                                ? `${m.doelentiteit_naam} wordt gemarkeerd als intercompany: open posten op deze tegenpartij verdwijnen uit alle afletter-voorstellen (RC-verrekening)`
                                : `${m.doelentiteit_naam} is niet langer intercompany: open posten doen weer gewoon mee in de afletter-voorstellen`,
                            })
                          }
                        />
                        {m.intercompany ? 'aan' : 'uit'}
                      </label>
                    </td>
                    <td>
                      {m.doel_administratie_id === null ? (
                        <span className="hint" style={{ margin: 0 }}>
                          kiesbaar ná onboarding
                        </span>
                      ) : schema?.fout ? (
                        <span className="hint" style={{ margin: 0, color: 'var(--orange)' }}>
                          {schema.fout}
                        </span>
                      ) : (
                        <SearchableCombobox
                          label={`Provisie-GB in ${m.doelentiteit_naam}`}
                          toonLabel={false}
                          opties={schema?.opties ?? []}
                          waarde={m.provisie_kosten_ledger_id}
                          onWijzig={(id) =>
                            setPending({
                              type: 'mapping',
                              mappingId: m.id,
                              wijziging: { provisie_kosten_ledger_id: id },
                              omschrijving: `De vaste provisie-GB in ${m.doelentiteit_naam} wordt gewijzigd — elke volgende spiegel-inkoopfactuur boekt de provisie op deze rekening`,
                            })
                          }
                          placeholder="Kies provisie-rekening…"
                        />
                      )}
                    </td>
                    <td>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                        <input
                          type="checkbox"
                          aria-label={`Actief voor ${m.doelentiteit_naam}`}
                          style={{ width: 'auto' }}
                          checked={m.actief}
                          onChange={(e) =>
                            setPending({
                              type: 'mapping',
                              mappingId: m.id,
                              wijziging: { actief: e.target.checked },
                              omschrijving: e.target.checked
                                ? `${m.doelentiteit_naam} wordt weer een kiesbare doelentiteit`
                                : `${m.doelentiteit_naam} wordt gedeactiveerd — niet meer kiesbaar in nieuwe verdelingen (bestaande boekingen blijven staan; er wordt nooit iets verwijderd)`,
                            })
                          }
                        />
                        {m.actief ? 'aan' : 'uit'}
                      </label>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint" style={{ marginBottom: 0 }}>
        De whitelist wordt server-side afgedwongen: doorbelasten buiten deze lijst is technisch
        onmogelijk. Een medewerker kan bovendien alleen kiezen wat de server toestaat — elke wijziging
        hier staat in het audit log.
      </p>

      {pending && (
        <BevestigDialog
          titel="Doorbelasting-instelling wijzigen?"
          bericht={berichtVoor(pending, naam)}
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
