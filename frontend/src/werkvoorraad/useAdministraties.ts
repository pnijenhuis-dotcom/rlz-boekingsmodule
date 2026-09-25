import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type { AdministratieDto, MijnAdministratiesResponseDto } from '../api/types'

interface UseAdministratiesResultaat {
  administraties: AdministratieDto[] | null
  fout: string | null
}

/** Alleen de administraties waar de ingelogde gebruiker scope op heeft (GET /auth/administraties
 * — Beheerder ziet alles, zie app/auth/service.py::mijn_administraties).
 *
 * `voorgeladen` (blok 7 feedbackrun A 25-09, FV-18): een ouder dat de lijst al heeft (WerkvoorraadScreen) geeft 'm door,
 * dan haalt dit component 'm NIET opnieuw op. Aanleiding: `DocumentenBulkBalk` mount/unmount bij élke tabwissel zodra
 * klant-accordering aanstaat (de "Klaar om te boeken"-tab heeft een andere bulk-balk) en deed zo per tabwissel een
 * GET /auth/administraties — een tabwissel is client-side en hoort géén server-fetch te veroorzaken. */
export function useAdministraties(voorgeladen?: AdministratieDto[] | null): UseAdministratiesResultaat {
  const [administraties, setAdministraties] = useState<AdministratieDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const zelfOphalen = voorgeladen === undefined

  useEffect(() => {
    if (!zelfOphalen) return
    let actief = true
    apiJson<MijnAdministratiesResponseDto>('/auth/administraties')
      .then((data) => {
        if (actief) setAdministraties(data.administraties)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [zelfOphalen])

  if (!zelfOphalen) return { administraties: voorgeladen ?? null, fout: null }
  return { administraties, fout }
}
