import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { LeverancierProRatoDto, ProjectverdelingInstellingenDto } from '../api/types'
import {
  haalLeveranciersProRato,
  haalProjectverdelingInstellingenOp,
  zetLeverancierProRato,
  zetProjectverdelingInstellingen,
} from '../document/projectverdelingApi'
import { SkeletonRegels, Switch } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { InstellingRij } from './AdministratieDetailPagina'
import { BevestigDialog } from './BevestigDialog'

interface Pending {
  vendorId: string
  naam: string
  nieuweWaarde: boolean
}

/** Per-leverancier-instelling "verdelen: pro rato omzet" (blok C 04-09, ontwerpnotitie ④) — Beheerder-only
 * (tab Boeken & AI van de administratie-detailpagina; backend 403 voor andere rollen). AAN = élk document van
 * die leverancier krijgt automatisch een verdeelvoorstel mét alleen de restant-regel. Zelfde sectie-patroon als
 * LeverancierAutoboeken. */
export function LeverancierProjectverdeling({ administratieId }: { administratieId: string }) {
  const [leveranciers, setLeveranciers] = useState<LeverancierProRatoDto[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [laadVersie, setLaadVersie] = useState(0)
  const [pending, setPending] = useState<Pending | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)

  useEffect(() => {
    setLeveranciers(null)
    setLaadFout(null)
    let actueel = true
    haalLeveranciersProRato(administratieId)
      .then((dto) => {
        if (actueel) setLeveranciers(dto.leveranciers)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, laadVersie])

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      await zetLeverancierProRato(administratieId, pending.vendorId, pending.nieuweWaarde)
      setLeveranciers(
        (huidig) =>
          huidig?.map((l) => (l.vendor_id === pending.vendorId ? { ...l, projectverdeling_pro_rato: pending.nieuweWaarde } : l)) ?? null,
      )
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }} data-testid="leverancier-projectverdeling">
      <h2>Projectverdeling pro rato omzet per leverancier</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Aan = elke inkoopfactuur van deze leverancier krijgt op het controlescherm automatisch een verdeelvoorstel: het
        bedrag excl. wordt pro rato de omzet van de vorige maand over de actieve projecten verdeeld (vaste regels
        kunnen vooraf). De controleur ziet en bevestigt de verdeling vóór het boeken.
      </p>
      {laadFout && (
        <FoutMelding melding="De leveranciers konden niet geladen worden." detail={laadFout} onOpnieuw={() => setLaadVersie((v) => v + 1)} />
      )}
      {leveranciers === null && !laadFout && <SkeletonRegels />}
      {leveranciers !== null && leveranciers.length === 0 && (
        <p className="hint">Nog geen leveranciers bekend voor deze administratie — de leverancierslijst komt uit de sync.</p>
      )}
      {leveranciers !== null && leveranciers.length > 0 && (
        <div className="tabel-scroll sticky-koppen" style={{ marginTop: 10 }}>
          <table>
            <tbody>
              <tr>
                <th>Leverancier</th>
                <th>Verdelen: pro rato omzet</th>
              </tr>
              {leveranciers.map((l) => {
                const naam = l.naam ?? l.vendor_id
                return (
                  <tr key={l.vendor_id}>
                    <td>{naam}</td>
                    <td>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                        <Switch
                          aria-label={`Pro rato omzet verdelen voor ${naam}`}
                          checked={l.projectverdeling_pro_rato}
                          onChange={(e) => setPending({ vendorId: l.vendor_id, naam, nieuweWaarde: e.target.checked })}
                        />
                        {l.projectverdeling_pro_rato ? 'aan' : 'uit'}
                      </label>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {pending && (
        <BevestigDialog
          titel="Pro rato verdelen wijzigen?"
          bericht={
            pending.nieuweWaarde
              ? `Facturen van ${pending.naam} krijgen voortaan automatisch een verdeelvoorstel pro rato omzet over de actieve projecten. De controleur bevestigt vóór het boeken; de harde checks blijven blokkerend.`
              : `Het automatische verdeelvoorstel wordt uitgeschakeld voor ${pending.naam} — verdelen blijft mogelijk via "Projectverdeling…" op het document.`
          }
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

/** Beheerder-instellingen per administratie (blok C 04-09): hercontrole-drempel in % (default 5) en de wachttijd
 * in weken vóór het signaal "inkoop zonder omzet" spreekt (default 4). Opslaan bij verlaten van het veld. */
export function ProjectverdelingInstellingen({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [stand, setStand] = useState<ProjectverdelingInstellingenDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actueel = true
    haalProjectverdelingInstellingenOp(administratieId)
      .then((dto) => {
        if (actueel) setStand(dto)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [administratieId])

  const zet = async (invoer: { drempel_pct?: string; wachtweken?: number }) => {
    setFout(null)
    try {
      setStand(await zetProjectverdelingInstellingen(administratieId, invoer))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    }
  }

  return (
    <div className="panel inst-paneel" style={{ marginTop: 16 }} data-testid="projectverdeling-instellingen">
      <InstellingRij
        titel="Projectverdeling — hercontrole-drempel"
        uitleg="Maandelijks rekent het systeem geboekte pro-rato-verdelingen na tegen de actuele omzet van dezelfde maand; wijkt de verdeling méér af dan deze drempel, dan verschijnt het signaal 'verdeling wijkt x% af' mét de actie Herverdelen…"
      >
        <label className="inst-switch-label">
          drempel
          <input
            type="number"
            inputMode="decimal"
            min={0.5}
            max={100}
            step={0.5}
            aria-label={`Hercontrole-drempel projectverdeling voor ${naam}`}
            key={stand?.drempel_pct ?? 'laden'}
            defaultValue={stand?.drempel_pct ?? ''}
            disabled={stand === null}
            style={{ width: 70, padding: '2px 6px' }}
            onBlur={(e) => {
              const waarde = e.target.value.replace(',', '.')
              if (waarde !== '' && stand && Number(waarde) !== Number(stand.drempel_pct)) void zet({ drempel_pct: waarde })
            }}
          />
          %
        </label>
      </InstellingRij>
      <InstellingRij
        titel="Inkoop zonder omzet — wachttijd"
        uitleg="Het weekanalyse-signaal 'inkoop zonder omzet' spreekt pas als het project minimaal zoveel weken loopt (startdatum uit de projectspecificatie, anders de eerste kostenweek). 0 = direct signaleren."
      >
        <label className="inst-switch-label">
          na
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={52}
            step={1}
            aria-label={`Wachttijd inkoop zonder omzet voor ${naam}`}
            key={stand?.wachtweken ?? 'laden'}
            defaultValue={stand?.wachtweken ?? ''}
            disabled={stand === null}
            style={{ width: 60, padding: '2px 6px' }}
            onBlur={(e) => {
              const waarde = e.target.value
              if (waarde !== '' && stand && Number(waarde) !== stand.wachtweken) void zet({ wachtweken: Number(waarde) })
            }}
          />
          weken
        </label>
      </InstellingRij>
      {fout && <div className="fout">{fout}</div>}
    </div>
  )
}
