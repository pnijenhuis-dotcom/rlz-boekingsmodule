/** Testhulp (punt 2 "groen = niets tonen", 02-10): de herkomst-chips van het controlescherm staan sinds 02-10 achter
 * "Herkomst tonen" per blok. Tests die een herkomst-chip beweren, klappen eerst álle blokken uit — zo blijft élke
 * bestaande bewering staan (de chips zijn verborgen, niet weg). Idempotent: alleen knoppen die nog op "tonen" staan. */
import { fireEvent, screen } from '@testing-library/react'

export async function toonHerkomst(): Promise<void> {
  await screen.findAllByRole('button', { name: /^Herkomst (tonen|verbergen)$/ })
  for (const knop of screen.queryAllByRole('button', { name: 'Herkomst tonen' })) fireEvent.click(knop)
}
