import { useSearchParams } from 'react-router-dom'
import { ProjectenKantoorbreedScreen } from './ProjectenKantoorbreedScreen'
import { ProjectenScreen } from './ProjectenScreen'

/** Eén route `/projecten` (C5 07-09, kernprincipe 7 "administratie = filter, nooit poort"):
 * zónder `?administratie=` = de kantoorbrede Inzicht-lijst over alle administraties; mét
 * `?administratie=<id>` = de bestaande projectenlijst per administratie (deeplink-doel vanaf de
 * klantpagina, de chip op de documentenlijst en de administratie-link in de kantoorbrede lijst). */
export function ProjectenIngang() {
  const [searchParams] = useSearchParams()
  return searchParams.get('administratie') ? <ProjectenScreen /> : <ProjectenKantoorbreedScreen />
}
