import { useCallback, useEffect, useState } from 'react'
import { trekApparaatIn, type ApparaatDto } from '../accordering/accorderingApi'
import {
  apparaatNaam,
  haalWebauthnConfig,
  registreerPasskey,
  webauthnBeschikbaar,
  type WebauthnConfigDto,
} from '../accordeur/webauthnClient'
import {
  haalKantoorApparaten,
  haalMijnApparaten,
  kantoorRegistratieOpties,
  kantoorRegistratieVoltooien,
  type KantoorApparaatDto,
} from '../auth/passkeyApi'

function formatMoment(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

interface ApparaatRij {
  apparaat: ApparaatDto
  /** Alleen gevuld in het beheerder-overzicht (apparaten van medewerkers). */
  gebruikerNaam?: string
}

function ApparatenTabel({
  rijen,
  metGebruiker,
  onIntrekken,
}: {
  rijen: ApparaatRij[]
  metGebruiker: boolean
  onIntrekken: (apparaatId: string) => void
}) {
  return (
    // .tabel-scroll (kliktest 2026-08-16, ~1170px): kolommen en de Intrekken-knop clipten
    // rechts buiten het paneel zonder scroll — brede inhoud scrolt intern.
    <div className="tabel-scroll">
    <table>
      <thead>
        <tr>
          {metGebruiker && <th>Medewerker</th>}
          <th>Apparaat</th>
          <th>Geregistreerd</th>
          <th>Laatst gebruikt</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rijen.map(({ apparaat, gebruikerNaam }) => (
          <tr key={apparaat.id}>
            {metGebruiker && <td>{gebruikerNaam}</td>}
            <td>
              {apparaat.apparaat_naam ?? 'Onbekend apparaat'}
              {apparaat.is_dev_stub && <span className="chip"> dev-stub</span>}
            </td>
            <td>{formatMoment(apparaat.aangemaakt_op)}</td>
            <td>{formatMoment(apparaat.laatst_gebruikt_op)}</td>
            <td>
              {apparaat.ingetrokken_op ? (
                <span className="chip">ingetrokken</span>
              ) : (
                <span className="chip geheugen">actief</span>
              )}
            </td>
            <td>
              {!apparaat.ingetrokken_op && (
                <button type="button" className="btn secondary" onClick={() => onIntrekken(apparaat.id)}>
                  Intrekken
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}

/** Beveiliging (kantoor-passkeys, platformbesluit 0020): eigen passkeys registreren en
 * intrekken — zichtbaar voor élke kantoor-rol, niet alleen de Beheerder. De Beheerder ziet
 * daarnaast het kill-switch-overzicht van alle kantoor-apparaten (accordeur-apparaten hebben
 * hun eigen overzicht onder Klant-accordering). Wachtwoord + TOTP blijft altijd werken: de
 * laatste passkey intrekken sluit nooit buiten. */
export function BeveiligingInstellingen({ isBeheerder }: { isBeheerder: boolean }) {
  const [apparaten, setApparaten] = useState<ApparaatDto[] | null>(null)
  const [kantoorApparaten, setKantoorApparaten] = useState<KantoorApparaatDto[] | null>(null)
  const [config, setConfig] = useState<WebauthnConfigDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([
      haalMijnApparaten(),
      haalWebauthnConfig(),
      isBeheerder ? haalKantoorApparaten() : Promise.resolve(null),
    ])
      .then(([mijn, configDto, kantoor]) => {
        setApparaten(mijn.apparaten)
        setConfig(configDto)
        setKantoorApparaten(kantoor?.apparaten ?? null)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [isBeheerder])

  useEffect(() => {
    laad()
  }, [laad])

  const registratieMogelijk = webauthnBeschikbaar() || config?.dev_stub === true

  const toevoegen = async () => {
    setFout(null)
    setBezig(true)
    try {
      if (webauthnBeschikbaar()) {
        const { opties } = await kantoorRegistratieOpties()
        const credential = await registreerPasskey(opties)
        await kantoorRegistratieVoltooien({ credential, apparaat_naam: apparaatNaam() })
      } else {
        // Dev-stub (alleen werkzaam buiten productie, server-side dubbel vergrendeld).
        await kantoorRegistratieVoltooien({ dev_stub: true, apparaat_naam: `${apparaatNaam()} (dev-stub)` })
      }
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Passkey toevoegen mislukt')
    } finally {
      setBezig(false)
    }
  }

  const intrekken = async (apparaatId: string) => {
    setFout(null)
    try {
      await trekApparaatIn(apparaatId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2 style={{ marginTop: 0 }}>Beveiliging — passkeys</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Passkeys zijn de eerste inlogstap (Touch ID, Windows Hello, beveiligingssleutel of een passkey op je
        telefoon); wachtwoord + TOTP blijft altijd werken als terugval. Registreer per apparaat één passkey.
      </p>
      {fout && <div className="fout">{fout}</div>}

      {apparaten === null && !fout && <p className="hint">Laden…</p>}
      {apparaten !== null && (
        <>
          {apparaten.length === 0 ? (
            <p className="hint" style={{ margin: 0 }}>
              Nog geen passkeys geregistreerd — je logt in met wachtwoord + TOTP.
            </p>
          ) : (
            <ApparatenTabel
              rijen={apparaten.map((apparaat) => ({ apparaat }))}
              metGebruiker={false}
              onIntrekken={(id) => void intrekken(id)}
            />
          )}
          <div className="actions" style={{ margin: '10px 0 0' }}>
            <button type="button" className="btn" disabled={bezig || !registratieMogelijk} onClick={() => void toevoegen()}>
              {bezig ? 'Bezig…' : 'Passkey toevoegen (dit apparaat)'}
            </button>
          </div>
          {!registratieMogelijk && config !== null && (
            <p className="hint" style={{ marginBottom: 0 }}>
              Passkeys vereisen een beveiligde verbinding (https of localhost) — op dit adres is registreren
              niet mogelijk.
            </p>
          )}
          <p className="hint" style={{ marginBottom: 0 }}>
            Intrekken blokkeert het apparaat per direct: de passkey én alle passkey-sessies van dat apparaat
            vervallen. De laatste passkey intrekken sluit je nooit buiten — wachtwoord + TOTP blijft werken.
          </p>
        </>
      )}

      {isBeheerder && kantoorApparaten !== null && kantoorApparaten.length > 0 && (
        <>
          <h3 style={{ margin: '16px 0 0' }}>Apparaten van medewerkers (kill-switch)</h3>
          <ApparatenTabel
            rijen={kantoorApparaten.map((apparaat) => ({ apparaat, gebruikerNaam: apparaat.gebruiker_naam }))}
            metGebruiker
            onIntrekken={(id) => void intrekken(id)}
          />
          <p className="hint" style={{ marginBottom: 0 }}>
            Als Beheerder kun je élk kantoor-apparaat intrekken; de medewerker valt dan terug op wachtwoord +
            TOTP. Accordeur-apparaten beheer je onder Klant-accordering.
          </p>
        </>
      )}
    </div>
  )
}
