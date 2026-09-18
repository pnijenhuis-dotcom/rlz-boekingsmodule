import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { beeindigAfwezigheid, haalAfwezigheidOp, voegAfwezigheidToe, type AfwezigheidDto } from '../planning/planningApi'
import { Button, FormField } from '../ui/basis'

/* Kaartje "Afwezig" in Beheer › Veldwerkers › dossier (planning v3 slice 5, Peter 18-09; CONTRACT_4): alleen "op deze
 * dagen niet plannen" — géén verlofadministratie, géén saldo, géén goedkeuring. Toevoegen (van/tot/reden) en beëindigen
 * (= `tot` vervroegen); NOOIT verwijderen (audit oud→nieuw server-side). De planning toont de stand in de pool, het
 * ploeg-paneel en de conflictenbalk (plannen op zo'n dag = oranje conflict, niet blokkerend). */

function datumNl(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric', year: 'numeric' })
}

function vandaagIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function AfwezigKaart({ administratieId, gebruikerId, naam }: { administratieId: string; gebruikerId: string; naam: string }) {
  const [lijst, setLijst] = useState<AfwezigheidDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [toevoegen, setToevoegen] = useState(false)
  const [van, setVan] = useState('')
  const [tot, setTot] = useState('')
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)

  function laad() {
    if (!administratieId) return
    haalAfwezigheidOp(administratieId, gebruikerId)
      .then((l) => {
        setLijst(l)
        setFout(null)
      })
      .catch((err: unknown) => {
        // 403/409 = geen recht/geen opt-in → kaartje bestaat niet (toon-regel); 404 = route nog niet gedeployed → idem.
        if (err instanceof ApiError && (err.status === 403 || err.status === 409 || err.status === 404)) setFout('')
        else setFout(err instanceof Error ? err.message : 'Laden mislukt')
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(laad, [administratieId, gebruikerId])

  async function actie(fn: () => Promise<unknown>) {
    setBezig(true)
    setFout(null)
    try {
      await fn()
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  if (fout === '') return null
  const vandaag = vandaagIso()
  const actueel = (lijst ?? []).filter((a) => a.tot >= vandaag).sort((a, b) => a.van.localeCompare(b.van))
  const voorbij = (lijst ?? []).filter((a) => a.tot < vandaag)
  return (
    <div className="panel" data-testid="afwezig-kaart" style={{ marginTop: 10 }}>
      <h3 style={{ margin: '0 0 6px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
        🏖 Afwezig
        <span className="hint" style={{ margin: 0, fontWeight: 400 }}>op deze dagen niet plannen — geen verlofadministratie</span>
        {!toevoegen && (
          <Button variant="secundair" maat="klein" style={{ marginLeft: 'auto' }} onClick={() => setToevoegen(true)} disabled={bezig}>
            + Toevoegen
          </Button>
        )}
      </h3>
      {fout && <div className="fout">{fout}</div>}
      {lijst !== null && actueel.length === 0 && !toevoegen && <p className="hint" style={{ margin: 0 }}>Geen (aankomende) afwezigheid voor {naam}.</p>}
      {actueel.map((a) => (
        <div key={a.id} data-testid={`afwezig-${a.id}`} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 12.5 }}>
          <span>
            <b>
              {datumNl(a.van)} t/m {datumNl(a.tot)}
            </b>
            {a.reden ? <span style={{ color: 'var(--muted)' }}> · {a.reden}</span> : null}
          </span>
          <button
            type="button"
            className="linkbtn"
            style={{ marginLeft: 'auto', fontSize: 11.5 }}
            disabled={bezig}
            title="Beëindigen = de einddatum vervroegen naar vandaag (of de begindatum als die later ligt); nooit verwijderen"
            onClick={() => void actie(() => beeindigAfwezigheid({ administratie_id: administratieId, id: a.id, tot: a.van > vandaag ? a.van : vandaag }))}
          >
            Beëindigen
          </button>
        </div>
      ))}
      {voorbij.length > 0 && (
        <p className="hint" style={{ fontSize: 11 }}>
          {voorbij.length} eerdere {voorbij.length === 1 ? 'periode' : 'perioden'} (historie blijft staan)
        </p>
      )}
      {toevoegen && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr auto', gap: 8, alignItems: 'end', marginTop: 8 }}>
          <FormField label="Van">
            <input type="date" value={van} onChange={(e) => setVan(e.target.value)} aria-label="Afwezig van" />
          </FormField>
          <FormField label="Tot en met">
            <input type="date" value={tot} min={van || undefined} onChange={(e) => setTot(e.target.value)} aria-label="Afwezig tot en met" />
          </FormField>
          <FormField label="Reden (optioneel)">
            <input value={reden} onChange={(e) => setReden(e.target.value)} placeholder="bv. verlof, cursus" aria-label="Reden afwezigheid" />
          </FormField>
          <div style={{ display: 'flex', gap: 6 }}>
            <Button variant="secundair" maat="klein" onClick={() => setToevoegen(false)} disabled={bezig}>
              Annuleren
            </Button>
            <Button
              maat="klein"
              disabled={bezig || !van || !tot || tot < van}
              onClick={() =>
                void actie(async () => {
                  await voegAfwezigheidToe({ administratie_id: administratieId, gebruiker_id: gebruikerId, van, tot, reden: reden.trim() || null })
                  setToevoegen(false)
                  setVan('')
                  setTot('')
                  setReden('')
                })
              }
            >
              Opslaan
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
