import { useEffect, useState } from 'react'

/** Compacte regelweergave van de boekingsregels-tabel (punt 7 run A, Peter 02-10: "de regel-tabel scrolt horizontaal
 * zodat OMSCHRIJVING en het ×-knopje buiten beeld vallen op 1455 px"; overflow-les 18-09).
 *
 * Gemeten 02-10 (harness.html, headless, splitter-default 42/58): de formulier-pane is 530 px breed op 1280 px,
 * 591 px op 1385 px en 632 px op 1455 px, terwijl de kolomminima van 27-08/08-09 optellen tot 738 px (906 px mét
 * projectplicht). Kolommen smaller maken herhaalt de implosie van 27-08 (comboboxen van 22 px, omschrijving per letter
 * gebroken); de kolomminima blijven dus staan. In plaats daarvan schakelt de tabel om zodra haar container smaller is
 * dan die som: élke regel wordt dan één blok mét de omschrijving bovenaan (volle breedte) en de velden eronder in een
 * wrap-raster mét een label per veld (`data-label`), de ×-knop rechtsboven — niets valt buiten beeld, geen horizontale
 * scroll. Boven de som blijft de tabel exact zoals vóór 02-10 (`<colgroup>`-minima + inline min-width).
 *
 * Deterministisch op de containerbreedte (ResizeObserver; zonder ResizeObserver — jsdom, oude browsers — blijft de
 * brede tabel mét `.tabel-scroll` als vangnet). Het element komt als STATE binnen (callback-ref), niet als ref-object:
 * de tabel mount pas ná het laden van het boekvoorstel en een ref-object triggert dan geen her-run van het effect
 * (gemeten 02-10: zonder projectplicht bleef de tabel 738 px breed in een container van 590 px). Geen instelling, geen
 * server-state. */
export function useCompacteRegels(el: HTMLElement | null, minimaleBreedte: number): boolean {
  const [compact, setCompact] = useState(false)
  useEffect(() => {
    if (!el || typeof ResizeObserver === 'undefined') return
    const meet = () => setCompact(isCompact(el.clientWidth, minimaleBreedte))
    meet()
    const observer = new ResizeObserver(() => meet())
    observer.observe(el)
    return () => observer.disconnect()
  }, [el, minimaleBreedte])
  return compact
}

/** Puur: compact zodra de container (de `.tabel-scroll`-wrapper) smaller is dan de som van de kolomminima. Een
 * container zonder maat (0, nog niet gelayout) is nooit compact. */
export function isCompact(containerBreedte: number, minimaleBreedte: number): boolean {
  return containerBreedte > 0 && containerBreedte < minimaleBreedte
}
