// Afdelingen-beheer per administratie (bouwrun 28-08 blok A, mockup afdelingen.html §1 = norm):
// tabel Afdeling / Accorderingsroute / Staande goedkeuringen, per rij "Route wijzigen" en
// "Archiveren" (nooit verwijderen), "+ Afdeling toevoegen". De terugval "Algemeen" volgt de
// administratie-route (Instellingen › Klant-accordering) en is niet archiveerbaar. Verschijnt
// alleen als de toggle van de administratie aan staat.
import { useCallback, useEffect, useState } from 'react'
import { haalAccorderingKandidaten, type KandidaatDto } from '../accordering/accorderingApi'
import {
  archiveerAfdeling,
  haalAfdelingen,
  maakAfdelingAan,
  routeSamenvatting,
  zetAfdelingRoute,
  type AfdelingDto,
} from '../afdelingen/afdelingenApi'
import { ApiError } from '../api/client'
import { BevestigDialog } from './BevestigDialog'
import { Badge, Button, Select, SkeletonRegels } from '../ui/basis'

interface LaagInvoer {
  accordeurId: string
  drempel: string
}

function RouteEditor({
  administratieId,
  afdeling,
  kandidaten,
  onKlaar,
}: {
  administratieId: string
  afdeling: AfdelingDto
  kandidaten: KandidaatDto[]
  onKlaar: (melding: string | null) => void
}) {
  const [lagen, setLagen] = useState<LaagInvoer[]>(
    afdeling.route.length > 0
      ? afdeling.route.map((laag) => ({ accordeurId: laag.accordeur_gebruiker_id, drempel: laag.bedrag_drempel ?? '' }))
      : [{ accordeurId: '', drempel: '' }],
  )
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await zetAfdelingRoute(
        administratieId,
        afdeling.id,
        lagen
          .filter((laag) => laag.accordeurId)
          .map((laag, index) => ({
            volgnummer: index + 1,
            accordeur_gebruiker_id: laag.accordeurId,
            bedrag_drempel: laag.drempel ? laag.drempel.replace(',', '.') : null,
          })),
      )
      const vervallen = resultaat.rondes_vervallen
      onKlaar(
        vervallen > 0
          ? `Route van "${afdeling.naam}" opgeslagen. ${vervallen} lopende ${vervallen === 1 ? 'accordering is' : 'accorderingen zijn'} vervallen (route gewijzigd) en staan weer op "Klaar om te boeken" — bied ze opnieuw aan.`
          : `Route van "${afdeling.naam}" opgeslagen.`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="panel" style={{ marginTop: 8, display: 'grid', gap: 10 }} data-testid="afdeling-route-editor">
      <b>Accorderingsroute — {afdeling.naam}</b>
      {fout && <div className="fout">{fout}</div>}
      {kandidaten.length === 0 && (
        <p className="hint" style={{ margin: 0 }}>
          Geen klant-accordeurs met toegang tot deze administratie — nodig eerst een gebruiker uit met de rol
          Klant-accordeur en koppel die aan deze administratie.
        </p>
      )}
      {lagen.map((laag, index) => (
        <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ minWidth: 52 }}>Laag {index + 1}</span>
          <Select
            aria-label={`Accordeur laag ${index + 1} (${afdeling.naam})`}
            value={laag.accordeurId}
            onChange={(e) =>
              setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, accordeurId: e.target.value } : l)))
            }
          >
            <option value="">— kies accordeur —</option>
            {kandidaten.map((k) => (
              <option key={k.id} value={k.id}>
                {k.naam}
              </option>
            ))}
          </Select>
          <input
            aria-label={`Bedragdrempel laag ${index + 1} (${afdeling.naam})`}
            placeholder="drempel (leeg = alle facturen)"
            style={{ width: 220 }}
            value={laag.drempel}
            onChange={(e) => setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)))}
          />
          <Button variant="secundair" maat="klein" onClick={() => setLagen((huidig) => huidig.filter((_, i) => i !== index))}>
            Verwijderen
          </Button>
        </div>
      ))}
      <div className="actions" style={{ margin: 0 }}>
        <Button variant="secundair" maat="klein" onClick={() => setLagen((huidig) => [...huidig, { accordeurId: '', drempel: '' }])}>
          + Laag toevoegen
        </Button>
        <Button maat="klein" disabled={bezig} onClick={() => void opslaan()}>
          {bezig ? 'Opslaan…' : 'Route opslaan'}
        </Button>
        <Button variant="ghost" maat="klein" onClick={() => onKlaar(null)}>
          Annuleren
        </Button>
      </div>
      <div className="hint" style={{ margin: 0 }}>
        Deze route vervángt de administratie-route voor documenten van deze afdeling. Wijzigen laat lopende rondes
        van deze afdeling vervallen (zichtbaar, mét reden) — net als bij de administratie-route.
      </div>
    </div>
  )
}

export function AfdelingenBeheer({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [afdelingen, setAfdelingen] = useState<AfdelingDto[] | null>(null)
  const [kandidaten, setKandidaten] = useState<KandidaatDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [routeVoor, setRouteVoor] = useState<string | null>(null)
  const [nieuweNaam, setNieuweNaam] = useState('')
  const [toevoegenOpen, setToevoegenOpen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [archiveerVoor, setArchiveerVoor] = useState<AfdelingDto | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([haalAfdelingen(administratieId), haalAccorderingKandidaten(administratieId)])
      .then(([lijst, kandidatenDto]) => {
        setAfdelingen(lijst.afdelingen)
        setKandidaten(kandidatenDto.kandidaten)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Afdelingen laden mislukt'))
  }, [administratieId])

  useEffect(() => laad(), [laad])

  const toevoegen = async () => {
    const schoon = nieuweNaam.trim()
    if (!schoon) return
    setBezig(true)
    setFout(null)
    try {
      await maakAfdelingAan(administratieId, schoon)
      setNieuweNaam('')
      setToevoegenOpen(false)
      setMelding(`Afdeling "${schoon}" toegevoegd — stel nu de accorderingsroute in.`)
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Toevoegen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const archiveren = async () => {
    if (!archiveerVoor) return
    setBezig(true)
    setFout(null)
    try {
      await archiveerAfdeling(administratieId, archiveerVoor.id)
      setMelding(`Afdeling "${archiveerVoor.naam}" gearchiveerd — documenten die er nog naar wijzen vragen om een nieuwe keuze.`)
      setArchiveerVoor(null)
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Archiveren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const actieve = (afdelingen ?? []).filter((a) => a.actief)
  const gearchiveerd = (afdelingen ?? []).filter((a) => !a.actief)

  return (
    <div className="panel afdelingen-beheer" data-testid={`afdelingen-${administratieId}`}>
      <h3 style={{ margin: 0 }}>Afdelingen — {naam}</h3>
      <p className="hint" style={{ marginTop: 4 }}>
        Per afdeling een eigen accorderingsroute (zelfde lagen als de klant-accordering). Afdelingen worden
        gearchiveerd, nooit verwijderd — documenten verwijzen ernaar. &ldquo;Algemeen&rdquo; is de terugval en volgt
        de route van de administratie.
      </p>
      {fout && <div className="fout">{fout}</div>}
      {melding && (
        <div className="hint" role="status">
          {melding}
        </div>
      )}
      {afdelingen === null && !fout ? (
        <SkeletonRegels />
      ) : (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Afdeling</th>
                <th>Accorderingsroute</th>
                <th>Staande goedkeuringen</th>
                <th className="acties" />
              </tr>
            </thead>
            <tbody>
              {actieve.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{a.naam}</b>{' '}
                    {a.is_terugval && (
                      <Badge variant="stil" title="Volgt de accorderingsroute van de administratie">
                        terugval
                      </Badge>
                    )}
                  </td>
                  <td>
                    {a.is_terugval
                      ? 'Route van de administratie (bestaande config)'
                      : a.route.length > 0
                        ? routeSamenvatting(a.route)
                        : <Badge variant="warn">nog geen route — aanbieden blokkeert</Badge>}
                  </td>
                  <td>{a.staande_goedkeuringen > 0 ? `${a.staande_goedkeuringen} actief` : '—'}</td>
                  <td className="acties" style={{ whiteSpace: 'nowrap' }}>
                    {a.is_terugval ? (
                      <span className="hint">route wijzigen: Klant-accordering</span>
                    ) : (
                      <>
                        <Button variant="secundair" maat="klein" onClick={() => setRouteVoor(routeVoor === a.id ? null : a.id)}>
                          Route wijzigen
                        </Button>{' '}
                        <Button variant="ghost" maat="klein" onClick={() => setArchiveerVoor(a)}>
                          Archiveren
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {gearchiveerd.map((a) => (
                <tr key={a.id} style={{ opacity: 0.6 }}>
                  <td>
                    {a.naam} <Badge variant="stil">gearchiveerd</Badge>
                  </td>
                  <td>—</td>
                  <td>{a.staande_goedkeuringen > 0 ? `${a.staande_goedkeuringen} actief` : '—'}</td>
                  <td className="acties" />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {routeVoor && afdelingen && (
        <RouteEditor
          administratieId={administratieId}
          afdeling={afdelingen.find((a) => a.id === routeVoor)!}
          kandidaten={kandidaten}
          onKlaar={(m) => {
            setRouteVoor(null)
            if (m) {
              setMelding(m)
              laad()
            }
          }}
        />
      )}
      <div className="actions" style={{ marginTop: 8 }}>
        {toevoegenOpen ? (
          <>
            <input
              aria-label={`Naam nieuwe afdeling (${naam})`}
              placeholder="Naam van de afdeling"
              value={nieuweNaam}
              maxLength={80}
              onChange={(e) => setNieuweNaam(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void toevoegen()
              }}
            />
            <Button maat="klein" disabled={bezig || !nieuweNaam.trim()} onClick={() => void toevoegen()}>
              Toevoegen
            </Button>
            <Button variant="ghost" maat="klein" onClick={() => setToevoegenOpen(false)}>
              Annuleren
            </Button>
          </>
        ) : (
          <Button variant="secundair" maat="klein" onClick={() => setToevoegenOpen(true)}>
            + Afdeling toevoegen
          </Button>
        )}
      </div>
      {archiveerVoor && (
        <BevestigDialog
          titel={`Afdeling "${archiveerVoor.naam}" archiveren?`}
          bericht={`De afdeling verdwijnt uit de keuzelijst; documenten die er nog naar verwijzen blokkeren tot een andere afdeling is gekozen. De eigen accorderingsroute wordt uitgezet. Niets wordt verwijderd.`}
          bezig={bezig}
          fout={null}
          onBevestigen={() => void archiveren()}
          onAnnuleren={() => setArchiveerVoor(null)}
        />
      )}
    </div>
  )
}
