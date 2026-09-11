// Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag) — chip "RLZ zet rechten door — opnieuw
// over N min" (tooltip = letterlijk RLZ-antwoord), de compacte EersteSyncStatus-regel en de sync-chip op de rij.
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EersteSyncRunDto } from '../api/types'
import { EersteSyncStatus } from './AdministratieWizard'
import { syncFoutTooltip } from './AdministratiesV2'
import {
  isRechtenOnderweg,
  minutenTotVolgendePoging,
  rechtenOnderwegTekst,
  rechtenOnderwegTooltip,
  rlzAntwoordVan,
} from './eersteSyncStand'

const RLZ_ANTWOORD = '{"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}'
const NU = new Date('2026-09-11T12:00:00Z')

const WACHTEND: EersteSyncRunDto = {
  run_id: 'r1',
  status: 'rechten_onderweg',
  onderdelen: {
    taxrates: { status: 'klaar', aangemaakt: 3, bijgewerkt: 0 },
    ledgers: {
      status: 'rechten_onderweg',
      http_status: 403,
      rlz_melding: RLZ_ANTWOORD,
      rlz_recht: 'leesrecht Grootboek',
      fout: `Reeleezee weigert GET Ledgers (HTTP 403) — leesrecht Grootboek. RLZ zegt: "${RLZ_ANTWOORD}"`,
    },
  },
  aangevraagd_op: '2026-09-11T11:55:00Z',
  beeindigd_op: null,
  fout_reden: null,
  pogingen: 1,
  volgende_poging_op: '2026-09-11T12:04:30Z',
}

describe('eersteSyncStand — helpers (blok 3 run 11-09)', () => {
  it('herkent de stand en rekent de minuten tot de volgende poging naar boven af', () => {
    expect(isRechtenOnderweg(WACHTEND)).toBe(true)
    expect(isRechtenOnderweg({ ...WACHTEND, status: 'fout' })).toBe(false)
    expect(isRechtenOnderweg(null)).toBe(false)
    expect(minutenTotVolgendePoging(WACHTEND, NU)).toBe(5)
    expect(minutenTotVolgendePoging({ ...WACHTEND, volgende_poging_op: '2026-09-11T11:50:00Z' }, NU)).toBe(0)
    expect(minutenTotVolgendePoging({ ...WACHTEND, volgende_poging_op: null }, NU)).toBeNull()
  })

  it('chip-tekst "RLZ zet rechten door — opnieuw over N min", "zo dadelijk" bij 0, neutraal zonder tijdstip', () => {
    expect(rechtenOnderwegTekst(WACHTEND, NU)).toBe('RLZ zet rechten door — opnieuw over 5 min')
    expect(rechtenOnderwegTekst({ ...WACHTEND, volgende_poging_op: '2026-09-11T11:59:59Z' }, NU)).toBe('RLZ zet rechten door — opnieuw zo dadelijk')
    expect(rechtenOnderwegTekst({ ...WACHTEND, volgende_poging_op: undefined }, NU)).toBe('RLZ zet rechten door — wordt opnieuw geprobeerd')
  })

  it('tooltip draagt het letterlijke RLZ-antwoord, de poging en de 24-uursgrens', () => {
    expect(rlzAntwoordVan(WACHTEND)).toBe(RLZ_ANTWOORD)
    const tooltip = rechtenOnderwegTooltip(WACHTEND)
    expect(tooltip).toContain(`RLZ zegt: ${RLZ_ANTWOORD}`)
    expect(tooltip).toContain('poging 1')
    expect(tooltip).toContain('na 24 uur zonder resultaat wordt de sync rood')
  })

  it('syncFoutTooltip (rij-chip) leest óók een wachtend onderdeel', () => {
    expect(syncFoutTooltip(WACHTEND)).toBe(`Reeleezee weigert GET Ledgers (HTTP 403) — leesrecht Grootboek. RLZ zegt: "${RLZ_ANTWOORD}"`)
  })
})

describe('EersteSyncStatus — wachtende run (blok 3 run 11-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('compact: chip "rechten onderweg" + regel mét minuten en poging, geen poll (run loopt niet), wél "Sync opnieuw starten"', () => {
    vi.useFakeTimers({ now: NU })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<EersteSyncStatus compact administratie={{ id: 'a1', naam: 'Baard beheer & management', rlz_admin_id: 'x' }} initieel={WACHTEND} />)
    // run-chip én onderdeel-chip (ledgers) dragen dezelfde stand
    const chips = screen.getAllByText('rechten onderweg')
    expect(chips).toHaveLength(2)
    chips.forEach((chip) => expect(chip).toHaveClass('chip', 'afwijking'))
    expect(screen.getByText(/RLZ zet rechten door — opnieuw over 5 min \(poging 1\)/)).toBeInTheDocument()
    expect(screen.getByText(`RLZ zegt: ${RLZ_ANTWOORD}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync opnieuw starten voor Baard beheer & management' })).toBeEnabled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('volledig (wizard): uitlegregel over het automatisch herproberen tot 24 uur', () => {
    vi.useFakeTimers({ now: NU })
    vi.stubGlobal('fetch', vi.fn())
    render(<EersteSyncStatus administratie={{ id: 'a1', naam: 'Baard', rlz_admin_id: 'x' }} initieel={WACHTEND} />)
    expect(screen.getByTestId('eerste-sync-rechten-onderweg')).toHaveTextContent('tot 24 uur')
    expect(screen.getByTestId('eerste-sync-rechten-onderweg')).toHaveTextContent('opnieuw over 5 min (poging 1)')
  })
})
