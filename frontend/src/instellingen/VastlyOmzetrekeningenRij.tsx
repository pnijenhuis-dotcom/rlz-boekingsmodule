import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { useAuthOptioneel } from '../auth/AuthContext'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { haalVastlyInstellingen, zetVastlyOmzetrekening, type VastlyInstellingenDto, type VastlyOmzetrekeningStandDto } from '../reconciliatie/VastlyActies'
import { Badge } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'

/** Vastgoed-koppeling › Vastly-omzetrekeningen (Peter 29-09, migratie 0172): per regelsoort (huur · servicekosten ·
 * waarborg · overig) de vaste omzetrekening waarop een Vastly-factuurregel ZONDER grootboekcode geboekt wordt. Bron
 * "afgeleid" (uit de eigen geboekte Vastly-facturen of het eenduidige rekeningschema) of "door u gekozen"; leeg = de
 * module kan de rekening niet afleiden en meldt dat als bevinding "Rekening kiezen" zodra er een factuur op wacht.
 * Beheerder kiest (server-side poort), andere rollen lezen. Daaronder de verhuurder-entiteiten die naar deze
 * administratie wijzen (KvK of naam; bron identiteit/mens). Alleen zichtbaar bij een vastgoed-administratie. */

export const REGELSOORT_LABEL: Record<string, string> = {
  huur: 'Huur',
  servicekosten: 'Servicekosten',
  waarborg: 'Waarborg',
  overig: 'Overig',
}

export function bronTekst(stand: VastlyOmzetrekeningStandDto): string {
  if (stand.bron === 'mens') return 'door u gekozen'
  if (stand.bron === 'historie') return 'afgeleid uit historie/rekeningschema'
  return 'nog niet afleidbaar — kies zodra een factuur erop wacht'
}

export function VastlyOmzetrekeningenRij({ administratieId, naam }: { administratieId: string; naam: string }) {
  const auth = useAuthOptioneel()
  const magMuteren = auth === null || auth.rol === 'beheerder'
  const [stand, setStand] = useState<VastlyInstellingenDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      setStand(await haalVastlyInstellingen(administratieId))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const opties = useMemo<ComboboxOptie[]>(
    () => (stand?.keuzelijst ?? []).map((k) => ({ id: k.ledger_id, code: k.code, label: k.naam })),
    [stand],
  )

  const kies = async (regelsoort: string, ledgerId: string | null) => {
    if (!ledgerId || !stand) return
    setBezig(regelsoort)
    setFout(null)
    try {
      const nieuw = await zetVastlyOmzetrekening(administratieId, regelsoort, ledgerId)
      setStand({ ...stand, omzetrekeningen: stand.omzetrekeningen.map((o) => (o.regelsoort === regelsoort ? nieuw : o)) })
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    } finally {
      setBezig(null)
    }
  }

  return (
    <InstellingRij
      titel="Vastly-omzetrekeningen"
      uitleg={`Huurfacturen uit Vastly boeken automatisch als omzet in ${naam}. Draagt een factuurregel geen grootboekcode, dan gebruikt de module per regelsoort deze vaste omzetrekening. Verhuurder-entiteiten die hier landen staan eronder.`}
    >
      {laadFout && (
        <span className="hint" style={{ color: 'var(--red)' }}>
          {laadFout}
        </span>
      )}
      {stand && (
        <div className="flex flex-col gap-2" style={{ minWidth: 0 }}>
          {stand.omzetrekeningen.map((o) => (
            <div key={o.regelsoort} className="flex flex-wrap items-center gap-2" data-testid={`vastly-omzetrekening-${o.regelsoort}`}>
              <span style={{ minWidth: 110 }}>{REGELSOORT_LABEL[o.regelsoort] ?? o.regelsoort}</span>
              {magMuteren ? (
                <span style={{ minWidth: 260 }}>
                  <SearchableCombobox
                    label={`Omzetrekening ${REGELSOORT_LABEL[o.regelsoort] ?? o.regelsoort}`}
                    toonLabel={false}
                    opties={opties}
                    waarde={o.ledger_id}
                    onWijzig={(id) => void kies(o.regelsoort, id || null)}
                    placeholder={bezig === o.regelsoort ? 'Opslaan…' : 'Rekening kiezen…'}
                  />
                </span>
              ) : (
                <span>{o.code ? `${o.code} ${o.naam ?? ''}` : '—'}</span>
              )}
              <Badge variant={o.bron === 'mens' ? 'ok' : o.bron === 'historie' ? 'info' : 'warn'}>{bronTekst(o)}</Badge>
            </div>
          ))}
          {fout && (
            <span className="hint" style={{ color: 'var(--red)' }}>
              {fout}
            </span>
          )}
          <div className="hint">
            {stand.entiteiten.length === 0
              ? 'Nog geen verhuurder-entiteit gekoppeld — de eerste Vastly-factuur mét KvK koppelt zichzelf via de identiteit van de administratie; zonder KvK koppelt u éénmalig via Inzicht › Reconciliatie.'
              : `Verhuurder-entiteiten: ${stand.entiteiten.map((e) => `${e.weergave ?? e.sleutel} (${e.sleutel_soort} ${e.sleutel}, ${e.bron === 'mens' ? 'door u gekoppeld' : 'via identiteit'})`).join(' · ')}`}
          </div>
        </div>
      )}
    </InstellingRij>
  )
}
