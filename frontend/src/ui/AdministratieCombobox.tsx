import { useMemo } from 'react'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'

/** Doorzoekbare administratie-kiezer (punt 13, opruimrun 28-08): één wrapper op het bestaande
 * SearchableCombobox-patroon (portal, gevirtualiseerd, toetsenbord) voor élke plek waar een
 * administratie gekozen wordt — een kale <select> schaalt niet naar 50 klanten. Zelfde
 * semantiek als de oude selects: `waarde` is een administratie-id of leeg (null/''), `onWijzig`
 * krijgt altijd een id (de combobox kiest nooit "niets"). Referentie-implementatie was
 * document/VerplaatsModal.tsx. `toonLabel={false}` houdt het label als aria-label (tests:
 * getByLabelText blijft werken). */
interface Props {
  label: string
  administraties: ReadonlyArray<{ id: string; naam: string }>
  waarde: string | null | undefined
  onWijzig: (administratieId: string) => void
  placeholder?: string
  toonLabel?: boolean
  vereist?: boolean
  /** Verberg deze id's (bv. de huidige administratie bij "verplaats naar"). */
  uitgesloten?: ReadonlyArray<string>
}

export function AdministratieCombobox({
  label,
  administraties,
  waarde,
  onWijzig,
  placeholder,
  toonLabel = true,
  vereist,
  uitgesloten,
}: Props) {
  const opties = useMemo<ComboboxOptie[]>(
    () =>
      administraties
        .filter((a) => !uitgesloten || !uitgesloten.includes(a.id))
        .map((a) => ({ id: a.id, label: a.naam })),
    [administraties, uitgesloten],
  )
  return (
    <SearchableCombobox
      label={label}
      toonLabel={toonLabel}
      opties={opties}
      waarde={waarde || null}
      onWijzig={(id) => {
        if (id) onWijzig(id)
      }}
      placeholder={placeholder ?? 'Typ om een administratie te zoeken…'}
      vereist={vereist}
    />
  )
}
