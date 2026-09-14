import { kolomStijl, kopStijl } from '../gebruikers/gebruikersKolommen'
import { VELDWERKERS_KOLOMMEN, minimaleVeldwerkersTabelbreedte } from './veldwerkersKolommen'

/** `<colgroup>` + kopregel van de tabel op /veldwerkers uit één bron (veldwerkersKolommen.ts) — hetzelfde
 * patroon als `gebruikers/GebruikersTabelKop.tsx` (blok 2 vervolgrun 10-09): px-breedte per `<col>`, het
 * minimum op de `<th>`, koppen nooit afgekapt (`.gebruikers-tabel th { white-space: nowrap }`). De tabel
 * krijgt `min-width` = de som via `veldwerkersTabelStijl` — daaronder scrolt `.tabel-scroll` (actiekolom
 * sticky), nooit kolom-implosie. Bewust een eigen kop i.p.v. een generalisatie van GebruikersTabelKop: die
 * is gebonden aan `GebruikersTab` en de drie Gebruikers-tabs blijven ongewijzigd. */
export function VeldwerkersTabelKop() {
  return (
    <>
      <colgroup>
        {VELDWERKERS_KOLOMMEN.map((k) => (
          <col key={k.sleutel} className={`kol-${k.sleutel}`} style={kolomStijl(k)} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {VELDWERKERS_KOLOMMEN.map((k) => (
            <th key={k.sleutel} className={k.sleutel === 'acties' ? 'acties' : undefined} style={kopStijl(k)} scope="col">
              {k.kop}
            </th>
          ))}
        </tr>
      </thead>
    </>
  )
}

export function veldwerkersTabelStijl(): { minWidth: number } {
  return { minWidth: minimaleVeldwerkersTabelbreedte() }
}
