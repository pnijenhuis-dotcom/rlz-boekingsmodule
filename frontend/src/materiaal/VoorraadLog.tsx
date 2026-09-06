// Voorraadlog per mini-product (mockup mini-voorraad.html blok 2, ⑦/⑧): APPEND-ONLY, uitsluitend
// brongebonden mutaties — elke regel draagt datum · getekend aantal · soort · bron-link (factuur →
// controlescherm) · project · gemeld door. Er is géén corrigeer- of samenvoegfunctie: de stand is een
// pure afgeleide van deze regels. Gepagineerd 25 (server-side), uitklap-rij onder het product.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, SkeletonRegels } from '../ui/basis'
import { documentPad, getekendAantal, haalLog, PER_PAGINA, SOORT_LABEL, type LogLijstDto, type MutatieDto } from './miniVoorraadApi'

function ddmm(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${m[3]}-${m[2]}` : iso
}

/** Chip-kleur per soort: instroom = status-groen (geboekt feit), rest gedempt; beschadiging oranje (mens-gebeurtenis). */
function soortVariant(soort: MutatieDto['soort']): 'ok' | 'stil' | 'warn' {
  if (soort === 'instroom') return 'ok'
  if (soort === 'beschadiging') return 'warn'
  return 'stil'
}

/** Bron-omschrijving: "inkoopfactuur 260630 (Huvanco)" resp. "storno inkoopfactuur …" resp. "melding". */
export function bronTekst(m: MutatieDto): string {
  if (m.soort === 'beschadiging') return 'melding'
  const soort = m.soort === 'uitstroom' ? 'verkoopfactuur' : 'inkoopfactuur'
  const ref = m.document_referentie ? ` ${m.document_referentie}` : ''
  const lev = m.document_leverancier ? ` (${m.document_leverancier})` : ''
  return `${m.soort === 'storno' ? 'storno ' : ''}${soort}${ref}${lev}`
}

export function VoorraadLog({ administratieId, productId, productNaam }: { administratieId: string; productId: string; productNaam: string }) {
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<LogLijstDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actueel = true
    setFout(null)
    haalLog(administratieId, productId, pagina)
      .then((d) => {
        if (actueel) setData(d)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Voorraadlog laden mislukt.')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, productId, pagina])

  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? PER_PAGINA)))

  return (
    <div data-testid="voorraadlog" style={{ padding: '6px 0 4px' }}>
      <div className="hint" style={{ margin: '0 0 4px', display: 'flex', gap: 8, alignItems: 'center' }}>
        <b style={{ color: 'var(--text)' }}>Voorraadlog — {productNaam}</b>
        <span>append-only · uitsluitend brongebonden mutaties</span>
        {data && (
          <span style={{ marginLeft: 'auto' }}>
            {data.totaal} {data.totaal === 1 ? 'mutatie' : 'mutaties'}
          </span>
        )}
      </div>
      {fout && <div className="fout">{fout}</div>}
      {data === null && !fout && <SkeletonRegels />}
      {data && data.items.length === 0 && <div className="hint">Nog geen mutaties — de eerste instroom volgt bij het boeken van een inkoopfactuur.</div>}
      {data && data.items.length > 0 && (
        <table className="lines" aria-label={`Voorraadlog ${productNaam}`} style={{ fontSize: 12.5 }}>
          <tbody>
            {data.items.map((m) => (
              <tr key={m.id} data-testid="voorraadlog-regel">
                <td style={{ whiteSpace: 'nowrap', color: 'var(--muted)', width: 60 }}>{ddmm(m.datum)}</td>
                <td className="amount" style={{ width: 70, fontVariantNumeric: 'tabular-nums' }}>
                  <b>{getekendAantal(m.aantal)}</b>
                </td>
                <td style={{ width: 110 }}>
                  <Badge variant={soortVariant(m.soort)}>{SOORT_LABEL[m.soort]}</Badge>
                </td>
                <td>
                  {m.document_id ? (
                    <Link to={documentPad(administratieId, m.document_id)} className="text-primary no-underline hover:underline" aria-label={`Naar het document: ${bronTekst(m)}`}>
                      {bronTekst(m)} →
                    </Link>
                  ) : (
                    <span>{bronTekst(m)}</span>
                  )}
                  {m.project_naam && <span className="hint" style={{ margin: 0 }}> · project {m.project_naam}</span>}
                  {m.gemeld_door_naam && <span className="hint" style={{ margin: 0 }}> · gemeld door {m.gemeld_door_naam}</span>}
                  {m.boek_cyclus !== null && m.boek_cyclus > 1 && <span className="hint" style={{ margin: 0 }}> · boekcyclus {m.boek_cyclus}</span>}
                  {m.toelichting && (
                    <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                      “{m.toelichting}”
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && paginas > 1 && (
        <div className="hint" style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '6px 0 0' }}>
          <Button variant="ghost" maat="klein" aria-label="Vorige pagina log" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
            ‹
          </Button>
          <span>
            {pagina} van {paginas}
          </span>
          <Button variant="ghost" maat="klein" aria-label="Volgende pagina log" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
            ›
          </Button>
        </div>
      )}
    </div>
  )
}
