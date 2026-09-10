import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type { LeverancierAutoboekStand, LeverancierAutoboekenDto } from '../api/types'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, Switch, SkeletonRegels } from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { BevestigDialog } from './BevestigDialog'
import { geefLeverancierVrij, haalLeveranciersAutoboeken, zetLeverancierAutoboeken, zonderLeverancierUit } from './instellingenApi'

interface PendingWijziging {
  vendorId: string
  naam: string
  nieuweWaarde: boolean
}

function berichtVoor(pending: PendingWijziging): string {
  return pending.nieuweWaarde
    ? `Facturen van ${pending.naam} worden na extractie automatisch geboekt zodra alle harde checks ` +
        'groen zijn en het voorstel volledig uit bevestigd boekingsgeheugen komt. De controles blijven ' +
        'blokkerend. Weet je het zeker?'
    : `Automatisch boeken wordt uitgeschakeld voor ${pending.naam} — facturen wachten weer op de boek-klik ` +
        'van een medewerker.'
}

/** Stand van een leverancier (blok A bundel 10-09): de server geeft `stand`; een ouder antwoord zonder dat veld
 * wordt afgeleid uit de opt-in — nooit een lege chip. */
export function standVan(l: LeverancierAutoboekenDto, administratieLerenAan: boolean): LeverancierAutoboekStand {
  if (l.stand) return l.stand
  if (l.autoboeken_ingeschakeld) return administratieLerenAan ? 'boekt_automatisch' : 'handmatig_aan'
  return 'leert'
}

/** Chip per stand: "leert (n/3)" neutraal, "boekt automatisch" = groene STATUS-chip, "uitgezonderd" grijs mét de reden
 * als title, "handmatig aan" (opt-in door een mens zonder administratie-schakelaar). */
export function StandChip({ l, administratieLerenAan }: { l: LeverancierAutoboekenDto; administratieLerenAan: boolean }) {
  const stand = standVan(l, administratieLerenAan)
  const drempel = l.drempel ?? 3
  switch (stand) {
    case 'boekt_automatisch':
      return (
        <Badge variant="ok" title={l.bron === 'systeem' ? 'door het systeem geactiveerd ná de drempel' : 'door een Beheerder aangezet'}>
          boekt automatisch
        </Badge>
      )
    case 'uitgezonderd':
      return (
        <Badge variant="stil" title={l.uitzondering_reden ?? 'uitgezonderd door een Beheerder'}>
          uitgezonderd
        </Badge>
      )
    case 'handmatig_aan':
      return (
        <Badge variant="info" title="opt-in door een Beheerder — de administratie-schakelaar staat uit">
          handmatig aan
        </Badge>
      )
    default:
      return (
        <Badge variant="stil" title={l.gereset_op ? `reeks telt opnieuw sinds ${new Date(l.gereset_op).toLocaleDateString('nl-NL')} (storno/correctie)` : 'het systeem activeert bij de drempel'}>
          leert ({Math.min(l.reeks ?? 0, drempel)}/{drempel})
        </Badge>
      )
  }
}

/** Autoboeken per leverancier (CLAUDE.md: "Automatisch boeken = opt-in per leverancier; harde checks blijven áltijd
 * blokkerend"). Beheerder-only: de sectie leeft binnen de rol-gate van InstellingenScreen en de backend geeft 403 voor
 * andere rollen. Zelfde sectie-patroon als AccorderingInstellingen: eigen panel, administraties als prop uit het scherm.
 *
 * Blok A bundel 10-09 (besluit Peter 10-09, herziet "kandidaten → mens klikt aan"): staat de administratie-schakelaar
 * "Autoboeken (leren en boeken)" AAN, dan is dit een UITZONDERINGENLIJST — het systeem activeert leveranciers zelf; de
 * mens ziet per leverancier de stand (leert n/3 · boekt automatisch · uitgezonderd · handmatig aan) en kan alleen
 * "Uitzonderen…" (verplichte reden, audit) of "Vrijgeven". De kale aan/uit-switch blijft alleen zichtbaar als de
 * schakelaar UIT staat (de oude opt-in-flow). */
export function LeverancierAutoboeken({
  administraties,
  vasteAdministratieId,
  administratieLerenAan = false,
}: {
  administraties: { id: string; naam: string }[]
  /** Instellingen v3 (01-09): op de administratie-detailpagina staat de administratie vast — geen
   * combobox, zelfde component/endpoint (één bron, twee ingangen). */
  vasteAdministratieId?: string
  /** Blok A 10-09: de administratie-schakelaar staat aan → uitzonderingenlijst i.p.v. per-leverancier-switches. */
  administratieLerenAan?: boolean
}) {
  const [administratieId, setAdministratieId] = useState(vasteAdministratieId ?? '')
  const [leveranciers, setLeveranciers] = useState<LeverancierAutoboekenDto[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  // Hersleutel voor "Opnieuw proberen": ophogen forceert een refetch van dezelfde administratie.
  const [laadVersie, setLaadVersie] = useState(0)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)
  const [zoek, setZoek] = useState('')
  // Uitzonderen-dialoog (verplichte reden) + vrijgeven per rij.
  const [uitzonderVoor, setUitzonderVoor] = useState<LeverancierAutoboekenDto | null>(null)
  const [reden, setReden] = useState('')
  const [rijFout, setRijFout] = useState<{ vendorId: string; tekst: string } | null>(null)
  const [rijBezig, setRijBezig] = useState<string | null>(null)

  useEffect(() => {
    setLeveranciers(null)
    setLaadFout(null)
    if (!administratieId) return
    let actueel = true
    haalLeveranciersAutoboeken(administratieId)
      .then((dto) => {
        if (actueel) setLeveranciers(dto.leveranciers)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, laadVersie])

  const vervangRij = (rij: LeverancierAutoboekenDto) =>
    setLeveranciers((huidig) => huidig?.map((l) => (l.vendor_id === rij.vendor_id ? { ...l, ...rij } : l)) ?? null)

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      await zetLeverancierAutoboeken(administratieId, pending.vendorId, pending.nieuweWaarde)
      // Optimistische update op de al geladen lijst — de PUT is de bron; bij een fout hierboven
      // blijft de oude stand gewoon staan.
      setLeveranciers(
        (huidig) =>
          huidig?.map((l) =>
            l.vendor_id === pending.vendorId
              ? { ...l, autoboeken_ingeschakeld: pending.nieuweWaarde, stand: pending.nieuweWaarde ? 'handmatig_aan' : 'leert', bron: pending.nieuweWaarde ? 'mens' : null }
              : l,
          ) ?? null,
      )
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const uitzonderen = async () => {
    if (!uitzonderVoor || reden.trim() === '') return
    setRijBezig(uitzonderVoor.vendor_id)
    setRijFout(null)
    try {
      const rij = await zonderLeverancierUit(administratieId, uitzonderVoor.vendor_id, reden.trim())
      vervangRij({ ...rij, stand: rij.stand ?? 'uitgezonderd', uitzondering_reden: rij.uitzondering_reden ?? reden.trim() })
      setUitzonderVoor(null)
      setReden('')
    } catch (err) {
      setRijFout({ vendorId: uitzonderVoor.vendor_id, tekst: err instanceof ApiError ? err.message : 'Uitzonderen mislukt.' })
    } finally {
      setRijBezig(null)
    }
  }

  const vrijgeven = async (l: LeverancierAutoboekenDto) => {
    setRijBezig(l.vendor_id)
    setRijFout(null)
    try {
      const rij = await geefLeverancierVrij(administratieId, l.vendor_id)
      vervangRij({ ...rij, uitzondering_reden: rij.uitzondering_reden ?? null })
    } catch (err) {
      setRijFout({ vendorId: l.vendor_id, tekst: err instanceof ApiError ? err.message : 'Vrijgeven mislukt.' })
    } finally {
      setRijBezig(null)
    }
  }

  const getoond = useMemo(() => {
    if (!leveranciers) return null
    const q = zoek.trim().toLowerCase()
    return q ? leveranciers.filter((l) => (l.naam ?? l.vendor_id).toLowerCase().includes(q)) : leveranciers
  }, [leveranciers, zoek])

  return (
    <div className="panel" style={{ marginTop: 16 }} data-testid="leverancier-autoboeken" data-modus={administratieLerenAan ? 'uitzonderingen' : 'opt-in'}>
      <h2>{administratieLerenAan ? 'Autoboeken per leverancier — uitzonderingen' : 'Automatisch boeken per leverancier'}</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        {administratieLerenAan
          ? 'Het systeem activeert een leverancier zelf zodra een mens 3 op rij exact hetzelfde boekte. Hieronder de stand per leverancier; een uitzondering houdt een leverancier buiten de automatische activatie.'
          : 'Opt-in per leverancier: facturen die alle harde checks doorstaan én volledig op bevestigd boekingsgeheugen steunen, worden dan zonder boek-klik geboekt.'}
        {!vasteAdministratieId && ' Kies eerst een administratie.'}
      </p>
      {!vasteAdministratieId && (
        <AdministratieCombobox
          label="Administratie voor automatisch boeken"
          toonLabel={false}
          administraties={administraties}
          waarde={administratieId}
          onWijzig={setAdministratieId}
          placeholder="— kies administratie —"
        />
      )}

      {laadFout && (
        <FoutMelding
          melding="De leveranciers konden niet geladen worden."
          detail={laadFout}
          onOpnieuw={() => setLaadVersie((v) => v + 1)}
        />
      )}
      {administratieId && leveranciers === null && !laadFout && <SkeletonRegels />}
      {leveranciers !== null && leveranciers.length === 0 && (
        <p className="hint">
          Nog geen leveranciers bekend voor deze administratie — de leverancierslijst komt uit de
          Reeleezee-sync.
        </p>
      )}
      {leveranciers !== null && leveranciers.length > 0 && (
        <>
          <input
            type="search"
            aria-label="Zoek leverancier"
            placeholder="Zoek leverancier…"
            value={zoek}
            onChange={(e) => setZoek(e.target.value)}
            style={{ marginTop: 10, maxWidth: 320 }}
          />
          {/* sticky-koppen (kliktest 2026-08-21): de leverancierslijst is per administratie lang —
              koppen blijven in beeld tijdens het scrollen. */}
          <div className="tabel-scroll sticky-koppen" style={{ marginTop: 10 }}>
            <table>
              <tbody>
                <tr>
                  <th>Leverancier</th>
                  <th>{administratieLerenAan ? 'Stand' : 'Automatisch boeken'}</th>
                  {administratieLerenAan && <th className="acties" style={{ textAlign: 'right' }} />}
                </tr>
                {(getoond ?? []).map((l) => {
                  const naam = l.naam ?? l.vendor_id
                  const stand = standVan(l, administratieLerenAan)
                  return (
                    <tr key={l.vendor_id} data-testid={`leverancier-rij-${l.vendor_id}`}>
                      <td>{naam}</td>
                      {administratieLerenAan ? (
                        <>
                          <td>
                            <StandChip l={l} administratieLerenAan />
                            {rijFout?.vendorId === l.vendor_id && (
                              <span className="text-[12px] text-red" role="alert" style={{ marginLeft: 8 }}>
                                {rijFout.tekst}
                              </span>
                            )}
                          </td>
                          <td className="acties" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {stand === 'uitgezonderd' ? (
                              <button type="button" className="linkbtn" disabled={rijBezig === l.vendor_id} onClick={() => void vrijgeven(l)}>
                                Vrijgeven
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="linkbtn"
                                disabled={rijBezig === l.vendor_id}
                                onClick={() => {
                                  setReden('')
                                  setRijFout(null)
                                  setUitzonderVoor(l)
                                }}
                              >
                                Uitzonderen…
                              </button>
                            )}
                          </td>
                        </>
                      ) : (
                        <td>
                          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                            <Switch
                              aria-label={`Automatisch boeken voor ${naam}`}
                              checked={l.autoboeken_ingeschakeld}
                              onChange={(e) => setPending({ vendorId: l.vendor_id, naam, nieuweWaarde: e.target.checked })}
                            />
                            {l.autoboeken_ingeschakeld ? 'aan' : 'uit'}
                          </label>
                        </td>
                      )}
                    </tr>
                  )
                })}
                {getoond !== null && getoond.length === 0 && (
                  <tr>
                    <td colSpan={administratieLerenAan ? 3 : 2} className="hint">
                      Geen leverancier gevonden voor “{zoek}”.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="hint" style={{ marginBottom: 0 }}>
        {administratieLerenAan
          ? 'Een uitgezonderde leverancier wordt nooit door het systeem geactiveerd (reden verplicht, geauditeerd); vrijgeven kan de leverancier direct weer actief maken als de reeks al aan de drempel zit. Automatisch geboekte facturen blijven zichtbaar met de chip “automatisch”.'
          : 'Standaard staat automatisch boeken UIT; alleen een Beheerder kan dit wijzigen. Automatisch geboekte facturen blijven zichtbaar in de werkvoorraad-historie met de chip “automatisch”.'}
      </p>

      {pending && (
        <BevestigDialog
          titel="Automatisch boeken wijzigen?"
          bericht={berichtVoor(pending)}
          bezig={bezig}
          fout={wijzigenFout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setWijzigenFout(null)
            setPending(null)
          }}
        />
      )}

      <Dialog open={uitzonderVoor !== null} onOpenChange={(open) => !open && rijBezig === null && setUitzonderVoor(null)}>
        <DialogContent aria-describedby={undefined} data-testid="uitzonder-dialoog">
          <DialogTitle>Uitzonderen — {uitzonderVoor?.naam ?? uitzonderVoor?.vendor_id}</DialogTitle>
          <DialogDescription>
            Deze leverancier doet niet mee aan de automatische activatie; een eventuele opt-in gaat uit. De reden is verplicht
            en wordt geauditeerd; vrijgeven kan altijd.
          </DialogDescription>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void uitzonderen()
            }}
          >
            <FormField label="Reden" htmlFor="uitzonder-reden">
              <input id="uitzonder-reden" autoFocus value={reden} onChange={(e) => setReden(e.target.value)} placeholder="bv. wisselende projecten per factuur" />
            </FormField>
            {rijFout && uitzonderVoor && rijFout.vendorId === uitzonderVoor.vendor_id && <div className="fout">{rijFout.tekst}</div>}
            <DialogFooter>
              <Button type="button" variant="secundair" onClick={() => setUitzonderVoor(null)} disabled={rijBezig !== null}>
                Annuleren
              </Button>
              <Button type="submit" disabled={rijBezig !== null || reden.trim() === ''}>
                {rijBezig ? 'Bezig…' : 'Uitzonderen'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
