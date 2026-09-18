/** Beoordelen › Urenstaten (bug 18-09: chip "14 meerwerk/urenstaten te beoordelen" landde op een lege Meerwerk-pagina —
 * de 14 waren ingediende weekstaten). Tabel van ingediende weekstaten mét kolomminima (`beoordelenKolommen.ts`), per rij
 * één primaire knop Goedkeuren + ⋯ (Afkeuren… mét verplichte reden, Weekstaat openen). Kantoor-keuring = vangnet als
 * er geen tweede uitvoerder is (zelfde statusmachine + audit `keurder: kantoor`). Lege stand = actie/context (KP7):
 * "Geen urenstaten te beoordelen — laatste keuring <datum>" + ingang naar de planning. */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { GebruikerRijMenu } from '../gebruikers/GebruikerRijMenu'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { BEOORDELEN_KOLOMMEN, colStijl, minimaleBeoordelenBreedte } from './beoordelenKolommen'
import {
  haalKantoorWeekstaten,
  keurWeekstaatAfKantoor,
  keurWeekstaatGoedKantoor,
  type KantoorWeekstaatItemDto,
  type KantoorWeekstatenDto,
} from './meerwerkApi'

function getal(waarde: string, eenheid: string): string {
  return `${Number(waarde).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} ${eenheid}`
}

function tijdstip(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function datum(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function UrenstatenTab({
  administratieId,
  openWeekstaat,
  onAantal,
  meld,
}: {
  administratieId: string
  /** Opent het kantoor-weekstaatpaneel (`?weekstaat=<id>`) boven de tabs. */
  openWeekstaat: (weekstaatId: string) => void
  /** Teller voor de tab-kop — uit dezelfde lijst als de tabel (chip == tab, nooit uit de pas). */
  onAantal: (aantal: number) => void
  meld: (tekst: string) => void
}) {
  const [data, setData] = useState<KantoorWeekstatenDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState<string | null>(null)
  const [afkeur, setAfkeur] = useState<KantoorWeekstaatItemDto | null>(null)
  const [reden, setReden] = useState('')
  const [actieFout, setActieFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    haalKantoorWeekstaten(administratieId)
      .then((d) => {
        setData(d)
        onAantal(d.items.length)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, onAantal])
  useEffect(() => {
    setData(null)
    laad()
  }, [laad])

  async function goedkeuren(item: KantoorWeekstaatItemDto) {
    setBezig(item.weekstaat_id)
    setActieFout(null)
    try {
      await keurWeekstaatGoedKantoor(administratieId, item.weekstaat_id)
      meld(`Week ${item.weeknummer} van ${item.zzper_naam ?? 'de veldwerker'} goedgekeurd — dit is nu de getekende urenstaat.`)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Goedkeuren mislukt.')
    } finally {
      setBezig(null)
    }
  }

  async function afkeuren() {
    if (!afkeur) return
    setBezig(afkeur.weekstaat_id)
    setActieFout(null)
    try {
      await keurWeekstaatAfKantoor(administratieId, afkeur.weekstaat_id, reden.trim())
      meld(`Week ${afkeur.weeknummer} van ${afkeur.zzper_naam ?? 'de veldwerker'} afgekeurd en teruggestuurd — de reden staat in de app.`)
      setAfkeur(null)
      setReden('')
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Afkeuren mislukt.')
    } finally {
      setBezig(null)
    }
  }

  if (fout) return <FoutMelding melding="De urenstaten konden niet geladen worden." detail={fout} onOpnieuw={laad} />
  if (data === null) {
    return (
      <div aria-busy="true">
        <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
        <span className="skeleton" style={{ width: '40%' }} />
      </div>
    )
  }

  if (data.items.length === 0) {
    return (
      <div className="hint" data-testid="urenstaten-leeg" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>
          Geen urenstaten te beoordelen —{' '}
          {data.laatste_keuring_op ? `laatste keuring ${datum(data.laatste_keuring_op)}` : 'nog geen keuring in deze administratie'}.
        </span>
        <Link className="linkbtn" to={`/planning?administratie=${administratieId}`}>
          Planning openen →
        </Link>
      </div>
    )
  }

  return (
    <>
      {actieFout && <div className="fout">{actieFout}</div>}
      <div className="tabel-scroll sticky-koppen">
        <table
          className="gebruikers-tabel"
          data-testid="urenstaten-tabel"
          style={{ tableLayout: 'fixed', minWidth: minimaleBeoordelenBreedte(), width: '100%' }}
        >
          <colgroup>
            {BEOORDELEN_KOLOMMEN.map((k) => (
              <col key={k.sleutel} style={colStijl(k)} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {BEOORDELEN_KOLOMMEN.map((k) => (
                <th key={k.sleutel} style={{ minWidth: k.minPx, whiteSpace: 'nowrap' }} className={k.sleutel === 'acties' ? 'acties' : undefined}>
                  {k.kop}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.weekstaat_id} data-testid={`urenstaat-${item.weekstaat_id}`}>
                <td>
                  <b>{item.zzper_naam ?? 'veldwerker'}</b>
                  {item.ingediend_namens && item.ingediend_door_naam && (
                    <div className="cel-detail">ingediend door {item.ingediend_door_naam} (namens)</div>
                  )}
                </td>
                <td style={{ whiteSpace: 'normal' }}>{item.project_naam ?? '—'}</td>
                <td>
                  {item.jaar}-W{item.weeknummer}
                </td>
                <td className="amount">{getal(item.totaal_uren, 'u')}</td>
                <td className="amount">{Number(item.totaal_m2) > 0 ? getal(item.totaal_m2, 'm²') : '—'}</td>
                <td>{tijdstip(item.ingediend_op)}</td>
                <td className="acties">
                  <GebruikerRijMenu
                    naam={`${item.zzper_naam ?? 'veldwerker'} week ${item.weeknummer}`}
                    primair={
                      <Button maat="klein" disabled={bezig === item.weekstaat_id} onClick={() => void goedkeuren(item)}>
                        {bezig === item.weekstaat_id ? 'Bezig…' : 'Goedkeuren'}
                      </Button>
                    }
                    items={[
                      { label: 'Weekstaat openen', onClick: () => openWeekstaat(item.weekstaat_id) },
                      { label: 'Afkeuren…', gevaar: true, onClick: () => { setAfkeur(item); setReden(''); setActieFout(null) } },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint" style={{ marginBottom: 0 }}>
        Goedkeuren maakt de week de getekende urenstaat (toetsbron voor de factuurmatch). Normaal keurt een andere
        uitvoerder in de app; kantoor keurt hier als er geen tweede uitvoerder is. Elke keuring wordt geauditeerd.
      </p>
      {afkeur && (
        <Dialog open onOpenChange={(open) => !open && bezig === null && setAfkeur(null)}>
          <DialogContent>
            <DialogTitle>Week {afkeur.weeknummer} afkeuren</DialogTitle>
            <DialogDescription>
              De hele week van {afkeur.zzper_naam ?? 'de veldwerker'} op {afkeur.project_naam ?? 'dit project'} gaat terug naar
              "corrigeren"; de reden is verplicht en verschijnt letterlijk in de app.
            </DialogDescription>
            <textarea
              rows={3}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="bijv. dinsdag was een vrije dag — graag corrigeren"
              aria-label="Reden van afkeuring"
              style={{ width: '100%' }}
            />
            {actieFout && <div className="fout">{actieFout}</div>}
            <DialogFooter>
              <Button variant="secundair" onClick={() => setAfkeur(null)} disabled={bezig !== null}>
                Annuleren
              </Button>
              <Button variant="gevaar" disabled={bezig !== null || reden.trim() === ''} onClick={() => void afkeuren()}>
                {bezig ? 'Bezig…' : 'Afkeuren'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
