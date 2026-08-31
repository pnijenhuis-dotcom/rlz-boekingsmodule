// Numpad + voortgangs-dots (mockup app-lock-pincode.html schermen 1/2/5) — puur presentatie:
// de aanroeper houdt de code-state en beslist bij 5 cijfers. Cijfers verschijnen nooit op
// het scherm, alleen gevulde dots.

import { CODE_LENGTE } from '../../api/appSlot'

interface Props {
  code: string
  onCijfer: (cijfer: string) => void
  onWis: () => void
  /** Rood-gemarkeerde dots (na een foute code) zolang er nog niets nieuws is getypt. */
  fout?: boolean
  /** Optionele stille knop linksonder (bv. "‹ Terug" of "Opnieuw inloggen"). */
  linksKnop?: { label: string; onClick: () => void }
}

export function PincodeInvoer({ code, onCijfer, onWis, fout = false, linksKnop }: Props) {
  const dots = Array.from({ length: CODE_LENGTE }, (_, i) => {
    const vol = i < code.length
    const klasse = fout && code.length === 0 ? 'acc-pin-dot fout' : vol ? 'acc-pin-dot vol' : 'acc-pin-dot'
    return <span key={i} className={klasse} />
  })
  return (
    <>
      <div className="acc-pin-dots" data-testid="pin-dots">
        {dots}
      </div>
      <div className="acc-numpad">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((c) => (
          <button key={c} type="button" className="acc-num" onClick={() => onCijfer(c)}>
            {c}
          </button>
        ))}
        {linksKnop ? (
          <button type="button" className="acc-num stil" onClick={linksKnop.onClick}>
            {linksKnop.label}
          </button>
        ) : (
          <span />
        )}
        <button type="button" className="acc-num" onClick={() => onCijfer('0')}>
          0
        </button>
        <button type="button" className="acc-num stil" onClick={onWis}>
          Wis
        </button>
      </div>
    </>
  )
}
