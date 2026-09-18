/** Android-terugknop in de WEB-flow (SPOED 18-09): in een browsertab verlaat "terug" de app (de flow wisselt schermen
 * zonder history-entries), de gebruiker komt terug via een volledige herlaad en ziet het toegangscode-scherm — "uitgelogd".
 * De val: één history-entry bij binnenkomst; elke popstate zetten we terug en vertalen we naar het event `acc-terug`,
 * dat de flows afhandelen als "één scherm terug" (UrenFlow: `terugVan`). Native (Capacitor) heeft zijn eigen
 * backButton-afhandeling en slaat dit over. */
export const ACC_TERUG_EVENT = 'acc-terug'
const STATE = { accTerugVal: true }

export function installeerAndroidTerugVal(win: Window = window): () => void {
  const capacitor = (globalThis as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor
  if (capacitor?.isNativePlatform?.()) return () => undefined
  try {
    win.history.pushState(STATE, '')
  } catch {
    return () => undefined
  }
  const opPop = () => {
    try {
      win.history.pushState(STATE, '')
    } catch {
      /* geen history → niets te vangen */
    }
    win.dispatchEvent(new CustomEvent(ACC_TERUG_EVENT))
  }
  win.addEventListener('popstate', opPop)
  return () => win.removeEventListener('popstate', opPop)
}
