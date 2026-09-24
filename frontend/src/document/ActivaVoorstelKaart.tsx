// Activum aanmaken? — kaart op het inkoop-controlescherm (Activa / MVA fase 1, ontwerp docs/ONTWERP_ACTIVA_MVA.md §2,
// akkoord Peter 21-09; mockup controlescherm-v2.html ontwerpnotitie ⑨). Direct ná de offerte-match, vóór de actiebalk.
//
// Het is een VOORSTEL-kaart (norm `vk`-klassen, bank/VoorstelKaart.tsx), géén check-rij: boeken blokkeert nooit. Per
// boekvoorstelregel op een activarekening (`is_activa`) mét netto ≥ de activeringsgrens toont de kaart de voorgevulde
// activum-velden (omschrijving · rekening · aanschafwaarde · aanschafdatum · categorie · termijn · restwaarde ·
// afschrijvingsrekening) + de fiscale SIGNALEN (getoetst door code, nooit gerekend). Knoppen: "Activum aanmaken" (document
// nog niet geboekt → "Aanmaken ná boeken": koppeling `gepland`, de motor maakt het activum aan zodra de boeking staat) en
// "Niet activeren…" mét verplichte reden (niets verdwijnt stil). Stand per koppeling: gepland / aangemaakt in RLZ (groen =
// status) / niet geactiveerd mét reden / mislukt mét reden + "Opnieuw aanmaken" / beoordelen ná storno. Onder de grens =
// oranje regel (kleine aanschaf direct ten laste van het resultaat?). Register niet leesbaar (403 op FixedAssets) =
// oranje regel + knop uitgeschakeld mét die tekst. Een fout bij het laden blokkeert het scherm nooit (verrijking).
// BUG 24-09 (BLOw 23-09): de afschrijvingsrekening is voorgevuld uit de koppeling > instelling > CONVENTIE (kostenrekening 4xxx
// mét dezelfde omschrijving ná "Afschrijving…" — Peter 24-09 blok 6, herkomst-chip); zonder rekening is de combobox verplicht en staat de knop uit (server: 422).
// Teal = actie, groen = status (designpass v2). Gate: alleen soort `inkoopfactuur`; leeg antwoord = niets tonen.
import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import {
  activumAanmaken,
  activumOverslaan,
  AFSCHRIJVING_BRON_LABEL,
  AFSCHRIJVING_VEREIST_TEKST,
  haalActivaVoorstel,
  KOPPELING_STATUS_LABEL,
  REGISTER_NIET_LEESBAAR_TEKST,
  type ActivaKandidaatDto,
  type ActivaVoorstelDto,
} from '../activa/activaApi'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'
import { SearchableCombobox } from './SearchableCombobox'

export function ActivaVoorstelKaart({
  administratieId,
  documentId,
  status,
  soort,
  boekvoorstelVersie = 0,
}: {
  administratieId: string
  documentId: string
  status: string
  soort: string
  /** Ophogen bij een opgeslagen boekvoorstel: regels/bedragen/rekeningen kunnen gewijzigd zijn, dus opnieuw lezen. */
  boekvoorstelVersie?: number
}) {
  const [voorstel, setVoorstel] = useState<ActivaVoorstelDto | null>(null)
  // Afschrijvingsrekening per kandidaat (regel_volgnummer → ledger_id); voorgevuld uit de kandidaat, mens wint.
  const [afschrijving, setAfschrijving] = useState<Record<number, string | null>>({})
  const [bezig, setBezig] = useState<number | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [overslaanVoor, setOverslaanVoor] = useState<ActivaKandidaatDto | null>(null)
  const relevant = soort === 'inkoopfactuur'

  const neemOver = useCallback((v: ActivaVoorstelDto | null | undefined) => {
    // Fail-safe (gouden-set-les 21-09: het keten-harnas gaf `{}` en `v.kandidaten is not iterable` trok het HELE
    // controlescherm leeg — React ontkoppelt de root bij een onafgevangen render-fout): een antwoord zonder de twee
    // lijsten is geen voorstel → niets tonen. De kaart is verrijking en blokkeert het scherm nooit.
    if (!v || !Array.isArray(v.kandidaten) || !Array.isArray(v.onder_grens)) {
      setVoorstel(null)
      return
    }
    setVoorstel(v)
    setAfschrijving((huidig) => {
      const volgend: Record<number, string | null> = {}
      for (const k of v.kandidaten) volgend[k.regel_volgnummer] = huidig[k.regel_volgnummer] ?? k.afschrijving_ledger_id
      return volgend
    })
  }, [])

  const laad = useCallback(() => {
    if (!relevant) return
    let actief = true
    haalActivaVoorstel(administratieId, documentId)
      .then((v) => {
        if (actief) neemOver(v)
      })
      // Verrijking: een fout hier mag het controlescherm nooit blokkeren (de kaart is een voorstel).
      .catch(() => undefined)
    return () => {
      actief = false
    }
  }, [administratieId, documentId, relevant, neemOver])

  useEffect(() => {
    const opruimen = laad()
    return opruimen
  }, [laad, status, boekvoorstelVersie])

  if (!relevant || voorstel === null) return null
  if (voorstel.kandidaten.length === 0 && voorstel.onder_grens.length === 0) return null

  const registerDicht = voorstel.register_leesbaar === false
  const opties = voorstel.afschrijving_ledger_opties.map((o) => ({ id: o.ledger_id, code: o.code, label: o.naam }))

  const aanmaken = async (k: ActivaKandidaatDto) => {
    setBezig(k.regel_volgnummer)
    setFout(null)
    try {
      const v = await activumAanmaken(administratieId, documentId, k.regel_volgnummer, {
        afschrijving_ledger_id: afschrijving[k.regel_volgnummer] ?? null,
      })
      neemOver(v)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Activum aanmaken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(null)
    }
  }

  const overslaan = async (k: ActivaKandidaatDto, reden: string) => {
    setBezig(k.regel_volgnummer)
    setFout(null)
    try {
      const v = await activumOverslaan(administratieId, documentId, k.regel_volgnummer, reden)
      neemOver(v)
      setOverslaanVoor(null)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Niet activeren mislukt — probeer het opnieuw.')
    } finally {
      setBezig(null)
    }
  }

  const aantal = voorstel.kandidaten.length
  const aanmaakLabel = voorstel.document_geboekt ? 'Activum aanmaken' : 'Aanmaken ná boeken'

  return (
    <div className="panel" data-testid="activa-voorstel-kaart">
      <h2>
        Activum aanmaken?{' '}
        {aantal > 0 && (
          <Badge variant="info" data-testid="activa-chip-aantal">
            {aantal === 1 ? '1 regel wordt activum' : `${aantal} regels worden activum`}
          </Badge>
        )}
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Een aanschaf op een activarekening van {formatBedrag(voorstel.grens)} of meer
        {voorstel.grens_bron === 'rlz' ? ' (grens uit Reeleezee)' : ' (grens uit de instelling)'} wordt een activum in het
        register van Reeleezee; Reeleezee schrijft af. De module toetst de termijn, rekent zelf niets en verwijdert nooit.
        {voorstel.automatisch_ingeschakeld
          ? ' Automatisch aanmaken ná boeken staat AAN voor deze administratie — alleen kandidaten die u hier niet activeert blijven achter.'
          : ' Automatisch aanmaken staat uit — een mens beslist per regel.'}
      </p>

      {registerDicht && (
        <p className="vk-verschil" role="alert" data-testid="activa-register-dicht" style={{ marginTop: 0 }}>
          ⚠ {REGISTER_NIET_LEESBAAR_TEKST}
          {voorstel.register_fout ? ` — ${voorstel.register_fout}` : ''}
        </p>
      )}

      {fout && (
        <div className="fout" role="alert" data-testid="activa-fout">
          {fout}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {voorstel.kandidaten.map((k) => (
          <KandidaatKaart
            key={k.regel_volgnummer}
            kandidaat={k}
            opties={opties}
            afschrijvingId={afschrijving[k.regel_volgnummer] ?? null}
            onAfschrijving={(id) => setAfschrijving((h) => ({ ...h, [k.regel_volgnummer]: id }))}
            bezig={bezig === k.regel_volgnummer}
            registerDicht={registerDicht}
            aanmaakLabel={aanmaakLabel}
            onAanmaken={() => void aanmaken(k)}
            onOverslaan={() => setOverslaanVoor(k)}
          />
        ))}
      </div>

      {voorstel.onder_grens.map((o) => (
        <p
          key={`onder-${o.regel_volgnummer}`}
          className="vk-verschil"
          data-testid="activa-onder-grens"
          style={{ marginTop: 8, marginBottom: 0 }}
        >
          ⚠{' '}
          {o.tekst ||
            `${o.ledger_code} ${o.ledger_naam} ${formatBedrag(o.netto)} staat op een activarekening onder de grens ${formatBedrag(
              voorstel.grens,
            )} — kleine aanschaf direct ten laste van het resultaat?`}
        </p>
      ))}

      {overslaanVoor && (
        <NietActiverenDialoog
          kandidaat={overslaanVoor}
          bezig={bezig === overslaanVoor.regel_volgnummer}
          onBevestigen={(reden) => void overslaan(overslaanVoor, reden)}
          onAnnuleren={() => setOverslaanVoor(null)}
        />
      )}
    </div>
  )
}

function KandidaatKaart({
  kandidaat: k,
  opties,
  afschrijvingId,
  onAfschrijving,
  bezig,
  registerDicht,
  aanmaakLabel,
  onAanmaken,
  onOverslaan,
}: {
  kandidaat: ActivaKandidaatDto
  opties: { id: string; code: string; label: string }[]
  afschrijvingId: string | null
  onAfschrijving: (id: string | null) => void
  bezig: boolean
  registerDicht: boolean
  aanmaakLabel: string
  onAanmaken: () => void
  onOverslaan: () => void
}) {
  const kop = k.koppeling
  const stand = kop?.status ?? null
  const definitief = stand === 'aangemaakt' || stand === 'beoordelen'
  const datum = k.aanschafdatum ? formatDatumKort(k.aanschafdatum) : null
  // BUG 24-09 punt 2 (BLOw 23-09: twee keer "Aanmaken ná boeken" zonder rekening → mislukt): zonder afschrijvingsrekening
  // kan er niet gepland worden — combobox verplicht (rode rand + tekst), knop uit; de server weigert het óók (422).
  const rekeningVereist = !definitief && afschrijvingId === null
  const knopTitel = registerDicht ? REGISTER_NIET_LEESBAAR_TEKST : rekeningVereist ? AFSCHRIJVING_VEREIST_TEKST : undefined
  const knopUit = registerDicht || rekeningVereist
  // Herkomst-chip alleen zolang de mens de voorvulling niet overschreef.
  const bronLabel =
    afschrijvingId !== null && afschrijvingId === k.afschrijving_ledger_id && k.afschrijving_bron
      ? AFSCHRIJVING_BRON_LABEL[k.afschrijving_bron]
      : undefined

  return (
    <div className="vk" data-testid={`activa-kandidaat-${k.regel_volgnummer}`} style={{ maxWidth: 520, flex: '1 1 320px' }}>
      <div className="vk-kop" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span>{k.omschrijving || `Regel ${k.regel_volgnummer}`}</span>
        {!definitief && stand !== 'overgeslagen' && (
          <Badge variant="info" data-testid="activa-chip-wordt-activum">
            wordt activum
          </Badge>
        )}
      </div>
      <div className="vk-r">
        rekening <b>{k.ledger_code}</b> {k.ledger_naam}
      </div>
      <div className="vk-r">
        aanschafwaarde <b>{formatBedrag(k.aanschafwaarde)}</b>
        {datum ? ` · aanschafdatum ${datum}` : ''}
      </div>
      <div className="vk-r" style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span>
          categorie <b>{k.categorie_label}</b>
        </span>
        {k.categorie === 'onbekend' && (
          <Badge variant="warn" data-testid="activa-chip-controleer">
            controleer
          </Badge>
        )}
        <span>
          · termijn <b>{k.methode_naam}</b> ({k.termijn_maanden} mnd) · restwaarde {formatBedrag(k.restwaarde)}
        </span>
      </div>

      {!definitief && (
        <div style={{ marginTop: 6, maxWidth: 360 }}>
          <SearchableCombobox
            label="Afschrijvingsrekening"
            opties={opties}
            waarde={afschrijvingId}
            onWijzig={onAfschrijving}
            placeholder={opties.length === 0 ? 'Geen afschrijvingsrekening (0xxx) gevonden' : 'Kies afschrijvingsrekening…'}
            leegTekst="Geen afschrijvingsrekening (0xxx) in deze administratie — stel in onder Instellingen › Activa"
            vereist
            fout={rekeningVereist}
          />
          {bronLabel && (
            <Badge variant="info" data-testid="activa-chip-afschrijving-bron" title={`code ${k.afschrijving_ledger_code ?? ''}`}>
              {bronLabel}
            </Badge>
          )}
          {rekeningVereist && (
            <p className="vk-verschil" role="alert" data-testid="activa-rekening-vereist" style={{ marginTop: 4, marginBottom: 0 }}>
              ⚠ {AFSCHRIJVING_VEREIST_TEKST}
            </p>
          )}
        </div>
      )}
      {definitief && k.afschrijving_ledger_code && <div className="vk-r">afschrijvingsrekening {k.afschrijving_ledger_code}</div>}

      {k.signalen.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }} data-testid="activa-signalen">
          {k.signalen.map((s) => (
            <span key={s.code} className="chip afwijking" title={s.code} style={{ whiteSpace: 'normal' }}>
              {s.tekst}
            </span>
          ))}
        </div>
      )}

      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }} data-testid="activa-stand">
        {stand === null && (
          <>
            <button type="button" className="btn" disabled={bezig || knopUit} title={knopTitel} onClick={onAanmaken}>
              {bezig ? 'Bezig…' : aanmaakLabel}
            </button>
            <button type="button" className="linkbtn" disabled={bezig} onClick={onOverslaan}>
              Niet activeren…
            </button>
          </>
        )}
        {stand === 'gepland' && (
          <>
            <Badge variant="info" data-testid="activa-chip-gepland">
              {KOPPELING_STATUS_LABEL.gepland}
            </Badge>
            <button type="button" className="linkbtn" disabled={bezig} onClick={onOverslaan}>
              Toch niet
            </button>
          </>
        )}
        {stand === 'aangemaakt' && (
          <Badge variant="ok" stip data-testid="activa-chip-aangemaakt">
            {KOPPELING_STATUS_LABEL.aangemaakt}
            {kop?.rlz_receipt_number ? ` · nr ${kop.rlz_receipt_number}` : ''}
          </Badge>
        )}
        {stand === 'overgeslagen' && (
          <>
            <Badge variant="stil" data-testid="activa-chip-overgeslagen">
              {KOPPELING_STATUS_LABEL.overgeslagen}
            </Badge>
            {kop?.reden && <span className="hint">reden: {kop.reden}</span>}
            <button type="button" className="linkbtn" disabled={bezig || knopUit} title={knopTitel} onClick={onAanmaken}>
              Toch aanmaken
            </button>
          </>
        )}
        {stand === 'mislukt' && (
          <>
            <span className="text-[12px] text-red" role="alert" data-testid="activa-mislukt">
              {KOPPELING_STATUS_LABEL.mislukt}
              {kop?.reden ? ` — ${kop.reden}` : ''}
            </span>
            <button type="button" className="btn secondary" disabled={bezig || knopUit} title={knopTitel} onClick={onAanmaken}>
              {bezig ? 'Bezig…' : 'Opnieuw aanmaken'}
            </button>
          </>
        )}
        {stand === 'beoordelen' && (
          <Badge variant="warn" data-testid="activa-chip-beoordelen">
            factuur gestorneerd — beoordeel het activum in RLZ (niet verwijderd)
          </Badge>
        )}
      </div>
    </div>
  )
}

/** "Niet activeren…" = een besluit mét verplichte reden (niets verdwijnt stil; audit `activum_overgeslagen`). */
function NietActiverenDialoog({
  kandidaat,
  bezig,
  onBevestigen,
  onAnnuleren,
}: {
  kandidaat: ActivaKandidaatDto
  bezig: boolean
  onBevestigen: (reden: string) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const leeg = reden.trim() === ''
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent data-testid="activa-niet-activeren-dialoog">
        <DialogTitle>Niet activeren</DialogTitle>
        <DialogDescription>
          {kandidaat.omschrijving || `Regel ${kandidaat.regel_volgnummer}`} ({formatBedrag(kandidaat.aanschafwaarde)} op{' '}
          {kandidaat.ledger_code}) wordt géén activum in Reeleezee. Het besluit en de reden komen in de tijdlijn; u kunt het
          later alsnog aanmaken.
        </DialogDescription>
        <div className="row">
          <label htmlFor="activa-niet-activeren-reden">Reden (verplicht)</label>
          <textarea
            id="activa-niet-activeren-reden"
            rows={3}
            placeholder="Bijv.: huur/lease, geen eigendom · al opgenomen in een bestaand activum · onderhoud, geen investering"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => onBevestigen(reden.trim())} disabled={bezig || leeg}>
            {bezig ? 'Bezig…' : 'Niet activeren'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
