import type { IncomingMessage } from 'node:http'

/** Proxy-opbouw + bypass-logica voor vite.config.ts, als eigen module zodat
 * src/api/proxyDekking.test.ts het gedrag direct kan toetsen.
 *
 * Randgeval kliktest 2026-08-08: een browser-NAVIGATIE naar een pad mét trailing slash
 * (bv. /bank/) matcht de gegenereerde segment-key 'bank/' en kwam zo bij de backend uit —
 * backend-404 als kale JSON-pagina i.p.v. de SPA-route. Een document-navigatie hoort nooit
 * naar de backend: de bypass herkent 'm aan Accept: text/html ÉN Sec-Fetch-Dest: document
 * (dubbele voorwaarde — downloads via <a download> hebben dest 'empty', fetch/XHR stuurt
 * geen text/html-accept) en serveert dan de SPA. fetch/XHR blijft gewoon geproxied. */

export function isDocumentNavigatie(headers: IncomingMessage['headers']): boolean {
  const accept = headers.accept ?? ''
  const dest = headers['sec-fetch-dest'] ?? ''
  return accept.includes('text/html') && dest === 'document'
}

interface ProxyPrefixes {
  segmenten: string[]
  exacte_paden: string[]
}

export interface ProxyEntry {
  target: string
  bypass: (req: IncomingMessage) => string | undefined
}

export function bouwProxyMap(prefixes: ProxyPrefixes, backend: string): Record<string, ProxyEntry> {
  const entry: ProxyEntry = {
    target: backend,
    bypass: (req) => (isDocumentNavigatie(req.headers) ? '/index.html' : undefined),
  }
  return Object.fromEntries([
    ...prefixes.segmenten.map((segment): [string, ProxyEntry] => [`${segment}/`, entry]),
    ...prefixes.exacte_paden.map((pad): [string, ProxyEntry] => [pad, entry]),
  ])
}
