import { useEffect, useMemo, useState } from 'react'
import { normaliseerTekst } from '../bank/bankZoek'
import { Button } from '../ui/basis'
import { beschikbaarheid, beschikbaarheidLabel, dagKort, dichtstbijzijndeEerderePloeg, initialen, plusDagen, vrijTellers, type DagKaart } from './dagEerst'
import type { PlanningWeekDto } from './planningApi'

/* Ploeg kiezen — sinds v4 (Peter 28-09) DÉ werkwijze: klik op élke kaart (ook een gereserveerde) of lege cel → paneel rechts
 * (geen modaal; patroon MateriaalstandPaneel), kop project + dag + werkopdracht/starttijd (wijzigen = bestaande dag-override)
 * + de compacte "wie is nog vrij"-regel ("N vrij op ‹dag› · M vrij hele week" — vervangt de ZZP-pool), zoekveld, volledige
 * lijst veldwerkers in scope mét vinkjes en beschikbaarheid voor DIE dag (vrij groen · al op ‹project› oranje, wél kiesbaar ·
 * afwezig grijs, uitgeschakeld), uitvoerder-chip, chip "dossier onvolledig", "Zelfde ploeg als ‹vorige werkdag›",
 * "Toepassen op hele week", "Kopiëren naar ‹weekdag› volgende week" (alleen dezelfde weekdag — besluit Peter 28-09),
 * "+ Veldwerker toevoegen…" (quick-add, recht veldwerkerbeheer/Beheerder). Het paneel scrolt zelf (lijst), het hoofdscherm
 * niet. Opslaan (N) = diff → één bulk-call bij de aanroeper; iemand mét uren van de planning halen = bevestiging. */

export const PANEEL_LIJST_MAX = 60

export function vorigeWerkdagMetPlanning(data: PlanningWeekDto, kaart: DagKaart, werkdagen: string[]): { datum: string; gebruiker_ids: string[] } | null {
  return dichtstbijzijndeEerderePloeg(data, kaart.project_id, kaart.datum, werkdagen)
}

export function PloegPaneel({
  data,
  kaart,
  werkdagen,
  bezig,
  magVeldwerkerbeheer = false,
  nieuwVinkje = null,
  onSluiten,
  onOpslaan,
  onToepassenHeleWeek,
  onKopieVolgendeWeek,
  onNieuweVeldwerker,
  onWerkopdracht,
}: {
  data: PlanningWeekDto
  kaart: DagKaart
  werkdagen: string[]
  bezig: boolean
  /** Recht 'veldwerkerbeheer' of Beheerder — anders geen "+ Veldwerker toevoegen…". */
  magVeldwerkerbeheer?: boolean
  /** v4: id van een zojuist via quick-add aangemaakte veldwerker — wordt direct aangevinkt zodra hij in de pool staat. */
  nieuwVinkje?: string | null
  onSluiten: () => void
  onOpslaan: (toevoegen: string[], verwijderen: string[]) => void
  onToepassenHeleWeek: (gebruikerIds: string[]) => void
  /** v4: dezelfde kaart op dezelfde weekdag in week+1 (bulkroute, bron kopie_volgende_week). */
  onKopieVolgendeWeek?: (gebruikerIds: string[]) => void
  onNieuweVeldwerker?: () => void
  onWerkopdracht: () => void
}) {
  const huidig = useMemo(() => new Set(kaart.ploeg.map((k) => k.gebruiker_id)), [kaart])
  const vorige = vorigeWerkdagMetPlanning(data, kaart, werkdagen)
  // Lege cel (v4): de ploeg van de dichtstbijzijnde eerdere dag als VOORSTEL — voorgevinkt, nooit opgeslagen tot "Opslaan".
  const voorstel = kaart.leeg && vorige ? vorige : null
  const [vinkjes, setVinkjes] = useState<Set<string>>(() => new Set(voorstel ? voorstel.gebruiker_ids : huidig))
  const [zoek, setZoek] = useState('')
  const [alles, setAlles] = useState(false)
  useEffect(() => {
    if (nieuwVinkje && data.pool.some((p) => p.gebruiker_id === nieuwVinkje)) setVinkjes((v) => new Set(v).add(nieuwVinkje))
  }, [nieuwVinkje, data.pool])
  const termen = normaliseerTekst(zoek).split(' ').filter(Boolean)
  const lijst = data.pool
    .map((p) => ({ p, b: beschikbaarheid(data, p.gebruiker_id, kaart.datum, kaart.project_id) }))
    .filter(({ p }) => termen.length === 0 || termen.every((t) => normaliseerTekst(p.naam).includes(t)))
    .sort((a, b) => {
      const ka = vinkjes.has(a.p.gebruiker_id) ? 0 : a.b.soort === 'vrij' ? 1 : a.b.soort === 'al_op' ? 2 : 3
      const kb = vinkjes.has(b.p.gebruiker_id) ? 0 : b.b.soort === 'vrij' ? 1 : b.b.soort === 'al_op' ? 2 : 3
      return ka - kb || a.p.naam.localeCompare(b.p.naam, 'nl')
    })
  const getoond = alles || termen.length > 0 ? lijst : lijst.slice(0, PANEEL_LIJST_MAX)
  const toevoegen = [...vinkjes].filter((id) => !huidig.has(id))
  const verwijderen = [...huidig].filter((id) => !vinkjes.has(id))
  const vrij = vrijTellers(data, kaart.datum, werkdagen)
  const weekdagVolgende = dagKort(plusDagen(kaart.datum, 7))

  function wissel(id: string) {
    setVinkjes((v) => {
      const n = new Set(v)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  function opslaan() {
    // Verwijderen van iemand die al uren invulde op deze dag: bevestiging mét de urenstand — uren blijven staan.
    for (const id of verwijderen) {
      const persoon = kaart.ploeg.find((k) => k.gebruiker_id === id)
      if (persoon && (persoon.uren_status ?? 'geen') !== 'geen') {
        const uren = persoon.uren ? `${Number(persoon.uren).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u` : 'uren'
        if (!window.confirm(`${persoon.naam ?? 'Deze persoon'} heeft ${uren} ingevuld op deze dag — toch van de planning halen? De uren blijven staan.`)) return
      }
    }
    onOpslaan(toevoegen, verwijderen)
  }

  return (
    <div className="panel plan-paneel" data-testid="ploeg-paneel" role="region" aria-label="Ploeg kiezen">
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 14 }}>{kaart.project_naam ?? kaart.project_id}</h2>
          <div className="hint" style={{ margin: '2px 0 0' }}>
            {dagKort(kaart.datum)}
            {kaart.opdrachtgever ? ` · ${kaart.opdrachtgever}` : ''}
            {' · '}
            <button type="button" className="linkbtn" style={{ fontSize: 12 }} onClick={onWerkopdracht} title="Starttijd/werkopdracht voor deze dag wijzigen (dag-override)">
              {kaart.werkopdracht_tekst ? `📋 ${kaart.werkopdracht_tekst.slice(0, 40)}${kaart.werkopdracht_tekst.length > 40 ? '…' : ''} · wijzigen` : 'starttijd/werkopdracht instellen'}
            </button>
          </div>
          {kaart.gereserveerd && (
            <div className="hint" style={{ margin: '2px 0 0' }} data-testid="paneel-gereserveerd">
              <em className="plan-chip grijs">{kaart.leeg ? 'nog niet gepland' : 'gereserveerd · nog geen ploeg'}</em>{' '}
              {voorstel ? `voorstel: ploeg van ${dagKort(voorstel.datum)} (nog niet opgeslagen)` : 'vink de ploeg aan en sla op'}
            </div>
          )}
          <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }} data-testid="paneel-vrij" title={vrij.namen_week.length ? `Hele week vrij: ${vrij.namen_week.join(', ')}` : undefined}>
            {vrij.dag} vrij op {dagKort(kaart.datum)} · {vrij.week} vrij hele week
          </div>
        </div>
        <button type="button" className="linkbtn" aria-label="Paneel sluiten" style={{ marginLeft: 'auto', fontSize: 14 }} onClick={onSluiten}>
          ✕
        </button>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '10px 0 6px' }}>
        <Button
          variant="secundair"
          maat="klein"
          disabled={!vorige}
          title={vorige ? `Ploeg van ${dagKort(vorige.datum)} overnemen` : 'Geen eerdere werkdag mét planning op dit project deze week'}
          onClick={() => vorige && setVinkjes(new Set(vorige.gebruiker_ids))}
        >
          Zelfde ploeg als {vorige ? dagKort(vorige.datum) : 'vorige werkdag'}
        </Button>
        <Button
          variant="secundair"
          maat="klein"
          disabled={bezig || vinkjes.size === 0}
          title="Deze vinkjesstand naar álle werkdagen van de week (bestaande kaarten van dit project worden overgeslagen)"
          onClick={() => onToepassenHeleWeek([...vinkjes])}
        >
          Toepassen op hele week
        </Button>
        {onKopieVolgendeWeek && (
          <Button
            variant="secundair"
            maat="klein"
            disabled={bezig || vinkjes.size === 0}
            data-testid="kopie-volgende-week"
            title={`Deze kaart (project + ploeg, géén uren) op ${weekdagVolgende} — dezelfde weekdag in de volgende week. Afwezig = overgeslagen, al gepland = samengevoegd, elders gepland = oranje. Daarna in die week "Toepassen op hele week".`}
            onClick={() => onKopieVolgendeWeek([...vinkjes])}
          >
            Kopiëren naar {weekdagVolgende.split(' ')[0]} volgende week
          </Button>
        )}
      </div>
      <input type="search" aria-label="Zoek veldwerker" placeholder="Zoek veldwerker…" value={zoek} onChange={(e) => setZoek(e.target.value)} style={{ width: '100%', fontSize: 12.5, padding: '7px 10px', margin: '4px 0 6px' }} />
      <div className="hint" style={{ margin: '0 0 4px', fontSize: 11.5 }}>
        {vinkjes.size} gekozen · beschikbaarheid voor {dagKort(kaart.datum)}
      </div>
      <div className="plan-paneel-lijst" role="list">
        {getoond.map(({ p, b }) => {
          const aan = vinkjes.has(p.gebruiker_id)
          const afwezig = b.soort === 'afwezig'
          return (
            <label key={p.gebruiker_id} className={`plan-pl${afwezig ? ' afw' : ''}`} role="listitem" data-testid={`paneel-persoon-${p.gebruiker_id}`}>
              <input type="checkbox" checked={aan} disabled={afwezig && !aan} onChange={() => wissel(p.gebruiker_id)} aria-label={p.naam} />
              <span className={`plan-av${p.rol === 'uitvoerder' ? ' u' : ''}${b.soort === 'al_op' && aan ? ' c' : ''}${p.dossier_onvolledig ? ' d' : ''}`} aria-hidden>
                {initialen(p.naam)}
              </span>
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p.naam}
                {p.rol === 'uitvoerder' && <span className="plan-chip ok" style={{ marginLeft: 6 }}>uitv.</span>}
                {p.dossier_onvolledig && (
                  <span className="plan-chip warn" style={{ marginLeft: 6 }} data-testid={`dossier-onvolledig-${p.gebruiker_id}`} title="ZZP-dossier (KvK/IBAN/e-mail/documenten) nog niet compleet — verplicht vóór de goedkeuring van de eerste weekstaat (Beheer › Veldwerkers)">
                    dossier onvolledig
                  </span>
                )}
              </span>
              <span className={`st${b.soort === 'vrij' ? ' g' : b.soort === 'al_op' ? ' w' : ''}`} title={afwezig && b.reden ? b.reden : undefined}>
                {beschikbaarheidLabel(b)}
              </span>
            </label>
          )
        })}
        {lijst.length > getoond.length && (
          <button type="button" className="linkbtn" style={{ fontSize: 12, padding: '6px' }} onClick={() => setAlles(true)}>
            … {lijst.length - getoond.length} meer
          </button>
        )}
        {lijst.length === 0 && data.pool.length > 0 && <p className="hint">Geen veldwerker past bij &quot;{zoek.trim()}&quot;.</p>}
        {data.pool.length === 0 && <p className="hint">Nog geen veldwerkers in deze administratie.</p>}
        {magVeldwerkerbeheer && onNieuweVeldwerker && (
          <button
            type="button"
            className="linkbtn"
            style={{ fontSize: 12.5, padding: '8px 4px', display: 'block' }}
            data-testid="paneel-veldwerker-toevoegen"
            title="Veldwerker aanmaken (naam, rol, e-mail; scope = deze administratie) — direct aanvinkbaar; het dossier volgt via Beheer › Veldwerkers"
            onClick={onNieuweVeldwerker}
          >
            + Veldwerker toevoegen…
          </button>
        )}
      </div>
      <p className="hint" style={{ fontSize: 11 }}>Iemand met conflict kiezen mag — de kaart kleurt oranje. Afwezig = niet kiesbaar.</p>
      <div className="plan-paneel-voet">
        <Button variant="secundair" maat="klein" onClick={onSluiten} disabled={bezig}>
          Annuleren
        </Button>
        <Button maat="klein" onClick={opslaan} disabled={bezig || (toevoegen.length === 0 && verwijderen.length === 0)} data-testid="ploeg-opslaan">
          Opslaan ({vinkjes.size})
        </Button>
      </div>
    </div>
  )
}
