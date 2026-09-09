// Bundel 09-09 blok 2 (besluit Peter 08-09, herziet 01-09 beslispunt 2): een configuratiewijziging van de
// klant-accordering HERBEREKENT lopende rondes; alleen een ronde waarvan geen enkel gegeven akkoord meer past
// vervalt. Eén bron voor de tekst in de drie dialogen (detail-tab, bulk-dialoog, accordeur-venster) en de
// afdelingsroute — vooraf ("worden herberekend, waarvan M vervallen") en achteraf ("herberekend").

function rondes(n: number): string {
  return n === 1 ? '1 lopende accorderingsronde' : `${n} lopende accorderingsrondes`
}

/** Vooraf-telling (preview/bevestiging): "N lopende accorderingsrondes worden herberekend, waarvan M vervallen". */
export function rondesPreviewTekst(herberekend: number, vervallen: number): string {
  if (herberekend <= 0) return ''
  const kop = `${rondes(herberekend)} ${herberekend === 1 ? 'wordt' : 'worden'} herberekend`
  if (vervallen <= 0) return `${kop} (gegeven akkoorden blijven staan, ontbrekende lagen worden opnieuw aangevraagd)`
  return `${kop}, waarvan ${vervallen === 1 ? '1 vervalt' : `${vervallen} vervallen`} (geen enkel gegeven akkoord past daar nog; die documenten gaan terug naar "Klaar om te boeken")`
}

/** Achteraf (melding/toast), begint met een spatie zodat het achter "Opgeslagen." past; leeg bij 0. */
export function rondesTekst(herberekend: number, vervallen: number): string {
  if (herberekend <= 0) return ''
  const kop = ` ${rondes(herberekend)} herberekend: gegeven akkoorden blijven staan, ontbrekende lagen zijn opnieuw aangevraagd.`
  if (vervallen <= 0) return kop
  return `${kop} ${vervallen === 1 ? '1 daarvan is vervallen' : `${vervallen} daarvan zijn vervallen`} (geen enkel gegeven akkoord paste nog); die documenten staan weer op "Klaar om te boeken" — bied ze opnieuw aan.`
}
