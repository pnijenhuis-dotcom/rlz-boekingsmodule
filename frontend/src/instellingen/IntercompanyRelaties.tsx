import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { GebruikerRijMenu } from '../gebruikers/GebruikerRijMenu'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, SkeletonRegels } from '../ui/basis'
import {
  haalIntercompanyRelaties,
  haalRcKoppelingen,
  intercompanyAfleiden,
  zetAfkortingen,
  zetIntercompanyRelatieStatus,
  zetRcKoppelingStatus,
  type IcStatus,
  type IdentiteitDto,
  type IntercompanyRelatieDto,
  type RcKoppelingDto,
} from './intercompanyApi'

/** Instellingen › Boeken platformbreed — blok "Intercompany-relaties" + sectie "Rekening-courant" (blok A opdracht
 * Peter 16-09). Minimale mens: de relaties tussen onze administraties worden AFGELEID (KvK > btw > naam; de
 * doorbelasting-mapping telt als bevestigd) en de RC-grootboekrekeningen worden herkend op de naam van een andere
 * administratie (of een Beheerder-afkorting zoals "KF"). De Beheerder corrigeert alleen: bevestigen, uitsluiten mét
 * reden, terug naar afgeleid. Lijstpatroon (A ↔ B · basis · chip · ⋯), geen tegel, geen nieuwe pagina. Naam-only-relaties
 * zijn oranje "vermoedelijk — bevestigen" en tellen pas mee in de dagelijkse factuurmatch ná bevestiging. */

const STATUS_LABEL: Record<IcStatus, string> = { afgeleid: 'afgeleid', bevestigd: 'bevestigd', uitgesloten: 'uitgesloten' }
const BASIS_LABEL: Record<string, string> = {
  kvk: 'KvK-nummer',
  btw: 'btw-nummer',
  naam: 'naam',
  doorbelasting: 'doorbelasting',
  afkorting: 'afkorting',
  mens: 'handmatig',
}

function statusChipKlasse(status: IcStatus, basis: string): string {
  if (status === 'uitgesloten') return 'chip'
  if (status === 'bevestigd') return 'chip ok'
  return basis === 'naam' ? 'chip afwijking' : 'chip geheugen'
}

function StatusChip({ status, basis, actief }: { status: IcStatus; basis: string; actief: boolean }) {
  const tekst = status === 'afgeleid' && basis === 'naam' ? 'vermoedelijk — bevestigen' : STATUS_LABEL[status]
  const titel =
    status === 'uitgesloten'
      ? 'Uitgesloten door de Beheerder — telt niet mee'
      : actief
        ? 'Telt mee in de dagelijkse controle'
        : 'Alleen op naam herkend — telt pas mee ná bevestiging'
  return (
    <span className={statusChipKlasse(status, basis)} title={titel}>
      {tekst}
    </span>
  )
}

interface RedenActie {
  soort: 'relatie' | 'rc'
  id: string
  omschrijving: string
  status: IcStatus
}

function RedenDialoog({
  actie,
  bezig,
  fout,
  onBevestigen,
  onAnnuleren,
}: {
  actie: RedenActie
  bezig: boolean
  fout: string | null
  onBevestigen: (reden: string) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const geldig = reden.trim().length >= 3
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="ic-reden-dialoog">
        <DialogTitle>Uitsluiten: {actie.omschrijving}</DialogTitle>
        <DialogDescription>
          Deze {actie.soort === 'relatie' ? 'relatie' : 'rekening-courant-koppeling'} telt daarna niet meer mee in de dagelijkse
          controle. De reden komt in de audit; "Terug naar afgeleid" maakt het ongedaan.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (geldig) onBevestigen(reden.trim())
          }}
        >
          <FormField label="Reden" htmlFor="ic-reden">
            <textarea
              id="ic-reden"
              required
              rows={3}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="Bijvoorbeeld: dit is een externe klant met toevallig dezelfde naam."
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="secundair" onClick={onAnnuleren} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig || !geldig}>
              {bezig ? 'Bezig…' : 'Uitsluiten'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function foutTekst(err: unknown, standaard: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : standaard
}

function AfkortingenVeld({ identiteit, onOpgeslagen }: { identiteit: IdentiteitDto; onOpgeslagen: (dto: IdentiteitDto) => void }) {
  const [waarde, setWaarde] = useState(identiteit.afkortingen.join(', '))
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => setWaarde(identiteit.afkortingen.join(', ')), [identiteit.afkortingen])
  const gewijzigd = waarde.split(',').map((s) => s.trim()).filter(Boolean).join(', ') !== identiteit.afkortingen.join(', ')

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      onOpgeslagen(await zetAfkortingen(identiteit.administratie_id, waarde.split(',').map((s) => s.trim()).filter(Boolean)))
    } catch (err) {
      setFout(foutTekst(err, 'Opslaan mislukt'))
    } finally {
      setBezig(false)
    }
  }
  const invoerId = `ic-afk-${identiteit.administratie_id}`
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <input
        id={invoerId}
        type="text"
        aria-label={`Afkortingen voor ${identiteit.administratie_naam}`}
        value={waarde}
        placeholder="bv. KF, KFB"
        onChange={(e) => setWaarde(e.target.value)}
        style={{ width: 140 }}
      />
      {gewijzigd && (
        <button type="button" className="linkbtn" disabled={bezig} onClick={() => void opslaan()}>
          {bezig ? 'Bezig…' : 'Opslaan'}
        </button>
      )}
      {fout && <span className="fout">{fout}</span>}
    </div>
  )
}

export function IntercompanyRelaties() {
  const [relaties, setRelaties] = useState<IntercompanyRelatieDto[] | null>(null)
  const [koppelingen, setKoppelingen] = useState<RcKoppelingDto[] | null>(null)
  const [identiteiten, setIdentiteiten] = useState<IdentiteitDto[]>([])
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [reden, setReden] = useState<RedenActie | null>(null)
  const [bezig, setBezig] = useState(false)
  const [afleidBezig, setAfleidBezig] = useState(false)
  const [afleidUitkomst, setAfleidUitkomst] = useState<string | null>(null)
  const [toonAfkortingen, setToonAfkortingen] = useState(false)

  const laad = useCallback(() => {
    setLaadFout(null)
    Promise.all([haalIntercompanyRelaties(), haalRcKoppelingen()])
      .then(([rel, rc]) => {
        setRelaties(rel.relaties)
        setKoppelingen(rc.koppelingen)
        setIdentiteiten(rc.identiteiten)
      })
      .catch((err: unknown) => setLaadFout(foutTekst(err, 'Intercompany-relaties laden mislukt')))
  }, [])
  useEffect(() => laad(), [laad])

  const wijzigStatus = async (a: RedenActie, redenTekst: string | null) => {
    setBezig(true)
    setActieFout(null)
    try {
      if (a.soort === 'relatie') {
        const dto = await zetIntercompanyRelatieStatus(a.id, a.status, redenTekst)
        setRelaties((rijen) => (rijen ?? []).map((r) => (r.id === dto.id ? dto : r)))
      } else {
        const dto = await zetRcKoppelingStatus(a.id, a.status, redenTekst)
        setKoppelingen((rijen) => (rijen ?? []).map((k) => (k.id === dto.id ? dto : k)))
      }
      setReden(null)
    } catch (err) {
      setActieFout(foutTekst(err, 'Wijzigen mislukt'))
    } finally {
      setBezig(false)
    }
  }

  const menuItems = (soort: 'relatie' | 'rc', id: string, status: IcStatus, omschrijving: string) => {
    const items = []
    if (status !== 'bevestigd') items.push({ label: 'Bevestigen', onClick: () => void wijzigStatus({ soort, id, omschrijving, status: 'bevestigd' }, null) })
    if (status !== 'uitgesloten') items.push({ label: 'Uitsluiten…', gevaar: true, onClick: () => setReden({ soort, id, omschrijving, status: 'uitgesloten' }) })
    if (status !== 'afgeleid') items.push({ label: 'Terug naar afgeleid', onClick: () => void wijzigStatus({ soort, id, omschrijving, status: 'afgeleid' }, null) })
    return items
  }

  const afleiden = async () => {
    setAfleidBezig(true)
    setActieFout(null)
    setAfleidUitkomst(null)
    try {
      const r = await intercompanyAfleiden()
      const gelezen = r.identiteiten.gelezen ?? 0
      const meldingen = r.identiteit_meldingen.length
      setAfleidUitkomst(
        `Identiteiten gelezen: ${gelezen}${meldingen ? ` (${meldingen} melding${meldingen === 1 ? '' : 'en'})` : ''} · relaties nieuw ${r.relaties.relaties_nieuw}, bijgewerkt ${r.relaties.relaties_bijgewerkt} · RC-koppelingen nieuw ${r.rc_koppelingen.koppelingen_nieuw}, zonder tegenrekening ${r.rc_koppelingen.zonder_tegenrekening}` +
          (meldingen ? ` — ${r.identiteit_meldingen.join('; ')}` : ''),
      )
      laad()
    } catch (err) {
      setActieFout(foutTekst(err, 'Afleiden mislukt'))
    } finally {
      setAfleidBezig(false)
    }
  }

  const relatieOmschrijving = (r: IntercompanyRelatieDto) => `${r.entity_naam ?? 'relatie'} in ${r.administratie_a_naam} ↔ ${r.administratie_b_naam}`
  const rcOmschrijving = (k: RcKoppelingDto) => `${k.rekening_a_code ?? ''} ${k.rekening_a_naam ?? ''} (${k.administratie_a_naam}) ↔ ${k.administratie_b_naam}`

  return (
    <>
      <div
        id="intercompany"
        data-testid="intercompany-relaties"
        style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
          <div style={{ minWidth: 0, flex: '1 1 320px' }}>
            <h2 style={{ margin: 0 }}>Intercompany-relaties</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Welke crediteur of debiteur in de ene administratie is een ándere administratie van ons? Automatisch afgeleid uit
              KvK-nummer, btw-nummer of naam (en uit de doorbelasting). Deze paren voeden de dagelijkse controle "facturen tussen
              onze bedrijven matchen". Alleen op naam herkend = <b>vermoedelijk</b>: telt pas mee ná bevestigen. Uitsluiten vraagt
              een reden; niets verdwijnt.
            </p>
          </div>
          <Button type="button" variant="secundair" disabled={afleidBezig} onClick={() => void afleiden()}>
            {afleidBezig ? 'Bezig met afleiden…' : 'Nu afleiden'}
          </Button>
        </div>
        {afleidUitkomst && (
          <p className="hint" data-testid="ic-afleid-uitkomst" style={{ marginTop: 6 }}>
            {afleidUitkomst}
          </p>
        )}
        {laadFout && <div className="fout">{laadFout}</div>}
        {actieFout && !reden && <div className="fout">{actieFout}</div>}
        {relaties === null && !laadFout && <SkeletonRegels />}
        {relaties !== null && relaties.length === 0 && (
          <p className="hint" style={{ marginTop: 8 }}>
            Nog geen intercompany-relaties afgeleid. Klik "Nu afleiden" (of wacht op de nachtelijke sync) — er is dan minstens
            een KvK-nummer of naam per administratie nodig uit Reeleezee/Odoo.
          </p>
        )}
        {relaties !== null && relaties.length > 0 && (
          <div className="tabel-scroll" style={{ marginTop: 8 }}>
            <table className="gebruikers-tabel" style={{ minWidth: 760 }}>
              <thead>
                <tr>
                  <th>Administratie A</th>
                  <th>Relatie in A</th>
                  <th>Administratie B</th>
                  <th style={{ width: 120 }}>Basis</th>
                  <th style={{ width: 170 }}>Status</th>
                  <th style={{ width: 60 }} />
                </tr>
              </thead>
              <tbody>
                {relaties.map((r) => (
                  <tr key={r.id} data-testid="ic-relatie-rij">
                    <td>{r.administratie_a_naam}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.entity_naam ?? '—'}</div>
                      <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                        {r.richting === 'crediteur' ? 'crediteur — B levert aan A' : 'debiteur — A verkoopt aan B'}
                      </div>
                    </td>
                    <td>{r.administratie_b_naam}</td>
                    <td>{BASIS_LABEL[r.basis] ?? r.basis}</td>
                    <td>
                      <StatusChip status={r.status} basis={r.basis} actief={r.actief} />
                      {r.reden && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }} title={r.reden}>
                          {r.reden}
                        </div>
                      )}
                    </td>
                    <td>
                      <GebruikerRijMenu naam={relatieOmschrijving(r)} items={menuItems('relatie', r.id, r.status, relatieOmschrijving(r))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div
        id="rekening-courant"
        data-testid="rc-koppelingen"
        style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
          <div style={{ minWidth: 0, flex: '1 1 320px' }}>
            <h2 style={{ margin: 0 }}>Rekening-courant</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Balansrekeningen waarvan de naam een ándere administratie van ons noemt ("RC Kempen Facilities") worden gekoppeld
              aan de tegenrekening dáár. Deze paren voeden de dagelijkse controle "sluit de rekening-courant". Zonder
              tegenrekening = oranje: de andere kant heeft geen rekening die hierheen verwijst. Noemen jullie een administratie
              met een afkorting in rekeningnamen ("KF")? Zet die dan hier per administratie.
            </p>
          </div>
          <button type="button" className="linkbtn" onClick={() => setToonAfkortingen((v) => !v)}>
            {toonAfkortingen ? 'Verberg afkortingen' : `Afkortingen per administratie (${identiteiten.filter((i) => i.afkortingen.length).length})`}
          </button>
        </div>
        {toonAfkortingen && identiteiten.length > 0 && (
          <div className="tabel-scroll" style={{ marginTop: 8 }} data-testid="ic-afkortingen">
            <table style={{ minWidth: 560 }}>
              <thead>
                <tr>
                  <th>Administratie</th>
                  <th style={{ width: 120 }}>KvK</th>
                  <th style={{ width: 240 }}>Afkortingen (komma-gescheiden)</th>
                </tr>
              </thead>
              <tbody>
                {identiteiten.map((i) => (
                  <tr key={i.administratie_id}>
                    <td>
                      {i.administratie_naam}
                      {i.naam && i.naam !== i.administratie_naam && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          in {i.bron === 'odoo' ? 'Odoo' : 'Reeleezee'}: {i.naam}
                        </div>
                      )}
                    </td>
                    <td>{i.kvk ?? <span className="hint">niet gelezen</span>}</td>
                    <td>
                      <AfkortingenVeld
                        identiteit={i}
                        onOpgeslagen={(dto) => setIdentiteiten((lijst) => lijst.map((x) => (x.administratie_id === dto.administratie_id ? dto : x)))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {koppelingen === null && !laadFout && <SkeletonRegels />}
        {koppelingen !== null && koppelingen.length === 0 && (
          <p className="hint" style={{ marginTop: 8 }}>
            Nog geen rekening-courant-koppelingen herkend. Staat de andere administratie niet letterlijk in de rekeningnaam?
            Voeg dan een afkorting toe en klik "Nu afleiden".
          </p>
        )}
        {koppelingen !== null && koppelingen.length > 0 && (
          <div className="tabel-scroll" style={{ marginTop: 8 }}>
            <table className="gebruikers-tabel" style={{ minWidth: 820 }}>
              <thead>
                <tr>
                  <th>Rekening in A</th>
                  <th>Tegenrekening in B</th>
                  <th style={{ width: 110 }}>Basis</th>
                  <th style={{ width: 170 }}>Status</th>
                  <th style={{ width: 60 }} />
                </tr>
              </thead>
              <tbody>
                {koppelingen.map((k) => (
                  <tr key={k.id} data-testid="rc-koppeling-rij">
                    <td>
                      <div style={{ fontWeight: 600 }}>
                        {k.rekening_a_code} {k.rekening_a_naam}
                      </div>
                      <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                        {k.administratie_a_naam}
                      </div>
                    </td>
                    <td>
                      {k.rekening_b ? (
                        <>
                          <div style={{ fontWeight: 600 }}>
                            {k.rekening_b_code} {k.rekening_b_naam}
                          </div>
                          <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            {k.administratie_b_naam}
                          </div>
                        </>
                      ) : (
                        <>
                          <span className="chip afwijking" title={k.reden ?? 'Geen rekening in de tegenpartij verwijst hierheen'}>
                            zonder tegenrekening
                          </span>
                          <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            {k.administratie_b_naam}
                          </div>
                        </>
                      )}
                    </td>
                    <td>{BASIS_LABEL[k.basis] ?? k.basis}</td>
                    <td>
                      <StatusChip status={k.status} basis={k.basis === 'mens' ? 'mens' : 'rc'} actief={k.actief} />
                      {k.status === 'uitgesloten' && k.reden && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }} title={k.reden}>
                          {k.reden}
                        </div>
                      )}
                    </td>
                    <td>
                      <GebruikerRijMenu naam={rcOmschrijving(k)} items={menuItems('rc', k.id, k.status, rcOmschrijving(k))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {reden && (
        <RedenDialoog
          actie={reden}
          bezig={bezig}
          fout={actieFout}
          onBevestigen={(tekst) => void wijzigStatus(reden, tekst)}
          onAnnuleren={() => {
            setActieFout(null)
            setReden(null)
          }}
        />
      )}
    </>
  )
}
