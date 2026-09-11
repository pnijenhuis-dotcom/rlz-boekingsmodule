import { apiJson } from '../api/client'
import type { WerkvoorraadOverzichtDto } from '../api/types'

/** Klantenlijst met tellers (mockup #werkvoorraad) — alle administraties binnen de scope van de
 * gebruiker; het scherm verbergt zelf de klanten zonder openstaand werk. */
export function haalWerkvoorraadOverzichtOp(groepId: string | null = null): Promise<WerkvoorraadOverzichtDto> {
  // Blok 8 run 11-09: `groep_id` = server-side filter op het groepskenmerk (administratie is een filter, dit is er één meer).
  return apiJson<WerkvoorraadOverzichtDto>(`/werkvoorraad/overzicht${groepId ? `?groep_id=${encodeURIComponent(groepId)}` : ''}`)
}
