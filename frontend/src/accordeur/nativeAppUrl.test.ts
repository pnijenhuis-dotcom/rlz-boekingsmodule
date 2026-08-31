// Universal-link-vertaling (pincode-activatie 31-08): alleen /accordeur- en /activeren-paden,
// /activeren?token= → de in-app-activatieroute (?uitnodiging=) — zelfde vertaling als het
// kantoor-/activeren-scherm.

import { describe, expect, it } from 'vitest'
import { inAppPadVoorUrl } from './nativeAppUrl'

const BASIS = 'https://app.administratiekantoornijenhuis.nl'

describe('inAppPadVoorUrl', () => {
  it('vertaalt de activatielink naar de in-app-route', () => {
    expect(inAppPadVoorUrl(`${BASIS}/activeren?token=abc%2F123`)).toBe('/accordeur/activeren?uitnodiging=abc%2F123')
    expect(inAppPadVoorUrl(`${BASIS}/activeren?token=abc&herstel=1`)).toBe(
      '/accordeur/activeren?uitnodiging=abc&herstel=1',
    )
    expect(inAppPadVoorUrl(`${BASIS}/activeren`)).toBe('/accordeur/activeren')
  })

  it('laat accordeur-deep-links door mét querystring', () => {
    expect(inAppPadVoorUrl(`${BASIS}/accordeur?document=42`)).toBe('/accordeur?document=42')
    expect(inAppPadVoorUrl(`${BASIS}/accordeur/activeren?uitnodiging=x`)).toBe('/accordeur/activeren?uitnodiging=x')
  })

  it('negeert alles daarbuiten (hard principe: de app-lock/auth-cadans blijft de poort)', () => {
    expect(inAppPadVoorUrl(`${BASIS}/`)).toBeNull()
    expect(inAppPadVoorUrl(`${BASIS}/instellingen`)).toBeNull()
    expect(inAppPadVoorUrl(`${BASIS}/accordeurtje`)).toBeNull()
    expect(inAppPadVoorUrl('geen-url')).toBeNull()
  })
})
