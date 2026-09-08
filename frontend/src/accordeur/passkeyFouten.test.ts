// Blok 13 (07-09, Play-afwijzing variant B): de Credential-Manager-fout van Android wordt een
// eerlijke melding; iOS/web en andere fouten (incl. gewone annulering) blijven ongewijzigd.

import { describe, expect, it } from 'vitest'
import {
  GEEN_PASSKEY_BEHEERDER_MELDING,
  IOS_PASSKEY_MISLUKT_MELDING,
  isAndroidGeenPasskeyBeheerder,
  isIosPasskeyMislukt,
  loginFoutmelding,
} from './passkeyFouten'

describe('isAndroidGeenPasskeyBeheerder', () => {
  it('herkent de plugin-/GMS-varianten uit de emulator-reproductie van 07-09', () => {
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: No create options available.')).toBe(true)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: [28433] Operation failed')).toBe(true)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: CreatePasswordOrPasskeyOperation [28434]')).toBe(true)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: Provider status changed: CANCELED, source: REMOTE_PROVIDER')).toBe(true)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: No provider dependencies found on the device')).toBe(true)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: androidx.credentials.exceptions.CreateCredentialNoCreateOptionException')).toBe(true)
  })

  it('een gewone annulering of een andere fout is GEEN ontbrekende beheerder', () => {
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie geannuleerd')).toBe(false)
    expect(isAndroidGeenPasskeyBeheerder('Onjuiste inloggegevens')).toBe(false)
    expect(isAndroidGeenPasskeyBeheerder('Passkey-registratie mislukt: Timeout')).toBe(false)
    expect(isAndroidGeenPasskeyBeheerder('')).toBe(false)
  })
})

describe('loginFoutmelding', () => {
  const fout = new Error('Passkey-registratie mislukt: No create options available.')

  it('android: eerlijke melding mét handelingsperspectief', () => {
    expect(loginFoutmelding(fout, 'android')).toBe(GEEN_PASSKEY_BEHEERDER_MELDING)
    expect(GEEN_PASSKEY_BEHEERDER_MELDING).toContain('Google-account')
    expect(GEEN_PASSKEY_BEHEERDER_MELDING).toContain('schermvergrendeling')
    expect(GEEN_PASSKEY_BEHEERDER_MELDING).toContain('ander toestel')
  })

  it('iOS en web: het oorspronkelijke bericht, ongewijzigd', () => {
    expect(loginFoutmelding(fout, 'ios')).toBe(fout.message)
    expect(loginFoutmelding(fout, 'web')).toBe(fout.message)
  })

  it('android met een andere fout: oorspronkelijk bericht; niet-Error → generiek', () => {
    expect(loginFoutmelding(new Error('Onjuiste inloggegevens'), 'android')).toBe('Onjuiste inloggegevens')
    expect(loginFoutmelding('x', 'android')).toBe('Inloggen mislukt.')
  })
})

// Blok 2a (08-09): iOS geeft bij een mislukte registratie een kale Apple-tekst door — die krijgt een
// handelingsperspectief (iCloud-sleutelhanger/toegangscode); annulering en andere platforms ongewijzigd.
describe('iOS — mislukte passkey-registratie (blok 2a 08-09)', () => {
  const asFout = new Error(
    'Passkey-verzoek mislukt: The operation couldn’t be completed. (com.apple.AuthenticationServices.AuthorizationError error 1004.)',
  )

  it('isIosPasskeyMislukt herkent de plugin-/ASAuthorization-vorm, niet de annulering', () => {
    expect(isIosPasskeyMislukt(asFout.message)).toBe(true)
    expect(isIosPasskeyMislukt('Passkey-verzoek mislukt: Application with identifier X is not associated with domain Y')).toBe(true)
    expect(isIosPasskeyMislukt('Passkey-verzoek geannuleerd')).toBe(false)
    expect(isIosPasskeyMislukt('Ongeldige inloggegevens')).toBe(false)
  })

  it('ios: eerlijke melding mét de technische melding er kort achter', () => {
    const melding = loginFoutmelding(asFout, 'ios')
    expect(melding.startsWith(IOS_PASSKEY_MISLUKT_MELDING)).toBe(true)
    expect(melding).toContain('iCloud-sleutelhanger')
    expect(melding).toContain('AuthorizationError error 1004')
  })

  it('ios: weggetikte sheet blijft "Passkey-verzoek geannuleerd"; android/web laten de iOS-tekst ongemoeid', () => {
    expect(loginFoutmelding(new Error('Passkey-verzoek geannuleerd'), 'ios')).toBe('Passkey-verzoek geannuleerd')
    expect(loginFoutmelding(asFout, 'android')).toBe(asFout.message)
    expect(loginFoutmelding(asFout, 'web')).toBe(asFout.message)
  })
})
