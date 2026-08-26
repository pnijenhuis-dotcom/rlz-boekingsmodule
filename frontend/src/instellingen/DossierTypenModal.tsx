import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import {
  haalDossierDocumenttypen,
  zetDossierDocumenttypen,
  type DossierDocumenttypeDto,
} from '../meerwerk/meerwerkApi'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, useToastOptioneel, SkeletonRegels } from '../ui/basis'

/* Dossier-documenttypen als Beheerder-instelling per administratie (steigerbouw-run A1, 25-08).
 * Default-set (kopie ID, steigerpas, VCA vol, AVB, KvK-uittreksel) geldt tot de eerste
 * aanpassing; codes verdwijnen nooit (weglaten = inactief), zodat bestaande uploads zichtbaar
 * blijven. Elke wijziging geauditeerd. */
export function DossierTypenModal({ administratieId, naam, onSluiten }: { administratieId: string; naam: string; onSluiten: () => void }) {
  const { meld } = useToastOptioneel()
  const [typen, setTypen] = useState<DossierDocumenttypeDto[] | null>(null)
  const [isStandaard, setIsStandaard] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [nieuwNaam, setNieuwNaam] = useState('')

  useEffect(() => {
    haalDossierDocumenttypen(administratieId)
      .then((r) => {
        setTypen(r.typen)
        setIsStandaard(r.is_standaard)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Laden mislukt'))
  }, [administratieId])

  function wijzig(code: string, patch: Partial<DossierDocumenttypeDto>) {
    setTypen((huidig) => (huidig ?? []).map((t) => (t.code === code ? { ...t, ...patch } : t)))
  }

  function voegToe() {
    const naam = nieuwNaam.trim()
    if (!naam || !typen) return
    const code = naam
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40)
    if (code.length < 2 || typen.some((t) => t.code === code)) {
      setFout('Kies een unieke naam van minstens 2 tekens.')
      return
    }
    setTypen([...typen, { code, naam, verplicht: false, geldig_tot_vereist: false, bsn_gevoelig: false, volgorde: typen.length + 1, actief: true }])
    setNieuwNaam('')
  }

  async function opslaan() {
    if (!typen) return
    setBezig(true)
    setFout(null)
    try {
      const r = await zetDossierDocumenttypen(administratieId, typen)
      setTypen(r.typen)
      setIsStandaard(false)
      meld(`Documenttypen voor ${naam} opgeslagen — geauditeerd.`)
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent className="max-w-[720px]">
        <DialogTitle>Dossier-documenttypen — {naam}</DialogTitle>
        <DialogDescription>
          Welke documenten het ZZP-dossier per veldwerker moet bevatten (verplicht-vlag, geldig-tot verplicht, BSN-gevoelig =
          gemaskeerde weergave + geauditeerde inzage). Weglaten kan niet — uitzetten wel; bestaande uploads blijven zichtbaar.{' '}
          {isStandaard && <Badge variant="stil">standaardset — nog niet aangepast</Badge>}
        </DialogDescription>
        {fout && <div className="fout">{fout}</div>}
        {typen === null && !fout && <SkeletonRegels />}
        {typen !== null && (
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  <th>Document</th>
                  <th>Verplicht</th>
                  <th>Geldig-tot verplicht</th>
                  <th>BSN-gevoelig</th>
                  <th>Actief</th>
                </tr>
                {typen
                  .slice()
                  .sort((a, b) => a.volgorde - b.volgorde)
                  .map((t) => (
                    <tr key={t.code} style={{ opacity: t.actief ? 1 : 0.55 }}>
                      <td>
                        <input type="text" value={t.naam} onChange={(e) => wijzig(t.code, { naam: e.target.value })} style={{ width: '100%' }} />
                        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{t.code}</div>
                      </td>
                      <td>
                        <Checkbox checked={t.verplicht} onChange={(e) => wijzig(t.code, { verplicht: e.target.checked })} />
                      </td>
                      <td>
                        <Checkbox checked={t.geldig_tot_vereist} onChange={(e) => wijzig(t.code, { geldig_tot_vereist: e.target.checked })} />
                      </td>
                      <td>
                        <Checkbox checked={t.bsn_gevoelig} onChange={(e) => wijzig(t.code, { bsn_gevoelig: e.target.checked })} />
                      </td>
                      <td>
                        <Checkbox checked={t.actief} onChange={(e) => wijzig(t.code, { actief: e.target.checked })} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        {typen !== null && (
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <input type="text" placeholder="Nieuw documenttype (bv. G-rekening-overeenkomst)" value={nieuwNaam} onChange={(e) => setNieuwNaam(e.target.value)} style={{ flex: 1 }} />
            <Button variant="secundair" maat="klein" disabled={nieuwNaam.trim().length < 2} onClick={voegToe}>
              + Toevoegen
            </Button>
          </div>
        )}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || typen === null || typen.some((t) => !t.naam.trim())}>
            {bezig ? 'Bezig…' : 'Opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
