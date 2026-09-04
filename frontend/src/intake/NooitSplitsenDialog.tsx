import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieDto } from '../api/types'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { wijsSplitsingAf, type VerzamelbakItemDto } from './intakeApi'

/** Bijlage-bewuste omschrijving van één splitsingsdeel (blok B 04-09): "factuur + N bijlagepagina('s)" of
 * "factuur, N pagina('s)"; onbekend (voorstellen van vóór 04-09, fp=0) = geen toevoeging. Puur presentatie —
 * de getallen komen deterministisch uit de backend. */
export function bijlageOmschrijving(segment: { start_pagina: number; eind_pagina: number; bijlage_paginas?: number | null }): string {
  const bijlagen = segment.bijlage_paginas
  if (bijlagen === null || bijlagen === undefined) return ''
  if (bijlagen === 0) {
    const paginas = segment.eind_pagina - segment.start_pagina + 1
    return paginas === 1 ? 'factuur, 1 pagina' : `factuur, ${paginas} pagina's`
  }
  return bijlagen === 1 ? 'factuur + 1 bijlagepagina' : `factuur + ${bijlagen} bijlagepagina's`
}

/** "Is één factuur" (blok B 04-09, cases Universal Nederland/Delta): het splitsingsvoorstel wordt afgewezen
 * en het document blijft als één geheel (factuur + bijlagen) in de verzamelbak. Optioneel — vink default UIT
 * — onthoudt het kantoor de correctie als regel "mails van ‹afzender› voor ‹administratie› nooit splitsen":
 * de intake slaat voor dat afzenderadres de splitsings-AI dan over. Zonder afzender (upload) is de vink er
 * niet, mét uitleg; de administratie-kiezer staat vooringevuld op de suggestie van de rij. */
export function NooitSplitsenDialog({
  item,
  administraties,
  onGereed,
  onSluit,
}: {
  item: VerzamelbakItemDto
  administraties: AdministratieDto[]
  onGereed: () => void
  onSluit: () => void
}) {
  const [onthoud, setOnthoud] = useState(false)
  const [administratieId, setAdministratieId] = useState<string>(item.suggestie_administratie_id ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const afzender = item.afzender_hint
  const administratieNaam = administraties.find((a) => a.id === administratieId)?.naam
  const kanBevestigen = !bezig && (!onthoud || administratieId !== '')

  const bevestig = async () => {
    if (!item.splitsing_id) return
    setBezig(true)
    setFout(null)
    try {
      await wijsSplitsingAf(item.splitsing_id, null, { onthoudNietSplitsen: onthoud, administratieId: administratieId || null })
      onGereed()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afwijzen mislukt — niet verwerkt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluit()}>
      <DialogContent data-testid="nooit-splitsen-dialoog">
        <DialogTitle>Is één factuur</DialogTitle>
        <DialogDescription>
          Het splitsingsvoorstel wordt afgewezen; <b>{item.bestandsnaam}</b> blijft als één document (factuur mét
          bijlagen) in de verzamelbak en wijs je daarna gewoon toe.
        </DialogDescription>
        {afzender ? (
          <div style={{ display: 'grid', gap: 8, margin: '10px 0' }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, cursor: 'pointer' }}>
              <Checkbox checked={onthoud} onChange={(e) => setOnthoud(e.target.checked)} />
              <span>
                Onthoud: mails van <b>{afzender}</b> voor <b>{administratieNaam ?? '…'}</b> nooit splitsen
              </span>
            </label>
            {onthoud && (
              <>
                <AdministratieCombobox
                  label="Administratie voor de regel"
                  administraties={administraties}
                  waarde={administratieId}
                  onWijzig={setAdministratieId}
                  placeholder="— kies administratie —"
                />
                <p className="hint" style={{ margin: 0 }}>
                  De splitsings-AI wordt voor dit afzenderadres overgeslagen (één factuur + bijlagen); de tenaamstelling-toewijzing
                  loopt gewoon door. De regel staat op de administratie-detailpagina onder Algemeen › Intake-regels en is daar te
                  verwijderen. Handmatig samenvoegen in de verzamelbak blijft het vangnet.
                </p>
              </>
            )}
          </div>
        ) : (
          <p className="hint" data-testid="nooit-splitsen-geen-afzender">
            Dit document kwam zonder e-mail binnen (upload) — er is geen afzenderadres om een &ldquo;nooit
            splitsen&rdquo;-regel aan te koppelen.
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onSluit} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={!kanBevestigen}>
            {bezig ? 'Bezig…' : onthoud ? 'Afwijzen en onthouden' : 'Is één factuur'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
