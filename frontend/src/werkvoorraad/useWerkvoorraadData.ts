import { useCallback, useEffect, useState } from 'react'
import type { AdministratieDto, WerkvoorraadKlantDto } from '../api/types'
import { haalBankOverzicht } from '../bank/bankApi'
import { haalSpiegelTakenOp } from '../doorbelasting/doorbelastingApi'
import { haalWerkvoorraadOverzichtOp } from './werkvoorraadApi'

/** Gedeelde databron voor de werkvoorraad-ingang (IA-verbouwing fase 2): de KPI-rij én de
 * klantenlijst rekenen op dezelfde rijen, zodat tellers nooit uiteenlopen. Bank- en
 * spiegel-tellers zijn verrijking: een fout daar mag de lijst niet blokkeren (bestaand
 * faalvriendelijk patroon uit de oude Klantenlijst). */
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
  const [fout, setFout] = useState<string | null>(null)
  const [herlaadTeller, setHerlaadTeller] = useState(0)

  useEffect(() => {
    let actueel = true
    setFout(null)
    setKlanten(null)
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

  const herlaad = useCallback(() => setHerlaadTeller((t) => t + 1), [])
  return { klanten, fout, herlaad }
}
