import type { MutatieDto } from './bankApi'

/* Zoekveld op het bankscherm (blok A 16-09, Peter: "graag een zoekveld zodat je kan zoeken op alle openstaande betalingen
 * van 1 partij"). Client-side over de geladen lijst: tegenpartijnaam, IBAN, omschrijving, bedrag (met of zonder
 * punt/komma — "560925,88" en "560.925,88" zijn gelijk), factuur-/boekstuknummers in de omschrijving én in de voorstel-
 * tekst (open post, batch-posten, RLZ-koppelingen), genormaliseerd zoals de referentie-normalisatie van 16-09
 * (spaties tussen cijfergroepen = groepering). Puur; het scherm houdt de term in `?zoek=` (deeplink). */

function stripAccenten(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '')
}

/** Kleine letters, accenten weg, witruimte samengevouwen. */
export function normaliseerTekst(s: string | null | undefined): string {
  return stripAccenten(s ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

/** Cijferkern: alleen cijfers (voor nummers, IBAN's en bedragen — "560.925,88" → "56092588", "NL04 INGB 0117" → "040117"). */
export function cijferkern(s: string | null | undefined): string {
  return (s ?? '').replace(/\D/g, '')
}

/** Een bedrag-string ("-560925.88") als cijferkern zonder teken: "56092588". */
function bedragKern(bedrag: string | null | undefined): string {
  if (bedrag == null) return ''
  return cijferkern(bedrag)
}

/** Alle tekst waarop een mutatie vindbaar is. */
export function zoekvelden(m: MutatieDto): { tekst: string[]; cijfers: string[] } {
  const tekst: (string | null | undefined)[] = [m.tegenpartij_naam, m.omschrijving, m.tegenrekening_iban]
  const cijfers: string[] = [bedragKern(m.bedrag), bedragKern(m.open_bedrag), cijferkern(m.tegenrekening_iban)]
  const post = m.voorstel?.open_post
  if (post) tekst.push(post.tegenpartij_naam, post.referentie, post.klantreferentie, post.boekstuknummer)
  for (const p of m.voorstel?.batch?.posten ?? []) tekst.push(p.tegenpartij_naam, p.referentie, p.klantreferentie, p.boekstuknummer)
  if (m.voorstel?.batch?.sleutel) tekst.push(m.voorstel.batch.sleutel)
  for (const k of m.rlz_koppelingen ?? []) tekst.push(k.boekstuknummer, k.referentie, k.omschrijving)
  const schoon = tekst.filter((t): t is string => Boolean(t && t.trim()))
  // Nummers in vrije tekst: elk cijfer-/nummerdeel óók als kern (zodat "2026 0642" ≡ "20260642").
  for (const t of schoon) cijfers.push(cijferkern(t))
  return { tekst: schoon.map(normaliseerTekst), cijfers: cijfers.filter(Boolean) }
}

/** Matcht een mutatie de zoekterm? Elke spatie-gescheiden term moet ergens treffen (AND); een term met cijfers treft óók
 * op cijferkern (bedrag, IBAN, nummer met/zonder punt, komma of spaties). */
export function mutatieMatcht(m: MutatieDto, zoek: string): boolean {
  const termen = normaliseerTekst(zoek).split(' ').filter(Boolean)
  if (termen.length === 0) return true
  const velden = zoekvelden(m)
  return termen.every((term) => {
    if (velden.tekst.some((t) => t.includes(term))) return true
    const kern = cijferkern(term)
    return kern.length >= 2 && velden.cijfers.some((c) => c.includes(kern))
  })
}

export function filterMutaties(mutaties: MutatieDto[], zoek: string): MutatieDto[] {
  if (!normaliseerTekst(zoek)) return mutaties
  return mutaties.filter((m) => mutatieMatcht(m, zoek))
}

/** Totaal van de getoonde mutaties in gehele centen (nooit float-rekenen op bedragen). */
export function totaalCenten(mutaties: Pick<MutatieDto, 'bedrag' | 'open_bedrag'>[]): number {
  let som = 0
  for (const m of mutaties) {
    const b = m.open_bedrag ?? m.bedrag
    if (b == null) continue
    const n = Number(b)
    if (Number.isFinite(n)) som += Math.round(n * 100)
  }
  return som
}
