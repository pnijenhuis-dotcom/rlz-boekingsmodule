/* Run B punt 25 (feedback Peter 02-10: "beter onderscheid maken in de vakjes werken, nu zien we soms door de bomen het bos niet
 * meer"): per projectrij in de matrix een STABIELE, deterministische accentkleur — hash van het projectnummer (de cijferprefix van
 * de projectnaam; zonder nummer de genormaliseerde naam) → index in een palet van 8 contrastveilige tinten (tokens
 * `--projectkleur-0…7`, beide modi, geauditeerd in styles/contrast.test.ts). Zuiver afgeleid, nergens opgeslagen, geen
 * instelling: hetzelfde project krijgt in élke week, elke sessie en elke browser dezelfde tint. Zelfde FNV-1a-hash als
 * ui/Avatar.tsx. Identiteitskleur ≠ semantiek: teal blijft actie, groen blijft status — daarom zit geen van beide tokens in dit
 * palet. */

export const PROJECTKLEUR_AANTAL = 8

/** FNV-1a 32-bit — stabiel over sessies/browsers (geen Math.random). */
function fnv1a(tekst: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < tekst.length; i++) {
    h ^= tekst.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h
}

/** "25147 Hoofddorp (Grunsven)" → { nummer: "25147", rest: " Hoofddorp (Grunsven)" }; zonder cijferprefix → nummer null. Ook ná het
 * voorvoegsel "Afgesloten " (19-09, rij B4) wordt het nummer gelezen; dat voorvoegsel blijft dan in `voorvoegsel` staan. */
export function splitsProjectnummer(naam: string | null): { voorvoegsel: string; nummer: string | null; rest: string } {
  const tekst = naam ?? ''
  const m = /^((?:afgesloten\s+)?)(\d{3,})(\b.*)$/is.exec(tekst)
  if (!m) return { voorvoegsel: '', nummer: null, rest: tekst }
  return { voorvoegsel: m[1], nummer: m[2], rest: m[3] }
}

/** Sleutel voor de kleur: het projectnummer als dat er is, anders de genormaliseerde naam (kleine letters, enkele spaties). */
export function projectKleurSleutel(naam: string | null): string {
  const { nummer } = splitsProjectnummer(naam)
  if (nummer) return nummer
  return (naam ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

/** Index 0…7 in het palet — deterministisch op het projectnummer (of de naam). */
export function projectKleurIndex(naam: string | null, aantal = PROJECTKLEUR_AANTAL): number {
  return fnv1a(projectKleurSleutel(naam)) % aantal
}

/** CSS-waarde voor de rij: `var(--projectkleur-N)`. */
export function projectKleurVar(naam: string | null): string {
  return `var(--projectkleur-${projectKleurIndex(naam)})`
}
