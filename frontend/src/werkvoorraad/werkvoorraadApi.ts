import { apiJson } from '../api/client'
import type { WerkvoorraadOverzichtDto } from '../api/types'

/** Klantenlijst met tellers (mockup #werkvoorraad) — alle administraties binnen de scope van de
 * gebruiker; het scherm verbergt zelf de klanten zonder openstaand werk. */
export function haalWerkvoorraadOverzichtOp(): Promise<WerkvoorraadOverzichtDto> {
  return apiJson<WerkvoorraadOverzichtDto>('/werkvoorraad/overzicht')
}
