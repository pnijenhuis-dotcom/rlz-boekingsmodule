import { useCallback, useEffect, useState } from 'react'
import type { AdministratieDto, OpenVragenTellersDto, WerkvoorraadKlantDto } from '../api/types'
import { haalBankOverzicht } from '../bank/bankApi'
import { haalOpenVragenStandOp } from '../vragen/vragenApi'
import { haalWerkvoorraadOverzichtOp } from './werkvoorraadApi'

/** Gedeelde databron voor de werkvoorraad-ingang (IA-verbouwing fase 2): de KPI-rij én de
 * klantenlijst rekenen op dezelfde rijen, zodat tellers nooit uiteenlopen. De bank-teller is
 * verrijking: een fout daar mag de lijst niet blokkeren (bestaand faalvriendelijk patroon uit de oude
 * Klantenlijst). De KPI-kaart "Open vragen" leest sinds de design-ronde 03-09 (blok B2) de stand van
 * GET /vragen/stand — één definitie mét de kantoorbrede lijst. Sinds G1 (03-09) telt de klantenlijst-
 * kolom "Vragen" (`WerkvoorraadKlant.vragen`, server-side) diezelfde definitie.
 *
 * Blok 6 (11-09, beginscherm traag bij 71 administraties): (1) de spiegel-taken komen server-side mee in
 * het overzicht (`spiegel_taken`) — de N losse calls `GET /doorbelasting/{id}/spiegel-taken` (±71 per
 * schermopening) zijn weg; (2) de lijst verschijnt zodra het overzicht binnen is, de bank-kolom toont
 * een skeleton tot `/bank/overzicht` er is (`bank_open === undefined` = laadt, `null` = niet beschikbaar). */
export interface KlantRij extends Omit<WerkvoorraadKlantDto, 'spiegel_taken'> {
  /** undefined = bank-overzicht laadt nog; null = niet beschikbaar (fout); getal = open mutaties. */
  bank_open: number | null | undefined
  /** Server-side teller (blok 6 11-09); null blijft toegestaan voor oudere mocks/aanroepers. */
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

/** `groepId` (blok 8 run 11-09): server-side groepsfilter op het overzicht — doorgegeven aan de API, verder ongewijzigd. */
export function useWerkvoorraadData(administraties: AdministratieDto[], groepId: string | null = null) {
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
    haalWerkvoorraadOverzichtOp(groepId)
      .then(async (overzicht) => {
        if (!actueel) return
        // Eerste bytes: de lijst staat er zodra het overzicht binnen is; bank volgt als verrijking.
        setKlanten(
          overzicht.klanten.map((k) => ({ ...k, bank_open: undefined, spiegel_taken: k.spiegel_taken ?? 0 })),
        )
        const bank = await bankBelofte
        if (!actueel) return
        const bankPerAdministratie = new Map((bank?.klanten ?? []).map((b) => [b.administratie_id, b.open_mutaties]))
        setKlanten(
          overzicht.klanten.map((k) => ({
            ...k,
            bank_open: bank ? (bankPerAdministratie.get(k.administratie_id) ?? 0) : null,
            spiegel_taken: k.spiegel_taken ?? 0,
          })),
        )
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [herlaadTeller, administraties, groepId])

  const herlaad = useCallback(() => setHerlaadTeller((t) => t + 1), [])
  return { klanten, openVragen, fout, herlaad }
}
