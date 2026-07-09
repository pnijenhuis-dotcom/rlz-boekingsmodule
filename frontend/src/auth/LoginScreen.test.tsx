import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthContext'
import { LoginScreen } from './LoginScreen'

describe('LoginScreen', () => {
  beforeEach(() => {
    // AuthProvider probeert bij het laden altijd een stille refresh via de cookie — in een
    // schone testomgeving is er geen cookie, dus dit moet als "niet ingelogd" afhandelen.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont e-mail, wachtwoord en TOTP-velden', () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginScreen />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(screen.getByLabelText('E-mailadres')).toBeInTheDocument()
    expect(screen.getByLabelText('Wachtwoord')).toBeInTheDocument()
    expect(screen.getByLabelText('TOTP-code')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inloggen' })).toBeInTheDocument()
  })

  it('toont een nette melding i.p.v. de kale proxy-fout als de backend onbereikbaar is', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 502, statusText: 'Bad Gateway' }))),
    )

    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginScreen />
        </AuthProvider>
      </MemoryRouter>,
    )

    const melding = await screen.findByText(/backend is momenteel niet bereikbaar/i)
    expect(melding).toBeInTheDocument()
    expect(screen.queryByText('Bad Gateway')).not.toBeInTheDocument()
  })
})
