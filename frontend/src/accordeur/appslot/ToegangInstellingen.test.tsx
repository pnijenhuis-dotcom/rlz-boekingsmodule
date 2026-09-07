// Instellingen › Toegang — diagnoseregel (blok 12a 07-09): de laatste koude-start-meting uit de
// lokale opslag als één kopieerbare regel mét web-bundelversie en (native) app-build; zonder meting
// een eerlijke "nog geen koude start gemeten". Puur lokaal — er gaat geen request uit.

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { KOUDE_START_OPSLAG_SLEUTEL, WEB_BUILD_ID } from '../koudeStart'
import { ToegangInstellingen } from './ToegangInstellingen'

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving — in-memory vervanger (patroon standCache.test.ts).
beforeAll(() => {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => opslag.get(k) ?? null,
      setItem: (k: string, v: string) => void opslag.set(k, String(v)),
      removeItem: (k: string) => void opslag.delete(k),
      clear: () => opslag.clear(),
      key: (i: number) => [...opslag.keys()][i] ?? null,
      get length() {
        return opslag.size
      },
    } as Storage,
  })
})

vi.mock('../../api/appSlot', () => ({
  biometrieBeschikbaar: () => Promise.resolve(false),
  isBiometrieAan: () => Promise.resolve(false),
  isDirectVergrendelen: () => Promise.resolve(false),
  ontgrendelMetCode: () => Promise.resolve('ok'),
  wijzigCode: () => Promise.resolve('ok'),
  wisAppSlotLokaal: () => Promise.resolve(),
  zetBiometrieAan: () => Promise.resolve(true),
  zetBiometrieUit: () => Promise.resolve(),
  zetDirectVergrendelen: () => Promise.resolve(),
}))

const METING = {
  versie: 1,
  tijdstip: '2026-09-07T13:05:00',
  build: 'abc1234-20260907-1500',
  overzicht: {
    stappen: { 'app-render': 410, sessie: 2240, 'wachtrij-start': 2250, 'wachtrij-klaar': 2800, 'kaarten-render': 2900 },
    server: { wachtrij: 240 },
    afgeleid: { wachtrijClientMs: 550, wachtrijNetwerkMs: 310, totTotEersteKaartenMs: 2900 },
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.removeItem(KOUDE_START_OPSLAG_SLEUTEL)
})

function renderScherm() {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<ToegangInstellingen sluit={() => {}} uitloggen={() => Promise.resolve()} />)
  return fetchMock
}

describe('ToegangInstellingen — diagnoseregel', () => {
  it('toont de bewaarde meting als één regel (web-build, boot/sessie/server/netwerk/totaal) zonder request', () => {
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, JSON.stringify(METING))
    const fetchMock = renderScherm()
    expect(screen.getByText('Diagnose')).toBeInTheDocument()
    const regel = screen.getByTestId('acc-diagnose')
    expect(regel.tagName).toBe('CODE')
    expect(regel).toHaveTextContent(
      'web abc1234-20260907-1500 · boot 410 ms · sessie 1830 ms · server 240 ms · netwerk 310 ms · totaal 2900 ms · 07-09 13:05',
    )
    expect(regel).not.toHaveTextContent('app ')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('zonder meting: "nog geen koude start gemeten" mét de huidige web-bundelversie', () => {
    renderScherm()
    expect(screen.getByTestId('acc-diagnose')).toHaveTextContent(`web ${WEB_BUILD_ID} · nog geen koude start gemeten`)
  })

  it('native mét @capacitor/app: de app-build (versie + buildnummer) komt in de regel; zonder plugin niet', async () => {
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, JSON.stringify(METING))
    vi.stubGlobal('Capacitor', {
      isNativePlatform: () => true,
      Plugins: { App: { getInfo: () => Promise.resolve({ name: 'Nijenhuis', id: 'nl.aknijenhuis.goedkeuren', version: '1.0', build: '45' }) } },
    })
    renderScherm()
    await waitFor(() => expect(screen.getByTestId('acc-diagnose')).toHaveTextContent('web abc1234-20260907-1500 · app 1.0 (45) · boot 410 ms'))
  })

  it('"Kopiëren" zet de regel op het klembord en bevestigt kort', async () => {
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, JSON.stringify(METING))
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    renderScherm()
    screen.getByRole('button', { name: 'Kopiëren' }).click()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Gekopieerd' })).toBeInTheDocument())
    expect(writeText).toHaveBeenCalledWith(screen.getByTestId('acc-diagnose').textContent)
  })
})
