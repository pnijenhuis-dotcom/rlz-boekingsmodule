// "Wat is nieuw"-knop (D1, 01-09): ongelezen-dot per gebruiker, openen toont de releases en markeert gelezen.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { RELEASES } from './changelog'
import { WatIsNieuwKnop } from './WatIsNieuw'

// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon WerkvoorraadScreen.test.tsx).
function installeerLocalStorage() {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
      setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
      removeItem: (sleutel: string) => void opslag.delete(sleutel),
      clear: () => opslag.clear(),
    },
  })
}

function fakeAccessToken(sub: string): string {
  const payload = btoa(JSON.stringify({ sub, rol: 'boekhouding' })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function renderKnop(sub = 'gebruiker-1') {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      url === '/auth/token/vernieuwen'
        ? Promise.resolve(new Response(JSON.stringify({ access_token: fakeAccessToken(sub) }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
        : Promise.resolve(new Response(null, { status: 404 })),
    ),
  )
  return render(
    <AuthProvider>
      <WatIsNieuwKnop />
    </AuthProvider>,
  )
}

describe('WatIsNieuwKnop', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it('toont de dot voor een gebruiker die nog niets las; openen toont de nieuwste release en haalt de dot weg', async () => {
    const gebruiker = userEvent.setup()
    renderKnop()
    expect(await screen.findByTestId('wat-is-nieuw-dot')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: /Wat is nieuw/ }))
    const dialoog = await screen.findByTestId('wat-is-nieuw-dialoog')
    expect(dialoog).toHaveTextContent(RELEASES[0].titel)
    expect(dialoog).toHaveTextContent(RELEASES[0].punten[0])
    await waitFor(() => expect(screen.queryByTestId('wat-is-nieuw-dot')).not.toBeInTheDocument())
  })
})
