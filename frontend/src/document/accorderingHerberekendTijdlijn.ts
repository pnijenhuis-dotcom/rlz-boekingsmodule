// Tijdlijnregel "ronde herberekend" (bundel 09-09 blok 2): de backend schrijft bij een configuratiewijziging van de
// klant-accordering een notitie `detail.accordering_herberekend = {akkoorden_behouden, akkoorden_vervallen,
// opnieuw_aangevraagd: [volgnummers], alles_akkoord, lagen}` (service._herbereken_open_rondes). Puur, testbaar.

export interface AccorderingHerberekendDetail {
  akkoorden_behouden?: number
  akkoorden_vervallen?: number
  opnieuw_aangevraagd?: number[]
  alles_akkoord?: boolean
}

function akkoorden(n: number): string {
  return n === 1 ? '1 akkoord' : `${n} akkoorden`
}

export function accorderingHerberekendTekst(detail: unknown): string {
  const d = (detail && typeof detail === 'object' ? detail : {}) as AccorderingHerberekendDetail
  const behouden = typeof d.akkoorden_behouden === 'number' ? d.akkoorden_behouden : 0
  const vervallen = typeof d.akkoorden_vervallen === 'number' ? d.akkoorden_vervallen : 0
  const opnieuw = Array.isArray(d.opnieuw_aangevraagd) ? d.opnieuw_aangevraagd : []
  const delen: string[] = [`${akkoorden(behouden)} behouden`]
  if (vervallen > 0) delen.push(`${akkoorden(vervallen)} vervallen`)
  if (opnieuw.length > 0) delen.push(`${opnieuw.length === 1 ? 'laag' : 'lagen'} ${opnieuw.join(', ')} opnieuw aangevraagd`)
  if (d.alles_akkoord) delen.push('alle lagen gedekt — boeken gestart')
  return `Accordering herberekend (configuratie gewijzigd): ${delen.join(', ')}`
}
