import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { DocumentActieResponseDto, DocumentListItemDto, DocumentListResponseDto, UploadResponseDto } from '../api/types'
import { useAuthOptioneel } from '../auth/AuthContext'
import { haalAiKostenStatusOp, type AiKostenStatusDto } from '../instellingen/instellingenApi'
import { VerzamelbakPaneel } from '../intake/VerzamelbakPaneel'
import { verwerkEml } from '../intake/intakeApi'
import { FoutMelding } from '../ui/FoutMelding'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { Klantenlijst } from './Klantenlijst'
import { extractieActief, statusLabel } from './status'
import { StatusChip } from './StatusChip'
import { useAdministraties } from './useAdministraties'
import { VerwijderDialog } from './VerwijderDialog'

/** Ververs-interval zolang er documenten in extractie_wachtrij/extractie_bezig staan. */
const EXTRACTIE_POLL_MS = 3000

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatDatumKort(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

function formatBedrag(bedrag: string | null): string {
  if (bedrag === null) return '—'
  const numeriek = Number(bedrag)
  if (Number.isNaN(numeriek)) return '—'
  return numeriek.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

/** Mockup-flow (browserreview 2026-08-07 punt 3): de werkvoorraad opent als klantenlijst met
 * tellers (#werkvoorraad); een klik op een klant opent de documentenlijst van die administratie
 * (#klantpagina) met breadcrumb terug. De verzamelbak en de .eml-intake zijn administratie-
 * overstijgend en horen bij de klantenlijst-ingang. */
export function WerkvoorraadScreen() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')

  if (administratiesFout) {
    return (
      <FoutMelding
        melding="Uw administraties konden niet geladen worden. Controleer de verbinding en probeer het opnieuw."
        detail={administratiesFout}
        onOpnieuw={() => window.location.reload()}
      />
    )
  }
  if (!administraties) {
    return (
      <div className="panel" aria-busy="true">
        <span className="skeleton" style={{ width: '40%', marginBottom: 10 }} />
        <span className="skeleton" style={{ width: '70%' }} />
      </div>
    )
  }
  if (administraties.length === 0) {
    return <p className="hint">Geen administraties gekoppeld aan uw account.</p>
  }

  if (!administratieId) {
    return <WerkvoorraadIngang administraties={administraties} />
  }
  const administratie = administraties.find((a) => a.id === administratieId)
  return (
    <Klantpagina
      administratieId={administratieId}
      administratieNaam={administratie?.naam ?? 'Onbekende administratie'}
      administraties={administraties}
    />
  )
}

/** AI-kostenmelding (besluit 2026-08-14): de werkvoorraad is het bestaande meldingskanaal — bij
 * ≥80% van de maandlimiet een waarschuwing, bij 100% de blokkade-melding. Alleen voor de
 * Beheerder (het status-endpoint is Beheerder-only; de limiet is een Beheerder-instelling). */
function AiKostenBanner() {
  const rol = useAuthOptioneel()?.rol ?? null
  const [status, setStatus] = useState<AiKostenStatusDto | null>(null)
  useEffect(() => {
    if (rol !== 'beheerder') return
    haalAiKostenStatusOp()
      .then(setStatus)
      .catch(() => undefined) // melding is best-effort; de harde poort zit in de backend
  }, [rol])
  if (!status || (!status.waarschuwing_80 && !status.limiet_bereikt)) return null
  if (status.limiet_bereikt) {
    return (
      <div className="fout" role="alert" style={{ marginBottom: 12 }}>
        AI-maandlimiet bereikt ({status.maand}: € {status.verbruik_eur} van € {status.limiet_eur}) —
        AI-verwerking is geblokkeerd; nieuwe documenten volgen het handmatige pad. Limiet aanpassen kan op
        Instellingen.
      </div>
    )
  }
  return (
    <div className="hint" role="status" style={{ marginBottom: 12, color: 'var(--orange, #b45309)' }}>
      AI-kosten op {status.percentage}% van de maandlimiet ({status.maand}: € {status.verbruik_eur} van €{' '}
      {status.limiet_eur}) — bij 100% wordt AI-verwerking geblokkeerd.
    </div>
  )
}

function WerkvoorraadIngang({ administraties }: { administraties: { id: string; naam: string }[] }) {
  const [uploadFout, setUploadFout] = useState<string | null>(null)
  const [uploadBericht, setUploadBericht] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [sleepActief, setSleepActief] = useState(false)
  const [verzamelbakVersie, setVerzamelbakVersie] = useState(0)
  const bestandInputRef = useRef<HTMLInputElement>(null)

  const uploadEml = useCallback(async (bestand: File) => {
    if (!bestand.name.toLowerCase().endsWith('.eml')) {
      setUploadFout(
        `"${bestand.name}" is geen .eml-bestand. PDF's en UBL horen bij een klant: open eerst de klant in de lijst hieronder en upload daar.`,
      )
      return
    }
    setBezig(true)
    setUploadFout(null)
    setUploadBericht(null)
    try {
      const resultaat = await verwerkEml(bestand)
      setUploadBericht(
        resultaat.al_eerder_verwerkt
          ? `"${bestand.name}" was al eerder verwerkt (zelfde Message-ID) — niets dubbel gedaan.`
          : `"${bestand.name}" verwerkt: ${resultaat.bijlagen
              .map((b) => `${b.bestandsnaam} → ${b.uitkomst.replaceAll('_', ' ')}`)
              .join('; ') || 'geen bijlagen gevonden'}.`,
      )
      setVerzamelbakVersie((v) => v + 1)
    } catch (err) {
      setUploadFout(err instanceof Error ? err.message : 'Verwerken van de mail is mislukt.')
    } finally {
      setBezig(false)
    }
  }, [])

  return (
    <div>
      <div className="topbar">
        <h1>Werkvoorraad</h1>
      </div>

      <AiKostenBanner />

      <div
        className={`upload${sleepActief ? ' dragover' : ''}`}
        onClick={() => bestandInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setSleepActief(true)
        }}
        onDragLeave={() => setSleepActief(false)}
        onDrop={(e) => {
          e.preventDefault()
          setSleepActief(false)
          const bestand = e.dataTransfer.files?.[0]
          if (bestand) void uploadEml(bestand)
        }}
      >
        {bezig ? (
          'Bezig met verwerken…'
        ) : (
          <>
            Sleep hier een doorgestuurde mail (.eml) naartoe, of <b>blader</b>
            <br />
            <span style={{ fontSize: 12 }}>
              Bijlagen worden automatisch aan de juiste klant toegewezen; wat niet eenduidig koppelt komt in
              &ldquo;Niet toegewezen&rdquo; hieronder. Losse PDF&rsquo;s of UBL uploadt u bij de klant zelf.
            </span>
          </>
        )}
        <input
          ref={bestandInputRef}
          type="file"
          accept=".eml"
          style={{ display: 'none' }}
          onChange={(e) => {
            const bestand = e.target.files?.[0]
            if (bestand) void uploadEml(bestand)
          }}
        />
      </div>
      {uploadFout && <FoutMelding melding={uploadFout} />}
      {uploadBericht && (
        <div className="hint" style={{ marginTop: -10, marginBottom: 16 }}>
          {uploadBericht}
        </div>
      )}

      <VerzamelbakPaneel key={verzamelbakVersie} administraties={administraties} onGewijzigd={() => {}} />

      <Klantenlijst administraties={administraties} />
    </div>
  )
}

const STATUSFILTER_ALLE = 'alle'
/** Sentinel voor het autoboeken-filter — met prefix, zodat het nooit met een echte
 * DocumentStatus-waarde uit de backend kan botsen. */
const STATUSFILTER_AUTOMATISCH = '__automatisch_geboekt'

function Klantpagina({
  administratieId,
  administratieNaam,
  administraties,
}: {
  administratieId: string
  administratieNaam: string
  administraties: { id: string; naam: string }[]
}) {
  const navigate = useNavigate()
  const bestandInputRef = useRef<HTMLInputElement>(null)
  const { naamVoor } = useMedewerkers(administratieId)

  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [lijstFout, setLijstFout] = useState<string | null>(null)
  const [uploadFout, setUploadFout] = useState<string | null>(null)
  const [uploadBericht, setUploadBericht] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [sleepActief, setSleepActief] = useState(false)
  const [toonVerwijderd, setToonVerwijderd] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [statusFilter, setStatusFilter] = useState(STATUSFILTER_ALLE)
  // Hersleutel voor het verzamelbak-paneel: ophogen forceert een refetch (na .eml-upload).
  const [verzamelbakVersie, setVerzamelbakVersie] = useState(0)
  // Omzetmodule: soort van de eerstvolgende upload — 'kassarapport' gaat de rapport-extractie
  // en het omzetreview-scherm in i.p.v. de inkoopflow.
  const [uploadSoort, setUploadSoort] = useState<'inkoopfactuur' | 'kassarapport'>('inkoopfactuur')
  const [verwijderenVoor, setVerwijderenVoor] = useState<DocumentListItemDto | null>(null)
  const [verwijderenBezig, setVerwijderenBezig] = useState(false)
  const [verwijderenFout, setVerwijderenFout] = useState<string | null>(null)
  const [herstellenBezig, setHerstellenBezig] = useState<string | null>(null)
  const [herstellenFout, setHerstellenFout] = useState<string | null>(null)

  const laadDocumenten = useCallback(() => {
    setLijstFout(null)
    apiJson<DocumentListResponseDto>(
      `/administraties/${administratieId}/documenten${toonVerwijderd ? '?toon_verwijderd=true' : ''}`,
    )
      .then((data) => setDocumenten(data.documenten))
      .catch((err: unknown) => setLijstFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, toonVerwijderd])

  useEffect(() => {
    setDocumenten(null)
    laadDocumenten()
  }, [laadDocumenten])

  // Live extractiestatus (async extractie): zolang er documenten in de wachtrij of bij de
  // worker staan, ververst de lijst vanzelf — de statuschip loopt mee zonder handmatige reload.
  useEffect(() => {
    if (!documenten?.some((d) => extractieActief(d.status))) return
    const timer = setInterval(laadDocumenten, EXTRACTIE_POLL_MS)
    return () => clearInterval(timer)
  }, [documenten, laadDocumenten])

  const uploadBestand = useCallback(
    async (bestand: File) => {
      setBezig(true)
      setUploadFout(null)
      setUploadBericht(null)
      try {
        if (bestand.name.toLowerCase().endsWith('.eml')) {
          // E-mail-intake: een doorgestuurde/geëxporteerde mail — zelfde verwerking als het
          // centrale postvak (bijlagen worden gerouteerd; niet-eenduidig -> verzamelbak).
          const resultaat = await verwerkEml(bestand)
          setUploadBericht(
            resultaat.al_eerder_verwerkt
              ? `"${bestand.name}" was al eerder verwerkt (zelfde Message-ID) — niets dubbel gedaan.`
              : `"${bestand.name}" verwerkt: ${resultaat.bijlagen
                  .map((b) => `${b.bestandsnaam} → ${b.uitkomst.replaceAll('_', ' ')}`)
                  .join('; ') || 'geen bijlagen gevonden'}.`,
          )
          setVerzamelbakVersie((v) => v + 1)
          laadDocumenten()
          return
        }
        const formData = new FormData()
        formData.append('bestand', bestand)
        formData.append('soort', uploadSoort)
        const resultaat = await apiJson<UploadResponseDto>(`/administraties/${administratieId}/documenten`, {
          method: 'POST',
          body: formData,
        })
        setUploadBericht(
          resultaat.mogelijk_duplicaat_van
            ? `"${bestand.name}" geüpload — mogelijk duplicaat, gemarkeerd ter controle in de lijst.`
            : resultaat.status === 'extractie_wachtrij'
              ? `"${bestand.name}" geüpload — groot document, wordt op de achtergrond verwerkt. De status in de lijst loopt vanzelf mee.`
              : `"${bestand.name}" geüpload en in verwerking.`,
        )
        laadDocumenten()
      } catch (err) {
        setUploadFout(err instanceof Error ? err.message : 'Upload mislukt')
      } finally {
        setBezig(false)
      }
    },
    [administratieId, laadDocumenten, uploadSoort],
  )

  const opBestandGekozen = (bestanden: FileList | null) => {
    const bestand = bestanden?.[0]
    if (bestand) void uploadBestand(bestand)
  }

  const verwijderen = async (reden: string) => {
    if (!verwijderenVoor) return
    setVerwijderenBezig(true)
    setVerwijderenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${verwijderenVoor.id}/verwijderen`,
        { reden: reden || null },
      )
      setVerwijderenVoor(null)
      laadDocumenten()
    } catch (err) {
      setVerwijderenFout(err instanceof ApiError ? err.message : 'Verwijderen mislukt.')
    } finally {
      setVerwijderenBezig(false)
    }
  }

  const herstellen = async (documentId: string) => {
    setHerstellenBezig(documentId)
    setHerstellenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/herstellen`,
        {},
      )
      laadDocumenten()
    } catch (err) {
      setHerstellenFout(err instanceof ApiError ? err.message : 'Herstellen mislukt.')
    } finally {
      setHerstellenBezig(null)
    }
  }

  // Zoekveld + statusfilter (mockup #klantpagina: "Zoek op leverancier, bedrag, factuurnr…").
  const gefilterd = useMemo(() => {
    if (documenten === null) return null
    const term = zoekterm.trim().toLowerCase()
    return documenten.filter((d) => {
      // Autoboeken-filter: eigenschap-filter naast de statusfilters (chip "automatisch") —
      // werkt op de al geladen lijst, geboekte documenten zitten daar al in.
      if (statusFilter === STATUSFILTER_AUTOMATISCH) {
        if (!d.automatisch_geboekt) return false
      } else if (statusFilter !== STATUSFILTER_ALLE && d.status !== statusFilter) return false
      if (!term) return true
      const doorzoekbaar = [d.bestandsnaam, d.leverancier ?? '', d.totaalbedrag ?? '', statusLabel(d.status)]
        .join(' ')
        .toLowerCase()
      return doorzoekbaar.includes(term)
    })
  }, [documenten, zoekterm, statusFilter])

  const aanwezigeStatussen = useMemo(
    () => Array.from(new Set((documenten ?? []).map((d) => d.status))).sort(),
    [documenten],
  )

  // Zelfde geest als aanwezigeStatussen: de filteroptie "Automatisch geboekt" alleen tonen als
  // er ook echt automatisch geboekte documenten in de lijst staan.
  const heeftAutomatischGeboekt = useMemo(() => (documenten ?? []).some((d) => d.automatisch_geboekt), [documenten])

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to="/" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
            ← Werkvoorraad
          </Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {administratieNaam}
        </h1>
        <div className="adm-select">
          {(() => {
            const openVragen = (documenten ?? []).filter((d) => d.status === 'vraag_open').length
            if (openVragen === 0) return null
            return (
              <Link to={`/vragen?administratie=${administratieId}`} style={{ textDecoration: 'none' }}>
                <span className="chip vraag">
                  {openVragen} {openVragen === 1 ? 'vraag' : 'vragen'} open
                </span>
              </Link>
            )
          })()}
          {(() => {
            const wachtend = (documenten ?? []).filter((d) => d.status === 'wacht_op_iban_accordering').length
            if (wachtend === 0) return null
            return (
              <span className="chip blokkerend">
                {wachtend} IBAN-{wachtend === 1 ? 'accordering' : 'accorderingen'} wachtend
              </span>
            )
          })()}
        </div>
      </div>

      <div
        className={`upload${sleepActief ? ' dragover' : ''}`}
        onClick={() => bestandInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setSleepActief(true)
        }}
        onDragLeave={() => setSleepActief(false)}
        onDrop={(e) => {
          e.preventDefault()
          setSleepActief(false)
          opBestandGekozen(e.dataTransfer.files)
        }}
      >
        {bezig ? (
          'Bezig met uploaden…'
        ) : (
          <>
            Sleep hier een PDF-, UBL- of .eml-bestand (doorgestuurde mail) naartoe, of <b>blader</b>
            <br />
            <span style={{ fontSize: 12 }}>Sha256-duplicaatcheck bij binnenkomst; UBL wordt automatisch geparst.</span>
            <br />
            <label
              // flexWrap + maxWidth (responsive-fix 2026-08-15): op smalle vensters wikkelt de
              // select onder het label i.p.v. buiten de uploadzone te steken.
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexWrap: 'wrap',
                maxWidth: '100%',
                gap: 6,
                fontSize: 12,
                marginTop: 8,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              Documentsoort
              <select
                aria-label="Documentsoort voor upload"
                style={{ width: 'auto' }}
                value={uploadSoort}
                onChange={(e) => setUploadSoort(e.target.value as 'inkoopfactuur' | 'kassarapport')}
              >
                <option value="inkoopfactuur">Inkoopfactuur</option>
                <option value="kassarapport">Kassarapport (omzetboeking)</option>
              </select>
            </label>
          </>
        )}
        <input
          ref={bestandInputRef}
          type="file"
          accept=".pdf,.xml,.eml"
          style={{ display: 'none' }}
          onChange={(e) => opBestandGekozen(e.target.files)}
        />
      </div>
      {uploadFout && <FoutMelding melding={uploadFout} />}
      {uploadBericht && (
        <div className="hint" style={{ marginTop: -10, marginBottom: 16 }}>
          {uploadBericht}
        </div>
      )}

      <VerzamelbakPaneel key={verzamelbakVersie} administraties={administraties} onGewijzigd={() => laadDocumenten()} />

      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h2 style={{ margin: 0 }}>Openstaande zaken</h2>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, margin: 0 }}>
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={toonVerwijderd}
              onChange={(e) => setToonVerwijderd(e.target.checked)}
            />
            Toon verwijderde documenten
          </label>
        </div>
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            placeholder="Zoek op leverancier, bedrag, bestandsnaam…"
            aria-label="Zoek in documenten"
            style={{ maxWidth: 300 }}
            value={zoekterm}
            onChange={(e) => setZoekterm(e.target.value)}
          />
          <select
            aria-label="Filter op status"
            style={{ width: 'auto' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value={STATUSFILTER_ALLE}>Alle statussen</option>
            {aanwezigeStatussen.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
            {heeftAutomatischGeboekt && <option value={STATUSFILTER_AUTOMATISCH}>Automatisch geboekt</option>}
          </select>
        </div>
        {lijstFout && (
          <FoutMelding
            melding="De documentenlijst kon niet geladen worden."
            detail={lijstFout}
            onOpnieuw={laadDocumenten}
          />
        )}
        {herstellenFout && <FoutMelding melding={herstellenFout} />}
        {documenten === null && !lijstFout && (
          <div className="tabel-scroll">
            <table aria-busy="true">
              <tbody>
                {Array.from({ length: 4 }, (_, r) => (
                  <tr key={r} aria-hidden="true">
                    {Array.from({ length: 6 }, (_, k) => (
                      <td key={k}>
                        <span className="skeleton" style={{ width: k === 0 ? '70%' : '50%' }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {documenten !== null && documenten.length === 0 && (
          <p className="hint">
            Nog geen documenten voor deze administratie. Sleep een factuur in het uploadvak hierboven of stuur een
            mail door als .eml-bestand.
          </p>
        )}
        {documenten !== null && documenten.length > 0 && gefilterd !== null && gefilterd.length === 0 && (
          <p className="hint">Geen documenten die aan de zoekterm of het statusfilter voldoen.</p>
        )}
        {gefilterd !== null && gefilterd.length > 0 && (
          // .tabel-scroll (responsive-fix 2026-08-15): zeven kolommen + nowrap-statuschips
          // maken de tabel op smalle vensters breder dan het paneel — intern scrollen i.p.v.
          // door de paneelrand klippen (zelfde patroon als de boekingsregels-tabel; de mockup
          // kent geen smal breakpoint).
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Document</th>
                  <th>Leverancier</th>
                  <th>Factuurdatum</th>
                  <th className="amount">Bedrag (incl. btw)</th>
                  <th>Status</th>
                  <th>Toegewezen</th>
                  <th />
                </tr>
                {gefilterd.map((d) => {
                  const isVerwijderd = d.status === 'verwijderd'
                  // Backend blokkeert dit al hard (bewaarplicht/lopende accordering) — de UI mag de
                  // onmogelijke actie dan niet eens aanbieden, ook niet als disabled-knop.
                  const kanNietVerwijderdWorden = d.status === 'geboekt' || d.status === 'ter_accordering'
                  // Mockup: klik op een vraag-regel opent de vráág, niet het controlescherm — de
                  // vragen-view gefilterd op dit document. Een verwijderd document houdt de normale
                  // detailnavigatie (herstel-route), nooit een klik naar een niet-actiefbare vraag.
                  const isVraagRegel = d.status === 'vraag_open' && !isVerwijderd
                  // Omzetmodule: een kassarapport opent het omzetreview-scherm (mockup
                  // #omzetreview), niet het inkoop-controlescherm.
                  const isKassarapport = d.soort === 'kassarapport'
                  // Verkoopmodule: een Vastly-verkoopfactuur (VASTLY-VERKOOP-UBL, §2d) opent het
                  // verkoopreview-scherm.
                  const isVerkoopfactuur = d.soort === 'verkoopfactuur'
                  // Waarborg-route (§2d v1.11): een VASTLY-WAARBORG-bericht opent het
                  // waarborg-reviewscherm (memoriaal-boekpad).
                  const isWaarborg = d.soort === 'waarborg'
                  return (
                    <tr
                      key={d.id}
                      className="clickable"
                      onClick={() =>
                        navigate(
                          isVraagRegel
                            ? `/vragen?administratie=${administratieId}&document=${d.id}`
                            : isKassarapport
                              ? `/omzet/${administratieId}/${d.id}`
                              : isVerkoopfactuur
                                ? `/verkoop/${administratieId}/${d.id}`
                                : isWaarborg
                                  ? `/waarborg/${administratieId}/${d.id}`
                                  : `/documenten/${administratieId}/${d.id}`,
                        )
                      }
                    >
                      <td>
                        {d.bestandsnaam}
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                          {d.bron} · {formatDatum(d.aangemaakt_op)}
                        </div>
                      </td>
                      <td>{d.leverancier ?? '—'}</td>
                      <td>{d.factuurdatum ? formatDatumKort(d.factuurdatum) : '—'}</td>
                      <td className="amount">{formatBedrag(d.totaalbedrag)}</td>
                      <td>
                        {isKassarapport && <span className="chip klaar">omzetboeking</span>}{' '}
                        {isVerkoopfactuur && <span className="chip klaar">verkoopfactuur</span>}{' '}
                        {isWaarborg && <span className="chip klaar">waarborg</span>}{' '}
                        <StatusChip status={d.status} />
                        {d.automatisch_geboekt && (
                          <>
                            {' '}
                            <span className="chip geheugen">automatisch</span>
                          </>
                        )}
                        {d.afwijzing && (
                          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                            reden: &ldquo;{d.afwijzing.reden}&rdquo; — {naamVoor(d.afwijzing.afgewezen_door)}
                          </div>
                        )}
                        {d.mogelijk_duplicaat_van && (
                          <div style={{ marginTop: 4 }}>
                            <span className="chip vraag">Mogelijk duplicaat</span>{' '}
                            <Link
                              to={`/documenten/${administratieId}/${d.mogelijk_duplicaat_van.document_id}`}
                              onClick={(e) => e.stopPropagation()}
                              style={{ fontSize: 11.5 }}
                            >
                              van {d.mogelijk_duplicaat_van.bestandsnaam} ({formatDatumKort(d.mogelijk_duplicaat_van.aangemaakt_op)})
                            </Link>
                          </div>
                        )}
                      </td>
                      <td>{d.toegewezen_aan ? naamVoor(d.toegewezen_aan) : '—'}</td>
                      <td>
                        {isVerwijderd ? (
                          <button
                            type="button"
                            className="icon-btn"
                            disabled={herstellenBezig === d.id}
                            onClick={(e) => {
                              e.stopPropagation()
                              void herstellen(d.id)
                            }}
                          >
                            {herstellenBezig === d.id ? 'Bezig…' : '↺ Herstellen'}
                          </button>
                        ) : (
                          !kanNietVerwijderdWorden && (
                            <button
                              type="button"
                              className="icon-btn"
                              aria-label="Document verwijderen"
                              onClick={(e) => {
                                e.stopPropagation()
                                setVerwijderenFout(null)
                                setVerwijderenVoor(d)
                              }}
                            >
                              🗑
                            </button>
                          )
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {verwijderenVoor && (
        <VerwijderDialog
          bestandsnaam={verwijderenVoor.bestandsnaam}
          bezig={verwijderenBezig}
          fout={verwijderenFout}
          onBevestigen={(reden) => void verwijderen(reden)}
          onAnnuleren={() => setVerwijderenVoor(null)}
        />
      )}
    </div>
  )
}
