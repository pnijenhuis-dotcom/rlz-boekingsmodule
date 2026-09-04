import { ApiError } from '../api/client'

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
}

export function odooProbeLabel(sleutel: string): string {
  return ODOO_PROBE_LABELS[sleutel] ?? sleutel
}

export function odooProbeGroen(rapport: Record<string, string> | null | undefined): boolean {
  return Boolean(rapport) && Object.values(rapport ?? {}).length > 0 && Object.values(rapport ?? {}).every((v) => v === 'ok')
}

/** "Rechten-probe groen: grootboek · btw · relaties · journals · facturen · boeken" (mockup stap 3), of
 * bij rood de telling mét verwijzing naar het rapport eronder. */
export function odooProbeSamenvatting(rapport: Record<string, string> | null | undefined): string {
  if (!rapport || Object.keys(rapport).length === 0) return 'Rechten-probe: geen rapport'
  const entries = Object.entries(rapport)
  const groen = entries.filter(([, v]) => v === 'ok')
  if (groen.length === entries.length) return `Rechten-probe groen: ${entries.map(([k]) => odooProbeLabel(k)).join(' · ')}`
  return `Rechten-probe: ${groen.length} van ${entries.length} groen — zie rapport`
}

/** Foutmelding uit een Odoo-422: de backend stuurt `detail: {bericht, rapport}` (enkelvoud — anders dan de
 * RLZ-wizard-422 mét `rapporten` per administratie); de api-laag zet `bericht` als message. */
export function odooKoppelFout(err: unknown): { bericht: string; rapport: Record<string, string> | null } {
  const bericht = err instanceof Error ? err.message : 'Onbekende fout'
  if (err instanceof ApiError && err.detail && typeof err.detail === 'object' && 'rapport' in err.detail) {
    const rapport = (err.detail as { rapport: unknown }).rapport
    if (rapport && typeof rapport === 'object') return { bericht, rapport: rapport as Record<string, string> }
  }
  return { bericht, rapport: null }
}

/** Rapport per onderdeel: groen = chip ok, rood = chip blokkerend + de foutregel van de server. */
export function OdooProbeRapport({ rapport, alleenRood = false }: { rapport: Record<string, string>; alleenRood?: boolean }) {
  const entries = Object.entries(rapport).filter(([, v]) => !alleenRood || v !== 'ok')
  if (entries.length === 0) return null
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }} data-testid="odoo-probe-rapport">
      {entries.map(([sleutel, stand]) => (
        <li key={sleutel}>
          {odooProbeLabel(sleutel)}: <span className={`chip ${stand === 'ok' ? 'ok' : 'blokkerend'}`}>{stand === 'ok' ? 'ok' : '✗'}</span>
          {stand !== 'ok' && (
            <span className="fout" style={{ marginLeft: 6, fontSize: 12 }}>
              {stand}
            </span>
          )}
        </li>
      ))}
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
