// "Toon QR" (best-practice-punt D3, 01-09): rendert een BESTAANDE link (uitnodiging/herstel) als QR-code
// voor scannen op de bouwplaats — geen nieuw auth-pad, dezelfde eenmalige link en vervaltermijn, audit
// ongewijzigd. Werkt samen met de pincode-activatieflow van de native app (universal link).
import { QRCodeSVG } from 'qrcode.react'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from './basis'

export function QrLinkDialog({
  link,
  titel,
  uitleg,
  onSluiten,
}: {
  link: string | null
  titel: string
  uitleg?: string
  onSluiten: () => void
}) {
  return (
    <Dialog open={link !== null} onOpenChange={(open) => !open && onSluiten()}>
      <DialogContent data-testid="qr-dialoog" style={{ maxWidth: 420 }}>
        <DialogTitle>{titel}</DialogTitle>
        <DialogDescription>
          {uitleg ??
            'Laat de veldwerker deze code scannen met de telefoon — het is dezelfde eenmalige link als in de uitnodigingsmail, met dezelfde geldigheid (72 uur).'}
        </DialogDescription>
        {link && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '8px 0' }}>
            <div style={{ background: '#fff', padding: 12, borderRadius: 10 }}>
              <QRCodeSVG value={link} size={220} />
            </div>
            <code style={{ fontSize: 11, wordBreak: 'break-all', color: 'var(--muted)' }}>{link}</code>
          </div>
        )}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten}>
            Sluiten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
