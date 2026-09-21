// "Corrigeren…" op een GEBOEKT inkoop-/verkoop-/kassarapport-document (opdracht Peter 21-09, casus BLOW
// RLZ-04-00000357/358 fout btw-bedrag: "ik kan de storno-knop niet meer vinden"). Eén handeling vanuit het ⋯-menu:
// storno (actie 19) op het externe stuk + het document opnieuw klaarzetten in de werkvoorraad (boekcyclus +1, regels
// zoals ze waren), mét verplichte reden. De server is de poort: aangifte → tegenboek-pad, (deels) betaald → eerst
// afletteren terugdraaien in de bankmodule, doorbelasting beide kanten of geen, Odoo → tegenboeken, verdwenen → opnieuw
// boeken vanuit de reconciliatie. De dialoog haalt die toets op en toont per blokkade de route (nooit een knop die pas
// server-side faalt). Ná de correctie toont het controlescherm een gele balk uit de tijdlijnregel `gecorrigeerd`.
// Teal = actie (dialoogknop), geel = waarschuwing/status (balk). `?corrigeren=1` in de URL (archief-⋯-menu) opent de
// dialoog direct.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { CorrigeerBlokkadeDto, CorrigeerToetsDto, CorrigerenResponseDto, DocumentGebeurtenisDto } from '../api/types'
import { AnkerPopup, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import {
  AL_GECORRIGEERD_CODE,
  CORRIGEREN_REDEN_MINIMUM,
  corrigeerDocument,
  corrigerenBlokkadeUit,
  haalCorrigeerToetsOp,
} from './corrigerenApi'

export const CORRIGEERBARE_SOORTEN = ['inkoopfactuur', 'verkoopfactuur', 'kassarapport'] as const

/** Alleen een GEBOEKT document van een soort mét eigen boekmotor (spiegelt `corrigeren.CORRIGEERBARE_SOORTEN`). */
export function corrigerenMogelijk(status: string, soort: string): boolean {
  return status === 'geboekt' && (CORRIGEERBARE_SOORTEN as readonly string[]).includes(soort)
}

const SOORT_LABEL: Record<string, string> = {
  inkoopfactuur: 'inkoopfactuur',
  verkoopfactuur: 'verkoopfactuur',
  kassarapport: 'omzetboeking',
}

/** URL-ingang `?corrigeren=1` (archief-⋯-menu) + de open-state van de dialoog; sluiten verwijdert de param. */
export function useCorrigerenDialoog(): { open: boolean; setOpen: (open: boolean) => void } {
  const [searchParams, setSearchParams] = useSearchParams()
  const autoOpen = searchParams.get('corrigeren') === '1'
  const [open, setOpenState] = useState(autoOpen)
  useEffect(() => {
    if (autoOpen) setOpenState(true)
  }, [autoOpen])
  const setOpen = useCallback(
    (volgende: boolean) => {
      setOpenState(volgende)
      if (!volgende && autoOpen) {
        const p = new URLSearchParams(searchParams)
        p.delete('corrigeren')
        setSearchParams(p, { replace: true })
      }
    },
    [autoOpen, searchParams, setSearchParams],
  )
  return { open, setOpen }
}

/** Menu-item voor een bestaand ⋯-menu (`rijmenu`): tekstknop = linkbtn (norm 03-09). */
export function CorrigerenMenuItem({ onKies, disabled = false }: { onKies: () => void; disabled?: boolean }) {
  return (
    <button type="button" className="linkbtn" role="menuitem" disabled={disabled} aria-disabled={disabled} onClick={onKies}>
      Corrigeren…
    </button>
  )
}

/** Zelfstandig ⋯-menu mét alleen "Corrigeren…" — voor de verkoop-/omzet-reviewschermen die geen eigen ⋯-menu hebben. */
export function CorrigerenMenu({ onKies, label = 'Meer acties' }: { onKies: () => void; label?: string }) {
  const knop = useRef<HTMLButtonElement | null>(null)
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        ref={knop}
        type="button"
        className="icon-btn"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        ⋯
      </button>
      <AnkerPopup
        open={open}
        anker={knop}
        kant="onder"
        uitlijning="eind"
        className="rijmenu"
        role="menu"
        aria-label={label}
        onAnkerUitBeeld={() => setOpen(false)}
      >
        <CorrigerenMenuItem
          onKies={() => {
            setOpen(false)
            onKies()
          }}
        />
      </AnkerPopup>
    </>
  )
}

function BlokkadeRoute({ blokkade, onTegenboeken }: { blokkade: CorrigeerBlokkadeDto; onTegenboeken?: () => void }) {
  if (blokkade.actie === 'tegenboeken' && onTegenboeken) {
    return (
      <Button type="button" variant="secundair" maat="klein" onClick={onTegenboeken}>
        Tegenboeken…
      </Button>
    )
  }
  if (blokkade.actie === 'bank' && blokkade.actie_pad) {
    return (
      <Link to={blokkade.actie_pad} className="btn secondary">
        Naar de bankmodule →
      </Link>
    )
  }
  if (blokkade.actie === 'opnieuw_boeken' && blokkade.actie_pad) {
    return (
      <Link to={blokkade.actie_pad} className="btn secondary">
        Naar Inzicht › Reconciliatie →
      </Link>
    )
  }
  return null
}

export function CorrigerenDialog({
  administratieId,
  documentId,
  soort,
  open,
  onClose,
  onGecorrigeerd,
  onTegenboeken,
}: {
  administratieId: string
  documentId: string
  soort: string
  open: boolean
  onClose: () => void
  /** Ná een geslaagde correctie (óf een 409 "al gecorrigeerd": het document staat dan al klaar). */
  onGecorrigeerd: (resultaat: CorrigerenResponseDto | null) => void
  /** Alleen op een inkoopfactuur: opent de bestaande tegenboek-flow (TegenboekSectie, `?tegenboeken=1`). */
  onTegenboeken?: () => void
}) {
  const [toets, setToets] = useState<CorrigeerToetsDto | 'laden' | 'fout'>('laden')
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [blokkadesNa, setBlokkadesNa] = useState<CorrigeerBlokkadeDto[] | null>(null)
  const redenGeldig = reden.trim().length >= CORRIGEREN_REDEN_MINIMUM

  useEffect(() => {
    if (!open) return
    let actief = true
    setToets('laden')
    setFout(null)
    setBlokkadesNa(null)
    haalCorrigeerToetsOp(administratieId, documentId)
      .then((dto) => {
        if (actief) setToets(dto)
      })
      .catch(() => {
        if (actief) setToets('fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, open])

  const sluit = () => {
    if (bezig) return
    setReden('')
    setFout(null)
    onClose()
  }

  const bevestig = async () => {
    if (!redenGeldig) return
    setBezig(true)
    setFout(null)
    try {
      const r = await corrigeerDocument(administratieId, documentId, reden.trim())
      setReden('')
      onGecorrigeerd(r)
      onClose()
    } catch (err) {
      const detail = corrigerenBlokkadeUit(err)
      if (detail?.code === AL_GECORRIGEERD_CODE) {
        // Tweede klik of een collega was eerder: het document staat al klaar — geen fout, wel herladen.
        onGecorrigeerd(null)
        onClose()
      } else if (detail?.blokkades && detail.blokkades.length > 0) {
        setBlokkadesNa(detail.blokkades)
      } else {
        setFout(err instanceof ApiError ? err.message : 'Corrigeren mislukt.')
      }
    } finally {
      setBezig(false)
    }
  }

  if (!open) return null
  const label = SOORT_LABEL[soort] ?? 'document'
  const blokkades = blokkadesNa ?? (typeof toets === 'object' ? toets.blokkades : [])
  const beschikbaar = blokkadesNa === null && typeof toets === 'object' && toets.beschikbaar
  const doorbelasting = typeof toets === 'object' ? toets.doorbelasting : []

  return (
    <Dialog open onOpenChange={(o) => !o && sluit()}>
      <DialogContent aria-describedby={undefined} data-testid="corrigeren-dialoog">
        <DialogTitle>Corrigeren — storno en opnieuw klaarzetten</DialogTitle>
        <DialogDescription>
          De geboekte {label}
          {typeof toets === 'object' && toets.oud_boekstuknummer ? (
            <>
              {' '}
              <b>{toets.oud_boekstuknummer}</b>
            </>
          ) : null}{' '}
          wordt in de boekhouding teruggezet naar concept (actie 19 — hetzelfde stuk, geen creditnota) en komt hier terug
          als &ldquo;klaar om te boeken&rdquo; met de regels zoals ze waren. Je past alleen de fout aan en boekt opnieuw; de
          controles draaien dan opnieuw. Niets wordt verwijderd.
        </DialogDescription>

        {toets === 'laden' && <p className="hint">Poorten controleren (btw-aangifte, betaalstatus, doorbelasting)…</p>}
        {toets === 'fout' && (
          <div className="fout" role="alert">
            De controle vooraf kon niet geladen worden — probeer het opnieuw.
          </div>
        )}

        {blokkades.length > 0 && (
          <div data-testid="corrigeren-blokkades" style={{ marginTop: 8 }}>
            <div className="fout" role="alert">
              <strong>Corrigeren is hier niet mogelijk.</strong>
            </div>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {blokkades.map((b, i) => (
                <li key={`${b.code}-${i}`} style={{ marginBottom: 6 }}>
                  <span>{b.melding}</span>
                  {(b.actie === 'tegenboeken' && onTegenboeken) || b.actie === 'bank' || b.actie === 'opnieuw_boeken' ? (
                    <div style={{ marginTop: 4 }}>
                      <BlokkadeRoute
                        blokkade={b}
                        onTegenboeken={
                          onTegenboeken
                            ? () => {
                                sluit()
                                onTegenboeken()
                              }
                            : undefined
                        }
                      />
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )}

        {beschikbaar && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void bevestig()
            }}
          >
            {doorbelasting.length > 0 && (
              <p className="hint" data-testid="corrigeren-doorbelasting">
                Doorbelasting gaat mee terug: {doorbelasting.map((k) => k.doelentiteit).join(', ')} (verkoop én
                spiegel-inkoop worden gestorneerd; zet de doorbelasting daarna opnieuw klaar).
              </p>
            )}
            <FormField label="Reden (verplicht)" htmlFor="corrigeren-reden">
              <textarea
                id="corrigeren-reden"
                required
                rows={3}
                value={reden}
                onChange={(e) => setReden(e.target.value)}
                placeholder="Bijvoorbeeld: btw-bedrag stond op 48,18 in plaats van 56,93."
                style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                disabled={bezig}
              />
            </FormField>
            {!redenGeldig && reden.trim() !== '' && (
              <div className="hint">Geef een inhoudelijke reden (minimaal {CORRIGEREN_REDEN_MINIMUM} tekens).</div>
            )}
            {fout && (
              <div className="fout" role="alert">
                {fout}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || !redenGeldig}>
                {bezig ? 'Bezig…' : 'Storneren en opnieuw klaarzetten'}
              </Button>
            </DialogFooter>
          </form>
        )}
        {!beschikbaar && toets !== 'laden' && (
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={sluit}>
              Sluiten
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

interface CorrectieInfo {
  reden: string
  oudBoekstuknummer: string | null
  doorbelasting: string[]
  alConcept: boolean
  tijdstip: string
}

/** De laatste correctie waarna het document nog niet opnieuw geboekt is — bron van de gele balk. */
export function laatsteCorrectie(tijdlijn: DocumentGebeurtenisDto[], status: string): CorrectieInfo | null {
  if (status === 'geboekt') return null
  for (let i = tijdlijn.length - 1; i >= 0; i--) {
    const g = tijdlijn[i]
    if (g.naar_status === 'geboekt') return null
    const c = g.detail?.gecorrigeerd
    if (c && typeof c === 'object') {
      const info = c as Record<string, unknown>
      return {
        reden: typeof info.reden === 'string' ? info.reden : '',
        oudBoekstuknummer: typeof info.oud_boekstuknummer === 'string' ? info.oud_boekstuknummer : null,
        doorbelasting: Array.isArray(info.doorbelasting_teruggedraaid) ? info.doorbelasting_teruggedraaid.map(String) : [],
        alConcept: Array.isArray(info.al_concept) && info.al_concept.length > 0 && !(Array.isArray(info.gestorneerd) && info.gestorneerd.length > 0),
        tijdstip: g.tijdstip,
      }
    }
  }
  return null
}

/** Gele balk boven het controlescherm ná een correctie: reden + vorige boeking, zolang het document niet opnieuw geboekt is. */
export function CorrectieBalk({ tijdlijn, status }: { tijdlijn: DocumentGebeurtenisDto[]; status: string }) {
  const info = laatsteCorrectie(tijdlijn, status)
  if (!info) return null
  return (
    <div
      className="panel"
      data-testid="correctie-balk"
      role="status"
      style={{ background: 'var(--warn-bg)', color: 'var(--warn)', borderRadius: 10, padding: '10px 14px' }}
    >
      <b>Gecorrigeerd</b> — reden: &ldquo;{info.reden}&rdquo;
      {info.oudBoekstuknummer ? (
        <>
          {' '}
          · vorige boeking <b>{info.oudBoekstuknummer}</b> {info.alConcept ? 'stond al op concept' : 'gestorneerd (actie 19)'}
        </>
      ) : null}
      {info.doorbelasting.length > 0 ? <> · doorbelasting teruggedraaid: {info.doorbelasting.join(', ')}</> : null}
      <div className="hint" style={{ marginTop: 4, color: 'inherit' }}>
        De regels staan zoals ze waren — pas alleen de fout aan en boek opnieuw; de controles draaien opnieuw.
      </div>
    </div>
  )
}

/** Tijdlijnregel voor de gebeurtenis `gecorrigeerd` (DocumentDetailScreen). */
export function correctieTijdlijnTekst(detail: Record<string, unknown>, actorNaam: string): string | null {
  const c = detail.gecorrigeerd
  if (!c || typeof c !== 'object') return null
  const info = c as Record<string, unknown>
  const boekstuk = typeof info.oud_boekstuknummer === 'string' ? info.oud_boekstuknummer : null
  const reden = typeof info.reden === 'string' ? info.reden : null
  const db = Array.isArray(info.doorbelasting_teruggedraaid) ? info.doorbelasting_teruggedraaid.length : 0
  return `Gecorrigeerd door ${actorNaam}${boekstuk ? ` — vorige boeking ${boekstuk} gestorneerd (actie 19)` : ''}${db > 0 ? ` · doorbelasting ${db} kant(en) teruggedraaid` : ''}, opnieuw klaargezet${reden ? ` — “${reden}”` : ''}`
}
