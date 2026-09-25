#!/usr/bin/env node
// Tabwissel-meting (blok 7 feedbackrun A 25-09, FV-18 "scherm loopt vast bij wisselen tabblad"): drijft headless Chrome
// via het DevTools-protocol (raw WebSocket, Node ≥ 22 — geen npm-dependency, geen Playwright) naar het werkvoorraad-
// harnas mét een productie-achtige lijst (?docs=N) en laat de pagina zelf K × wisselen (?tabwissel=K). Bewust GEEN
// --virtual-time-budget/--dump-dom (overflow_sweep-recept): onder virtuele tijd staat performance.now() stil tijdens een
// lange taak en meet je 0 ms voor precies het werk dat je wilt zien. Hier loopt de échte klok.
//
// Gebruik (vanuit frontend/, vite moet draaien op POORT — scripts/tabwissel_meting.sh regelt dat):
//   node scripts/tabwissel_meting.mjs --poort=5207 --docs=400 --wissels=20 [--latency=0] [--max-ms=500] [--json]
// Exit 0 = meting binnen de grenzen (max ms per wissel ≤ --max-ms én 0 open fetches ná de lus), 1 = grens overschreden,
// 2 = meting mislukt (harnas/Chrome). Print altijd de meting (ook rood) plus console-fouten uit de pagina.
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const arg = (naam, standaard) => {
  const t = process.argv.find((a) => a.startsWith(`--${naam}=`))
  return t ? t.slice(naam.length + 3) : standaard
}
const POORT = Number(arg('poort', process.env.POORT ?? '5199'))
const DOCS = Number(arg('docs', '400'))
const WISSELS = Number(arg('wissels', '20'))
const LATENCY = Number(arg('latency', '0'))
const MAX_MS = Number(arg('max-ms', '500'))
const ALS_JSON = process.argv.includes('--json')
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const DEBUG_POORT = Number(arg('debug-poort', '9337'))
// --poll=1: een deel van de rijen staat in extractie_wachtrij/wordt_geboekt → de 3-s-poll van de lijst is actief (productie-
// situatie zodra één document bij de wachtrij/achtergrond-schrijver staat); --strict=0: zonder React StrictMode (dev-dubbelrender).
const POLL = arg('poll', '0')
const STRICT = arg('strict', '1')
const URL_ = `http://localhost:${POORT}/harness-werkvoorraad.html?docs=${DOCS}&tabwissel=${WISSELS}&latency=${LATENCY}&poll=${POLL}&strict=${STRICT}`

const profiel = mkdtempSync(join(tmpdir(), 'tabwissel-chrome-'))
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    `--user-data-dir=${profiel}`,
    `--remote-debugging-port=${DEBUG_POORT}`,
    '--window-size=1440,1600',
    '--enable-precise-memory-info',
    'about:blank',
  ],
  { stdio: ['ignore', 'ignore', 'pipe'] },
)
let chromeStderr = ''
chrome.stderr.on('data', (d) => {
  chromeStderr += String(d)
})
const opruimen = () => {
  try {
    chrome.kill('SIGKILL')
  } catch {
    // al weg
  }
  try {
    rmSync(profiel, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
  } catch {
    // Chrome schrijft soms nog een lockbestand weg tijdens SIGKILL — een achtergebleven tmp-map is geen meetfout.
  }
}
process.on('exit', opruimen)

const slaap = (ms) => new Promise((r) => setTimeout(r, ms))

async function wachtOpDebugger() {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${DEBUG_POORT}/json`)
      if (r.ok) return await r.json()
    } catch {
      // nog niet op
    }
    await slaap(100)
  }
  throw new Error(`Chrome DevTools niet bereikbaar op ${DEBUG_POORT}\n${chromeStderr}`)
}

class Cdp {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.wachtend = new Map()
    this.console = []
    this.fouten = []
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(String(ev.data))
      if (m.id && this.wachtend.has(m.id)) {
        const { resolve, reject } = this.wachtend.get(m.id)
        this.wachtend.delete(m.id)
        if (m.error) reject(new Error(m.error.message))
        else resolve(m.result)
      } else if (m.method === 'Runtime.consoleAPICalled') {
        const tekst = (m.params.args ?? []).map((a) => a.value ?? a.description ?? '').join(' ')
        this.console.push(`${m.params.type}: ${tekst}`)
      } else if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails
        this.fouten.push(d.exception?.description ?? d.text)
      }
    })
  }
  stuur(method, params = {}) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      this.wachtend.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async evalueer(expressie) {
    const r = await this.stuur('Runtime.evaluate', { expression: expressie, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text)
    return r.result.value
  }
}

function toon(uit, meta) {
  if (ALS_JSON) {
    console.log(JSON.stringify({ ...uit, ...meta }, null, 2))
    return
  }
  console.log(`tabwissel-meting: docs=${uit.docs} wissels=${uit.wissels} latency=${uit.latency} ms poll=${POLL} strict=${STRICT}`)
  console.log(`  ms per wissel     max ${uit.maxMs} · gem ${uit.gemMs} · reeks ${uit.tijden.join(',')}`)
  console.log(`  rijen per wissel  ${uit.rijen.join(',')}`)
  console.log(`  fetches           tijdens de lus ${uit.fetchGestartTijdens} · open ná de lus ${uit.fetchOpen} · afgebroken ${uit.fetchAfgebroken} · totaal ${uit.fetchTotaal}`)
  console.log(`  fetch per pad     ${Object.entries(uit.fetchPerUrl).map(([k, v]) => `${k}=${v}`).join(' ')}`)
  console.log(`  React-commits     tijdens de lus ${uit.commitsTijdens} (${(uit.commitsTijdens / uit.wissels).toFixed(1)} per wissel) · totaal ${uit.commitsTotaal} · render-ms totaal ${uit.renderMsTotaal}`)
  console.log(`  lange taken       ${uit.langeTaken} (langste ${uit.langsteTaakMs} ms) · heap ${uit.heapMb ?? '?'} MB · eerste render tot lijst ${meta.eersteRenderMs} ms`)
  if (uit.commitDuur) console.log(`  commit-duur (ms)  laatste ${uit.commitDuur.length}: ${uit.commitDuur.join(',')}`)
  if (uit.fetchEcht && uit.fetchEcht.length) console.log(`  buiten de mock    ${uit.fetchEcht.join(' | ')}`)
  if (meta.console.length) console.log(`  console (${meta.console.length}): ${meta.console.slice(0, 8).join(' | ').slice(0, 900)}`)
  if (meta.fouten.length) console.log(`  FOUTEN (${meta.fouten.length}): ${meta.fouten.slice(0, 5).join(' | ').slice(0, 900)}`)
}

try {
  const targets = await wachtOpDebugger()
  const pagina = targets.find((t) => t.type === 'page')
  if (!pagina) throw new Error('geen page-target')
  const ws = new WebSocket(pagina.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve)
    ws.addEventListener('error', reject)
  })
  const cdp = new Cdp(ws)
  await cdp.stuur('Runtime.enable')
  await cdp.stuur('Page.enable')
  const t0 = Date.now()
  await cdp.stuur('Page.navigate', { url: URL_ })
  let klaar = null
  let eersteRenderMs = null
  for (let i = 0; i < 1800; i++) {
    await slaap(100)
    if (eersteRenderMs === null) {
      const lijst = await cdp.evalueer(`document.querySelector('table.documenten-tabel') !== null`).catch(() => false)
      if (lijst) eersteRenderMs = Date.now() - t0
    }
    const stand = await cdp.evalueer(`document.body.dataset.tabwisselKlaar ?? ''`).catch(() => '')
    if (stand === 'ja' || stand === 'fout') {
      klaar = stand
      break
    }
  }
  if (klaar !== 'ja') {
    const fout = await cdp.evalueer(`document.body.dataset.tabwisselFout ?? ''`).catch(() => '')
    console.error(`tabwissel-meting MISLUKT (${klaar ?? 'timeout 180 s'}): ${fout}`)
    if (cdp.fouten.length) console.error(cdp.fouten.join('\n'))
    process.exit(2)
  }
  const uit = JSON.parse(await cdp.evalueer(`document.body.dataset.tabwisselJson`))
  const meta = { eersteRenderMs, console: cdp.console, fouten: cdp.fouten }
  toon(uit, meta)
  ws.close()
  // Mét actieve poll mag er ná de lus precies één lijst-request onderweg zijn (de tik van 3 s valt altijd ergens in het
  // trailing venster); zonder poll moet alles afgerond of afgebroken zijn. Tijdens de lus zelf hoort een tabwissel géén
  // request te starten — behalve de poll-tikken (max één per 3 s, nooit gestapeld).
  const maxOpen = POLL === '1' ? 1 : 0
  const maxTijdens = POLL === '1' ? Math.ceil((uit.gemMs * uit.wissels + 1500) / 3000) + 1 : 0
  const rood = uit.maxMs > MAX_MS || uit.fetchOpen > maxOpen || uit.fetchGestartTijdens > maxTijdens || cdp.fouten.length > 0
  if (rood) {
    console.log(`RESULTAAT: ROOD — grens max ${MAX_MS} ms/wissel, ≤ ${maxOpen} open fetch(es), ≤ ${maxTijdens} fetch(es) tijdens de lus, 0 paginafouten`)
    process.exit(1)
  }
  console.log(`RESULTAAT: GROEN — max ${uit.maxMs} ms/wissel ≤ ${MAX_MS}, ${uit.fetchOpen} open fetch(es) ≤ ${maxOpen}, ${uit.fetchGestartTijdens} fetch(es) tijdens de lus ≤ ${maxTijdens}, 0 paginafouten`)
  process.exit(0)
} catch (err) {
  console.error(`tabwissel-meting MISLUKT: ${err instanceof Error ? err.message : String(err)}`)
  process.exit(2)
}
