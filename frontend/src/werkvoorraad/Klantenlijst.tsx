import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AdministratieDto, WerkvoorraadKlantDto } from '../api/types'
import { haalBankOverzicht } from '../bank/bankApi'
import { haalSpiegelTakenOp } from '../doorbelasting/doorbelastingApi'
import { FoutMelding } from '../ui/FoutMelding'
import { haalWerkvoorraadOverzichtOp } from './werkvoorraadApi'

/** Werkvoorraad-ingang (mockup #werkvoorraad "Overzicht per klant"): alleen klanten mét
 * openstaand werk, elke teller klikbaar. De bank-kolom komt uit het bank-overzicht (aparte
 * fetch) — als die faalt blijft de rest van de lijst gewoon bruikbaar. De spiegel-taken-teller
 * (Kempen-doorbelasting) volgt hetzelfde faalvriendelijke patroon: fetch per administratie,
 * een fout telt als "geen data" en de kolom verschijnt alleen als er ergens een open taak is. */

interface KlantRij extends WerkvoorraadKlantDto {
  bank_open: number | null
  spiegel_taken: number | null
}

function heeftOpenstaandWerk(k: KlantRij): boolean {
  return (
    k.te_controleren +
      k.klaar_om_te_boeken +
      k.vragen +
      k.afgewezen +
      k.bij_klant +
      k.iban_wachtend +
      (k.bank_open ?? 0) +
      (k.spiegel_taken ?? 0) >
    0
  )
}

function Teller({ waarde, chipKlasse, label }: { waarde: number; chipKlasse: string; label?: string }) {
  if (waarde === 0) return <>—</>
  return (
    <span className={`chip ${chipKlasse}`}>
      {waarde}
      {label ? ` ${label}` : ''}
    </span>
  )
}

function SkeletonRijen({ kolommen, rijen }: { kolommen: number; rijen: number }) {
  return (
    <>
      {Array.from({ length: rijen }, (_, r) => (
        <tr key={r} aria-hidden="true">
          {Array.from({ length: kolommen }, (_, k) => (
            <td key={k}>
              <span className="skeleton" style={{ width: k === 0 ? '60%' : 28 }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

export function Klantenlijst({ administraties }: { administraties: AdministratieDto[] }) {
  const navigate = useNavigate()
  const [klanten, setKlanten] = useState<KlantRij[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [herlaadTeller, setHerlaadTeller] = useState(0)

  useEffect(() => {
    let actueel = true
    setFout(null)
    setKlanten(null)
    // Bank- en spiegel-tellers zijn verrijking: een fout daar mag de klantenlijst niet blokkeren.
    const bankBelofte = haalBankOverzicht().catch(() => null)
    const spiegelBelofte = Promise.all(
      administraties.map(async (a) => {
        try {
          const taken = await haalSpiegelTakenOp(a.id)
          return [a.id, taken.length] as const
        } catch {
          return [a.id, null] as const
        }
      }),
    )
    haalWerkvoorraadOverzichtOp()
      .then(async (overzicht) => {
        const [bank, spiegel] = await Promise.all([bankBelofte, spiegelBelofte])
        if (!actueel) return
        const bankPerAdministratie = new Map((bank?.klanten ?? []).map((b) => [b.administratie_id, b.open_mutaties]))
        const spiegelPerAdministratie = new Map(spiegel)
        setKlanten(
          overzicht.klanten.map((k) => ({
            ...k,
            bank_open: bank ? (bankPerAdministratie.get(k.administratie_id) ?? 0) : null,
            spiegel_taken: spiegelPerAdministratie.get(k.administratie_id) ?? null,
          })),
        )
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [herlaadTeller, administraties])

  const zichtbaar = (klanten ?? []).filter(heeftOpenstaandWerk)
  const verborgen = (klanten?.length ?? 0) - zichtbaar.length
  // Kolom alleen bij data (Kempen-doorbelasting is voor één administratie relevant — de rest
  // van het kantoor moet geen lege kolom zien).
  const toonSpiegel = (klanten ?? []).some((k) => (k.spiegel_taken ?? 0) > 0)

  return (
    <div className="panel">
      <h2>Overzicht per klant</h2>
      {fout && (
        <FoutMelding
          melding="De klantenlijst kon niet geladen worden."
          detail={fout}
          onOpnieuw={() => setHerlaadTeller((t) => t + 1)}
        />
      )}
      {!fout && (
        // .tabel-scroll (responsive-fix 2026-08-15): de tellerkolommen + nowrap-chips maken de
        // tabel op smalle vensters breder dan het paneel — dan scrolt de tabel intern i.p.v.
        // door de paneelrand te klippen (zelfde patroon als de boekingsregels-tabel; de mockup
        // kent geen smal breakpoint).
        <div className="tabel-scroll">
          <table>
            <tbody>
              <tr>
                <th>Administratie</th>
                <th>Te controleren</th>
                <th>Klaar om te boeken</th>
                <th>Vragen</th>
                <th>Afgewezen</th>
                <th>Bij klant (goedkeuring)</th>
                <th>Bank</th>
                {toonSpiegel && <th>Spiegel-taken</th>}
              </tr>
              {klanten === null && <SkeletonRijen kolommen={7} rijen={4} />}
              {zichtbaar.map((k) => (
                <tr
                  key={k.administratie_id}
                  className="clickable"
                  onClick={() => navigate(`/?administratie=${k.administratie_id}`)}
                >
                  <td>
                    <b>{k.naam}</b>{' '}
                    {k.iban_wachtend > 0 && (
                      <span className="chip blokkerend">
                        {k.iban_wachtend} IBAN-{k.iban_wachtend === 1 ? 'accordering' : 'accorderingen'}
                      </span>
                    )}
                  </td>
                  <td>
                    <Teller waarde={k.te_controleren} chipKlasse="ai" />
                  </td>
                  <td>
                    <Teller waarde={k.klaar_om_te_boeken} chipKlasse="klaar" />
                  </td>
                  <td
                    onClick={(e) => {
                      if (k.vragen === 0) return
                      e.stopPropagation()
                      navigate(`/vragen?administratie=${k.administratie_id}`)
                    }}
                  >
                    <Teller waarde={k.vragen} chipKlasse="vraag" />
                  </td>
                  <td>
                    <Teller waarde={k.afgewezen} chipKlasse="vraag" />
                  </td>
                  <td>
                    <Teller waarde={k.bij_klant} chipKlasse="geheugen" />
                  </td>
                  <td
                    onClick={(e) => {
                      if (!k.bank_open) return
                      e.stopPropagation()
                      navigate(`/bank/${k.administratie_id}`)
                    }}
                  >
                    {k.bank_open === null ? '—' : <Teller waarde={k.bank_open} chipKlasse="ai" />}
                  </td>
                  {toonSpiegel && (
                    <td title="Open spiegel-taken (doorbelasting): bron geboekt, spiegel-inkoopfactuur in de doel-administratie nog niet">
                      {k.spiegel_taken === null ? '—' : <Teller waarde={k.spiegel_taken} chipKlasse="vraag" />}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {klanten !== null && !fout && zichtbaar.length === 0 && (
        <p className="hint">
          Geen openstaand werk — alle {administraties.length}{' '}
          {administraties.length === 1 ? 'administratie is' : 'administraties zijn'} bij. Nieuwe documenten of
          bankmutaties verschijnen hier vanzelf.
        </p>
      )}
      {klanten !== null && zichtbaar.length > 0 && (
        <p className="hint">
          Alleen klanten mét openstaande zaken staan in deze lijst — is alles geboekt, dan verdwijnt de klant
          automatisch en verschijnt hij weer zodra er iets nieuws binnenkomt. Elke teller is klikbaar.
          {verborgen > 0 && (
            <span style={{ color: 'var(--muted)' }}>
              {' '}
              · {verborgen} {verborgen === 1 ? 'klant' : 'klanten'} zonder openstaande zaken (verborgen)
            </span>
          )}
        </p>
      )}
    </div>
  )
}
