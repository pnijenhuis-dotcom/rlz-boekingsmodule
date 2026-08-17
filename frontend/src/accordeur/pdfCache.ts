// Factuurbeeld-prefetchcache (snelheidslaag 2026-08-17, harde ontwerpeis Peter: de volgende
// factuur staat direct klaar). De cache dedupliceert blob-fetches per document zodat het
// vooruit-gemonteerde (verborgen) factuurbeeld van de eerstvolgende factuur dezelfde fetch
// deelt als het zichtbare beeld zodra die factuur opent. `snoei` ruimt blob-URL's op buiten
// het actieve venster — mislukkingen worden nooit gecachet (opnieuw openen = nieuwe poging).

import { haalFactuurBlob } from './accordeurApi'

type FactuurFetcher = (administratieId: string, documentId: string) => Promise<string>

interface CacheRij {
  promise: Promise<string>
  url: string | null
  verwijderd: boolean
}

export class FactuurCache {
  private rijen = new Map<string, CacheRij>()
  private fetcher: FactuurFetcher

  constructor(fetcher: FactuurFetcher = haalFactuurBlob) {
    this.fetcher = fetcher
  }

  /** Blob-URL voor dit document — gedeeld tussen prefetch en weergave. */
  haal(administratieId: string, documentId: string): Promise<string> {
    const bestaand = this.rijen.get(documentId)
    if (bestaand) return bestaand.promise
    const rij: CacheRij = { url: null, verwijderd: false, promise: Promise.resolve('') }
    rij.promise = this.fetcher(administratieId, documentId).then(
      (url) => {
        if (rij.verwijderd) {
          URL.revokeObjectURL(url)
        } else {
          rij.url = url
        }
        return url
      },
      (fout: unknown) => {
        if (this.rijen.get(documentId) === rij) this.rijen.delete(documentId)
        throw fout
      },
    )
    this.rijen.set(documentId, rij)
    return rij.promise
  }

  /** Houd alleen het actieve venster vast; al het andere wordt ge-revoked (geheugenrem). */
  snoei(bewaarDocumentIds: string[]): void {
    const bewaar = new Set(bewaarDocumentIds)
    for (const [id, rij] of this.rijen) {
      if (bewaar.has(id)) continue
      rij.verwijderd = true
      if (rij.url) URL.revokeObjectURL(rij.url)
      this.rijen.delete(id)
    }
  }

  resetVoorTests(): void {
    this.snoei([])
  }
}

export const factuurCache = new FactuurCache()
