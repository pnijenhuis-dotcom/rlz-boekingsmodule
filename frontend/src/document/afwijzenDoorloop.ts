// Afwijzen vanuit een reviewscherm zonder eigen lijstcontext (verkoop, kassarapport — run D 02-10 blok C): dezelfde
// doorloop als het inkoop-controlescherm ná afwijzen (`DocumentDetailScreen.naVerwerking`): het volgende verwerkbare
// document in de lijstvolgorde van de administratie (positioneel, cyclisch — `kiesVolgendDocument`, besluit Peter
// 07-09), anders terug naar de documentenlijst mét het actieve filter. De route volgt de soort van het volgende
// document (`documentRoute`), nooit een vast inkooppad.
import { apiJson } from '../api/client'
import type { DocumentListResponseDto } from '../api/types'
import { documentRoute } from '../werkvoorraad/format'
import { lijstRoute, type LijstContext } from '../werkvoorraad/lijstContext'
import { kiesVolgendDocument } from '../werkvoorraad/volgendDocument'

/** Statussen waaruit afgewezen kan worden — spiegel van `app/documenten/afwijzen.py::_HERSTELBARE_HERKOMSTEN`
 * (zelfde herstelbare herkomsten als bij vragen; heropenen keert er exact naar terug). De backend blijft de poort.
 * Een `klaar_om_te_boeken`-document ná "Corrigeren…" valt hier dus ook onder. */
export const AFWIJSBARE_STATUSSEN: ReadonlySet<string> = new Set(['te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken'])

export function isAfwijsbaar(status: string): boolean {
  return AFWIJSBARE_STATUSSEN.has(status)
}

/** Route ná een geslaagde afwijzing: volgende document in de lijst, anders de lijst zelf. Een onleesbare lijst =
 * terug naar de lijst (die toont de fout zelf). */
export async function routeNaAfwijzen(
  administratieId: string,
  documentId: string,
  context: LijstContext | null = null,
): Promise<string> {
  const doel = lijstRoute(administratieId, context)
  try {
    const lijst = await apiJson<DocumentListResponseDto>(`/administraties/${administratieId}/documenten`)
    const volgende = kiesVolgendDocument(lijst.documenten, documentId, context)
    return volgende ? documentRoute(administratieId, volgende, context) : doel
  } catch {
    return doel
  }
}
