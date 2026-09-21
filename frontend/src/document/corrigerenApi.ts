// Datalaag "Corrigeren…" (opdracht Peter 21-09) — spiegelt backend/app/documenten/schemas.py (corrigeer-toets /
// corrigeren). Eén leesroute (poorten + route) en één schrijfroute (storno + opnieuw klaarzetten, verplichte reden).

import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { CorrigeerBlokkadeDto, CorrigeerToetsDto, CorrigerenResponseDto } from '../api/types'

/** Minimale lengte van de reden — spiegelt `corrigeren.MIN_REDEN_LENGTE`. */
export const CORRIGEREN_REDEN_MINIMUM = 5

/** 409-code "tweede klik" — spiegelt `corrigeren.AL_GECORRIGEERD_CODE`. */
export const AL_GECORRIGEERD_CODE = 'al_gecorrigeerd'

export function haalCorrigeerToetsOp(administratieId: string, documentId: string): Promise<CorrigeerToetsDto> {
  return apiJson(`/administraties/${administratieId}/documenten/${documentId}/corrigeer-toets`)
}

export function corrigeerDocument(
  administratieId: string,
  documentId: string,
  reden: string,
): Promise<CorrigerenResponseDto> {
  return apiPostJson(`/administraties/${administratieId}/documenten/${documentId}/corrigeren`, { reden })
}

/** Het 409-detail van een geblokkeerde correctie (server: `CorrigerenNietToegestaan.als_detail`). */
export interface CorrigerenBlokkadeDetail {
  code: string
  bericht: string
  blokkades?: CorrigeerBlokkadeDto[]
  status?: string
}

export function corrigerenBlokkadeUit(err: unknown): CorrigerenBlokkadeDetail | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  const d = err.detail
  if (typeof d === 'object' && d !== null && typeof (d as { code?: unknown }).code === 'string') {
    return d as CorrigerenBlokkadeDetail
  }
  return null
}
