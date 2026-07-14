import { apiPostJson } from '../api/client'
import type { GeheugenVeldVoorstelDto, GeheugenVoorstelDto } from '../api/types'

/** UI-koppeling van het boekingsgeheugen (B6) aan het controlescherm: ophalen + de pure
 * beslislogica (prefill en chip-stand) los van React, zodat die direct unit-testbaar is —
 * zelfde patroon als bedrag.ts/crediteurSuggesties.ts. */

/** Sleutel waaronder een regel zijn geheugenvoorstel opvraagt: de getrimde omschrijving, of null
 * voor leverancier-niveau (samengevoegde regel, of een regel zonder omschrijving). De echte
 * regel-sleutel-normalisatie gebeurt server-side (app/geheugen/normalisatie.py); dit is alleen
 * de client-side dedupe-sleutel zodat identieke omschrijvingen één request delen. */
export function omschrijvingSleutel(omschrijving: string): string | null {
  const getrimd = omschrijving.trim()
  return getrimd === '' ? null : getrimd
}

/** POST met de omschrijving in de request-body — nooit in de URL (zelfde privacy-regel als
 * IBAN's: URL's belanden in access-logs). */
export function haalGeheugenVoorstel(
  administratieId: string,
  vendorId: string,
  regelOmschrijving: string | null,
): Promise<GeheugenVoorstelDto> {
  return apiPostJson<GeheugenVoorstelDto>(`/administraties/${administratieId}/boekingsgeheugen/voorstel`, {
    vendor_id: vendorId,
    regel_omschrijving: regelOmschrijving,
  })
}

export interface HandmatigeVelden {
  ledgerId: boolean
  taxrateId: boolean
  projectId: boolean
}

export interface GeheugenVulbareRegel {
  ledgerId: string | null
  taxrateId: string | null
  projectId: string | null
  handmatigeVelden: HandmatigeVelden
}

export type GeheugenPrefill = Partial<Pick<GeheugenVulbareRegel, 'ledgerId' | 'taxrateId' | 'projectId'>>

/** Prefill-besluit: uitsluitend velden die leeg zijn én nooit door de gebruiker zijn aangeraakt —
 * een handmatige keuze (ook een expres leeggemaakt veld) wordt nooit overschreven. Project alleen
 * bij projectplicht: zonder plicht is de kolom onzichtbaar en reist project_id niet mee in de PUT. */
export function bepaalPrefill(
  regel: GeheugenVulbareRegel,
  voorstel: GeheugenVoorstelDto,
  projectVerplicht: boolean,
): GeheugenPrefill {
  const vulling: GeheugenPrefill = {}
  if (voorstel.gb.waarde && regel.ledgerId === null && !regel.handmatigeVelden.ledgerId) {
    vulling.ledgerId = voorstel.gb.waarde
  }
  if (voorstel.btw.waarde && regel.taxrateId === null && !regel.handmatigeVelden.taxrateId) {
    vulling.taxrateId = voorstel.btw.waarde
  }
  if (projectVerplicht && voorstel.project.waarde && regel.projectId === null && !regel.handmatigeVelden.projectId) {
    vulling.projectId = voorstel.project.waarde
  }
  return vulling
}

export type GeheugenChipStand =
  /** Huidige waarde = de geheugen-waarde: rustige groene chip, oranje bij laag vertrouwen
   * (gesplitste stem / te weinig bevestiging / btw-leverancier-fallback — de backend-vlag). */
  | { soort: 'bevestigd'; oranje: boolean; telling: number; confidence: number; reden: string | null }
  /** Huidige (extractie- of opgeslagen) waarde wijkt af van het geheugen: oranje markeren,
   * nooit overnemen (domeinbeslissing "Afwijkingen markeren, niet overnemen"). */
  | { soort: 'afwijkend'; waarde: string; telling: number; confidence: number }

/** Chip-besluit per veld. Geen chip zonder geheugen-waarde, en geen chip zodra de gebruiker het
 * veld zelf heeft aangeraakt en iets anders koos — die keuze is van de mens (de leerlus leert er
 * bij het boeken van), markeren als afwijking zou alleen maar nagen. */
export function bepaalGeheugenChip(
  veld: GeheugenVeldVoorstelDto,
  huidigeWaarde: string | null,
  handmatig: boolean,
): GeheugenChipStand | null {
  if (veld.waarde === null) return null
  if (huidigeWaarde === veld.waarde) {
    return { soort: 'bevestigd', oranje: veld.oranje, telling: veld.telling, confidence: veld.confidence, reden: veld.reden }
  }
  if (handmatig) return null
  return { soort: 'afwijkend', waarde: veld.waarde, telling: veld.telling, confidence: veld.confidence }
}

/** Compacte hint-tekst naast een oranje chip — de volledige reden blijft in de tooltip staan. */
export function korteReden(reden: string | null): string | null {
  if (!reden) return null
  return reden
    .replace('alleen rlz-historie, nog geen app-bevestiging', 'uit historie, nog niet bevestigd')
    .replace('leverancier-fallback', 'btw via leverancier-niveau')
}
