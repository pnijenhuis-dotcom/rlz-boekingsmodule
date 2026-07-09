import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Zonder dit blijft de DOM van elke render() staan tussen tests binnen hetzelfde bestand —
// onopgemerkt zolang tests op unieke tekst zoeken, maar botst zodra twee tests dezelfde
// label/rol-tekst gebruiken (bv. meerdere "Controleren"-knoppen na elkaar).
afterEach(() => {
  cleanup()
})
