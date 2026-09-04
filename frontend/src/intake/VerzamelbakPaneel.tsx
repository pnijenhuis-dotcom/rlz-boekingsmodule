import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import type { AdministratieDto } from '../api/types'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import {
  bevestigSplitsing,
  bulkHoortNietBijOns,
  bulkWijsToe,
  haalVerzamelbakOp,
  hoortNietBijOns,
  maakSamenvoegenOngedaan,
  wijsToe,
  type BulkVerzamelbakResponseDto,
  type VerzamelbakActieResultaatDto,
  type VerzamelbakItemDto,
} from './intakeApi'
import { bijlageOmschrijving, NooitSplitsenDialog } from './NooitSplitsenDialog'
import { SamenvoegDialog } from './SamenvoegDialog'
import { VerzamelbakPreview } from './VerzamelbakPreview'

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Reden waarmee een mislukte optimistische actie LUID terugkomt op de rij — nooit stil. */
export function redenVoorMislukking(err: unknown): string {
  if (err instanceof BackendOnbereikbaarError) {
    return 'Server niet bereikbaar (time-out) — niet verwerkt. Probeer het opnieuw.'
  }
  if (err instanceof ApiError) return `Niet verwerkt: ${err.message}`
  return 'Actie mislukt — niet verwerkt. Probeer het opnieuw.'
}

/** Verzamelbak "Niet toegewezen" (mockup werkvoorraad-paneel): platform-breed — alles wat de
 * intake niet eenduidig kon koppelen, zichtbaar tot een mens beslist. Leeg = paneel onzichtbaar
 * (mockup). Toewijzen leert het geheugen; "hoort niet bij ons" vereist een reden; een
 * splitsingsvoorstel wordt hier bevestigd of afgewezen — nooit stil auto-verwerkt. */
export function VerzamelbakPaneel({
  administraties,
  onGewijzigd,
}: {
  administraties: AdministratieDto[]
  onGewijzigd?: () => void
}) {
  const [items, setItems] = useState<VerzamelbakItemDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [keuze, setKeuze] = useState<Record<string, string>>({})
  const [bezig, setBezig] = useState<string | null>(null)
  const [redenVoor, setRedenVoor] = useState<VerzamelbakItemDto | null>(null)
  // "Is één factuur" (blok B 04-09): bevestigingsdialoog mét optionele vink "nooit splitsen" voor deze afzender.
  const [nooitSplitsenVoor, setNooitSplitsenVoor] = useState<VerzamelbakItemDto | null>(null)
  const [reden, setReden] = useState('')
  // Optimistisch toewijzen / hoort-niet-bij-ons (besluit Peter 26-08, casus collega): de rij
  // verdwijnt per direct, het request loopt op de achtergrond; mislukt → rij LUID terug mét reden.
  const [rijFouten, setRijFouten] = useState<Record<string, string>>({})
  const [stilleMeldingen, setStilleMeldingen] = useState<string[]>([])
  const onderweg = useRef(new Set<string>())
  // Selectie (02-09): twee rijen → Samenvoegen (dialoog, mens kiest het leidende bestand); één of meer
  // rijen → bulk-toewijzen / bulk "hoort niet bij ons" (blok B, casus IC-stapel). Selecteer-alles werkt
  // binnen het actieve tekstfilter; rijen mét een open splitsingsvoorstel zijn nooit selecteerbaar.
  const [geselecteerd, setGeselecteerd] = useState<string[]>([])
  const [samenvoegOpen, setSamenvoegOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [bulkKeuze, setBulkKeuze] = useState('')
  const [bulkRedenOpen, setBulkRedenOpen] = useState(false)
  const [bulkUitkomst, setBulkUitkomst] = useState<string | null>(null)
  const [bulkBezig, setBulkBezig] = useState(false)

  const laad = useCallback(() => {
    haalVerzamelbakOp()
      .then((data) => setItems(data.items))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [])

  useEffect(() => {
    laad()
  }, [laad])

  const actie = async (documentId: string, werk: () => Promise<unknown>) => {
    setBezig(documentId)
    setFout(null)
    try {
      await werk()
      laad()
      onGewijzigd?.()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setBezig(null)
    }
  }

  /** Optimistisch (patroon accordeur-fase-1-verzendrij, zonder retry: de server is idempotent, een
   * herhaalde klik is veilig). De DB blijft de bron van waarheid — verwijderen is puur presentatie:
   * geslaagd → rij blijft weg (al_verwerkt = rustige melding, geen fout); mislukt (4xx/5xx/
   * time-out) → dezelfde rij terug op haar plek mét rode reden. */
  const optimistischeActie = async (item: VerzamelbakItemDto, werk: () => Promise<VerzamelbakActieResultaatDto>) => {
    const id = item.document_id
    if (onderweg.current.has(id)) return // dubbeltik-vangnet
    onderweg.current.add(id)
    let index = 0
    setItems((huidig) => {
      if (!huidig) return huidig
      index = Math.max(0, huidig.findIndex((i) => i.document_id === id))
      return huidig.filter((i) => i.document_id !== id)
    })
    setRijFouten((f) => {
      if (!(id in f)) return f
      const kopie = { ...f }
      delete kopie[id]
      return kopie
    })
    try {
      const r = await werk()
      if (r?.al_verwerkt) {
        setStilleMeldingen((m) => [...m, `${item.bestandsnaam}: ${r.melding ?? 'was al verwerkt — niets opnieuw gedaan.'}`])
      }
      onGewijzigd?.()
    } catch (err) {
      const reden = redenVoorMislukking(err)
      setItems((huidig) => {
        const lijst = huidig ?? []
        if (lijst.some((i) => i.document_id === id)) return lijst
        const kopie = [...lijst]
        kopie.splice(Math.min(index, kopie.length), 0, item)
        return kopie
      })
      setRijFouten((f) => ({ ...f, [id]: reden }))
    } finally {
      onderweg.current.delete(id)
    }
  }

  /** Bulk (blok B 02-09): optimistisch — álle geselecteerde rijen verdwijnen direct, één request; per rij
   * komt de uitkomst terug (patroon bulk-accordering): 'fout' = rij LUID terug mét reden, 'al_verwerkt' =
   * rustige melding, 'verwerkt' = weg. Faalt het request zelf (5xx/time-out) → alle rijen terug. */
  const bulkActie = async (
    ids: string[],
    werk: (ids: string[]) => Promise<BulkVerzamelbakResponseDto>,
    omschrijving: (r: BulkVerzamelbakResponseDto) => string,
  ) => {
    if (bulkBezig || ids.length === 0) return
    const teDoen = ids.filter((id) => !onderweg.current.has(id))
    if (teDoen.length === 0) return
    teDoen.forEach((id) => onderweg.current.add(id))
    const weggehaald: { item: VerzamelbakItemDto; index: number }[] = []
    setItems((huidig) => {
      if (!huidig) return huidig
      huidig.forEach((i, index) => {
        if (teDoen.includes(i.document_id)) weggehaald.push({ item: i, index })
      })
      return huidig.filter((i) => !teDoen.includes(i.document_id))
    })
    setGeselecteerd([])
    setBulkBezig(true)
    setBulkUitkomst(null)
    const zetTerug = (welke: { item: VerzamelbakItemDto; index: number }[], redenVoor: (id: string) => string) => {
      if (welke.length === 0) return
      setItems((huidig) => {
        const kopie = [...(huidig ?? [])]
        welke
          .sort((a, b) => a.index - b.index)
          .forEach(({ item, index }) => {
            if (!kopie.some((i) => i.document_id === item.document_id)) kopie.splice(Math.min(index, kopie.length), 0, item)
          })
        return kopie
      })
      setRijFouten((f) => {
        const kopie = { ...f }
        welke.forEach(({ item }) => {
          kopie[item.document_id] = redenVoor(item.document_id)
        })
        return kopie
      })
    }
    try {
      const r = await werk(teDoen)
      const fouten = new Map(r.uitkomsten.filter((u) => u.uitkomst === 'fout').map((u) => [u.document_id, u.reden]))
      zetTerug(
        weggehaald.filter(({ item }) => fouten.has(item.document_id)),
        (id) => `Niet verwerkt: ${fouten.get(id) ?? 'onbekende reden'}`,
      )
      const alVerwerkt = r.uitkomsten.filter((u) => u.uitkomst === 'al_verwerkt')
      if (alVerwerkt.length > 0) {
        setStilleMeldingen((m) => [
          ...m,
          ...alVerwerkt.map((u) => `${u.bestandsnaam ?? u.document_id}: ${u.reden ?? 'was al verwerkt — niets opnieuw gedaan.'}`),
        ])
      }
      setBulkUitkomst(omschrijving(r))
      onGewijzigd?.()
    } catch (err) {
      const reden = redenVoorMislukking(err)
      zetTerug(weggehaald, () => reden)
      setBulkUitkomst(null)
    } finally {
      teDoen.forEach((id) => onderweg.current.delete(id))
      setBulkBezig(false)
    }
  }

  if (items === null || items.length === 0) {
    // Mockup: leeg = paneel onzichtbaar. Een laadfout tonen we wel — nooit stil.
    return fout ? (
      <FoutMelding
        melding='De verzamelbak "Niet toegewezen" kon niet geladen worden.'
        detail={fout}
        onOpnieuw={laad}
      />
    ) : null
  }

  const filterTerm = filter.trim().toLowerCase()
  const zichtbaar = filterTerm
    ? items.filter((i) =>
        [i.bestandsnaam, i.afzender_hint ?? '', i.tenaamstelling ?? '', administraties.find((a) => a.id === i.suggestie_administratie_id)?.naam ?? '']
          .join(' ')
          .toLowerCase()
          .includes(filterTerm),
      )
    : items
  // Rijen mét een al-toegewezen zusje (PDF/UBL van dezelfde factuur) blijven buiten "selecteer alles":
  // bulk-toewijzen zou er een tweede document van maken. Los aanvinken kan wél (mens beslist).
  const selecteerbaar = zichtbaar.filter((i) => !i.splitsing_voorstel && !i.zusje_document_id)
  const zusjesZichtbaar = zichtbaar.filter((i) => i.zusje_document_id).length
  const geselecteerdeItems = items.filter((i) => geselecteerd.includes(i.document_id))
  const allesGeselecteerd = selecteerbaar.length > 0 && selecteerbaar.every((i) => geselecteerd.includes(i.document_id))
  // Vooringevuld als álle geselecteerde rijen dezelfde suggestie dragen (blok B); anders kiest de mens.
  const gedeeldeSuggestie = (() => {
    const s = new Set(geselecteerdeItems.map((i) => i.suggestie_administratie_id ?? ''))
    return s.size === 1 && !s.has('') ? [...s][0] : ''
  })()
  const bulkDoel = bulkKeuze || gedeeldeSuggestie
  const bulkDoelNaam = administraties.find((a) => a.id === bulkDoel)?.naam

  return (
    <div className="panel" style={{ borderLeft: '3px solid var(--orange)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Niet toegewezen — handmatig koppelen ({items.length})</h2>
        <input
          type="search"
          aria-label="Filter verzamelbak"
          placeholder="filter op bestand, afzender, tenaamstelling…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ marginLeft: 'auto', minWidth: 240, fontSize: 12.5 }}
        />
        {filterTerm && (
          <span className="hint" style={{ margin: 0 }} data-testid="verzamelbak-filter-telling">
            {zichtbaar.length} van {items.length}
          </span>
        )}
      </div>
      {zusjesZichtbaar > 0 && (
        <div className="hint" data-testid="verzamelbak-zusje-banner" style={{ marginTop: 6 }}>
          ⚠ {zusjesZichtbaar} {zusjesZichtbaar === 1 ? 'rij is' : 'rijen zijn'} een UBL/PDF waarvan de tegenhanger uit dezelfde e-mail
          al is toegewezen. Toewijzen maakt dan een tweede document van dezelfde factuur; deze rijen vallen buiten
          &ldquo;selecteer alles&rdquo; en dragen een chip.
        </div>
      )}
      {geselecteerd.length > 0 && (
        <div
          className="bulkbalk"
          data-testid="verzamelbak-bulkbalk"
          style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 8, padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 10, fontSize: 12.5 }}
        >
          <strong>{geselecteerd.length} geselecteerd</strong>
          <span style={{ minWidth: 260 }}>
            <AdministratieCombobox
              label="Bulk toewijzen aan"
              toonLabel={false}
              administraties={administraties}
              waarde={bulkDoel}
              onWijzig={setBulkKeuze}
              placeholder="— kies administratie —"
            />
          </span>
          <button
            type="button"
            className="btn"
            style={{ padding: '5px 12px' }}
            disabled={!bulkDoel || bulkBezig}
            title={bulkDoel ? undefined : 'Kies eerst een administratie'}
            onClick={() =>
              void bulkActie(
                geselecteerd,
                (ids) => bulkWijsToe(ids, bulkDoel),
                (r) =>
                  `${r.verwerkt} toegewezen aan ${bulkDoelNaam ?? 'de administratie'}` +
                  (r.al_verwerkt > 0 ? `, ${r.al_verwerkt} al eerder verwerkt` : '') +
                  (r.fout > 0 ? `, ${r.fout} niet verwerkt (zie de rode rijen)` : '') +
                  '.',
              )
            }
          >
            Toewijzen aan {bulkDoelNaam ?? '…'} ({geselecteerd.length}) ✓
          </button>
          <button
            type="button"
            className="btn secondary"
            style={{ padding: '5px 12px' }}
            disabled={bulkBezig}
            onClick={() => {
              setReden('')
              setBulkRedenOpen(true)
            }}
          >
            Hoort niet bij ons ({geselecteerd.length})
          </button>
          <button
            type="button"
            className="btn secondary"
            style={{ padding: '5px 12px' }}
            disabled={geselecteerd.length !== 2 || bulkBezig}
            title={geselecteerd.length === 2 ? 'Twee bestanden van dezelfde factuur samenvoegen tot één document' : 'Selecteer precies twee rijen'}
            onClick={() => setSamenvoegOpen(true)}
          >
            Samenvoegen ({geselecteerd.length})
          </button>
          <button type="button" className="linkbtn" onClick={() => setGeselecteerd([])}>
            selectie wissen
          </button>
        </div>
      )}
      {bulkUitkomst && (
        <div className="hint" data-testid="verzamelbak-bulk-uitkomst" style={{ marginTop: 6 }}>
          {bulkUitkomst}
        </div>
      )}
      {fout && <div className="fout">{fout}</div>}
      {stilleMeldingen.length > 0 && (
        <div className="hint" data-testid="verzamelbak-al-verwerkt" style={{ marginTop: 0 }}>
          {stilleMeldingen.map((m, i) => (
            <div key={i}>{m}</div>
          ))}
        </div>
      )}
      {/* .tabel-scroll (responsive-fix 2026-08-15): vijf kolommen + toewijzen-select en
          actieknoppen maken de tabel op smalle vensters breder dan het paneel — intern
          scrollen i.p.v. door de paneelrand klippen (zelfde patroon als de
          boekingsregels-tabel; de mockup kent geen smal breakpoint). */}
      <div className="tabel-scroll">
        <table>
          <tbody>
            <tr>
              <th style={{ width: 28 }}>
                <input
                  type="checkbox"
                  aria-label={filterTerm ? `Selecteer alle ${selecteerbaar.length} gefilterde rijen` : `Selecteer alle ${selecteerbaar.length} rijen`}
                  checked={allesGeselecteerd}
                  disabled={selecteerbaar.length === 0}
                  onChange={(e) =>
                    setGeselecteerd((g) =>
                      e.target.checked
                        ? [...g.filter((id) => !selecteerbaar.some((i) => i.document_id === id)), ...selecteerbaar.map((i) => i.document_id)]
                        : g.filter((id) => !selecteerbaar.some((i) => i.document_id === id)),
                    )
                  }
                />
              </th>
              <th>Document</th>
              <th>Binnengekomen via</th>
              <th>Tenaamstelling / suggestie</th>
              <th>Toewijzen aan</th>
              <th />
            </tr>
            {zichtbaar.map((item) => {
              const suggestieNaam = administraties.find((a) => a.id === item.suggestie_administratie_id)?.naam
              const gekozen = keuze[item.document_id] ?? item.suggestie_administratie_id ?? ''
              // Proportionele validatie (02-09): een deel mét ongeldig_reden is door code afgewezen —
              // de mens ziet het; bevestigen kan pas als het voorstel geen ongeldig deel meer bevat.
              const ongeldigeDelen = (item.splitsing_voorstel ?? []).filter((s) => s.ongeldig_reden)
              // De échte intake-reden (02-09): "geen tenaamstelling gelezen" alleen als de AI niets las.
              const redenLabel = item.reden_label ?? (item.tenaamstelling ? null : 'geen tenaamstelling gelezen')
              const isGeselecteerd = geselecteerd.includes(item.document_id)
              return (
                <tr key={item.document_id}>
                  <td style={{ padding: '8px 4px' }}>
                    {!item.splitsing_voorstel && (
                      <input
                        type="checkbox"
                        aria-label={`Selecteer ${item.bestandsnaam}`}
                        checked={isGeselecteerd}
                        onChange={(e) =>
                          setGeselecteerd((g) =>
                            e.target.checked ? [...g.filter((id) => id !== item.document_id), item.document_id] : g.filter((id) => id !== item.document_id),
                          )
                        }
                      />
                    )}
                  </td>
                  <td>
                    {/* D1 (besluit 25-08): voorbeeld bij hover, klik = volledige weergave — lazy. */}
                    <VerzamelbakPreview
                      documentId={item.document_id}
                      bestandsnaam={item.bestandsnaam}
                      tenaamstelling={item.tenaamstelling}
                      beeldBestandsnaam={item.beeld_bestandsnaam ?? null}
                    />{' '}
                    {item.bestandsnaam}
                    {item.beeld_bestandsnaam && (
                      <span
                        className="chip geheugen"
                        style={{ marginLeft: 6 }}
                        title={
                          item.samengevoegd_document_id
                            ? 'Handmatig samengevoegd: dit bestand is leidend, het andere is het beeld/de bron'
                            : 'Gebundeld bij de intake: UBL + PDF van dezelfde factuur — UBL leidend, PDF als beeld'
                        }
                        data-testid="beeld-chip"
                      >
                        📎 {item.beeld_bestandsnaam}
                      </span>
                    )}
                    {item.zusje_document_id && (
                      <span
                        className="chip vraag"
                        style={{ marginLeft: 6 }}
                        data-testid="zusje-chip"
                        title={`${item.zusje_bestandsnaam ?? 'De tegenhanger'} uit dezelfde e-mail is al toegewezen${
                          administraties.find((a) => a.id === item.zusje_administratie_id)?.naam
                            ? ` aan ${administraties.find((a) => a.id === item.zusje_administratie_id)?.naam}`
                            : ''
                        } — deze rij toewijzen maakt een tweede document van dezelfde factuur.`}
                      >
                        ⚠ tegenhanger al toegewezen
                        {administraties.find((a) => a.id === item.zusje_administratie_id)?.naam
                          ? ` (${administraties.find((a) => a.id === item.zusje_administratie_id)?.naam})`
                          : ''}
                      </span>
                    )}
                    {item.samengevoegd_document_id && (
                      <button
                        type="button"
                        className="linkbtn"
                        style={{ marginLeft: 6, fontSize: 11.5 }}
                        disabled={bezig === item.document_id}
                        onClick={() =>
                          void actie(item.document_id, () => maakSamenvoegenOngedaan(item.document_id))
                        }
                      >
                        samenvoegen ongedaan maken
                      </button>
                    )}
                    {rijFouten[item.document_id] && (
                      <div className="fout" role="alert" style={{ marginTop: 4, fontSize: 12 }}>
                        {rijFouten[item.document_id]}{' '}
                        <button type="button" className="btn secondary" style={{ padding: '2px 8px' }} onClick={laad}>
                          Lijst verversen
                        </button>
                      </div>
                    )}
                    {item.soort !== 'inkoopfactuur' && (
                      <div>
                        <span className="chip klaar">{item.soort}</span>
                      </div>
                    )}
                    {item.splitsing_voorstel && (
                      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
                        Splitsingsvoorstel: {item.splitsing_voorstel.length} facturen —{' '}
                        {item.splitsing_voorstel
                          .map((s) => {
                            const bijlagen = bijlageOmschrijving(s)
                            return `p.${s.start_pagina}-${s.eind_pagina} ${s.tenaamstelling ?? '?'}${
                              bijlagen ? ` (${bijlagen})` : ''
                            }${s.ongeldig_reden ? ` ⚠ ongeldig (${s.ongeldig_reden})` : ''}`
                          })
                          .join(' · ')}
                      </div>
                    )}
                  </td>
                  <td>
                    {item.bron === 'email' ? 'e-mail' : 'upload'}
                    {item.afzender_hint ? ` · ${item.afzender_hint}` : ''}
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{formatDatum(item.aangemaakt_op)}</div>
                  </td>
                  <td>
                    {item.tenaamstelling && <span>&ldquo;{item.tenaamstelling}&rdquo;</span>}
                    {redenLabel && (
                      <div>
                        <span className="chip vraag" title={item.reden ?? undefined}>
                          {redenLabel}
                        </span>
                      </div>
                    )}
                    {suggestieNaam && (
                      <div>
                        <span className="chip ai">suggestie: {suggestieNaam}</span>
                      </div>
                    )}
                  </td>
                  <td>
                    {item.splitsing_voorstel ? (
                      <span className="hint" style={{ margin: 0 }}>
                        eerst de splitsing beoordelen
                      </span>
                    ) : (
                      <AdministratieCombobox
                        label={`Toewijzen aan voor ${item.bestandsnaam}`}
                        toonLabel={false}
                        administraties={administraties}
                        waarde={gekozen}
                        onWijzig={(id) => setKeuze((k) => ({ ...k, [item.document_id]: id }))}
                        placeholder="— kies administratie —"
                      />
                    )}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {item.splitsing_voorstel && item.splitsing_id ? (
                      <>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: '5px 12px' }}
                          disabled={bezig === item.document_id || ongeldigeDelen.length > 0}
                          title={
                            ongeldigeDelen.length > 0
                              ? 'Het voorstel bevat een deel met een ongeldig paginabereik — kies "Is één factuur" en wijs het document handmatig toe.'
                              : undefined
                          }
                          onClick={() =>
                            void actie(item.document_id, () =>
                              bevestigSplitsing(
                                item.splitsing_id!,
                                item.splitsing_voorstel!.map((s) => ({
                                  start_pagina: s.start_pagina,
                                  eind_pagina: s.eind_pagina,
                                  tenaamstelling: s.tenaamstelling,
                                })),
                              ),
                            )
                          }
                        >
                          Splitsing bevestigen ✓
                        </button>{' '}
                        <button
                          type="button"
                          className="btn secondary"
                          style={{ padding: '5px 12px' }}
                          disabled={bezig === item.document_id}
                          onClick={() => setNooitSplitsenVoor(item)}
                        >
                          Is één factuur
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: '5px 12px' }}
                          disabled={!gekozen || bezig === item.document_id}
                          onClick={() => void optimistischeActie(item, () => wijsToe(item.document_id, gekozen))}
                        >
                          Toewijzen ✓
                        </button>{' '}
                        <button
                          type="button"
                          className="btn secondary"
                          style={{ padding: '5px 12px' }}
                          disabled={bezig === item.document_id}
                          onClick={() => {
                            setReden('')
                            setRedenVoor(item)
                          }}
                        >
                          Hoort niet bij ons
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="hint">
        Alles wat de intake niet eenduidig aan een administratie kan koppelen komt hier terecht — er raakt
        nooit iets kwijt. Elke handmatige toewijzing wordt onthouden: dezelfde tenaamstelling wordt de volgende
        keer automatisch gekoppeld (een afzender alleen buiten de kantoor-/doorstuuradressen). UBL + PDF van
        dezelfde factuur worden bij binnenkomst gebundeld; mist dat een keer, selecteer dan twee rijen en kies
        &ldquo;Samenvoegen&rdquo;. Selecteer meerdere rijen (of alles binnen het filter) om ze in één keer toe te
        wijzen of als &ldquo;hoort niet bij ons&rdquo; af te handelen.
      </div>

      {nooitSplitsenVoor && (
        <NooitSplitsenDialog
          item={nooitSplitsenVoor}
          administraties={administraties}
          onSluit={() => setNooitSplitsenVoor(null)}
          onGereed={() => {
            setNooitSplitsenVoor(null)
            laad()
            onGewijzigd?.()
          }}
        />
      )}
      {samenvoegOpen && geselecteerd.length === 2 && (() => {
        const a = items.find((i) => i.document_id === geselecteerd[0])
        const b = items.find((i) => i.document_id === geselecteerd[1])
        if (!a || !b) return null
        return (
          <SamenvoegDialog
            items={[a, b]}
            onSluit={() => setSamenvoegOpen(false)}
            onGereed={(r) => {
              setSamenvoegOpen(false)
              setGeselecteerd([])
              if (r.waarschuwingen.length > 0) setStilleMeldingen((m) => [...m, ...r.waarschuwingen.map((w) => `Samengevoegd met waarschuwing: ${w}`)])
              laad()
              onGewijzigd?.()
            }}
          />
        )
      })()}
      {bulkRedenOpen && geselecteerd.length > 0 && (
        <div className="modal-bg open">
          <div className="modal">
            <h2>Hoort niet bij ons — {geselecteerd.length} documenten</h2>
            <div className="row">
              <label htmlFor="bulk-niet-van-ons-reden">Reden (verplicht, geldt voor de hele selectie)</label>
              <textarea
                id="bulk-niet-van-ons-reden"
                rows={3}
                value={reden}
                onChange={(e) => setReden(e.target.value)}
                placeholder="Bijv.: facturen voor een ander kantoor / geen klant van ons"
              />
            </div>
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setBulkRedenOpen(false)}>
                Annuleren
              </button>
              <button
                type="button"
                className="btn warn"
                disabled={!reden.trim()}
                onClick={() => {
                  const schoneReden = reden.trim()
                  const ids = geselecteerd
                  setBulkRedenOpen(false)
                  void bulkActie(
                    ids,
                    (sel) => bulkHoortNietBijOns(sel, schoneReden),
                    (r) =>
                      `${r.verwerkt} vastgelegd als "hoort niet bij ons"` +
                      (r.al_verwerkt > 0 ? `, ${r.al_verwerkt} al eerder verwerkt` : '') +
                      (r.fout > 0 ? `, ${r.fout} niet verwerkt (zie de rode rijen)` : '') +
                      '.',
                  )
                }}
              >
                Vastleggen ({geselecteerd.length}) ✓
              </button>
            </div>
          </div>
        </div>
      )}
      {redenVoor && (
        <div className="modal-bg open">
          <div className="modal">
            <h2>Hoort niet bij ons — {redenVoor.bestandsnaam}</h2>
            <div className="row">
              <label htmlFor="niet-van-ons-reden">Reden (verplicht)</label>
              <textarea
                id="niet-van-ons-reden"
                rows={3}
                value={reden}
                onChange={(e) => setReden(e.target.value)}
                placeholder="Bijv.: factuur voor een ander kantoor / geen klant van ons"
              />
            </div>
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setRedenVoor(null)}>
                Annuleren
              </button>
              <button
                type="button"
                className="btn warn"
                disabled={!reden.trim()}
                onClick={() => {
                  const doel = redenVoor
                  const schoneReden = reden.trim()
                  setRedenVoor(null)
                  void optimistischeActie(doel, () => hoortNietBijOns(doel.document_id, schoneReden))
                }}
              >
                Vastleggen ✓
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
