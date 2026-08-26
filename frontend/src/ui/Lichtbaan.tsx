import { useEffect } from 'react'

/** Lichtbaan (designpass v2 punt 3, Vastly-patroon 24-08): subtiele radiale teal-gloed bovenaan
 * het landingsscherm — ALLEEN op de werkvoorraad-ingang en ALLEEN in het donkere thema. Zet een
 * klasse op <html>; de tekening staat in shell/Shell.css (`html.dark.lichtbaan .main::before`),
 * zodat de paginaboom geen wrapper nodig heeft. Unmount = klasse weg, dus geen ander scherm
 * erft de gloed. thema.ts blijft ongewijzigd (de gloed volgt de bestaande `dark`-klasse). */
export function Lichtbaan() {
  useEffect(() => {
    document.documentElement.classList.add('lichtbaan')
    return () => document.documentElement.classList.remove('lichtbaan')
  }, [])
  return null
}
