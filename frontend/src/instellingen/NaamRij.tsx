import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Badge, Button } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'
import { neemBronnaamOver, wijzigAdministratieNaam } from './instellingenApi'

/** Instellingenrij "Naam" op Instellingen › Administraties › ‹administratie› › Algemeen (opdracht Peter 15-09,
 * migratie 0144; casus Camping "Nieuwenhoven" → in Odoo hernoemd naar "Strandpark Zilverduynen").
 *
 * - Inline bewerken (Beheerder-only — de hele pagina is Beheerder-scherm): Bewerken → invoer + Opslaan/annuleren,
 *   Enter/Escape; opslaan = PUT /administraties/{id}/naam (audit `administratie_naam_gewijzigd`); 409 bij een bezette
 *   naam toont de reden van de server letterlijk.
 * - Herkomst: `naam_bron` 'odoo'|'rlz' = "volgt Odoo/Reeleezee" (de sync neemt een hernoeming automatisch over);
 *   'mens' = handmatig gezet — heet de bron dan anders, dan chip "in Odoo heet deze administratie nu ‹naam›" + linkbtn
 *   "Naam overnemen" (POST …/naam-overnemen, houdt 'mens').
 * Zelfde zelfstandige patroon als GroepRij (eigen fetch, geen PendingToggle: een naam is geen geldpoort). Ná een
 * wijziging herlaadt de lijst (`onGewijzigd`) zodat kop, breadcrumb, klantenlijst en combobox dezelfde naam zien. */

const BRON_LABEL: Record<string, string> = { odoo: 'Odoo', rlz: 'Reeleezee' }

export function bronLabel(a: Pick<AdministratieInstellingenDto, 'naam_bron' | 'boekhoud_backend'>): string {
  const bron = a.naam_bron && a.naam_bron !== 'mens' ? a.naam_bron : a.boekhoud_backend === 'odoo' ? 'odoo' : 'rlz'
  return BRON_LABEL[bron] ?? bron
}

export function bronAfwijkend(a: Pick<AdministratieInstellingenDto, 'naam' | 'bron_naam'>): boolean {
  const bron = (a.bron_naam ?? '').replace(/\s+/g, ' ').trim()
  return bron !== '' && bron.toLocaleLowerCase() !== a.naam.replace(/\s+/g, ' ').trim().toLocaleLowerCase()
}

function datum(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function NaamRij({
  administratie: a,
  onGewijzigd,
}: {
  administratie: AdministratieInstellingenDto
  onGewijzigd?: () => void
}) {
  const [bewerken, setBewerken] = useState(false)
  const [invoer, setInvoer] = useState(a.naam)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)
  const volgtBron = (a.naam_bron ?? 'mens') !== 'mens'
  const afwijkend = !volgtBron && bronAfwijkend(a)
  const label = bronLabel(a)
  const gearchiveerd = Boolean(a.gearchiveerd_op)

  const start = () => {
    setInvoer(a.naam)
    setFout(null)
    setOpgeslagen(false)
    setBewerken(true)
  }
  const annuleer = () => {
    setBewerken(false)
    setInvoer(a.naam)
    setFout(null)
  }
  const opslaan = async () => {
    const schoon = invoer.replace(/\s+/g, ' ').trim()
    if (!schoon) {
      setFout('De naam mag niet leeg zijn.')
      return
    }
    if (schoon === a.naam && !volgtBron) {
      setBewerken(false)
      return
    }
    setBezig(true)
    setFout(null)
    try {
      await wijzigAdministratieNaam(a.id, schoon)
      setBewerken(false)
      setOpgeslagen(true)
      onGewijzigd?.()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }
  const overnemen = async () => {
    setBezig(true)
    setFout(null)
    try {
      await neemBronnaamOver(a.id)
      setOpgeslagen(true)
      onGewijzigd?.()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Overnemen mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <InstellingRij
      titel="Naam"
      uitleg={
        volgtBron
          ? `Volgt de naam in ${label}: wordt de administratie dáár hernoemd, dan neemt de module dat bij de eerstvolgende sync over. Zelf een naam zetten stopt dat volgen.`
          : `Handmatig gezet — de naam in ${label} overschrijft deze niet. Heet de administratie in ${label} anders, dan zie je dat hier met de knop "Naam overnemen".`
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {bewerken ? (
            <>
              <input
                aria-label={`Naam van ${a.naam}`}
                value={invoer}
                autoFocus
                disabled={bezig}
                maxLength={200}
                style={{ width: 280 }}
                onChange={(e) => setInvoer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void opslaan()
                  }
                  if (e.key === 'Escape') annuleer()
                }}
              />
              <Button type="button" maat="klein" disabled={bezig || !invoer.trim()} onClick={() => void opslaan()}>
                {bezig ? 'Bezig…' : 'Opslaan'}
              </Button>
              <button type="button" className="linkbtn" onClick={annuleer} disabled={bezig}>
                annuleren
              </button>
            </>
          ) : (
            <>
              <strong data-testid="administratie-naam">{a.naam}</strong>
              {volgtBron ? (
                <Badge
                  variant="stil"
                  title={a.naam_gevolgd_op ? `laatst overgenomen uit ${label} op ${datum(a.naam_gevolgd_op)}` : `de naam volgt ${label}`}
                >
                  volgt {label}
                </Badge>
              ) : (
                <Badge variant="stil" title="Door een Beheerder gezet; de bron overschrijft deze naam niet.">
                  handmatig
                </Badge>
              )}
              {!gearchiveerd && (
                <button type="button" className="linkbtn" onClick={start} disabled={bezig} aria-label={`Naam bewerken van ${a.naam}`}>
                  Bewerken
                </button>
              )}
            </>
          )}
          {opgeslagen && !fout && <span className="text-[12px] text-ok">opgeslagen</span>}
          {fout && (
            <span className="text-[12px] text-red" role="alert">
              {fout}
            </span>
          )}
        </div>
        {afwijkend && !bewerken && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }} data-testid="bronnaam-afwijkend">
            <Badge variant="warn" title={a.bron_naam_gezien_op ? `gelezen uit ${label} op ${datum(a.bron_naam_gezien_op)}` : undefined}>
              in {label} heet deze administratie nu “{a.bron_naam}”
            </Badge>
            {!gearchiveerd && (
              <button type="button" className="linkbtn" onClick={() => void overnemen()} disabled={bezig}>
                Naam overnemen
              </button>
            )}
          </div>
        )}
      </div>
    </InstellingRij>
  )
}
