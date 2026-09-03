import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiJson } from '../api/client'
import type { AdministratieDto, DocumentListItemDto, DocumentListResponseDto } from '../api/types'
import { BankOverzichtScreen } from '../bank/BankOverzichtScreen'
import { FoutMelding } from '../ui/FoutMelding'
import { OpenVragenKantoorbreed } from '../vragen/OpenVragenKantoorbreed'
import { Breadcrumb } from './Breadcrumb'
import { documentRoute, amountKlasse, formatBedrag, ouderdomLabel } from './format'
import { StatusChip } from './StatusChip'
import { teVerwerken, type KlantRij } from './useWerkvoorraadData'

/* Kantoorbrede dwarsdoorsneden (IA-besluit 15-08): de klikbare KPI-kaarten bovenaan de
 * werkvoorraad vervangen de losse Vragen- en Bank-tabbladen. Elke weergave toont één dimensie
 * over álle klanten heen. Open vragen draaien sinds de design-ronde 03-09 (blok B2, mockup
 * inzicht-kantoorbreed.html ④) op het server-side endpoint GET /vragen (`OpenVragenKantoorbreed`) —
 * de client-side N+1-fan-out per administratie is daar vervallen. Te verwerken / bij klant lezen nog
 * per administratie uit de bestaande scope-veilige endpoints (alleen administraties met teller > 0). */

export type WerkvoorraadFilter = 'te_verwerken' | 'vragen' | 'bank' | 'bij_klant'

export const FILTER_LABELS: Record<WerkvoorraadFilter, string> = {
  te_verwerken: 'Te verwerken — alle klanten',
  vragen: 'Open vragen — alle klanten',
  bank: 'Bank af te letteren — alle klanten',
  bij_klant: 'Bij klant ter accordering — alle klanten',
}

/** Zelfde statusverzameling als de backend-teller "te verwerken" (werkvoorraad_overzicht):
 * de te-controleren-statussen + klaar_om_te_boeken. */
const TE_VERWERKEN_STATUSSEN = new Set([
  'ontvangen',
  'extractie_wachtrij',
  'extractie_bezig',
  'te_controleren',
  'handmatig_afmaken',
  'boeken_mislukt',
  'klaar_om_te_boeken',
])

export function FilterWeergave({
  filter,
  klanten,
  klantenFout,
  administraties,
}: {
  filter: WerkvoorraadFilter
  klanten: KlantRij[] | null
  klantenFout: string | null
  administraties: AdministratieDto[]
}) {
  if (filter === 'bank') {
    return (
      <div>
        <Breadcrumb stappen={[{ label: 'Werkvoorraad', naar: '/' }]} huidige="Bank af te letteren" />
        <BankOverzichtScreen />
      </div>
    )
  }
  if (filter === 'vragen') {
    return (
      <div>
        <div className="topbar">
          <div>
            <Breadcrumb stappen={[{ label: 'Werkvoorraad', naar: '/' }]} huidige={FILTER_LABELS.vragen} />
            <h1>{FILTER_LABELS.vragen}</h1>
          </div>
        </div>
        <OpenVragenKantoorbreed />
      </div>
    )
  }
  return (
    <DocumentDwarsdoorsnede
      filter={filter}
      klanten={klanten}
      klantenFout={klantenFout}
      administraties={administraties}
    />
  )
}

interface DwarsRij {
  administratieId: string
  administratieNaam: string
  document: DocumentListItemDto
}

function DocumentDwarsdoorsnede({
  filter,
  klanten,
  klantenFout,
  administraties,
}: {
  filter: 'te_verwerken' | 'bij_klant'
  klanten: KlantRij[] | null
  klantenFout: string | null
  administraties: AdministratieDto[]
}) {
  const navigate = useNavigate()
  const [rijen, setRijen] = useState<DwarsRij[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const naamPer = useMemo(() => new Map(administraties.map((a) => [a.id, a.naam])), [administraties])

  // Alleen administraties bevragen waar de teller > 0 is — de overzichtsdata bepaalt de scope.
  const relevanteIds = useMemo(() => {
    if (klanten === null) return null
    return klanten
      .filter((k) => (filter === 'te_verwerken' ? teVerwerken(k) > 0 : k.bij_klant > 0))
      .map((k) => k.administratie_id)
  }, [klanten, filter])

  useEffect(() => {
    if (relevanteIds === null) return
    let actueel = true
    setFout(null)
    setRijen(null)
    Promise.all(
      relevanteIds.map(async (id) => {
        const data = await apiJson<DocumentListResponseDto>(`/administraties/${id}/documenten`)
        return data.documenten
          .filter((d) =>
            filter === 'te_verwerken' ? TE_VERWERKEN_STATUSSEN.has(d.status) : d.status === 'ter_accordering',
          )
          .map(
            (document): DwarsRij => ({
              administratieId: id,
              administratieNaam: naamPer.get(id) ?? id,
              document,
            }),
          )
      }),
    )
      .then((per) => {
        if (actueel)
          setRijen(per.flat().sort((a, b) => a.document.aangemaakt_op.localeCompare(b.document.aangemaakt_op)))
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [relevanteIds, filter, naamPer])

  const laden = klanten === null || rijen === null

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb stappen={[{ label: 'Werkvoorraad', naar: '/' }]} huidige={FILTER_LABELS[filter]} />
          <h1>{FILTER_LABELS[filter]}</h1>
        </div>
      </div>
      <div className="panel">
        {(klantenFout || fout) && (
          <FoutMelding melding="De dwarsdoorsnede kon niet geladen worden." detail={klantenFout ?? fout ?? undefined} />
        )}
        {!klantenFout && !fout && laden && (
          <div aria-busy="true">
            <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
            <span className="skeleton" style={{ width: '40%' }} />
          </div>
        )}
        {rijen !== null && (
          <>
            {rijen.length === 0 && (
              <p className="hint">
                {filter === 'te_verwerken' ? 'Niets te verwerken — alle klanten zijn bij.' : 'Niets bij klanten ter accordering.'}
              </p>
            )}
            {rijen.length > 0 && (
              <div className="tabel-scroll">
                <table>
                  <tbody>
                    <tr>
                      <th>Klant</th>
                      <th>Document</th>
                      <th>Leverancier</th>
                      <th className="amount">Bedrag</th>
                      <th>Status</th>
                      <th>Sinds</th>
                    </tr>
                    {rijen.map((rij) => (
                      <tr
                        key={rij.document.id}
                        className="clickable"
                        onClick={() => navigate(documentRoute(rij.administratieId, rij.document))}
                      >
                        <td>
                          <b>{rij.administratieNaam}</b>
                        </td>
                        <td>{rij.document.bestandsnaam}</td>
                        <td>{rij.document.leverancier ?? '—'}</td>
                        <td className={amountKlasse(rij.document.totaalbedrag)}>{formatBedrag(rij.document.totaalbedrag)}</td>
                        <td>
                          <StatusChip status={rij.document.status} />
                        </td>
                        <td>{ouderdomLabel(rij.document.aangemaakt_op)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
