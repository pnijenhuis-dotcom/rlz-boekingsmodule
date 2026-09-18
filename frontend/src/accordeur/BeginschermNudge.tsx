/** "Zet deze app op je beginscherm" (SPOED 18-09): een web-toestel in een gewoon browsertabblad verliest bij elke
 * volledige herlaad (terugknop uit de app, pull-to-refresh, tabblad-herstel) het geheugen — als geïnstalleerde PWA
 * start de app als een echte app, krijgt persistente opslag en heeft geen browserbalk/terugknop-val. Eén kaart, weg te
 * klikken (lokaal onthouden). */
import { useState } from 'react'
import { beginschermNudgeWeg, beginschermStappen, toonBeginschermNudge } from '../api/webToestel'

export function BeginschermNudge() {
  const [zichtbaar, setZichtbaar] = useState(() => toonBeginschermNudge())
  if (!zichtbaar) return null
  return (
    <div className="acc-notitie waarschuw" data-testid="beginscherm-nudge" style={{ margin: '10px 16px 0' }}>
      <span>📲</span>
      <span>
        <b>Zet deze app op je beginscherm.</b> Dan start hij als een echte app, blijft hij ingelogd en verlies je niets bij
        een terugknop of verversen. {beginschermStappen()}{' '}
        <button
          type="button"
          className="acc-tekstlink"
          onClick={() => {
            beginschermNudgeWeg()
            setZichtbaar(false)
          }}
        >
          Niet meer tonen
        </button>
      </span>
    </div>
  )
}
