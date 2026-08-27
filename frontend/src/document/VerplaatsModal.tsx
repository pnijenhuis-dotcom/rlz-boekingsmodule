import { useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type { DocumentVerplaatsResponseDto } from '../api/types'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { SearchableCombobox, type ComboboxOptie } from './SearchableCombobox'
import { verplaatsDocument } from './verplaatsen'

interface Props {
  administratieId: string
  administratieNaam: string | null
  documentId: string
  bestandsnaam: string
  /** Open vragen op het document (verhuizen mee — de modal benoemt dat). */
  openVragen: number
  /** Gelezen tenaamstelling (punt 6a): voedt de optionele "onthoud"-checkbox; null = geen checkbox. */
  tenaamstelling?: string | null
  onVerplaatst: (resultaat: DocumentVerplaatsResponseDto) => void
  onAnnuleren: () => void
}

/** "Verplaats naar andere administratie…" (addendum kantoor-run 27-08 punt 5): doel via de
 * doorzoekbare combobox (alleen administraties waar de gebruiker scope op heeft, de huidige
 * uitgezonderd), met vooraf de consequenties: veldvoorstel/boekvoorstel vervallen en de extractie
 * draait opnieuw in het doel; het toewijzings-geheugen leert mee terug; tijdlijn + audit. */
export function VerplaatsModal({
  administratieId,
  administratieNaam,
  documentId,
  bestandsnaam,
  openVragen,
  tenaamstelling = null,
  onVerplaatst,
  onAnnuleren,
}: Props) {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [doelId, setDoelId] = useState<string | null>(null)
  // Punt 6a (werkstroom-run 27/28-08): default UIT — géén automatische leer-regel; alleen op
  // expliciet verzoek leert het geheugen "deze tenaamstelling hoort bij <doel>" (register-match-gat).
  const [onthoud, setOnthoud] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const opties = useMemo<ComboboxOptie[]>(
    () => (administraties ?? []).filter((a) => a.id !== administratieId).map((a) => ({ id: a.id, label: a.naam })),
    [administraties, administratieId],
  )
  const doelNaam = opties.find((o) => o.id === doelId)?.label ?? null

  const versturen = async () => {
    if (!doelId) return
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await verplaatsDocument(administratieId, documentId, doelId, onthoud && !!tenaamstelling)
      onVerplaatst(resultaat)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Verplaatsen mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent
        aria-describedby="verplaats-uitleg"
        // De combobox-listbox portalt buiten de dialog-content; een klik op een optie is voor Radix
        // een "klik buiten" en zou de modal sluiten — dat is géén sluiten.
        onPointerDownOutside={(e) => {
          if ((e.target as Element | null)?.closest?.('.combobox-listbox')) e.preventDefault()
        }}
        onInteractOutside={(e) => {
          if ((e.target as Element | null)?.closest?.('.combobox-listbox')) e.preventDefault()
        }}
      >
        <DialogTitle>Verplaats naar andere administratie</DialogTitle>
        <DialogDescription id="verplaats-uitleg">
          <strong>{bestandsnaam}</strong> staat nu in {administratieNaam ?? 'deze administratie'}. Kies de administratie waar het
          document thuishoort.
        </DialogDescription>

        <SearchableCombobox
          label="Doeladministratie"
          opties={opties}
          waarde={doelId}
          onWijzig={setDoelId}
          placeholder="Typ om een administratie te zoeken…"
          vereist
        />
        {administratiesFout && <div className="fout">Kon de administraties niet laden: {administratiesFout}</div>}
        {administraties && opties.length === 0 && (
          <div className="hint">U heeft geen toegang tot een andere administratie om naartoe te verplaatsen.</div>
        )}

        <ul className="hint" style={{ margin: '12px 0 0', paddingLeft: 18, lineHeight: 1.5 }}>
          <li>
            Het veld- en boekvoorstel vervallen; de extractie draait opnieuw in {doelNaam ?? 'de doeladministratie'} (grootboek,
            crediteuren en projecten zijn per administratie).
          </li>
          <li>
            Het toewijzings-geheugen leert mee: een leer-regel (tenaamstelling/afzender) die naar{' '}
            {administratieNaam ?? 'deze administratie'} wees, wordt gecorrigeerd — de volgende mail landt direct goed.
          </li>
          {openVragen > 0 && (
            <li>
              {openVragen === 1 ? 'De open vraag verhuist mee' : `De ${openVragen} open vragen verhuizen mee`} en blijft
              boeken blokkeren tot de vraagsteller afhandelt.
            </li>
          )}
          <li>De verhuizing komt in de tijdlijn en het audit-log (van → naar, door wie).</li>
        </ul>

        {tenaamstelling && (
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 12, fontSize: 12.5 }}>
            <Checkbox checked={onthoud} onChange={(e) => setOnthoud(e.target.checked)} disabled={bezig} />
            <span>
              Onthoud: tenaamstelling <b>&ldquo;{tenaamstelling}&rdquo;</b> hoort bij {doelNaam ?? 'de doeladministratie'}
              <span className="hint" style={{ display: 'block', marginTop: 2 }}>
                Alleen als de toewijzing níét uit een leer-regel kwam (bv. een match op de administratienaam) — anders
                herhaalt de intake dezelfde fout bij de volgende mail. Standaard uit; niets wordt automatisch geleerd.
              </span>
            </span>
          </label>
        )}

        {fout && (
          <div className="fout" role="alert" style={{ marginTop: 10 }}>
            {fout}
          </div>
        )}

        <DialogFooter>
          <Button variant="secundair" type="button" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void versturen()} disabled={bezig || !doelId}>
            {bezig ? 'Verplaatsen…' : `Verplaatsen${doelNaam ? ` naar ${doelNaam}` : ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
