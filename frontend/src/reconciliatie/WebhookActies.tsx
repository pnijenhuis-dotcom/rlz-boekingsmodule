// Handeling "Nu opnieuw" + statuschip op de twee bevindingen van blok `webhooks` (run A 02-10 punt 17, Peter 02-10):
// een event naar Vastly dat de ontvanger (nog) niet kan koppelen (409 `niet_koppelbaar`, koppelcontract §3c) wacht
// mét oplopende cadans (1 u → 6 u → 24 u → dagelijks, max 14 dagen) in status `wacht_op_ontvanger`; ná 14 dagen staat
// het `mislukt` mét de reden uit Vastly's antwoord. Sinds 02-10 avond (besluit Peter, punt 17a) óók de derde soort
// `webhook_aflevering_mislukt`: een storing (5xx/429/timeout) die ná de 7-dagen-cadans nog niet aankwam, of een 4xx-weigering
// (payloadfout, direct mislukt) — chip "mislukt na 7 dagen storing" / "geweigerd (payloadfout)" + dezelfde knop.
// Er is geen outbox-scherm in de kantoor-UI — déze rij is de
// zichtbaarheid: chip "wacht op ontvanger · volgende poging …" (status, groen is het niet) en de knop "Nu opnieuw" (teal
// = actie) die de rij buiten de cadans om direct één afleverronde geeft (server: POST
// /reconciliatie/webhooks/{outbox_id}/nu-opnieuw). Een mislukte handeling is zichtbaar naast de knop, nooit stil.
import { useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export function isWebhookWachtOpOntvanger(r: BevindingDto): boolean {
  return (
    r.blok === 'webhooks' &&
    r.detail?.afwijking_soort === 'webhook_wacht_op_ontvanger' &&
    typeof r.detail?.outbox_id === 'string' &&
    r.administratie_id !== null
  )
}

export function isWebhookNietKoppelbaarVerlopen(r: BevindingDto): boolean {
  return (
    r.blok === 'webhooks' &&
    r.detail?.afwijking_soort === 'webhook_niet_koppelbaar_verlopen' &&
    typeof r.detail?.outbox_id === 'string' &&
    r.administratie_id !== null
  )
}

export function isWebhookAfleveringMislukt(r: BevindingDto): boolean {
  return (
    r.blok === 'webhooks' &&
    r.detail?.afwijking_soort === 'webhook_aflevering_mislukt' &&
    typeof r.detail?.outbox_id === 'string' &&
    r.administratie_id !== null
  )
}

/** Eén van de drie webhook-bevindingen mét handeling "Nu opnieuw". */
export function isWebhookBevindingMetNuOpnieuw(r: BevindingDto): boolean {
  return isWebhookWachtOpOntvanger(r) || isWebhookNietKoppelbaarVerlopen(r) || isWebhookAfleveringMislukt(r)
}

export interface WebhookNuOpnieuwResultaatDto {
  outbox_id: string
  administratie_id: string
  status_voor: string
  status_na: string
  uitkomst: string
}

export function webhookNuOpnieuw(outboxId: string, administratieId: string): Promise<WebhookNuOpnieuwResultaatDto> {
  return apiJson(`/reconciliatie/webhooks/${outboxId}/nu-opnieuw`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

const STATUS_TEKST: Record<string, string> = {
  wacht_op_ontvanger: 'wacht op ontvanger',
  openstaand: 'openstaand',
  afgeleverd: 'afgeleverd',
  mislukt: 'mislukt',
}

function datumTijd(iso: unknown): string | null {
  if (typeof iso !== 'string' || !iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Statuschip van de outbox-rij: status + volgende poging (wachtend) of "mislukt na 14 dagen" (verlopen) + reden. */
export function webhookStatusTekst(r: BevindingDto): string {
  const reden = typeof r.detail?.reden === 'string' ? (r.detail.reden as string) : null
  const pogingen = typeof r.detail?.wacht_pogingen === 'number' ? (r.detail.wacht_pogingen as number) : null
  if (isWebhookNietKoppelbaarVerlopen(r)) {
    const dagen = typeof r.detail?.max_dagen === 'number' ? (r.detail.max_dagen as number) : 14
    return `mislukt na ${dagen} dagen wachten${reden ? ` · ${reden}` : ''}${pogingen !== null ? ` · ${pogingen} pogingen` : ''}`
  }
  if (isWebhookAfleveringMislukt(r)) {
    if (r.detail?.reden_soort === 'payloadfout') return `geweigerd (payloadfout, herhalen zinloos)${reden ? ` · ${reden}` : ''}`
    const dagen = typeof r.detail?.max_dagen === 'number' ? (r.detail.max_dagen as number) : 7
    const storing = typeof r.detail?.storing_pogingen === 'number' ? (r.detail.storing_pogingen as number) : null
    return `mislukt na ${dagen} dagen storing${reden ? ` · ${reden}` : ''}${storing !== null ? ` · ${storing} pogingen` : ''}`
  }
  const volgende = datumTijd(r.detail?.volgende_poging_op)
  return `${STATUS_TEKST.wacht_op_ontvanger}${volgende ? ` · volgende poging ${volgende}` : ''}${reden ? ` · ${reden}` : ''}${
    pogingen !== null ? ` · poging ${pogingen}` : ''
  }`
}

export function WebhookStatusChip({ bevinding }: { bevinding: BevindingDto }) {
  return (
    <span
      className="chip"
      data-status={isWebhookNietKoppelbaarVerlopen(bevinding) || isWebhookAfleveringMislukt(bevinding) ? 'mislukt' : 'wacht_op_ontvanger'}
    >
      {webhookStatusTekst(bevinding)}
    </span>
  )
}

export function NuOpnieuwActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<WebhookNuOpnieuwResultaatDto | null>(null)
  const outboxId = String(bevinding.detail?.outbox_id ?? '')
  const referentie = typeof bevinding.detail?.referentie === 'string' ? (bevinding.detail.referentie as string) : outboxId

  const uitvoeren = async () => {
    if (!outboxId || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await webhookNuOpnieuw(outboxId, bevinding.administratie_id)
      setKlaar(r)
      onGelukt(
        r.status_na === 'afgeleverd'
          ? `${referentie} is alsnog afgeleverd bij Vastly (${r.uitkomst}).`
          : `${referentie} opnieuw aangeboden: ${r.uitkomst}`,
      )
    } catch (err) {
      // 409 = de rij wacht niet (meer), 404 = buiten scope — zichtbaar, nooit stil.
      setFout(err instanceof ApiError ? err.message : 'Nu opnieuw mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <span className="hint">
        {STATUS_TEKST[klaar.status_na] ?? klaar.status_na} — {klaar.uitkomst}
      </span>
    )
  }
  return (
    <>
      <WebhookStatusChip bevinding={bevinding} />{' '}
      <Button variant="primair" maat="klein" onClick={() => void uitvoeren()} disabled={!outboxId || bezig} aria-label={`${referentie} nu opnieuw aanbieden`}>
        {bezig ? 'Bezig…' : 'Nu opnieuw'}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
    </>
  )
}
