// Voorstel-kaart (blok E5–E9 nachtrun 01/02-09, mockup bank-voorstel-kaart.html = bouwnorm, akkoord
// Peter): per afletter-match de specs van de doel-post — tegenpartij (RLZ-naam), documentsoort +
// factuurnummer/referentie, boekstuknummer, factuurdatum en het open bedrag — álle velden uit de
// bestaande payment_item_cache (Document($expand=Entity)), géén extra RLZ-calls per rij; ontbreekt een
// veld, dan valt die regel weg (nooit een lege of wachtende kaart). Match-reden-chip in de kaart
// (groen = exacte match, oranje = bevestigen mét reden); deelmatch expliciet ("restant € X blijft
// open"); geen match = rustige tekstregel. Eén component, twee plekken (mutatielijst + splitsen-dialoog).
// Puur presentatie: de matchmotor en de volgorde stap 1–5 zijn ongewijzigd.
// Blok 2 bundel 08-09: de chip-tekst komt uit `bron` van de motor ("IBAN + nummer + bedrag", "nummer + bedrag, naam
// onbekend") — de kaart verzint geen "naam + referentie" meer als de naam niet getoetst is.
import type { MutatieDto, OpenPostDto, VoorstelDto } from './bankApi'

export function formatBedrag(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined) return '—'
  const getal = typeof bedrag === 'number' ? bedrag : Number(bedrag)
  return getal.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

function centen(bedrag: string | number | null | undefined): number | null {
  if (bedrag === null || bedrag === undefined) return null
  const n = typeof bedrag === 'number' ? bedrag : Number(bedrag)
  return Number.isFinite(n) ? Math.round(Math.abs(n) * 100) : null
}

/** Restant (in centen, ≥ 0) dat ná deze koppeling open blijft op de post: |open| − |mutatie|, cent-exact
 * via gehele centen (nooit float-rekenen op bedragen). null = niet bepaalbaar (ontbrekend bedrag). */
export function restantCenten(mutatieBedrag: string | number | null, openBedrag: string | number | null | undefined): number | null {
  const m = centen(mutatieBedrag)
  const o = centen(openBedrag)
  if (m === null || o === null) return null
  return Math.max(0, o - m)
}

export function isDeelbetaling(mutatieBedrag: string | number | null, openBedrag: string | number | null | undefined): boolean {
  const restant = restantCenten(mutatieBedrag, openBedrag)
  return restant !== null && restant > 0
}

export interface MatchChip {
  tekst: string
  /** groen = exacte match (komt bij opt-in in aanmerking voor auto-afletteren), oranje = bevestigen. */
  kleur: 'groen' | 'oranje'
}

/** Specifieke match-reden (E6) per voorstel-soort — de motor bepaalt wát matchte (`bron`, blok 2 08-09:
 * "naam + nummer + bedrag", "IBAN + nummer + bedrag", "nummer + bedrag, naam onbekend", "naam + nummer, bedrag
 * wijkt af"); dit vertaalt alleen naar klantleesbare copy. `deel` blijft de restant-indicatie (E7). */
export function matchChip(voorstel: Pick<VoorstelDto, 'soort'> & Partial<Pick<VoorstelDto, 'bron' | 'kleur' | 'historie_k' | 'historie_n'>>, deel: boolean): MatchChip | null {
  const bron = voorstel.bron?.trim() || null
  switch (voorstel.soort) {
    case 'exacte_match':
      return { tekst: `exacte match — ${bron ?? 'naam + nummer + bedrag'}`, kleur: 'groen' }
    case 'deel_match':
      return {
        tekst: `match op ${bron ?? (deel ? 'nummer, bedrag wijkt af' : 'twee van drie kenmerken')} — bevestigen`,
        kleur: 'oranje',
      }
    case 'rlz_voorstel':
      return { tekst: 'voorstel Reeleezee — alleen bedrag, geen naam of nummer — bevestigen', kleur: 'oranje' }
    case 'historie_regel':
      return historieChip({ ...voorstel, soort: 'historie_regel', kleur: (voorstel as { kleur?: 'groen' | 'oranje' }).kleur ?? 'oranje' })
    default:
      return null
  }
}

/** Historie-regel (blok B bundel 10-09, stap 3b): "k van n op ‹rekening›" uit `historie_k/_n` + de rekening uit `bron`
 * ("historie: 3 van 3 op 4400 Huur"); groen = 100 % (automatisch-kandidaat), oranje = bevestigen. null = geen historie-regel. */
export function historieChip(voorstel: Pick<VoorstelDto, 'soort' | 'kleur'> & Partial<Pick<VoorstelDto, 'bron' | 'historie_k' | 'historie_n'>>): MatchChip | null {
  if (voorstel.soort !== 'historie_regel') return null
  const bron = voorstel.bron?.trim() ?? ''
  const opIndex = bron.indexOf(' op ')
  const rekening = opIndex >= 0 ? bron.slice(opIndex + 4).trim() : null
  const kvn =
    voorstel.historie_k != null && voorstel.historie_n != null
      ? `${voorstel.historie_k} van ${voorstel.historie_n}`
      : bron.replace(/^historie:\s*/i, '').replace(/\s+op\s+.*$/, '').trim() || null
  const kern = [kvn, rekening ? `op ${rekening}` : null].filter(Boolean).join(' ')
  if (voorstel.kleur === 'groen') return { tekst: `historie-regel${kern ? ` — ${kern}` : ''}`, kleur: 'groen' }
  return { tekst: `historie${kern ? `: ${kern}` : ''} — bevestigen`, kleur: 'oranje' }
}

/** Leesbaar label van de uitval-oorzaak vóór het "—" in de reden ("avg_gate — …" → "AI staat uit (AVG-gate)"). */
export const AI_TOETS_OORZAAK_LABEL: Record<string, string> = {
  avg_gate: 'AI staat uit (AVG-gate)',
  api_key: 'geen API-key',
  kostengrens: 'AI-kostengrens bereikt',
  ai_fout: 'AI-fout/timeout',
}

export function aiToetsOorzaakLabel(oorzaak: string | null | undefined): string {
  if (!oorzaak) return 'onbekende oorzaak'
  return AI_TOETS_OORZAAK_LABEL[oorzaak] ?? oorzaak.replace(/_/g, ' ')
}

/** AI-plausibiliteitstoets (blok B 10-09) op de rij/kaart: `twijfel` = oranje "AI-twijfel: ‹reden›" (niet automatisch
 * geboekt, mens beoordeelt); `overgeslagen` = grijze "zonder AI-toets: ‹reden›" — sinds blok 4 (10-09 avond, besluit
 * Peter "uitval = doorlopen, zichtbaar") betekent dat: de toets viel technisch uit (AVG-gate, API-key, kostengrens,
 * AI-fout) en de automatische boeking loopt/liep door zónder AI-oordeel; controleer steekproefsgewijs.
 * `plausibel`/null = geen chip (de boeking zelf draagt dan de chip "automatisch"). */
export function AiToetsChip({ mutatie }: { mutatie: Pick<MutatieDto, 'ai_toets_uitkomst' | 'ai_toets_reden' | 'ai_toets_op'> }) {
  const uitkomst = mutatie.ai_toets_uitkomst ?? null
  if (uitkomst !== 'twijfel' && uitkomst !== 'overgeslagen') return null
  const reden = mutatie.ai_toets_reden?.trim() || 'geen reden meegegeven'
  const wanneer = formatDatum(mutatie.ai_toets_op ?? null)
  const title = `${
    uitkomst === 'twijfel'
      ? 'De AI-toets twijfelde aan het voorstel — niet automatisch geboekt, een mens beoordeelt.'
      : 'De AI-toets viel technisch uit — de deterministische controles waren groen, de automatische boeking loopt door zónder AI-toets. Controleer steekproefsgewijs.'
  }${wanneer ? ` (${wanneer})` : ''}`
  return (
    <span className={uitkomst === 'twijfel' ? 'chip ai' : 'chip'} title={title} data-testid={`ai-toets-${uitkomst}`}>
      {uitkomst === 'twijfel' ? `AI-twijfel: ${reden}` : `zonder AI-toets: ${reden}`}
    </span>
  )
}

function formatDatum(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric', year: 'numeric' })
}

export const GEEN_MATCH_TEKST = 'Geen open post of regel gevonden — handmatig beoordelen.'

/** Geen match = klein neutraal chipje "handmatig" (iteratie 2, feedback Peter 02-09: op een echte
 * rekening met 40+ handmatige rijen was de herhaalde tekstregel rommelig); de uitleg staat als
 * tooltip op het chipje en éénmalig bij de kolomkop. */
export function HandmatigChip() {
  return (
    <span className="chip handmatig" title={GEEN_MATCH_TEKST} data-testid="voorstel-handmatig">
      handmatig
    </span>
  )
}

/** Kaart voor een afletter-voorstel (exacte_match / deel_match / rlz_voorstel mét open_post). */
export function VoorstelKaart({
  voorstel,
  mutatieBedrag,
  compact = false,
}: {
  voorstel: Pick<VoorstelDto, 'soort' | 'open_post'> & Partial<Pick<VoorstelDto, 'bron'>>
  mutatieBedrag: string | number | null
  /** Splitsen-dialoog: zelfde kaart, zonder de chip (de keuze is daar al gemaakt). */
  compact?: boolean
}) {
  const post: OpenPostDto | null = voorstel.open_post ?? null
  if (!post) return <HandmatigChip />
  const deel = isDeelbetaling(mutatieBedrag, post.bedrag)
  const restant = restantCenten(mutatieBedrag, post.bedrag)
  const chip = compact ? null : matchChip(voorstel, deel)
  const kop = post.tegenpartij_naam ?? post.referentie ?? 'Open post'
  const heeftDocumentDeel = Boolean(post.documentsoort || post.referentie)
  const datum = formatDatum(post.factuurdatum ?? null)
  return (
    <div className={`vk${compact ? ' vk-compact' : ''}`} data-testid="voorstel-kaart">
      <div className="vk-kop">{kop}</div>
      {(heeftDocumentDeel || post.boekstuknummer) && (
        <div className="vk-r">
          {post.documentsoort ? `${post.documentsoort} ` : ''}
          {post.referentie ? <b>{post.referentie}</b> : null}
          {post.boekstuknummer ? `${heeftDocumentDeel ? ' · ' : ''}${post.boekstuknummer}` : ''}
        </div>
      )}
      {(datum || post.bedrag !== null) && (
        <div className="vk-r">
          {datum ? `factuurdatum ${datum}` : ''}
          {datum && post.bedrag !== null ? ' · ' : ''}
          {post.bedrag !== null ? (
            <>
              open <b>{formatBedrag(post.bedrag)}</b>
            </>
          ) : null}
        </div>
      )}
      {deel && restant !== null && (
        <div className="vk-verschil" data-testid="voorstel-deelbetaling">
          deelbetaling — restant {formatBedrag(restant / 100)} blijft open
        </div>
      )}
      {chip && <span className={`chip ${chip.kleur === 'groen' ? 'geheugen' : 'ai'} vk-chip`}>{chip.tekst}</span>}
    </div>
  )
}
