// Kantoor-WebAuthn-glue (verhuisd uit accordeur/ op 08-09-2026, app-auth zonder passkey): het
// apparaat-label voor de kantoor-apparatenlijst, incl. de iPad-desktop-UA-regel (iPad-ronde 29-08).
import { describe, expect, it } from 'vitest'
import { apparaatNaam, isIpadOs } from './webauthnClient'

describe('apparaatNaam / isIpadOs', () => {
  const ipadOs = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15'

  it('iPadOS met desktop-UA ("Macintosh") is een iPad zodra er een aanraakscherm is; een Mac blijft Mac', () => {
    expect(isIpadOs(ipadOs, 5)).toBe(true)
    expect(isIpadOs(ipadOs, 0)).toBe(false)
    expect(isIpadOs('Mozilla/5.0 (iPad; CPU OS 12_0 like Mac OS X)', 0)).toBe(true)
    expect(apparaatNaam(ipadOs, 5)).toBe('iPad')
    expect(apparaatNaam(ipadOs, 0)).toBe('Mac')
  })

  it('herkent iPhone, Android en Windows; onbekend = "Onbekend apparaat"', () => {
    expect(apparaatNaam('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 5)).toBe('iPhone')
    expect(apparaatNaam('Mozilla/5.0 (Linux; Android 14; Pixel 8)', 5)).toBe('Android-toestel')
    expect(apparaatNaam('Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 0)).toBe('Windows-pc')
    expect(apparaatNaam('Mozilla/5.0 (darwin) jsdom/24.0.0', 0)).toBe('Onbekend apparaat')
  })
})
