/** Thema-toggle (nazorg controls-review 2026-08-16): initThema() draait ná de eerste render
 * van de knop — bij systeem-donker zonder opgeslagen keuze las de knop een verouderde stand en
 * deed de eerste klik zichtbaar niets. De knop moet de LIVE DOM-stand wisselen, altijd. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { ThemaKnop } from './ThemaKnop'

// Deze jsdom-omgeving heeft geen window.localStorage — precies het scenario waarvoor thema.ts
// defensief is (keuze wordt dan niet onthouden, wisselen werkt onverkort). De tests toetsen
// daarom de DOM-klassen, niet de opslag.
afterEach(() => {
  document.documentElement.classList.remove('dark')
  document.body.classList.remove('dark')
})

describe('ThemaKnop', () => {
  it('wisselt van donker naar licht, ook als de dark-klasse pas ná de eerste render gezet is', async () => {
    render(<ThemaKnop />)
    // Bootst initThema() in een later effect na (systeem-donker): de knop rendert eerst
    // zonder klasse, daarna wordt de pagina alsnog donker.
    document.documentElement.classList.add('dark')
    document.body.classList.add('dark')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Thema wisselen' }))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.body.classList.contains('dark')).toBe(false)
  })

  it('wisselt van licht naar donker (html én body)', async () => {
    render(<ThemaKnop />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Thema wisselen' }))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.body.classList.contains('dark')).toBe(true)
  })
})
