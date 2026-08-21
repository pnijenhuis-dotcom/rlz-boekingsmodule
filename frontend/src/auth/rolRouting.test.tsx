// Rollen-gate-regressie (kliktest Peter 2026-08-21): een veldrol (zzper/uitvoerder/
// detacheerder) die via de web-app binnenkomt mag NOOIT de kantoor-shell zien — zelfde
// fail-closed patroon als de accordeur. De kantoor-shell rendert uitsluitend voor een
// expliciete kantoorrol (allowlist); al het andere (incl. onbekende rollen) landt op
// /accordeur. De backend-403's zijn de echte beveiliging (tests/security/
// test_rol_endpoint_gates.py) — dit bewaakt de routing-laag.

import { render, screen, waitFor } from '@testing-library/react'
import { Suspense } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthContext'
import { isKantoorRol, isVeldRol } from './rollen'
import KantoorApp from '../KantoorApp'

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}

function stubSessie(rol: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (invoer: RequestInfo | URL) => {
      const url = String(invoer)
      if (url.includes('/auth/token/vernieuwen')) {
        return new Response(
          JSON.stringify({ access_token: fakeToken({ sub: crypto.randomUUID(), rol }) }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      // Alle vervolg-calls (werkvoorraad e.d.): leeg antwoord volstaat — het gaat hier
      // uitsluitend om waar de router de gebruiker neerzet.
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function renderOpRoot() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <Suspense fallback={<p>Laden…</p>}>
          <Routes>
            <Route path="/accordeur/*" element={<div data-testid="externe-app-surface" />} />
            <Route path="/*" element={<KantoorApp />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('rol-allowlists (spiegel van backend/app/auth/rollen.py)', () => {
  it('kantoor- en veldrollen sluiten elkaar uit; accordeur en onbekend horen nergens bij', () => {
    for (const rol of ['beheerder', 'boekhouding_projecten', 'boekhouding']) {
      expect(isKantoorRol(rol)).toBe(true)
      expect(isVeldRol(rol)).toBe(false)
    }
    for (const rol of ['zzper', 'uitvoerder', 'detacheerder']) {
      expect(isVeldRol(rol)).toBe(true)
      expect(isKantoorRol(rol)).toBe(false)
    }
    for (const rol of ['klant_accordeur', 'toekomstige_rol', null]) {
      expect(isKantoorRol(rol)).toBe(false)
    }
    expect(isVeldRol('klant_accordeur')).toBe(false)
  })
})

describe('web-routing per rol', () => {
  it.each(['zzper', 'uitvoerder', 'detacheerder', 'klant_accordeur'])(
    'externe rol %s op / → externe app-surface, nooit de kantoor-shell',
    async (rol) => {
      stubSessie(rol)
      renderOpRoot()
      await waitFor(() => expect(screen.getByTestId('externe-app-surface')).toBeInTheDocument())
    },
  )

  it('onbekende (toekomstige) rol valt fail-closed naar de externe surface, niet het kantoor', async () => {
    stubSessie('nog_niet_bestaande_rol')
    renderOpRoot()
    await waitFor(() => expect(screen.getByTestId('externe-app-surface')).toBeInTheDocument())
  })
})
