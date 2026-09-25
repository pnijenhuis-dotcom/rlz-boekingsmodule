/** FV-08 (feedbackrun A 25-09, Universal: "bedragen moeten handmatig opgeteld worden, bv. defecten en transporten uit de
 * bijlage"): een bedragveld accepteert een REKENEXPRESSIE — `20+30` → 50,00, `1.250,50*2` → 2.501,00, `(10+5)*2`,
 * `100/3` → 33,33. Eigen parser (shunting-yard), géén `eval`/`Function`. Getallen conform `normaliseerBedrag`: een komma is
 * het decimaalteken (punten zijn dan duizendtal-scheiders), zonder komma is een punt het decimaalteken. Rekenen gebeurt
 * in centen (integers) voor + en −; × en ÷ op het exacte product/quotiënt, het EINDRESULTAAT ROUND_HALF_UP op 2 decimalen.
 * Ongeldig (lege operand, onbekend teken, deling door 0, ongebalanceerde haakjes) = `null` — het veld blijft dan zoals
 * getypt. Een kaal getal is geen expressie (`isExpressie` = false) en blijft ongewijzigd. Code voor cijfers, geen AI. */

const OPERATOREN: Record<string, { prio: number; rechts: boolean }> = {
  '+': { prio: 1, rechts: false },
  '-': { prio: 1, rechts: false },
  '*': { prio: 2, rechts: false },
  '/': { prio: 2, rechts: false },
  '~': { prio: 3, rechts: true }, // unaire min
}

type Token = { soort: 'getal'; waarde: number } | { soort: 'op'; op: string } | { soort: '(' } | { soort: ')' }

/** Half-up op 2 decimalen (zelfde conventie als regelsom.py / bedragModus.rondCenten). */
export function rondHalfUp2(waarde: number): number {
  const teken = waarde < 0 ? -1 : 1
  return (teken * Math.round(Math.abs(waarde) * 100 + Number.EPSILON)) / 100
}

/** Eén getal-token in NL- of punt-notatie → getal; null als het geen getal is. */
function parseGetal(tekst: string): number | null {
  const schoon = tekst.trim()
  if (!schoon) return null
  let genormaliseerd: string
  if (schoon.includes(',')) {
    if (!/^\d{1,3}(\.\d{3})*,\d+$/.test(schoon) && !/^\d+,\d+$/.test(schoon)) return null
    genormaliseerd = schoon.replace(/\./g, '').replace(',', '.')
  } else {
    if (!/^\d+(\.\d+)?$/.test(schoon)) return null
    genormaliseerd = schoon
  }
  const getal = Number(genormaliseerd)
  return Number.isFinite(getal) ? getal : null
}

function tokeniseer(invoer: string): Token[] | null {
  const tokens: Token[] = []
  let i = 0
  const s = invoer.trim().replace(/[×x]/g, '*').replace(/[÷:]/g, '/').replace(/[–—−]/g, '-')
  while (i < s.length) {
    const c = s[i]
    if (/\s/.test(c)) {
      i++
      continue
    }
    if (/[0-9.,]/.test(c)) {
      let j = i
      while (j < s.length && /[0-9.,]/.test(s[j])) j++
      const getal = parseGetal(s.slice(i, j))
      if (getal === null) return null
      const vorige = tokens[tokens.length - 1]
      if (vorige && (vorige.soort === 'getal' || vorige.soort === ')')) return null // "20 30": geen operator ertussen
      tokens.push({ soort: 'getal', waarde: getal })
      i = j
      continue
    }
    if (c === '(' || c === ')') {
      tokens.push({ soort: c })
      i++
      continue
    }
    if (c === '+' || c === '-' || c === '*' || c === '/') {
      const vorige = tokens[tokens.length - 1]
      const unair = c === '-' && (!vorige || vorige.soort === 'op' || vorige.soort === '(')
      if (c === '+' && (!vorige || vorige.soort === 'op' || vorige.soort === '(')) {
        i++ // unaire plus: negeren
        continue
      }
      tokens.push({ soort: 'op', op: unair ? '~' : c })
      i++
      continue
    }
    return null
  }
  return tokens
}

/** Is dit méér dan een kaal getal (dus iets om uit te rekenen)? */
export function isExpressie(invoer: string): boolean {
  const s = invoer.trim()
  if (!s) return false
  if (parseGetal(s) !== null) return false
  return /[+\-*/()×x÷:–—−]/.test(s) && /\d/.test(s)
}

/** Evalueert een expressie deterministisch → bedrag (2 decimalen) of null. Een kaal getal geeft dat getal terug. */
export function evalueerBedragExpressie(invoer: string): number | null {
  const tokens = tokeniseer(invoer)
  if (!tokens || tokens.length === 0) return null
  // Shunting-yard → RPN.
  const uit: Token[] = []
  const stapel: Token[] = []
  for (const t of tokens) {
    if (t.soort === 'getal') uit.push(t)
    else if (t.soort === 'op') {
      const o1 = OPERATOREN[t.op]
      while (stapel.length) {
        const top = stapel[stapel.length - 1]
        if (top.soort !== 'op') break
        const o2 = OPERATOREN[top.op]
        if ((o1.rechts && o1.prio < o2.prio) || (!o1.rechts && o1.prio <= o2.prio)) uit.push(stapel.pop() as Token)
        else break
      }
      stapel.push(t)
    } else if (t.soort === '(') stapel.push(t)
    else {
      let gevonden = false
      while (stapel.length) {
        const top = stapel.pop() as Token
        if (top.soort === '(') {
          gevonden = true
          break
        }
        uit.push(top)
      }
      if (!gevonden) return null
    }
  }
  while (stapel.length) {
    const top = stapel.pop() as Token
    if (top.soort === '(') return null
    uit.push(top)
  }
  // RPN evalueren — + en − in centen (integers), × en ÷ exact.
  const waarden: number[] = []
  for (const t of uit) {
    if (t.soort === 'getal') waarden.push(t.waarde)
    else if (t.soort === 'op') {
      if (t.op === '~') {
        if (waarden.length < 1) return null
        waarden.push(-(waarden.pop() as number))
        continue
      }
      if (waarden.length < 2) return null
      const b = waarden.pop() as number
      const a = waarden.pop() as number
      let r: number
      if (t.op === '+') r = (Math.round(a * 100) + Math.round(b * 100)) / 100
      else if (t.op === '-') r = (Math.round(a * 100) - Math.round(b * 100)) / 100
      else if (t.op === '*') r = a * b
      else {
        if (b === 0) return null
        r = a / b
      }
      if (!Number.isFinite(r)) return null
      waarden.push(r)
    }
  }
  if (waarden.length !== 1) return null
  return rondHalfUp2(waarden[0])
}

/** Bedrag als NL-invoertekst ("2501,00"). */
export function formatBedragInvoer(waarde: number): string {
  return waarde.toFixed(2).replace('.', ',')
}

/** Voor kale bedragvelden (btw-veld): is de invoer een expressie én uitrekenbaar → het resultaat als NL-invoertekst,
 * anders null (niets doen). */
export function rekenBedragExpressieUit(invoer: string): string | null {
  if (!isExpressie(invoer)) return null
  const uitkomst = evalueerBedragExpressie(invoer)
  return uitkomst === null ? null : formatBedragInvoer(uitkomst)
}
