// Voorstel-kaart (blok E5–E9 nachtrun 01/02-09, mockup bank-voorstel-kaart.html = bouwnorm, akkoord
// Peter): per afletter-match de specs van de doel-post — tegenpartij (RLZ-naam), documentsoort +
// factuurnummer/referentie, boekstuknummer, factuurdatum en het open bedrag — álle velden uit de
// bestaande payment_item_cache (Document($expand=Entity)), géén extra RLZ-calls per rij; ontbreekt een
// veld, dan valt die regel weg (nooit een lege of wachtende kaart). Match-reden-chip in de kaart
// (groen = exacte match, oranje = bevestigen mét reden); deelmatch expliciet ("restant € X blijft
// open"); geen match = rustige tekstregel. Eén component, twee plekken (mutatielijst + splitsen-dialoog).
// Puur presentatie: de matchmotor en de volgorde stap 1–5 zijn ongewijzigd.
import type { OpenPostDto, VoorstelDto } from './bankApi'

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

/** Specifieke match-reden (E6) per voorstel-soort — deterministisch uit het bestaande `soort`
 * (de motor bepaalt; dit vertaalt alleen naar klantleesbare copy). */
export function matchChip(voorstel: Pick<VoorstelDto, 'soort'>, deel: boolean): MatchChip | null {
  switch (voorstel.soort) {
    case 'exacte_match':
      return { tekst: 'exacte match — naam + factuurnummer + bedrag', kleur: 'groen' }
    case 'deel_match':
      return {
        tekst: deel ? 'match op naam + referentie, bedrag wijkt af — bevestigen' : 'match op naam + referentie — bevestigen',
        kleur: 'oranje',
      }
    case 'rlz_voorstel':
      return { tekst: 'match op bedrag, geen referentie — bevestigen', kleur: 'oranje' }
    default:
      return null
  }
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
  voorstel: Pick<VoorstelDto, 'soort' | 'open_post'>
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
