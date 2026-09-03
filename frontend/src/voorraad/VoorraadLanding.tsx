// Inzicht › Voorraad — KANTOORBREDE landing (design-ronde 03-09 blok B3, mockup inzicht-kantoorbreed.html
// ⑤ = bouwnorm; principe minimale mens, maximale autonomie — besluit Peter 02-09). Het kandidaten-patroon:
// één lijst van artikelgroepen buiten tolerantie over álle voorraad-administraties in scope, zwaarste
// afwijking eerst, administratie als facet-filter (nooit poort), zoekveld op artikelgroep, server-side
// paginering 25, per rij één primaire handeling "Bekijk regels →" (opent het bestaande detail per
// administratie mét de drill-down voorgefilterd op groep + periode). Chips = STATUS (oranje/rood naar
// zwaarte, groen = alles binnen tolerantie); teal = ACTIE. Controle-laag: nooit een boeking.
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { Badge, Button, Paginering, SkeletonRegels } from '../ui/basis'
import { formatDatumKort } from '../werkvoorraad/format'
import { aantal, detailPad, haalVoorraadVerschillen, verschilTekst, VOORRAAD_PER_PAGINA, type VoorraadVerschillenLijstDto } from './voorraadApi'

export function VoorraadLanding() {
  const navigate = useNavigate()
  const [zoekParams, setZoekParams] = useSearchParams()
  // Facet in de URL (`administratie_id`) — de werkvoorraad-teller "Voorraadverschil" landt hier voorgefilterd.
  const administratieId = zoekParams.get('administratie_id') ?? ''
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<VoorraadVerschillenLijstDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)

  useEffect(() => {
    let actueel = true
    setFout(null)
    haalVoorraadVerschillen({ administratieId: administratieId || undefined, q: zoek, pagina })
      .then((dto) => {
        if (actueel) setData(dto)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, zoek, pagina, versie])

  const kiesFacet = (id: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (id) p.set('administratie_id', id)
    else p.delete('administratie_id')
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const tellers = data?.tellers
  const facetten = data?.facetten ?? []
  const paginas = data ? Math.max(1, Math.ceil(data.totaal / VOORRAAD_PER_PAGINA)) : 1

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Voorraad</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Artikelgroepen waarvan de telling buiten de tolerantie van de theoretische stand valt — over alle administraties
            met &ldquo;Voorraad bijhouden&rdquo;, zwaarste afwijking eerst. Puur signaal, nooit een boeking.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="voorraad-landing">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          {tellers && tellers.groepen > 0 && (
            <Badge variant="warn" data-testid="chip-buiten-tolerantie">
              {tellers.groepen} buiten tolerantie
            </Badge>
          )}
          {tellers && tellers.groepen === 0 && tellers.administraties_met_voorraad > 0 && (
            <Badge variant="ok">✓ alles binnen tolerantie</Badge>
          )}
          {tellers && (
            <Badge variant="stil">
              {tellers.administraties_met_voorraad} {tellers.administraties_met_voorraad === 1 ? 'administratie' : 'administraties'} met voorraad
            </Badge>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <div style={{ minWidth: 260 }}>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={facetten.map((f) => ({ id: f.id, naam: f.aantal > 0 ? `${f.naam} (${f.aantal})` : f.naam }))}
              waarde={administratieId || null}
              onWijzig={(id) => kiesFacet(id)}
              placeholder="Administratie: alle"
            />
          </div>
          {administratieId && (
            <button type="button" className="linkbtn" onClick={() => kiesFacet(null)}>
              alle administraties
            </button>
          )}
          <input
            type="search"
            aria-label="Zoek artikelgroep"
            placeholder="🔍 zoek artikelgroep…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 220 }}
          />
        </div>

        {fout && <FoutMelding melding="De voorraadverschillen konden niet geladen worden." detail={fout} onOpnieuw={() => setVersie((v) => v + 1)} />}
        {!fout && data === null && <SkeletonRegels />}

        {data !== null && tellers && tellers.administraties_met_voorraad === 0 && (
          // Lege stand = actie: zonder opt-in is er niets te tonen — wijs de weg.
          <p className="hint" data-testid="voorraad-geen-optin">
            Nog geen administratie met &ldquo;Voorraad bijhouden&rdquo; in uw scope. Een Beheerder zet de opt-in aan op{' '}
            <Link to="/instellingen/administraties">Instellingen › Administraties</Link> (tab Voorraad).
          </p>
        )}
        {data !== null && tellers && tellers.administraties_met_voorraad > 0 && data.totaal === 0 && (
          <p className="hint" data-testid="voorraad-leeg">
            {tellers.groepen === 0
              ? 'Geen artikelgroepen buiten tolerantie — alle tellingen sluiten aan op de theoretische stand (groepen zonder telling geven geen signaal).'
              : 'Geen artikelgroepen buiten tolerantie binnen dit filter.'}
          </p>
        )}

        {data !== null && data.totaal > 0 && (
          <div className="tabel-scroll">
            <table data-testid="verschillen-tabel">
              <thead>
                <tr>
                  <th style={{ width: '30%' }}>Artikelgroep</th>
                  <th>Administratie</th>
                  <th>Verschil</th>
                  <th className="acties" />
                </tr>
              </thead>
              <tbody>
                {data.rijen.map((r) => (
                  <tr key={`${r.administratie_id}:${r.artikelgroep_id}`}>
                    <td>
                      <b>{r.naam}</b>
                      <div className="hint" style={{ fontSize: 11 }}>
                        theoretisch {aantal(r.theoretisch)} · telling {aantal(r.systeemstand)} {r.eenheid} op {formatDatumKort(r.telling_datum)} · tolerantie{' '}
                        {aantal(r.tolerantie_pct, 2)}%
                      </div>
                    </td>
                    <td>{r.administratie_naam}</td>
                    <td>
                      <Badge variant={r.zwaarte === 'rood' ? 'danger' : 'warn'} title={r.zwaarte === 'rood' ? 'zware afwijking (≥ 5× de tolerantie)' : 'buiten tolerantie'}>
                        ⚑ {verschilTekst(r)}
                      </Badge>
                    </td>
                    <td className="acties" style={{ whiteSpace: 'nowrap' }}>
                      <Button maat="klein" onClick={() => navigate(detailPad(r, data.van, data.tot))}>
                        Bekijk regels →
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data !== null && tellers && tellers.administraties_met_voorraad > 0 && (
          <div className="hint" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 10, marginBottom: 0 }} data-testid="verschillen-voet">
            <span>
              ‹ {data.pagina} van {paginas} › · {tellers.groepen} {tellers.groepen === 1 ? 'groep' : 'groepen'} over {tellers.administraties}{' '}
              {tellers.administraties === 1 ? 'administratie' : 'administraties'}
              {data.totaal !== tellers.groepen && ` · ${data.totaal} binnen dit filter`}
            </span>
            <span style={{ marginLeft: 'auto' }} />
            <Paginering pagina={pagina} totaal={data.totaal} grootte={VOORRAAD_PER_PAGINA} onPagina={setPagina} label="groepen" />
          </div>
        )}
      </div>
    </div>
  )
}
