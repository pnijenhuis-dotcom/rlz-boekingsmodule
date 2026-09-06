// Koude-start-meting accordeur-app (blok D1 opdracht 06-09): lichtgewicht timing-log rond de
// opstartketen — WebView-boot → eerste render → slot/sessie → wachtrij-/vragen-fetch → eerste
// kaarten. Alle tijden zijn ms sinds `performance.timeOrigin` (= navigatiestart van de webview,
// dus inclusief het laden van de bundel). Uitsluitend lokaal: performance.mark/measure +
// console.debug; in dev/native staat het overzicht óók op `window.__koudeStart` (uitlezen via
// Safari Web Inspector / chrome://inspect). Er gaat NOOIT iets naar de server — dit is
// diagnostiek voor de kliktest, geen telemetrie.
//
// Server-kant: de leesroutes /accordering/wachtrij en /accordering/vragen dragen een
// `Server-Timing: <naam>;dur=<ms>`-header (router.py) — die wordt hier bij de fetch genoteerd
// zodat "wachttijd" te splitsen is in netwerk (client-duur − server-duur) en server.

export type KoudeStartStap =
  | 'app-render' // AccordeurApp is voor het eerst gerenderd (bundel geladen + React gemount)
  | 'slot-status' // native: slot-status bekend (geen/vergrendeld/ontgrendeld)
  | 'slot-ontgrendeld' // native: code/biometrie geaccepteerd, stille refresh start
  | 'sessie' // access-token aanwezig (stille refresh geslaagd óf ontgrendeld/ingelogd)
  | 'cache-render' // eerste kaarten uit de lokale cache getoond (D2)
  | 'wachtrij-start'
  | 'wachtrij-klaar'
  | 'vragen-start'
  | 'vragen-klaar'
  | 'kaarten-render' // eerste kaarten uit VERSE data getoond

export interface ServerTiming {
  naam: string
  duurMs: number
}

export interface KoudeStartOverzicht {
  /** ms sinds navigatiestart, per stap (alleen de stappen die bereikt zijn). */
  stappen: Partial<Record<KoudeStartStap, number>>
  /** Server-duur per leesroute uit de Server-Timing-header (ms). */
  server: Partial<Record<'wachtrij' | 'vragen', number>>
  /** Afgeleide duren (ms): netwerk = client-duur − server-duur. */
  afgeleid: {
    wachtrijClientMs?: number
    wachtrijNetwerkMs?: number
    vragenClientMs?: number
    vragenNetwerkMs?: number
    totTotEersteKaartenMs?: number
  }
}

const PREFIX = 'acc:'

let stappen: Partial<Record<KoudeStartStap, number>> = {}
let server: Partial<Record<'wachtrij' | 'vragen', number>> = {}
let samenvattingGelogd = false

function nu(): number {
  try {
    return Math.round(performance.now())
  } catch {
    return 0
  }
}

/** Parse van een Server-Timing-header ("wachtrij;dur=12.3, db;dur=4") — alleen `dur`-metrics. */
export function parseServerTiming(header: string | null | undefined): ServerTiming[] {
  if (!header) return []
  const uit: ServerTiming[] = []
  for (const deel of header.split(',')) {
    const [naamRuw, ...params] = deel.trim().split(';')
    const naam = naamRuw.trim()
    if (!naam) continue
    for (const p of params) {
      const m = /^\s*dur\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$/.exec(p)
      if (m) uit.push({ naam, duurMs: Number(m[1]) })
    }
  }
  return uit
}

/** Markeert een stap — alleen de EERSTE keer per app-run (een tweede verversing is geen koude
 * start). performance.mark faalt stil waar de API ontbreekt. */
export function markeer(stap: KoudeStartStap): void {
  if (stappen[stap] !== undefined) return
  stappen[stap] = nu()
  try {
    performance.mark(`${PREFIX}${stap}`)
  } catch {
    // geen User Timing API — de eigen tabel volstaat
  }
  if (stap === 'kaarten-render') logSamenvatting()
}

/** Noteert de server-duur van een leesroute (uit de Server-Timing-header van de response). */
export function noteerServerTiming(route: 'wachtrij' | 'vragen', header: string | null | undefined): void {
  if (server[route] !== undefined) return
  const gevonden = parseServerTiming(header).find((t) => t.naam === route)
  if (gevonden) server[route] = gevonden.duurMs
}

function verschil(van: KoudeStartStap, tot: KoudeStartStap): number | undefined {
  const a = stappen[van]
  const b = stappen[tot]
  return a !== undefined && b !== undefined ? b - a : undefined
}

export function overzicht(): KoudeStartOverzicht {
  const wachtrijClientMs = verschil('wachtrij-start', 'wachtrij-klaar')
  const vragenClientMs = verschil('vragen-start', 'vragen-klaar')
  return {
    stappen: { ...stappen },
    server: { ...server },
    afgeleid: {
      wachtrijClientMs,
      wachtrijNetwerkMs:
        wachtrijClientMs !== undefined && server.wachtrij !== undefined
          ? Math.max(0, wachtrijClientMs - server.wachtrij)
          : undefined,
      vragenClientMs,
      vragenNetwerkMs:
        vragenClientMs !== undefined && server.vragen !== undefined ? Math.max(0, vragenClientMs - server.vragen) : undefined,
      totTotEersteKaartenMs: stappen['cache-render'] ?? stappen['kaarten-render'],
    },
  }
}

function inDevOfNative(): boolean {
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor
  return Boolean(import.meta.env?.DEV) || Boolean(cap?.isNativePlatform?.())
}

function logSamenvatting(): void {
  if (samenvattingGelogd) return
  samenvattingGelogd = true
  const o = overzicht()
  try {
    for (const [van, tot] of [
      ['wachtrij-start', 'wachtrij-klaar'],
      ['vragen-start', 'vragen-klaar'],
      ['app-render', 'sessie'],
      ['sessie', 'kaarten-render'],
    ] as [KoudeStartStap, KoudeStartStap][]) {
      if (stappen[van] !== undefined && stappen[tot] !== undefined) {
        performance.measure(`${PREFIX}${van}→${tot}`, `${PREFIX}${van}`, `${PREFIX}${tot}`)
      }
    }
  } catch {
    // measure faalt stil zonder marks
  }
  if (inDevOfNative()) {
    ;(window as { __koudeStart?: KoudeStartOverzicht }).__koudeStart = o
    console.debug('[koude start accordeur-app] ms sinds navigatiestart:', o.stappen, 'server:', o.server, 'afgeleid:', o.afgeleid)
  }
}

/** Alleen voor tests: begin opnieuw (module-singleton). */
export function resetVoorTests(): void {
  stappen = {}
  server = {}
  samenvattingGelogd = false
  try {
    performance.clearMarks()
    performance.clearMeasures()
  } catch {
    // geen User Timing API
  }
}
