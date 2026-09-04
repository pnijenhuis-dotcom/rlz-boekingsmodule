import { useCallback, useEffect, useState } from 'react'
import type { AdministratieDto, OpenVragenTellersDto, WerkvoorraadKlantDto } from '../api/types'
import { haalBankOverzicht } from '../bank/bankApi'
import { haalSpiegelTakenOp } from '../doorbelasting/doorbelastingApi'
import { haalOpenVragenStandOp } from '../vragen/vragenApi'
import { haalWerkvoorraadOverzichtOp } from './werkvoorraadApi'

/** Gedeelde databron voor de werkvoorraad-ingang (IA-verbouwing fase 2): de KPI-rij én de
 * klantenlijst rekenen op dezelfde rijen, zodat tellers nooit uiteenlopen. Bank- en
 * spiegel-tellers zijn verrijking: een fout daar mag de lijst niet blokkeren (bestaand
 * faalvriendelijk patroon uit de oude Klantenlijst). De KPI-kaart "Open vragen" leest sinds de
 * design-ronde 03-09 (blok B2) de stand van GET /vragen/stand — één definitie mét de kantoorbrede
 * lijst (open vraag-rij op een niet-verdwenen document, óók vragen aan de klant-accordeur op
 * documenten bij de klant/geboekt). Sinds G1 (03-09) telt de klantenlijst-kolom "Vragen"
 * (`WerkvoorraadKlant.vragen`, server-side) diezelfde definitie — kaart en kolom lopen niet meer uiteen. */
export interface KlantRij extends WerkvoorraadKlantDto {
  bank_open: number | null
  spiegel_taken: number | null
}

export function teVerwerken(k: KlantRij): number {
  return k.te_controleren + k.klaar_om_te_boeken
}

export function heeftOpenstaandWerk(k: KlantRij): boolean {
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

export function useWerkvoorraadData(administraties: AdministratieDto[]) {
  const [klanten, setKlanten] = useState<KlantRij[] | null>(null)
  const [openVragen, setOpenVragen] = useState<OpenVragenTellersDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [herlaadTeller, setHerlaadTeller] = useState(0)

  useEffect(() => {
    let actueel = true
    setFout(null)
    setKlanten(null)
    setOpenVragen(null)
    const bankBelofte = haalBankOverzicht().catch(() => null)
    // Stand open vragen (B2.3): verrijking — een fout hier blokkeert de lijst niet, de kaart toont dan "—".
    haalOpenVragenStandOp()
      .then((stand) => {
        if (actueel && typeof stand?.open === 'number') setOpenVragen(stand)
      })
      .catch(() => undefined)
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

  const herlaad = useCallback(() => setHerlaadTeller((t) => t + 1), [])
  return { klanten, openVragen, fout, herlaad }
}
