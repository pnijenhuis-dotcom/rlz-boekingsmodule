// Instellingen › Toegang — diagnoseregel (blok 12a 07-09): de laatste koude-start-meting uit de
// lokale opslag als één kopieerbare regel mét web-bundelversie en (native) app-build; zonder meting
// een eerlijke "nog geen koude start gemeten". Puur lokaal — er gaat geen request uit.

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { SLOT_MODUS_SLEUTEL } from '../../api/webVeiligeOpslag'
import { APPSLOT_AUDIT_SLEUTEL } from '../appAuthApi'
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
  CODE_LENGTE: 5,
  isZwakkeCode: () => false,
  haalCredentialId: () => Promise.resolve('cred-1'),
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

// Blok 2b (08-09): de laatste verbindingsfout van het slot staat als staart in dezelfde regel — lokaal, geen request.
describe('ToegangInstellingen — laatste verbindingsfout (2b)', () => {
  it('toont oorzaak + tijdstip achter de koude-start-meting', () => {
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, JSON.stringify(METING))
    localStorage.setItem(
      'accordeur-laatste-verbindingsfout',
      JSON.stringify({ versie: 1, tijdstip: '2026-09-08T10:12:00', oorzaak: 'timeout', technisch: 'AbortError: afgebroken', pad: '/auth/token/vernieuwen' }),
    )
    const fetchMock = renderScherm()
    expect(screen.getByTestId('acc-diagnose')).toHaveTextContent(
      'totaal 2900 ms · 07-09 13:05 · laatste verbindingsfout: timeout (AbortError: afgebroken) 08-09 10:12',
    )
    expect(fetchMock).not.toHaveBeenCalled()
    localStorage.removeItem('accordeur-laatste-verbindingsfout')
  })
})

// App-auth zonder passkey (contract §5d, 08-09): toegangscode wijzigen mét server-event (zonder code) +
// lokale audit-regel, en "Dit toestel loskoppelen".
describe('ToegangInstellingen — toegangscode wijzigen + loskoppelen (§5d)', () => {
  async function tikCode(code: string) {
    for (const c of code) await userEvent.click(screen.getByRole('button', { name: c }))
  }

  function renderMetFetch(uitloggen = vi.fn(() => Promise.resolve())) {
    const aanroepen: { methode: string; pad: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        aanroepen.push({ methode: init?.method ?? 'GET', pad: String(invoer), body: init?.body ?? null })
        return Promise.resolve(new Response(null, { status: 204 }))
      }),
    )
    render(<ToegangInstellingen sluit={() => {}} uitloggen={uitloggen} />)
    return { aanroepen, uitloggen }
  }

  it('rijen heten "Toegangscode wijzigen" en "Dit toestel loskoppelen"; zonder wijziging geen "Laatste wijziging"', () => {
    renderMetFetch()
    expect(screen.getByText('Toegangscode wijzigen')).toBeInTheDocument()
    expect(screen.getByText('Dit toestel loskoppelen')).toBeInTheDocument()
    expect(screen.queryByTestId('acc-laatste-wijziging')).toBeNull()
    expect(screen.queryByText(/Face ID gebruiken/)).toBeNull()
  })

  it('huidige code → nieuwe code 2× → melding, POST /auth/app/toegangscode-gewijzigd (leeg body) + lokale audit-regel', async () => {
    const { aanroepen } = renderMetFetch()
    await userEvent.click(screen.getByText('Toegangscode wijzigen'))
    expect(screen.getByText('Voer je huidige toegangscode in')).toBeInTheDocument()
    await tikCode('13579')
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
    await tikCode('24680')
    await screen.findByText('Nog één keer')
    await tikCode('24680')
    expect(await screen.findByText('Je toegangscode is gewijzigd.')).toBeInTheDocument()
    await waitFor(() => expect(aanroepen.some((a) => a.pad === '/auth/app/toegangscode-gewijzigd' && a.methode === 'POST')).toBe(true))
    expect(aanroepen.find((a) => a.pad === '/auth/app/toegangscode-gewijzigd')!.body).toBeNull()
    const audit = JSON.parse(localStorage.getItem(APPSLOT_AUDIT_SLEUTEL) ?? '[]') as { actie: string; tijdstip: string }[]
    expect(audit).toHaveLength(1)
    expect(audit[0].actie).toBe('toegangscode_gewijzigd')
    expect(JSON.stringify(audit)).not.toContain('24680')
    expect(screen.getByTestId('acc-laatste-wijziging')).toHaveTextContent(/^Laatste wijziging: \d\d-\d\d \d\d:\d\d$/)
    localStorage.removeItem(APPSLOT_AUDIT_SLEUTEL)
  })

  it('"Dit toestel loskoppelen" → bevestiging → POST /auth/app-lock/ontkoppelen, slot-vlag weg, uitloggen aangeroepen', async () => {
    localStorage.setItem(SLOT_MODUS_SLEUTEL, '1')
    const { aanroepen, uitloggen } = renderMetFetch()
    await userEvent.click(screen.getByText('Dit toestel loskoppelen'))
    expect(screen.getByText('Dit toestel loskoppelen?')).toBeInTheDocument()
    expect(
      screen.getByText('Wist de toegang op dit toestel en trekt het toestel bij het kantoor in. Opnieuw koppelen kan met een nieuwe uitnodiging.'),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ja, koppel dit toestel los' }))
    await waitFor(() => expect(uitloggen).toHaveBeenCalledTimes(1))
    expect(aanroepen.some((a) => a.pad === '/auth/app-lock/ontkoppelen' && a.methode === 'POST')).toBe(true)
    expect(localStorage.getItem(SLOT_MODUS_SLEUTEL)).toBeNull()
  })
})
