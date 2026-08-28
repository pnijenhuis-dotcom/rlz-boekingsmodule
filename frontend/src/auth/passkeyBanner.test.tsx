import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { PasskeyToevoegenBanner } from './PasskeyToevoegenBanner'
import { markeerCrossDeviceLogin, markeerPasskeyBannerAfgehandeld, moetPasskeyBannerTonen } from './passkeyBanner'

// Node 22+ schaduwt window.localStorage/sessionStorage in de jsdom-testomgeving met zijn eigen
// (lege) experimental global — in-memory vervanger, zelfde patroon als Meldingen.test.tsx.
function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
    setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
    removeItem: (sleutel: string) => void opslag.delete(sleutel),
    clear: () => opslag.clear(),
    key: (i: number) => [...opslag.keys()][i] ?? null,
    get length() {
      return opslag.size
    },
  }
}

beforeAll(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: inMemoryOpslag() })
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: inMemoryOpslag() })
})

// Kantoor-web banner "Passkey toevoegen op dit apparaat?" (besluit 28-08, mockup
// activatie-mobiel.html §3): alleen ná een cross-device-login, hooguit 1× per apparaat.
describe('passkeyBanner — regel', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('zonder cross-device-login: geen banner', () => {
    expect(moetPasskeyBannerTonen()).toBe(false)
  })

  it('ná een cross-device-login: banner, tot één van beide keuzes is gemaakt — daarna nooit meer op dit apparaat', () => {
    markeerCrossDeviceLogin()
    expect(moetPasskeyBannerTonen()).toBe(true)
    markeerPasskeyBannerAfgehandeld()
    expect(moetPasskeyBannerTonen()).toBe(false)
    // Een volgende cross-device-login op hetzelfde apparaat toont 'm niet opnieuw.
    markeerCrossDeviceLogin()
    expect(moetPasskeyBannerTonen()).toBe(false)
  })
})

function Locatie() {
  const locatie = useLocation()
  return <div data-testid="locatie">{locatie.pathname}</div>
}

describe('PasskeyToevoegenBanner', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('"Passkey toevoegen" → Instellingen › Beveiliging en de banner is definitief weg', async () => {
    markeerCrossDeviceLogin()
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<PasskeyToevoegenBanner />} />
          <Route path="/instellingen/beveiliging" element={<Locatie />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByTestId('passkey-banner')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Passkey toevoegen' }))
    expect(await screen.findByTestId('locatie')).toHaveTextContent('/instellingen/beveiliging')
    expect(moetPasskeyBannerTonen()).toBe(false)
  })

  it('"Niet nu" sluit en onthoudt de keuze', async () => {
    markeerCrossDeviceLogin()
    render(
      <MemoryRouter>
        <PasskeyToevoegenBanner />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Niet nu' }))
    expect(screen.queryByTestId('passkey-banner')).toBeNull()
    expect(moetPasskeyBannerTonen()).toBe(false)
  })

  it('rendert niets zonder cross-device-login', () => {
    render(
      <MemoryRouter>
        <PasskeyToevoegenBanner />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('passkey-banner')).toBeNull()
  })
})
