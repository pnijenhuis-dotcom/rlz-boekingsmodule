import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiJson } from '../api/client'
import type { DocumentListItemDto, DocumentListResponseDto, UploadResponseDto, VraagDto } from '../api/types'
import { haalRekeningen, type RekeningenDto } from '../bank/bankApi'
import { verwerkEml } from '../intake/intakeApi'
import { Badge, Select } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalVragenOp } from '../vragen/vragenApi'
import { Breadcrumb } from './Breadcrumb'
import { documentRoute, formatBedrag, isOpenstaand, ouderdomLabel, soortLabel } from './format'
import { KpiRij } from './KpiRij'

/* Klantpagina = STANDEN (IA-besluit 15-08, mockup #scherm-klant): documenten per soort, bank
 * per rekening — alleen tellers; werken gebeurt in het deelscherm (één soort/rekening).
 * Toon-regel: secties en regels alleen zichtbaar bij teller > 0. */

interface SoortStand {
  soort: string
  open: number
  oudste: string | null
}

export function KlantStanden({
  administratieId,
  administratieNaam,
}: {
  administratieId: string
  administratieNaam: string
}) {
  const navigate = useNavigate()
  const { naamVoor } = useMedewerkers(administratieId)
  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [documentenFout, setDocumentenFout] = useState<string | null>(null)
  const [rekeningen, setRekeningen] = useState<RekeningenDto | null>(null)
  const [rekeningenGeladen, setRekeningenGeladen] = useState(false)
  const [vragen, setVragen] = useState<VraagDto[] | null>(null)

  const laadDocumenten = useCallback(() => {
    setDocumentenFout(null)
    apiJson<DocumentListResponseDto>(`/administraties/${administratieId}/documenten`)
      .then((data) => setDocumenten(data.documenten))
      .catch((err: unknown) => setDocumentenFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  useEffect(() => {
    setDocumenten(null)
    laadDocumenten()
  }, [laadDocumenten])

  // Bank en vragen zijn verrijking van de standen: een fout daar blokkeert de pagina niet
  // (zelfde faalvriendelijke patroon als de klantenlijst).
  useEffect(() => {
    let actueel = true
    setRekeningen(null)
    setRekeningenGeladen(false)
    haalRekeningen(administratieId)
      .then((data) => {
        if (!actueel) return
        setRekeningen(data)
        setRekeningenGeladen(true)
      })
      .catch(() => {
        if (actueel) setRekeningenGeladen(true)
      })
    haalVragenOp(administratieId)
      .then((data) => {
        if (actueel) setVragen(data.vragen)
      })
      .catch(() => {
        if (actueel) setVragen(null)
      })
    return () => {
      actueel = false
    }
  }, [administratieId])

  const open = useMemo(() => (documenten ?? []).filter(isOpenstaand), [documenten])
  const standen: SoortStand[] = useMemo(() => {
    const perSoort = new Map<string, DocumentListItemDto[]>()
    for (const d of open) {
      const lijst = perSoort.get(d.soort) ?? []
      lijst.push(d)
      perSoort.set(d.soort, lijst)
    }
    return Array.from(perSoort.entries())
      .map(([soort, docs]) => ({
        soort,
        open: docs.length,
        oudste: docs.reduce<string | null>(
          (oudste, d) => (oudste === null || d.aangemaakt_op < oudste ? d.aangemaakt_op : oudste),
          null,
        ),
      }))
      .sort((a, b) => b.open - a.open)
  }, [open])

  const openVragen = useMemo(() => (vragen ?? []).filter((v) => v.status === 'open'), [vragen])
  const vraagTeller = open.filter((d) => d.status === 'vraag_open').length
  const terAccordering = useMemo(() => open.filter((d) => d.status === 'ter_accordering'), [open])
  const ibanWachtend = open.filter((d) => d.status === 'wacht_op_iban_accordering').length
  const teVerwerken = open.filter((d) => d.status !== 'vraag_open' && d.status !== 'ter_accordering').length
  const openRekeningen = (rekeningen?.rekeningen ?? []).filter((r) => r.open_mutaties > 0)
  const bankOpen = openRekeningen.reduce((som, r) => som + r.open_mutaties, 0)

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb stappen={[{ label: 'Werkvoorraad', naar: '/' }]} huidige={administratieNaam} />
          <h1>{administratieNaam}</h1>
        </div>
        {ibanWachtend > 0 && (
          <span className="chip blokkerend">
            {ibanWachtend} IBAN-{ibanWachtend === 1 ? 'accordering' : 'accorderingen'} wachtend
          </span>
        )}
      </div>

      {/* KPI-niveau leeft óók per klant (mockup punt 2). */}
      <KpiRij
        laden={documenten === null && !documentenFout}
        kaarten={[
          {
            label: 'Te verwerken',
            waarde: documenten === null ? null : teVerwerken,
            stipKleur: 'warn',
            onClick: () => navigate(`/?administratie=${administratieId}&sectie=documenten`),
          },
          {
            label: 'Vragen',
            waarde: documenten === null ? null : vraagTeller,
            stipKleur: 'danger',
            delta: vraagTeller > 0 ? 'blokkeert boeken' : undefined,
            deltaWarn: true,
            onClick: () => navigate(`/?administratie=${administratieId}&sectie=vragen`),
          },
          {
            label: 'Bank af te letteren',
            waarde: rekeningenGeladen ? bankOpen : null,
            stipKleur: 'info',
            onClick: bankOpen > 0 ? () => navigate(`/bank/${administratieId}`) : undefined,
          },
          {
            label: 'Bij klant',
            waarde: documenten === null ? null : terAccordering.length,
            stipKleur: 'purple',
          },
        ]}
      />

      <KlantUpload administratieId={administratieId} onGeupload={laadDocumenten} />

      {documentenFout && (
        <FoutMelding
          melding="De documentstanden konden niet geladen worden."
          detail={documentenFout}
          onOpnieuw={laadDocumenten}
        />
      )}

      {/* Documenten per soort — alleen soorten met openstand (toon-regel 15-08). */}
      <div className="panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: standen.length > 0 ? 0 : 8 }}>
          <h2 style={{ margin: 0 }}>Te verwerken documenten</h2>
          {documenten !== null && open.length > 0 && <Badge variant="warn">{open.length} open</Badge>}
        </div>
        {documenten === null && !documentenFout && (
          <div aria-busy="true" style={{ paddingTop: 10 }}>
            <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
            <span className="skeleton" style={{ width: '40%' }} />
          </div>
        )}
        {documenten !== null && standen.length === 0 && (
          <p className="hint">Niets te verwerken — nieuwe documenten verschijnen hier vanzelf per soort.</p>
        )}
        {standen.length > 0 && (
          <div className="tabel-scroll" style={{ marginTop: 10 }}>
            <table>
              <tbody>
                <tr>
                  <th>Soort</th>
                  <th className="amount">Open</th>
                  <th>Oudste</th>
                  <th />
                </tr>
                {standen.map((stand) => (
                  <tr
                    key={stand.soort}
                    className="clickable"
                    onClick={() => navigate(`/?administratie=${administratieId}&sectie=documenten&soort=${stand.soort}`)}
                  >
                    <td>
                      <b>{soortLabel(stand.soort)}</b>
                    </td>
                    <td className="amount">{stand.open}</td>
                    <td>{stand.oudste ? ouderdomLabel(stand.oudste) : '—'}</td>
                    <td style={{ textAlign: 'right' }}>
                      <span className="rijlink text-primary" style={{ fontWeight: 600 }}>
                        Verwerken →
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {documenten !== null && (
          <p className="hint" style={{ marginBottom: 0 }}>
            Werken gebeurt per soort in het deelscherm.{' '}
            <button
              type="button"
              className="linkbtn"
              style={{ color: 'var(--primary)', border: 'none', background: 'none', cursor: 'pointer', padding: 0 }}
              onClick={() => navigate(`/?administratie=${administratieId}&sectie=documenten`)}
            >
              Alle documenten (incl. geboekt en verwijderd) →
            </button>
          </p>
        )}
      </div>

      {/* Openstaande vragen — alleen bij teller > 0. */}
      {openVragen.length > 0 && (
        <div className="panel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>Openstaande vragen</h2>
            <Badge variant="danger">{openVragen.length}</Badge>
          </div>
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Vraag</th>
                  <th>Bij</th>
                  <th>Sinds</th>
                  <th />
                </tr>
                {openVragen.map((vraag) => (
                  <tr
                    key={vraag.id}
                    className="clickable"
                    onClick={() =>
                      navigate(`/?administratie=${administratieId}&sectie=vragen&document=${vraag.document_id}`)
                    }
                  >
                    <td>
                      <b>{vraag.vraag_tekst}</b>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                        blokkeert {vraag.document_bestandsnaam}
                      </div>
                    </td>
                    <td>{naamVoor(vraag.toegewezen_aan)}</td>
                    <td>{ouderdomLabel(vraag.gesteld_op)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <span className="text-primary" style={{ fontWeight: 600 }}>
                        Beantwoorden →
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Bank per rekening — alleen rekeningen met open mutaties (toon-regel 15-08). */}
      {openRekeningen.length > 0 && (
        <div className="panel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <h2 style={{ margin: 0 }}>Bank — af te letteren</h2>
            <Badge variant="info">{bankOpen} open</Badge>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            Per rekening een eigen afletterscherm — deze pagina toont alleen de stand.
          </p>
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Rekening</th>
                  <th className="amount">Open mutaties</th>
                  <th />
                </tr>
                {openRekeningen.map((rekening) => (
                  <tr
                    key={rekening.id}
                    className="clickable"
                    onClick={() => navigate(`/bank/${administratieId}?rekening=${rekening.id}`)}
                  >
                    <td>
                      <b>{rekening.naam ?? 'Rekening'}</b>
                      {rekening.iban && (
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{rekening.iban}</div>
                      )}
                    </td>
                    <td className="amount">{rekening.open_mutaties}</td>
                    <td style={{ textAlign: 'right' }}>
                      <span className="text-primary" style={{ fontWeight: 600 }}>
                        Afletteren →
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Bij klant ter accordering — alleen bij teller > 0. */}
      {terAccordering.length > 0 && (
        <div className="panel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>Bij klant ter accordering</h2>
            <Badge variant="paars">{terAccordering.length}</Badge>
          </div>
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Document</th>
                  <th>Leverancier</th>
                  <th className="amount">Bedrag</th>
                  <th>Sinds</th>
                </tr>
                {terAccordering.map((d) => (
                  <tr key={d.id} className="clickable" onClick={() => navigate(documentRoute(administratieId, d))}>
                    <td>
                      <b>{d.bestandsnaam}</b>
                    </td>
                    <td>{d.leverancier ?? '—'}</td>
                    <td className="amount">{formatBedrag(d.totaalbedrag)}</td>
                    <td>{ouderdomLabel(d.laatst_gewijzigd_op)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

/** Upload gericht op déze klant (besluit 15-08: sleep-upload blijft óók op de klantpagina —
 * direct toegewezen, geen verzamelbak; .eml volgt de tenaamstelling-route). */
function KlantUpload({ administratieId, onGeupload }: { administratieId: string; onGeupload: () => void }) {
  const bestandInputRef = useRef<HTMLInputElement>(null)
  const [bezig, setBezig] = useState(false)
  const [sleepActief, setSleepActief] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [bericht, setBericht] = useState<string | null>(null)
  const [uploadSoort, setUploadSoort] = useState<'inkoopfactuur' | 'kassarapport'>('inkoopfactuur')

  const uploadBestand = useCallback(
    async (bestand: File) => {
      setBezig(true)
      setFout(null)
      setBericht(null)
      try {
        if (bestand.name.toLowerCase().endsWith('.eml')) {
          const resultaat = await verwerkEml(bestand)
          setBericht(
            resultaat.al_eerder_verwerkt
              ? `"${bestand.name}" was al eerder verwerkt (zelfde Message-ID) — niets dubbel gedaan.`
              : `"${bestand.name}" verwerkt: ${resultaat.bijlagen
                  .map((b) => `${b.bestandsnaam} → ${b.uitkomst.replaceAll('_', ' ')}`)
                  .join('; ') || 'geen bijlagen gevonden'}.`,
          )
          onGeupload()
          return
        }
        const formData = new FormData()
        formData.append('bestand', bestand)
        formData.append('soort', uploadSoort)
        const resultaat = await apiJson<UploadResponseDto>(`/administraties/${administratieId}/documenten`, {
          method: 'POST',
          body: formData,
        })
        setBericht(
          resultaat.mogelijk_duplicaat_van
            ? `"${bestand.name}" geüpload — mogelijk duplicaat, gemarkeerd ter controle.`
            : resultaat.status === 'extractie_wachtrij'
              ? `"${bestand.name}" geüpload — groot document, wordt op de achtergrond verwerkt.`
              : `"${bestand.name}" geüpload en in verwerking.`,
        )
        onGeupload()
      } catch (err) {
        setFout(err instanceof Error ? err.message : 'Upload mislukt')
      } finally {
        setBezig(false)
      }
    },
    [administratieId, onGeupload, uploadSoort],
  )

  return (
    <>
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
          if (bestand) void uploadBestand(bestand)
        }}
      >
        {bezig ? (
          'Bezig met uploaden…'
        ) : (
          <>
            Sleep hier een PDF-, UBL- of .eml-bestand naartoe, of <b>blader</b> — meteen toegewezen aan deze klant
            <br />
            <span style={{ fontSize: 12 }}>Sha256-duplicaatcheck bij binnenkomst; UBL wordt automatisch geparst.</span>
            <br />
            <label
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
              <Select
                aria-label="Documentsoort voor upload"
                value={uploadSoort}
                onChange={(e) => setUploadSoort(e.target.value as 'inkoopfactuur' | 'kassarapport')}
              >
                <option value="inkoopfactuur">Inkoopfactuur</option>
                <option value="kassarapport">Kassarapport (omzetboeking)</option>
              </Select>
            </label>
          </>
        )}
        <input
          ref={bestandInputRef}
          type="file"
          accept=".pdf,.xml,.eml"
          style={{ display: 'none' }}
          onChange={(e) => {
            const bestand = e.target.files?.[0]
            if (bestand) void uploadBestand(bestand)
          }}
        />
      </div>
      {fout && <FoutMelding melding={fout} />}
      {bericht && (
        <div className="hint" style={{ marginTop: -10, marginBottom: 16 }}>
          {bericht}
        </div>
      )}
    </>
  )
}
