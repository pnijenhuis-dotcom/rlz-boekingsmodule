// Optimistische besluit-verzender (snelheidslaag 2026-08-17, harde ontwerpeis Peter):
// akkoord/afwijzen gaat in de UI per direct door — de server-call loopt hier op de
// achtergrond, sequentieel (FIFO, volgorde van klikken) mét begrensde retry. Faalt een
// besluit definitief, dan meldt de luisteraar dat en komt het document ZICHTBAAR terug in de
// wachtrij — nooit stil verloren (geld-integriteit boven snelheid). Retries zijn veilig:
// de backend behandelt een herhaald besluit idempotent (accordering/service.py,
// _herhaald_besluit — kernprincipe 5).

import { ApiError, BackendOnbereikbaarError } from '../api/client'
import { geefAkkoord, isVoorwaardenVereist, wijsAf, type WachtrijItemDto } from './accordeurApi'

export type BesluitSoort = 'akkoord' | 'afwijzen'

export interface BesluitOpdracht {
  item: WachtrijItemDto
  soort: BesluitSoort
  staandeRegelAanmaken: boolean
  reden: string | null
}

export interface BesluitLuisteraar {
  /** Definitief mislukt (na retries of een harde 4xx): het document hoort zichtbaar terug in
   * de rij. `voorwaardenNodig` = de server eist (opnieuw) het voorwaarden-akkoord. */
  onDefinitiefMislukt: (opdracht: BesluitOpdracht, voorwaardenNodig: boolean) => void
  onAantalOnderwegGewijzigd: (aantal: number) => void
}

export const MAX_POGINGEN = 5
export const BACKOFF_MS = [1000, 3000, 8000, 15000] as const

/** Alleen fouten waarbij het besluit de server mogelijk niet (verwerkt) bereikte zijn het
 * herproberen waard: netwerk/timeout/gateway (BackendOnbereikbaarError) en 5xx. Elke 4xx is
 * een uitspraak van de server over dít verzoek — herhalen verandert daar niets aan. */
function isTijdelijkeFout(fout: unknown): boolean {
  if (fout instanceof BackendOnbereikbaarError) return true
  return fout instanceof ApiError && fout.status >= 500
}

function standaardWacht(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

interface Deps {
  geefAkkoord: typeof geefAkkoord
  wijsAf: typeof wijsAf
  wacht: (ms: number) => Promise<void>
}

export class BesluitVerzender {
  private deps: Deps
  private rij: BesluitOpdracht[] = []
  private onderwegIds = new Set<string>()
  private bezig = false
  private luisteraar: BesluitLuisteraar | null = null
  private generatie = 0

  constructor(deps: Partial<Deps> = {}) {
    this.deps = { geefAkkoord, wijsAf, wacht: standaardWacht, ...deps }
  }

  zetLuisteraar(luisteraar: BesluitLuisteraar | null): void {
    this.luisteraar = luisteraar
  }

  isOnderweg(documentId: string): boolean {
    return this.onderwegIds.has(documentId)
  }

  aantalOnderweg(): number {
    return this.onderwegIds.size
  }

  /** Zet een besluit in de verzendrij. Dubbelklik-vangnet: per document maximaal één besluit
   * tegelijk onderweg. */
  verstuur(opdracht: BesluitOpdracht): void {
    if (this.onderwegIds.has(opdracht.item.document_id)) return
    this.onderwegIds.add(opdracht.item.document_id)
    this.rij.push(opdracht)
    this.meldAantal()
    if (!this.bezig) void this.verwerkRij()
  }

  resetVoorTests(): void {
    this.generatie += 1
    this.rij = []
    this.onderwegIds.clear()
    this.bezig = false
    this.luisteraar = null
  }

  private meldAantal(): void {
    this.luisteraar?.onAantalOnderwegGewijzigd(this.onderwegIds.size)
  }

  private async verwerkRij(): Promise<void> {
    this.bezig = true
    const gen = this.generatie
    while (this.rij.length > 0) {
      const opdracht = this.rij.shift()
      if (!opdracht) break
      await this.verzendMetRetry(opdracht, gen)
      if (gen !== this.generatie) return
      this.onderwegIds.delete(opdracht.item.document_id)
      this.meldAantal()
    }
    this.bezig = false
  }

  private async verzendMetRetry(opdracht: BesluitOpdracht, gen: number): Promise<void> {
    for (let poging = 1; poging <= MAX_POGINGEN; poging++) {
      try {
        await this.voerUit(opdracht)
        return
      } catch (fout) {
        if (gen !== this.generatie) return
        if (!isTijdelijkeFout(fout) || poging === MAX_POGINGEN) {
          this.luisteraar?.onDefinitiefMislukt(opdracht, isVoorwaardenVereist(fout))
          return
        }
        await this.deps.wacht(BACKOFF_MS[Math.min(poging - 1, BACKOFF_MS.length - 1)])
        if (gen !== this.generatie) return
      }
    }
  }

  private async voerUit(opdracht: BesluitOpdracht): Promise<void> {
    const { item } = opdracht
    if (opdracht.soort === 'akkoord') {
      await this.deps.geefAkkoord(item.administratie_id, item.document_id, opdracht.staandeRegelAanmaken)
    } else {
      await this.deps.wijsAf(item.administratie_id, item.document_id, opdracht.reden ?? '')
    }
  }
}

export const besluitVerzender = new BesluitVerzender()
