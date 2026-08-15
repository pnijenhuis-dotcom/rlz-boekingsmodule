// Kantoor-passkeys (platformbesluit 0020): passkey als eerste authenticatielijn op het
// kantoor-loginscherm, wachtwoord + TOTP als volwaardig terugvalpad. Dit is alleen de
// API-glue voor de kantoor-endpoints — de browser-WebAuthn-glue (registreerPasskey/
// ondertekenAssertie/webauthnBeschikbaar/…) wordt hergebruikt uit accordeur/webauthnClient.ts
// (tweede afnemer van dezelfde bouwstenen, geen nieuw auth-systeem).

import type { ApparaatDto } from '../accordering/accorderingApi'
import { apiJson, apiPostJson } from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'

export interface KantoorPasskeyOptiesDto {
  /** Assertion-options-JSON; null kan alleen samen met dev_stub=true (alleen een
   * stub-credential in een actieve dev-stub-omgeving — afronden met dev_stub). */
  opties: string | null
  dev_stub: boolean
}

export interface KantoorApparaatDto extends ApparaatDto {
  gebruiker_id: string
  gebruiker_naam: string
}

/** Stap 1 van de passkey-login (usernameless mag niet — het e-mailadres blijft het startpunt).
 * 409 = geen bruikbare passkey voor dit adres → de aanroeper valt terug op wachtwoord + TOTP. */
export function kantoorLoginOpties(eMail: string): Promise<KantoorPasskeyOptiesDto> {
  return apiPostJson('/auth/webauthn/kantoor/login/opties', { e_mail: eMail })
}

export function kantoorLoginVoltooien(
  eMail: string,
  payload: { credential?: Record<string, unknown>; dev_stub?: boolean },
): Promise<TokenPaarResponseDto> {
  return apiPostJson('/auth/webauthn/kantoor/login/voltooien', { e_mail: eMail, ...payload })
}

/** Registratie vanaf Instellingen → beveiliging: de ingelogde sessie is de machtiging (geen
 * apart setup-token zoals bij de accordeur-activeringsflow). */
export function kantoorRegistratieOpties(): Promise<{ opties: string }> {
  return apiPostJson('/auth/webauthn/kantoor/registratie/opties', {})
}

export function kantoorRegistratieVoltooien(payload: {
  credential?: Record<string, unknown>
  apparaat_naam: string
  dev_stub?: boolean
}): Promise<ApparaatDto> {
  return apiPostJson('/auth/webauthn/kantoor/registratie/voltooien', payload)
}

/** Eigen passkey-apparaten (elke rol) — naam, registratiedatum, laatst gebruikt, status. */
export function haalMijnApparaten(): Promise<{ apparaten: ApparaatDto[] }> {
  return apiJson('/auth/mijn/apparaten')
}

/** Beheerder-only: alle kantoor-passkey-apparaten mét gebruikersnaam (kill-switch-overzicht). */
export function haalKantoorApparaten(): Promise<{ apparaten: KantoorApparaatDto[] }> {
  return apiJson('/auth/apparaten/kantoor')
}
