import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { LeverancierAutoboekenDto } from '../api/types'
import { Select, Switch } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { BevestigDialog } from './BevestigDialog'
import { haalLeveranciersAutoboeken, zetLeverancierAutoboeken } from './instellingenApi'

interface PendingWijziging {
  vendorId: string
  naam: string
  nieuweWaarde: boolean
}

function berichtVoor(pending: PendingWijziging): string {
  return pending.nieuweWaarde
    ? `Facturen van ${pending.naam} worden na extractie automatisch geboekt zodra alle harde checks ` +
        'groen zijn en het voorstel volledig uit bevestigd boekingsgeheugen komt. De controles blijven ' +
        'blokkerend. Weet je het zeker?'
    : `Automatisch boeken wordt uitgeschakeld voor ${pending.naam} — facturen wachten weer op de boek-klik ` +
        'van een medewerker.'
}

/** Autoboeken-opt-in per leverancier (CLAUDE.md: "Automatisch boeken = opt-in per leverancier;
 * harde checks blijven áltijd blokkerend" — de verplichte poort vóór het eerste autoboeken van
 * inkoopfacturen). Beheerder-only: de sectie leeft binnen de rol-gate van InstellingenScreen en
 * de backend geeft 403 voor andere rollen. Zelfde sectie-patroon als AccorderingInstellingen:
 * eigen panel, administraties als prop uit het scherm. */
export function LeverancierAutoboeken({
  administraties,
}: {
  administraties: { id: string; naam: string }[]
}) {
  const [administratieId, setAdministratieId] = useState('')
  const [leveranciers, setLeveranciers] = useState<LeverancierAutoboekenDto[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  // Hersleutel voor "Opnieuw proberen": ophogen forceert een refetch van dezelfde administratie.
  const [laadVersie, setLaadVersie] = useState(0)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)

  useEffect(() => {
    setLeveranciers(null)
    setLaadFout(null)
    if (!administratieId) return
    let actueel = true
    haalLeveranciersAutoboeken(administratieId)
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
      await zetLeverancierAutoboeken(administratieId, pending.vendorId, pending.nieuweWaarde)
      // Optimistische update op de al geladen lijst — de PUT is de bron; bij een fout hierboven
      // blijft de oude stand gewoon staan.
      setLeveranciers(
        (huidig) =>
          huidig?.map((l) =>
            l.vendor_id === pending.vendorId ? { ...l, autoboeken_ingeschakeld: pending.nieuweWaarde } : l,
          ) ?? null,
      )
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Automatisch boeken per leverancier</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Opt-in per leverancier: facturen die alle harde checks doorstaan én volledig op bevestigd
        boekingsgeheugen steunen, worden dan zonder boek-klik geboekt. Kies eerst een administratie.
      </p>
      <Select
        aria-label="Administratie voor automatisch boeken"
        value={administratieId}
        onChange={(e) => setAdministratieId(e.target.value)}
      >
        <option value="">— kies administratie —</option>
        {administraties.map((a) => (
          <option key={a.id} value={a.id}>
            {a.naam}
          </option>
        ))}
      </Select>

      {laadFout && (
        <FoutMelding
          melding="De leveranciers konden niet geladen worden."
          detail={laadFout}
          onOpnieuw={() => setLaadVersie((v) => v + 1)}
        />
      )}
      {administratieId && leveranciers === null && !laadFout && <p className="hint">Laden…</p>}
      {leveranciers !== null && leveranciers.length === 0 && (
        <p className="hint">
          Nog geen leveranciers bekend voor deze administratie — de leverancierslijst komt uit de
          Reeleezee-sync.
        </p>
      )}
      {leveranciers !== null && leveranciers.length > 0 && (
        // sticky-koppen (kliktest 2026-08-21): de leverancierslijst is per administratie lang —
        // koppen blijven in beeld tijdens het scrollen.
        <div className="tabel-scroll sticky-koppen" style={{ marginTop: 10 }}>
        <table>
          <tbody>
            <tr>
              <th>Leverancier</th>
              <th>Automatisch boeken</th>
            </tr>
            {leveranciers.map((l) => {
              const naam = l.naam ?? l.vendor_id
              return (
                <tr key={l.vendor_id}>
                  <td>{naam}</td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <Switch
                        aria-label={`Automatisch boeken voor ${naam}`}
                        checked={l.autoboeken_ingeschakeld}
                        onChange={(e) =>
                          setPending({ vendorId: l.vendor_id, naam, nieuweWaarde: e.target.checked })
                        }
                      />
                      {l.autoboeken_ingeschakeld ? 'aan' : 'uit'}
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
        Standaard staat automatisch boeken UIT; alleen een Beheerder kan dit wijzigen. Automatisch
        geboekte facturen blijven zichtbaar in de werkvoorraad-historie met de chip &ldquo;automatisch&rdquo;.
      </p>

      {pending && (
        <BevestigDialog
          titel="Automatisch boeken wijzigen?"
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
