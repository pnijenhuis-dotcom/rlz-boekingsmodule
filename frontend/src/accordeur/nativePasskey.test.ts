// Native-passkey-seam (store-app fase 2): in de Capacitor-schil lopen registratie/assertie
// via de NatievePasskey-plugin; buiten de schil (of bij een half plugin-oppervlak) blijft
// het webpad (navigator.credentials) ongewijzigd — fail-closed detectie.

import { afterEach, describe, expect, it, vi } from 'vitest'
import { natievePasskeyPlugin } from './nativePasskey'
import { ondertekenAssertie, registreerPasskey, webauthnBeschikbaar } from './webauthnClient'

function stubCapacitor(plugin: unknown, native = true) {
  vi.stubGlobal('Capacitor', {
    isNativePlatform: () => native,
    Plugins: { NatievePasskey: plugin },
  })
}

const volledigPlugin = {
  registreer: vi.fn(() => Promise.resolve({ credentialJson: '{"id":"cred-1","type":"public-key"}' })),
  onderteken: vi.fn(() => Promise.resolve({ credentialJson: '{"id":"cred-2","type":"public-key"}' })),
}

afterEach(() => {
  vi.unstubAllGlobals()
  volledigPlugin.registreer.mockClear()
  volledigPlugin.onderteken.mockClear()
})

describe('natievePasskeyPlugin — detectie', () => {
  it('geeft null zonder Capacitor-global (gewone browser/PWA)', () => {
    expect(natievePasskeyPlugin()).toBeNull()
  })

  it('geeft null wanneer Capacitor er is maar niet native draait (webweergave via schil-dev)', () => {
    stubCapacitor(volledigPlugin, false)
    expect(natievePasskeyPlugin()).toBeNull()
  })

  it('geeft null bij een half plugin-oppervlak (fail-closed, terug naar webpad)', () => {
    stubCapacitor({ registreer: () => Promise.resolve({ credentialJson: '{}' }) })
    expect(natievePasskeyPlugin()).toBeNull()
  })

  it('geeft de plugin in de native schil', () => {
    stubCapacitor(volledigPlugin)
    expect(natievePasskeyPlugin()).not.toBeNull()
  })
})

describe('webauthnClient in de native schil', () => {
  it('webauthnBeschikbaar is true via de plugin, óók zonder PublicKeyCredential in de webview', () => {
    expect('PublicKeyCredential' in window).toBe(false) // jsdom ≈ WKWebView: geen WebAuthn
    expect(webauthnBeschikbaar()).toBe(false)
    stubCapacitor(volledigPlugin)
    expect(webauthnBeschikbaar()).toBe(true)
  })

  it('registreerPasskey geeft de options-JSON byte-exact door en parseert de credential-JSON', async () => {
    stubCapacitor(volledigPlugin)
    const optiesJson = '{"challenge":"abc","rp":{"id":"administratiekantoornijenhuis.nl"}}'
    const credential = await registreerPasskey(optiesJson)
    expect(volledigPlugin.registreer).toHaveBeenCalledWith({ optiesJson })
    expect(credential).toEqual({ id: 'cred-1', type: 'public-key' })
  })

  it('ondertekenAssertie loopt via de plugin', async () => {
    stubCapacitor(volledigPlugin)
    const credential = await ondertekenAssertie('{"challenge":"xyz"}')
    expect(volledigPlugin.onderteken).toHaveBeenCalledWith({ optiesJson: '{"challenge":"xyz"}' })
    expect(credential).toEqual({ id: 'cred-2', type: 'public-key' })
  })

  it('een geannuleerde native prompt komt als fout bij de aanroeper (schermen tonen de melding)', async () => {
    stubCapacitor({
      registreer: () => Promise.reject(new Error('Passkey-registratie geannuleerd')),
      onderteken: () => Promise.reject(new Error('Passkey-verificatie geannuleerd')),
    })
    await expect(registreerPasskey('{}')).rejects.toThrow('geannuleerd')
    await expect(ondertekenAssertie('{}')).rejects.toThrow('geannuleerd')
  })
})
