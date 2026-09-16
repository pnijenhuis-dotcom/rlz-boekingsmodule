import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { GebruikerRijMenu } from '../gebruikers/GebruikerRijMenu'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, SkeletonRegels } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { haalStores, koppelStore, wijzigStore, type OmzetStoreDto } from './storesApi'

/** Instellingen › Boeken platformbreed — blok "Stores" (Peter 16-09 avond: Sunshine Island is een eigen BV, dus een
 * ándere administratie dan Elderveld; migratie 0151). Eén platformbrede lijst store → administratie: de dagstaat noemt
 * de store zélf ("Store Used"), dus die is leidend boven mailbox/tenaamstelling. Een onbekende store zet de dagstaat in
 * de verzamelbak mét de reden en een link naar dít blok (lege stand = actie). Lijstpatroon (store · administratie ·
 * status · ⋯), één primaire knop "+ Store koppelen"; ontkoppelen = actief uit, nooit verwijderen. De per-administratie-
 * lijst op Boeken & AI is sinds 0151 alleen een afgeleide weergave ("stores die hier landen"). */

function foutTekst(err: unknown, standaard: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : standaard
}

export function StoresBlok() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [stores, setStores] = useState<OmzetStoreDto[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [nieuweStore, setNieuweStore] = useState('')
  const [nieuweAdministratie, setNieuweAdministratie] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [verhuis, setVerhuis] = useState<OmzetStoreDto | null>(null)
  const [verhuisDoel, setVerhuisDoel] = useState<string | null>(null)

  const laad = useCallback(() => {
    setLaadFout(null)
    haalStores()
      .then((d) => setStores(d.stores))
      .catch((err: unknown) => setLaadFout(foutTekst(err, 'Stores laden mislukt')))
  }, [])
  useEffect(() => laad(), [laad])

  const koppel = async () => {
    const naam = nieuweStore.trim()
    if (!naam || !nieuweAdministratie) return
    setBezig(true)
    setActieFout(null)
    try {
      const dto = await koppelStore(naam, nieuweAdministratie)
      setStores((rijen) => {
        const rest = (rijen ?? []).filter((r) => r.id !== dto.id)
        return [...rest, dto].sort((a, b) => a.store_norm.localeCompare(b.store_norm))
      })
      setNieuweStore('')
    } catch (err) {
      setActieFout(foutTekst(err, 'Store koppelen mislukt'))
    } finally {
      setBezig(false)
    }
  }

  const wijzig = async (rij: OmzetStoreDto, body: { administratie_id?: string; actief?: boolean }) => {
    setBezig(true)
    setActieFout(null)
    try {
      const dto = await wijzigStore(rij.id, body)
      setStores((rijen) => (rijen ?? []).map((r) => (r.id === dto.id ? dto : r)))
      setVerhuis(null)
    } catch (err) {
      setActieFout(foutTekst(err, 'Wijzigen mislukt'))
    } finally {
      setBezig(false)
    }
  }

  const menuItems = (rij: OmzetStoreDto) => [
    { label: 'Andere administratie…', onClick: () => { setVerhuisDoel(rij.administratie_id); setVerhuis(rij) } },
    rij.actief
      ? { label: 'Ontkoppelen', gevaar: true, onClick: () => void wijzig(rij, { actief: false }) }
      : { label: 'Opnieuw activeren', onClick: () => void wijzig(rij, { actief: true }) },
  ]

  const lijst = administraties ?? []

  return (
    <div id="stores" data-testid="stores-blok" style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
      <div style={{ minWidth: 0 }}>
        <h2 style={{ margin: 0 }}>Stores (kassarapporten zonnestudio)</h2>
        <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
          De dagstaat van een studio noemt zelf de store (&ldquo;Store Used&rdquo;). Hier staat per store in welke administratie
          de dagstaat én de kascheck van die dag landen — één lijst voor alle administraties, elke store hoogstens één keer.
          Een dagstaat met een store die hier niet staat, komt in de verzamelbak met de reden en een link naar dit blok.
          Ontkoppelen laat de regel staan (uit); niets verdwijnt.
        </p>
      </div>
      {laadFout && <div className="fout">{laadFout}</div>}
      {administratiesFout && <div className="fout">{administratiesFout}</div>}
      {actieFout && !verhuis && <div className="fout" role="alert">{actieFout}</div>}
      {stores === null && !laadFout && <SkeletonRegels />}
      {stores !== null && stores.length === 0 && (
        <p className="hint" data-testid="stores-blok-leeg" style={{ marginTop: 8 }}>
          Nog geen store gekoppeld — voeg hieronder de naam toe zoals hij in de dagstaat staat (bijvoorbeeld &ldquo;Elderveld&rdquo;
          of &ldquo;Sunshine Island&rdquo;) en kies de administratie.
        </p>
      )}
      {stores !== null && stores.length > 0 && (
        <div className="tabel-scroll" style={{ marginTop: 8 }}>
          <table className="gebruikers-tabel" style={{ minWidth: 560 }}>
            <thead>
              <tr>
                <th>Store (&ldquo;Store Used&rdquo;)</th>
                <th>Administratie</th>
                <th style={{ width: 130 }}>Status</th>
                <th style={{ width: 60 }} />
              </tr>
            </thead>
            <tbody>
              {stores.map((r) => (
                <tr key={r.id} data-testid="store-rij">
                  <td style={{ fontWeight: 600 }}>{r.store_naam}</td>
                  <td>{r.administratie_naam}</td>
                  <td>
                    <span className={r.actief ? 'chip ok' : 'chip'} title={r.bron === 'migratie' ? 'overgenomen uit de oude per-administratie-lijst' : undefined}>
                      {r.actief ? 'actief' : 'ontkoppeld'}
                    </span>
                  </td>
                  <td>
                    <GebruikerRijMenu naam={`store ${r.store_naam}`} items={menuItems(r)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form
        style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 10 }}
        onSubmit={(e) => {
          e.preventDefault()
          void koppel()
        }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5 }}>
          Nieuwe store
          <input
            aria-label="Naam nieuwe store"
            placeholder="Store Used, bv. Sunshine Island"
            value={nieuweStore}
            disabled={bezig}
            style={{ width: 240 }}
            onChange={(e) => setNieuweStore(e.target.value)}
          />
        </label>
        <div style={{ minWidth: 280 }}>
          <AdministratieCombobox
            label="Administratie voor deze store"
            administraties={lijst}
            waarde={nieuweAdministratie}
            onWijzig={setNieuweAdministratie}
          />
        </div>
        <Button type="submit" disabled={bezig || !nieuweStore.trim() || !nieuweAdministratie}>
          + Store koppelen
        </Button>
      </form>
      {verhuis && (
        <Dialog open onOpenChange={(o) => !o && !bezig && setVerhuis(null)}>
          <DialogContent aria-describedby={undefined} data-testid="store-verhuis-dialoog">
            <DialogTitle>Store &ldquo;{verhuis.store_naam}&rdquo; naar een andere administratie</DialogTitle>
            <DialogDescription>
              Nieuwe dagstaten met deze store landen daarna in de gekozen administratie. Al toegewezen documenten
              verhuizen niet mee (dat kan per document via &ldquo;Verplaatsen&rdquo;).
            </DialogDescription>
            <AdministratieCombobox
              label="Nieuwe administratie"
              administraties={lijst}
              waarde={verhuisDoel}
              onWijzig={setVerhuisDoel}
              uitgesloten={[verhuis.administratie_id]}
            />
            {actieFout && <div className="fout" role="alert" style={{ marginTop: 8 }}>{actieFout}</div>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setVerhuis(null)} disabled={bezig}>
                Annuleren
              </Button>
              <Button
                type="button"
                disabled={bezig || !verhuisDoel || verhuisDoel === verhuis.administratie_id}
                onClick={() => verhuisDoel && void wijzig(verhuis, { administratie_id: verhuisDoel })}
              >
                {bezig ? 'Bezig…' : 'Verhuizen'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
