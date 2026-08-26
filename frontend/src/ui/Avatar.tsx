/* Avatar met initialen en een deterministische kleur (designpass v2, punt 2 — mockup-kaart
 * "Herkenning per administratie"): vaste 8-kleuren-set (--avatar-0…7, tokens.css), keuze =
 * hash(id) mod 8 — zuiver afgeleid, nergens opgeslagen, dus in élke lijst dezelfde kleur voor
 * dezelfde administratie/gebruiker. Puur presentatie. */

/** FNV-1a-achtige 32-bit stringhash — stabiel over sessies en browsers (geen Math.random). */
export function avatarIndex(id: string, aantal = 8): number {
  let h = 0x811c9dc5
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h % aantal
}

/** "Kempen Facilities B.V." → "KF"; één woord → eerste twee letters; rechtsvormen tellen niet. */
export function initialen(naam: string): string {
  const woorden = naam
    .replace(/[()]/g, ' ')
    .split(/[\s\-–_.]+/)
    .filter((w) => w && !/^(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|holding|bv|nv|vof|de|het|van|der|den|&)$/i.test(w))
  if (woorden.length === 0) return naam.slice(0, 2).toUpperCase()
  if (woorden.length === 1) return woorden[0].slice(0, 2).toUpperCase()
  return (woorden[0][0] + woorden[1][0]).toUpperCase()
}

export function Avatar({ id, naam, klein }: { id: string; naam: string; klein?: boolean }) {
  return (
    <span
      className={klein ? 'avatar klein' : 'avatar'}
      style={{ background: `var(--avatar-${avatarIndex(id)})` }}
      aria-hidden="true"
      data-testid="avatar"
    >
      {initialen(naam)}
    </span>
  )
}
