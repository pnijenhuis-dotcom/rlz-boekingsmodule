import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type { AdministratieDto, MijnAdministratiesResponseDto } from '../api/types'

interface UseAdministratiesResultaat {
  administraties: AdministratieDto[] | null
  fout: string | null
}

/** Alleen de administraties waar de ingelogde gebruiker scope op heeft (GET /auth/administraties
 * — Beheerder ziet alles, zie app/auth/service.py::mijn_administraties). */
export function useAdministraties(): UseAdministratiesResultaat {
  const [administraties, setAdministraties] = useState<AdministratieDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
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
  }, [])

  return { administraties, fout }
}
