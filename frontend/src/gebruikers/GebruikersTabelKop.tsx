import { GEBRUIKERS_KOLOMMEN, kolomStijl, kopStijl, minimaleTabelbreedte, type GebruikersTab } from './gebruikersKolommen'

/** `<colgroup>` + kopregel van een gebruikers-tabel uit één bron (gebruikersKolommen.ts, blok 2 vervolgrun
 * 10-09 avond): px-breedte per `<col>`, het minimum op de `<th>`, koppen nooit afgekapt
 * (`.gebruikers-tabel th { white-space: nowrap }`). De tabel zelf krijgt `min-width` = de som via
 * `gebruikersTabelStijl` — daaronder scrolt `.tabel-scroll` (actiekolom sticky), nooit kolom-implosie. */
export function GebruikersTabelKop({ tab }: { tab: GebruikersTab }) {
  const kolommen = GEBRUIKERS_KOLOMMEN[tab]
  return (
    <>
      <colgroup>
        {kolommen.map((k) => (
          <col key={k.sleutel} className={`kol-${k.sleutel}`} style={kolomStijl(k)} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {kolommen.map((k) => (
            <th key={k.sleutel} className={k.sleutel === 'acties' ? 'acties' : undefined} style={kopStijl(k)} scope="col">
              {k.kop}
            </th>
          ))}
        </tr>
      </thead>
    </>
  )
}

export function gebruikersTabelStijl(tab: GebruikersTab): { minWidth: number } {
  return { minWidth: minimaleTabelbreedte(tab) }
}
