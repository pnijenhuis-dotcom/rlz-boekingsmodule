// Factuur ↔ offerte-match op het inkoop-controlescherm (blok B 04-09; mockup
// offerte-matching.html blok 2 = norm, notities ②③⑤).
//
// Het is een MELDING + chip, géén nieuwe check-rij: de harde checks blijven onveranderd en de
// match blokkeert nooit (⑤). Groen = "binnen de goedgekeurde offerte" mét verbruiksbalk; oranje =
// "buiten de offerte" mét het bedrag erover, óf "geen goedgekeurde offerte gevonden" — beide mét
// "Koppel offerte…" en het handelingsperspectief dat meerwerk een eigen verplichting hoort te
// krijgen. `geen_verplichting` rendert niets: er is niets te melden. `niet_toetsbaar` rendert sinds 15-09 (Peter,
// casus Olieman: de offerte wachtte op één accordeur) WÉL als er een verplichting van deze leverancier gevonden is —
// "gevonden maar niet toetsbaar: <reden>" mét "Open de verplichting →" en "Koppel offerte…"; anders stil.
// Peter 18-09 (casus Bouwadvies): het verbruik telt óók de facturen mee die nog niet geboekt zijn (onderweg) — de kaart
// zegt "€ 70.000 van € 1.192.922,50 · waarvan € 20.000 nog niet geboekt (1 factuur ter accordering)" en de balk toont
// geboekt vol, onderweg gearceerd, deze factuur gemarkeerd (zelfde DTO als de accordeur-app).
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button } from '../ui/basis'
import { formatBedrag, formatDatumKort, TERMINALE_STATUSSEN } from '../werkvoorraad/format'
import { VerbruiksBalk } from '../verplichting/VerbruiksBalk'
import {
  haalOfferteMatch,
  MEERWERK_PERSPECTIEF,
  onderwegTekst,
  SOORT_LABEL_TEKST,
  type VerplichtingMatchDto,
} from '../verplichting/verplichtingApi'
import { KoppelOfferteDialog } from './KoppelOfferteDialog'

function SOORT_LABEL_TEXT_OF(label: keyof typeof SOORT_LABEL_TEKST): string {
  return SOORT_LABEL_TEKST[label].toLowerCase()
}

/** Uitkomsten die iets te melden hebben; de rest blijft stil. */
const ZICHTBAAR = new Set(['binnen', 'buiten', 'geen_match', 'meerdere_kandidaten'])

export function OfferteMatchMelding({
  administratieId,
  documentId,
  status,
  soort,
  boekvoorstelVersie = 0,
}: {
  administratieId: string
  documentId: string
  status: string
  soort: string
  /** Ophogen bij een opgeslagen boekvoorstel: het bedrag/project kan gewijzigd zijn, dus opnieuw lezen. */
  boekvoorstelVersie?: number
}) {
  const [match, setMatch] = useState<VerplichtingMatchDto | null>(null)
  const [koppelOpen, setKoppelOpen] = useState(false)
  const relevant = soort === 'inkoopfactuur'

  const laad = useCallback(() => {
    if (!relevant) return
    let actief = true
    haalOfferteMatch(administratieId, documentId)
      .then((m) => {
        if (actief) setMatch(m)
      })
      // Verrijking: een fout hier mag het controlescherm nooit blokkeren (de match is een signaal).
      .catch(() => undefined)
    return () => {
      actief = false
    }
  }, [administratieId, documentId, relevant])

  useEffect(() => {
    const opruimen = laad()
    return opruimen
  }, [laad, status, boekvoorstelVersie])

  if (!relevant || match === null) return null
  const wachtend = match.uitkomst === 'niet_toetsbaar' && Boolean(match.verplichting || match.niet_toetsbaar_reden)
  if (!ZICHTBAAR.has(match.uitkomst) && !wachtend) return null

  const v = match.verplichting
  const isBinnen = match.uitkomst === 'binnen'
  const geboekt = TERMINALE_STATUSSEN.includes(status)
  const termijnTekst = match.termijn ? ` (${match.termijn}e termijn)` : ''
  // Peter 18-09: verbruik = geboekt + onderweg — de zin "waarvan € X nog niet geboekt (N facturen ter accordering)"
  // maakt zichtbaar waarom het cumulatief hoger is dan wat er al geboekt staat.
  const onderwegZin = onderwegTekst(
    match.verbruik_onderweg,
    match.onderweg_aantal,
    match.onderweg_ter_accordering,
    formatBedrag,
  )
  const onderwegProps = {
    aantal: match.onderweg_aantal ?? 0,
    bedrag: match.verbruik_onderweg ?? null,
    terAccordering: match.onderweg_ter_accordering ?? 0,
  }
  const akkoordRegel = v
    ? `${v.leverancier_naam ?? 'leverancier'} · ${v.soort_label ? SOORT_LABEL_TEKST[v.soort_label].toLowerCase() : 'offerte'} ${
        v.offertenummer ?? '(zonder nummer)'
      }${v.goedgekeurd_door_naam ? ` (akkoord ${v.goedgekeurd_door_naam}${v.goedgekeurd_op ? `, ${formatDatumKort(v.goedgekeurd_op)}` : ''})` : ''}`
    : null

  return (
    <div className="panel" data-testid="offerte-match-melding">
      <h2>
        Offerte{' '}
        {isBinnen ? (
          <Badge variant="ok" data-testid="offerte-chip-binnen">
            binnen offerte
          </Badge>
        ) : wachtend ? (
          <Badge variant="stil" data-testid="offerte-chip-wachtend">
            offerte nog niet toetsbaar
          </Badge>
        ) : (
          <Badge variant="warn" data-testid="offerte-chip-buiten">
            buiten offerte
          </Badge>
        )}
        {match.handmatig_gekoppeld && (
          <>
            {' '}
            <Badge variant="paars">handmatig gekoppeld</Badge>
          </>
        )}
      </h2>

      {isBinnen && v && (
        <>
          <p style={{ margin: '0 0 10px' }}>
            ✓ <b>Binnen de goedgekeurde offerte</b> — {akkoordRegel}: deze factuur{termijnTekst}{' '}
            {formatBedrag(match.bedrag_excl)} past; verbruik ná deze factuur {formatBedrag(match.verbruik_na)} van{' '}
            {formatBedrag(v.totaal_excl)}
            {onderwegZin ? <span data-testid="offerte-onderweg"> · {onderwegZin}</span> : null}.
          </p>
          <VerbruiksBalk
            verbruikt={match.verbruik_geboekt ?? match.verbruik_voor}
            labelBedrag={match.verbruik_na}
            onderweg={onderwegProps}
            eigen={match.bedrag_excl}
            totaal={v.totaal_excl}
            percentage={match.percentage_na}
            testId="offerte-balk"
          />
        </>
      )}

      {wachtend && (
        <p style={{ margin: '0 0 10px' }} data-testid="offerte-wachtend">
          ⏳ <b>Offerte van deze leverancier gevonden maar niet toetsbaar</b>
          {v ? ` — ${v.soort_label ? SOORT_LABEL_TEXT_OF(v.soort_label) : 'offerte'} ${v.offertenummer ?? '(zonder nummer)'}` : ''}
          {match.niet_toetsbaar_reden ? `: ${match.niet_toetsbaar_reden}` : ''}. Zodra de offerte is goedgekeurd
          wordt deze factuur automatisch alsnog getoetst; boeken blijft mogelijk.
        </p>
      )}

      {!isBinnen && !wachtend && (
        <>
          <p style={{ margin: '0 0 10px' }}>
            ⚠{' '}
            {match.uitkomst === 'buiten' && v ? (
              <>
                <b>Buiten de offerte</b> — cumulatief {formatBedrag(match.verbruik_na)} van{' '}
                {formatBedrag(v.totaal_excl)}
                {match.overschrijding_excl ? ` (− ${formatBedrag(match.overschrijding_excl)} over)` : ''}
                {onderwegZin ? <span data-testid="offerte-onderweg"> · {onderwegZin}</span> : null}.
              </>
            ) : match.uitkomst === 'meerdere_kandidaten' ? (
              <>
                <b>Meerdere goedgekeurde offertes mogelijk</b> voor deze leverancier + dit project — koppel de juiste
                één keer, daarna wordt die keuze onthouden.
              </>
            ) : (
              <>
                <b>Geen goedgekeurde offerte gevonden</b> voor deze leverancier + dit project.
              </>
            )}
          </p>
          {match.uitkomst === 'buiten' && v && (
            <VerbruiksBalk
              verbruikt={match.verbruik_geboekt ?? match.verbruik_voor}
              labelBedrag={match.verbruik_na}
              onderweg={onderwegProps}
              eigen={match.bedrag_excl}
              totaal={v.totaal_excl}
              percentage={match.percentage_na}
              over={match.overschrijding_excl}
              testId="offerte-balk"
            />
          )}
          <p className="hint" data-testid="meerwerk-perspectief" style={{ marginTop: 0 }}>
            {MEERWERK_PERSPECTIEF} Boeken blijft mogelijk — dit is een signaal, geen blokkade.
          </p>
        </>
      )}

      {match.melding && !wachtend && (
        <p className="hint" style={{ marginTop: 0 }} data-testid="offerte-match-toelichting">
          {match.melding}
        </p>
      )}

      <div className="actions">
        {v && (
          <Link className="btn secondary" to={`/verplichting/${administratieId}/${v.document_id}`}>
            Open de verplichting →
          </Link>
        )}
        {!geboekt && (
          <Button variant="secundair" onClick={() => setKoppelOpen(true)}>
            Koppel offerte…
          </Button>
        )}
      </div>

      {koppelOpen && (
        <KoppelOfferteDialog
          administratieId={administratieId}
          documentId={documentId}
          match={match}
          onGekoppeld={(nieuw) => {
            setMatch(nieuw)
            setKoppelOpen(false)
          }}
          onSluiten={() => setKoppelOpen(false)}
        />
      )}
    </div>
  )
}
