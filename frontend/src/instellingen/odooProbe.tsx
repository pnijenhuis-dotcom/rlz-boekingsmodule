import { ApiError, BackendOnbereikbaarError } from '../api/client'

/** Odoo-adapter blok E (03-09, mockup odoo-koppeling-ui.html): gedeelde presentatie van de Odoo-probe.
 * De server levert per onderdeel 'ok' óf een leesbare foutregel mét handelingsperspectief (notitie ⑥,
 * vertaal_rlz_boekfout-patroon — bv. "geen schrijfrecht op account.move — geef de API-gebruiker
 * boekhoudrechten in Odoo"). Dit bestand vertaalt alleen de sleutels naar mensentaal en tekent het
 * rapport; het oordeel (groen/rood) komt van de server. Onbekende sleutel = de sleutel zelf tonen,
 * nooit stil weglaten. */

const ODOO_PROBE_LABELS: Record<string, string> = {
  verbinding: 'verbinding',
  versie: 'versie',
  company: 'company',
  ledgers: 'grootboek',
  grootboek: 'grootboek',
  'account.account': 'grootboek',
  taxrates: 'btw',
  btw: 'btw',
  'account.tax': 'btw',
  vendors: 'relaties',
  partners: 'relaties',
  relaties: 'relaties',
  'res.partner': 'relaties',
  journals: 'journals',
  'account.journal': 'journals',
  facturen: 'facturen',
  'account.move': 'facturen',
  'account.move:read': 'facturen (lezen)',
  'account.move.line': 'factuurregels',
  projects: 'projecten',
  'project.project': 'projecten',
  'account.analytic.account': 'projecten',
  producten: 'producten',
  'product.product': 'producten',
  bijlagen: 'bijlagen',
  'ir.attachment': 'bijlagen',
  boeken: 'boeken (schrijven)',
  schrijven: 'boeken (schrijven)',
  'account.move:write': 'boeken (schrijven)',
  'account.move:create': 'boeken (schrijven)',
  lock_dates: 'lock-dates',
  'dagboek:memoriaal': 'memoriaal-dagboek',
  'dagboek:inkoop': 'inkoopdagboek',
  'dagboek:verkoop': 'verkoopdagboek',
  probe: 'probe',
}

export function odooProbeLabel(sleutel: string): string {
  return ODOO_PROBE_LABELS[sleutel] ?? sleutel
}

/** Eén ok-toets, spiegel van `app/odoo/probe.py::is_ok`: "ok" óf "ok (toelichting)" — bv. "ok (memoriaal-dagboek:
 * MEM)" of "ok (geen lock dates)". De toelichting tussen haakjes toont het rapport als hint. */
export function odooProbeOk(waarde: string | null | undefined): boolean {
  return waarde === 'ok' || (typeof waarde === 'string' && waarde.startsWith('ok ('))
}

function okToelichting(waarde: string): string | null {
  const m = /^ok \((.*)\)$/.exec(waarde)
  return m ? m[1] : null
}

export function odooProbeGroen(rapport: Record<string, string> | null | undefined): boolean {
  return Boolean(rapport) && Object.values(rapport ?? {}).length > 0 && Object.values(rapport ?? {}).every((v) => odooProbeOk(v))
}

/** "Rechten-probe groen: grootboek · btw · relaties · journals · facturen · boeken" (mockup stap 3), of
 * bij rood de telling mét verwijzing naar het rapport eronder. */
export function odooProbeSamenvatting(rapport: Record<string, string> | null | undefined): string {
  if (!rapport || Object.keys(rapport).length === 0) return 'Rechten-probe: geen rapport'
  const entries = Object.entries(rapport)
  const groen = entries.filter(([, v]) => odooProbeOk(v))
  if (groen.length === entries.length) return `Rechten-probe groen: ${entries.map(([k]) => odooProbeLabel(k)).join(' · ')}`
  return `Rechten-probe: ${groen.length} van ${entries.length} groen — zie rapport`
}

/** Punt 4 (14-09): oude probe-rapporten en koppel-fouten dragen nog exception-namen ("Odoo niet bereikbaar:
 * HTTPStatusError"); de server vertaalt sinds 14-09 zelf (status + pad + één zin), dit is de vertaling voor wat al
 * opgeslagen staat op bestaande koppelingen. Onbekend = ongewijzigd, nooit informatie wegvertalen. */
const EXCEPTION_VERTALING: [RegExp, string][] = [
  [/HTTPStatusError/, 'Odoo antwoordde met een HTTP-fout — controleer of de URL alleen het domein is (bv. https://naam.odoo.com)'],
  [/ConnectError|ConnectTimeout/, 'geen verbinding met de host — controleer het domein en of de omgeving online is'],
  [/ReadTimeout|WriteTimeout|PoolTimeout|TimeoutException/, 'time-out — Odoo antwoordde niet op tijd, probeer het opnieuw'],
  [/RemoteProtocolError|TransportError|NetworkError/, 'netwerkfout richting Odoo — probeer het opnieuw'],
  [/JSONDecodeError|ValueError/, 'onleesbaar antwoord van Odoo — controleer of de URL alleen het domein is'],
]

export function vertaalOdooFouttekst(tekst: string): string {
  for (const [re, vertaling] of EXCEPTION_VERTALING) {
    if (re.test(tekst)) return tekst.replace(/\b[\w.]*(Error|Timeout|Exception)\b/, vertaling)
  }
  return tekst
}

/** Punt 4 (14-09), spiegel van `app/odoo/ids.py::normaliseer_odoo_url`: webclient-paden (/odoo, /web, /odoo/action-…),
 * trailing slash en query worden scheme + host; zonder scheme = https. Ongeldig = null (de server oordeelt definitief). */
export function normaliseerOdooUrl(invoer: string): string | null {
  const kaal = invoer.trim()
  if (!kaal) return null
  let scheme = 'https'
  let rest = kaal
  const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\/(.*)$/.exec(kaal)
  if (m) {
    if (!/^https?$/i.test(m[1])) return null
    scheme = m[1].toLowerCase()
    rest = m[2]
  }
  const host = rest.split(/[/?#]/, 1)[0].trim().toLowerCase()
  if (!host || /\s/.test(host)) return null
  if (!host.includes('.') && !/^localhost(:\d+)?$/.test(host)) return null
  return `${scheme}://${host}`
}

/** Foutmelding uit een Odoo-422/409: de backend stuurt `detail: {bericht, rapport}` (enkelvoud — anders dan de
 * RLZ-wizard-422 mét `rapporten` per administratie); de api-laag zet `bericht` als message. Punt 3 (14-09): een
 * onbereikbaar-/time-out-fout draagt de context ("tijdens de probe van company 7 (Lusso)") — de kale tekst "De backend is
 * momenteel niet bereikbaar" mag in de wizard niet meer zonder context verschijnen. */
export function odooKoppelFout(err: unknown, context?: { companyId: number; naam: string | null }): { bericht: string; rapport: Record<string, string> | null; onbereikbaar?: boolean } {
  if (err instanceof BackendOnbereikbaarError) {
    const wie = context ? ` van company ${context.companyId}${context.naam ? ` (${context.naam})` : ''}` : ''
    // Onze eigen lange AbortController (odooLangeRequestSignal) meldt zich bij de api-laag als 'netwerk' mét AbortError —
    // voor de gebruiker is dat dezelfde time-out.
    const isTimeout = err.oorzaak === 'timeout' || /AbortError/.test(err.technisch ?? '')
    const bericht =
      isTimeout
        ? `probe onderbroken (time-out na ${Math.round(ODOO_TIMEOUT_TEKST_S)} s)${wie} — probeer deze company los`
        : `backend niet bereikbaar tijdens de probe${wie} (${err.oorzaak === 'server' ? 'gateway-fout' : 'netwerkfout'}) — probeer deze company los`
    return { bericht, rapport: null, onbereikbaar: true }
  }
  const bericht = vertaalOdooFouttekst(err instanceof Error ? err.message : 'Onbekende fout')
  if (err instanceof ApiError && err.detail && typeof err.detail === 'object' && 'rapport' in err.detail) {
    const rapport = (err.detail as { rapport: unknown }).rapport
    if (rapport && typeof rapport === 'object' && Object.keys(rapport as object).length > 0) return { bericht, rapport: rapport as Record<string, string> }
  }
  return { bericht, rapport: null }
}

/** De time-out die de api-laag hanteert voor de lange Odoo-requests, in seconden (alleen voor de melding). */
const ODOO_TIMEOUT_TEKST_S = 90

/** Rapport per onderdeel: groen = chip ok (+ toelichting tussen haakjes als hint), rood = chip blokkerend + de
 * foutregel van de server (oude exception-namen vertaald). */
export function OdooProbeRapport({ rapport, alleenRood = false }: { rapport: Record<string, string>; alleenRood?: boolean }) {
  const entries = Object.entries(rapport).filter(([, v]) => !alleenRood || !odooProbeOk(v))
  if (entries.length === 0) return null
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }} data-testid="odoo-probe-rapport">
      {entries.map(([sleutel, stand]) => {
        const ok = odooProbeOk(stand)
        const toelichting = ok ? okToelichting(stand) : null
        return (
          <li key={sleutel}>
            {odooProbeLabel(sleutel)}: <span className={`chip ${ok ? 'ok' : 'blokkerend'}`}>{ok ? 'ok' : '✗'}</span>
            {toelichting && (
              <span className="hint" style={{ marginLeft: 6, fontSize: 12 }}>
                {toelichting}
              </span>
            )}
            {!ok && (
              <span className="fout" style={{ marginLeft: 6, fontSize: 12 }}>
                {vertaalOdooFouttekst(stand)}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function odooHost(url: string | null | undefined): string {
  if (!url) return ''
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

export function datumNl(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function datumTijdKort(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })}`
}
