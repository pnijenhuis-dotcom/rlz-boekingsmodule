import { describe, expect, it } from 'vitest'
import { activatieOpDitApparaat, isMobielUserAgent } from './webauthnClient'

// Beslisregel activatielink (besluit Peter 28-08, mockup activatie-mobiel.html beslispunt 1):
// capability-check + UA-vangnet, twijfel = stop-scherm (fail-safe richting telefoon).
describe('activatieOpDitApparaat', () => {
  const basis = { native: false, devStub: false }

  it('telefoon mét platform-authenticator → doorgaan', () => {
    expect(activatieOpDitApparaat({ ...basis, mobielUa: true, platformAuthenticator: true })).toBe('doorgaan')
  })

  it('desktop-UA → stop, óók als de desktop een platform-authenticator heeft (Touch ID/Windows Hello)', () => {
    expect(activatieOpDitApparaat({ ...basis, mobielUa: false, platformAuthenticator: true })).toBe('stop')
    expect(activatieOpDitApparaat({ ...basis, mobielUa: false, platformAuthenticator: false })).toBe('stop')
  })

  it('telefoon zonder of met onbekende capability = twijfel → stop', () => {
    expect(activatieOpDitApparaat({ ...basis, mobielUa: true, platformAuthenticator: false })).toBe('stop')
    expect(activatieOpDitApparaat({ ...basis, mobielUa: true, platformAuthenticator: null })).toBe('stop')
  })

  it('native schil (Capacitor-plugin) en dev-stub (LAN-kliktest) gaan altijd door', () => {
    expect(activatieOpDitApparaat({ native: true, devStub: false, mobielUa: false, platformAuthenticator: null })).toBe(
      'doorgaan',
    )
    expect(activatieOpDitApparaat({ native: false, devStub: true, mobielUa: false, platformAuthenticator: null })).toBe(
      'doorgaan',
    )
  })
})

describe('isMobielUserAgent', () => {
  it('herkent iPhone/iPad/Android, niet Mac/Windows/jsdom', () => {
    expect(isMobielUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')).toBe(true)
    expect(isMobielUserAgent('Mozilla/5.0 (Linux; Android 14; Pixel 8)')).toBe(true)
    expect(isMobielUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)')).toBe(false)
    expect(isMobielUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe(false)
    expect(isMobielUserAgent('Mozilla/5.0 (darwin) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/24.0.0')).toBe(false)
  })
})
