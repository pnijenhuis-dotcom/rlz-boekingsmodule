import { useGroepen } from '../instellingen/groepen'
import { groepLabel } from '../instellingen/groepen'
import { Select } from './basis'

/** Filter "Groep" voor kantoorbrede overzichten (blok 8 run 11-09: klantenlijst + Inzicht › Reconciliatie).
 * Administratie is een FILTER (Kernprincipe 7) — dit is er één meer: de keuze reist als querystring-param mee
 * (`?groep=` op de werkvoorraad, `?groep_id=` op de reconciliatie) en gaat server-side als `groep_id` mee.
 * Rendert NIETS zolang er geen groepen zijn of de lijst niet laadt — geen lege select, geen blokkade. Een gekozen
 * gearchiveerde groep blijft kiesbaar (deeplink), gemarkeerd "(gearchiveerd)". */
export function GroepFilter({
  waarde,
  onWijzig,
  label = 'Groep',
}: {
  waarde: string | null
  onWijzig: (groepId: string | null) => void
  label?: string
}) {
  const { groepen } = useGroepen(true)
  if (!groepen || groepen.length === 0) return null
  const zichtbaar = groepen.filter((g) => g.actief || g.id === waarde)
  if (zichtbaar.length === 0) return null
  return (
    <Select
      aria-label={label}
      data-testid="groep-filter"
      value={waarde ?? ''}
      onChange={(e) => onWijzig(e.target.value || null)}
      style={{ width: 'auto' }}
    >
      <option value="">{label}: alle</option>
      {zichtbaar.map((g) => (
        <option key={g.id} value={g.id}>
          {label}: {groepLabel(g)}
          {g.aantal_administraties ? ` (${g.aantal_administraties})` : ''}
        </option>
      ))}
    </Select>
  )
}
