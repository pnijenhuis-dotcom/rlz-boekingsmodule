import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../ui/basis'
import { markeerPasskeyBannerAfgehandeld, moetPasskeyBannerTonen } from './passkeyBanner'

/** Eenmalige banner ná een cross-device-passkey-login (28-08): stelt voor om op dít apparaat
 * een passkey toe te voegen (Instellingen › Beveiliging). Keuze wordt per apparaat onthouden. */
export function PasskeyToevoegenBanner() {
  const navigate = useNavigate()
  const [zichtbaar, setZichtbaar] = useState(() => moetPasskeyBannerTonen())
  if (!zichtbaar) return null
  const sluit = () => {
    markeerPasskeyBannerAfgehandeld()
    setZichtbaar(false)
  }
  return (
    <div className="melding-banner passkey-banner" role="status" data-testid="passkey-banner">
      <div className="melding-tekst">
        <b>Passkey toevoegen op dit apparaat?</b>{' '}
        <span className="hint">
          U logde in met de passkey van uw telefoon. Voeg hier een passkey toe en u logt voortaan direct in — zonder
          QR-code.
        </span>
      </div>
      <div className="melding-acties">
        <Button
          maat="klein"
          onClick={() => {
            sluit()
            void navigate('/instellingen/beveiliging')
          }}
        >
          Passkey toevoegen
        </Button>
        <Button variant="secundair" maat="klein" onClick={sluit}>
          Niet nu
        </Button>
      </div>
    </div>
  )
}
