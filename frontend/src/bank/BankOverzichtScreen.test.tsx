import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BankOverzichtScreen } from './BankOverzichtScreen'

const ADMIN_MET_OPEN = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_ZONDER_OPEN = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(klanten: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/bank/overzicht')) {
        return Promise.resolve(jsonResponse({ klanten }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/bank']}>
      <Routes>
        <Route path="/bank" element={<BankOverzichtScreen />} />
        <Route path="/bank/:administratieId" element={<p>bankdetail-pagina</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const klantMetOpen = {
  administratie_id: ADMIN_MET_OPEN,
  naam: 'Kempen Groep B.V.',
  open_mutaties: 6,
  oudste_open_datum: '2026-06-29',
  rekeningen: ['ING zakelijk', 'Kas'],
  laatste_sync_op: '2026-08-02T06:00:00Z',
  ooit_gesynchroniseerd: true,
}

const klantZonderOpen = {
  administratie_id: ADMIN_ZONDER_OPEN,
  naam: 'BLOW B.V.',
  open_mutaties: 0,
  oudste_open_datum: null,
  rekeningen: [],
  laatste_sync_op: null,
  ooit_gesynchroniseerd: false,
}

describe('BankOverzichtScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont klanten met open mutaties met teller en rekeningen', async () => {
    installFetchMock([klantMetOpen, klantZonderOpen])
    renderScherm()

    expect(await screen.findByText('Kempen Groep B.V.')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
    expect(screen.getByText('ING zakelijk · Kas')).toBeInTheDocument()
  })

  it('toont nooit-gesynchroniseerde klanten onder "Overige klanten"', async () => {
    installFetchMock([klantMetOpen, klantZonderOpen])
    renderScherm()

    expect(await screen.findByText('BLOW B.V.')).toBeInTheDocument()
    expect(screen.getByText(/nog nooit gesynchroniseerd/)).toBeInTheDocument()
  })

  it('navigeert naar het bankdetail bij klik op een klant', async () => {
    installFetchMock([klantMetOpen])
    renderScherm()

    await userEvent.click(await screen.findByText('Kempen Groep B.V.'))
    expect(await screen.findByText('bankdetail-pagina')).toBeInTheDocument()
  })

  it('toont een nette melding zonder open werk', async () => {
    installFetchMock([klantZonderOpen])
    renderScherm()

    expect(await screen.findByText(/Geen klanten met onverwerkte mutaties/)).toBeInTheDocument()
  })
})
