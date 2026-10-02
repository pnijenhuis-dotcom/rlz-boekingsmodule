// Native 1.3 / vc7 (run D 02-10 blok F, bug Peter 02-10 "Opslag-verwijderfout: null"): het SlotOpslagFout-scherm biedt
// "App-opslag opnieuw instellen" alleen als (a) de schil `herstel` draagt én (b) de laatste slotfout een KLUIS-fout is;
// anders (web-adapter, schil < 1.3, controle-fout) de melding van 10-09 ongewijzigd = het afwezig-pad.

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { SLOTFOUT_OPSLAG_SLEUTEL, bewaarLaatsteSlotfout, isKluisOpslagFout, leesLaatsteSlotfout } from '../../api/slotDiagnose'
import { herstelOpslag, kanOpslagHerstellen } from '../../api/appSlot'
import { APP_OPSLAG_HERSTEL_KOP, APP_OPSLAG_HERSTEL_MISLUKT_MELDING, SLOT_OPSLAG_MISLUKT_MELDING, SlotOpslagFout } from './SlotOpslagFout'

type Kluis = {
  zet: (o: { sleutel: string; waarde: string }) => Promise<void>
  haal: (o: { sleutel: string }) => Promise<{ waarde: string | null }>
  verwijder: (o: { sleutel: string }) => Promise<void>
  herstel?: () => Promise<{ hersteld: boolean }>
}

function stubNatief(kluis: Kluis): void {
  ;(window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    Plugins: { VeiligeOpslag: kluis },
  }
}

function kluisZonderHerstel(): Kluis {
  const opslag = new Map<string, string>()
  return {
    zet: ({ sleutel, waarde }) => {
      opslag.set(sleutel, waarde)
      return Promise.resolve()
    },
    haal: ({ sleutel }) => Promise.resolve({ waarde: opslag.get(sleutel) ?? null }),
    verwijder: ({ sleutel }) => {
      opslag.delete(sleutel)
      return Promise.resolve()
    },
  }
}

/** De fout van de foto IMG_2512: de kluis is onleesbaar, de laatste genoteerde slotfout is het `verwijder` uit herstelSlotWaarde. */
function noteerKluisfoutVanDeFoto(): void {
  bewaarLaatsteSlotfout({ handeling: 'verwijder', sleutel: 'appslot_slot', reden: new Error('Opslag-verwijderfout: null') })
}

// jsdom in deze suite heeft geen localStorage/sessionStorage (zelfde in-memory vervanger als AppActiveren.test.tsx).
function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (k: string) => opslag.get(k) ?? null,
    setItem: (k: string, v: string) => void opslag.set(k, String(v)),
    removeItem: (k: string) => void opslag.delete(k),
    clear: () => opslag.clear(),
    key: (i: number) => [...opslag.keys()][i] ?? null,
    get length() {
      return opslag.size
    },
  }
}

beforeAll(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: inMemoryOpslag() })
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: inMemoryOpslag() })
})

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  delete (window as unknown as { Capacitor?: unknown }).Capacitor
  localStorage.clear()
})

describe('isKluisOpslagFout — patroon van de plugin-rejecties', () => {
  it('herkent de Android-kluisfouten (ook "null" als bericht) en de iOS-Keychain-fouten', () => {
    noteerKluisfoutVanDeFoto()
    expect(isKluisOpslagFout(leesLaatsteSlotfout())).toBe(true)
    for (const reden of ['Opslag-schrijffout: AEADBadTagException (zonder melding)', 'Opslag-leesfout: KeyStoreException: x', 'Keychain-schrijffout (-34018)']) {
      bewaarLaatsteSlotfout({ handeling: 'schrijf', sleutel: 'appslot_slot', reden })
      expect(isKluisOpslagFout(leesLaatsteSlotfout())).toBe(true)
    }
  })

  it('een eigen controle-uitkomst is GEEN kluisfout (afwezig-pad)', () => {
    bewaarLaatsteSlotfout({ handeling: 'instellen', sleutel: 'appslot_slot', reden: 'terugleescontrole mislukt: opslag geeft niet terug wat geschreven is' })
    expect(isKluisOpslagFout(leesLaatsteSlotfout())).toBe(false)
    expect(isKluisOpslagFout(null)).toBe(false)
  })
})

describe('kanOpslagHerstellen / herstelOpslag', () => {
  it('web (geen Capacitor) en een schil zonder `herstel` → niet beschikbaar, niets aangeroepen', async () => {
    expect(kanOpslagHerstellen()).toBe(false)
    expect(await herstelOpslag()).toBe('niet_beschikbaar')
    stubNatief(kluisZonderHerstel())
    expect(kanOpslagHerstellen()).toBe(false)
    expect(await herstelOpslag()).toBe('niet_beschikbaar')
  })

  it('schil mét `herstel`: plugin aangeroepen, laatste slotfout gewist; een rejectie = mislukt mét diagnose zonder waarde', async () => {
    const herstel = vi.fn(() => Promise.resolve({ hersteld: true }))
    stubNatief({ ...kluisZonderHerstel(), herstel })
    noteerKluisfoutVanDeFoto()
    expect(kanOpslagHerstellen()).toBe(true)
    expect(await herstelOpslag()).toBe('hersteld')
    expect(herstel).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(SLOTFOUT_OPSLAG_SLEUTEL)).toBeNull()

    stubNatief({ ...kluisZonderHerstel(), herstel: () => Promise.reject(new Error('Opslag-herstelfout: KeyStoreException (zonder melding)')) })
    expect(await herstelOpslag()).toBe('mislukt')
    const fout = leesLaatsteSlotfout()
    expect(fout?.handeling).toBe('herstel')
    expect(fout?.reden).toContain('Opslag-herstelfout')
  })
})

describe('SlotOpslagFout-scherm', () => {
  it('kluisfout + schil mét herstel: kop "App-opslag opnieuw instellen", knop roept herstel aan en vervolgt de activatieflow (opnieuw)', async () => {
    const herstel = vi.fn(() => Promise.resolve({ hersteld: true }))
    stubNatief({ ...kluisZonderHerstel(), herstel })
    noteerKluisfoutVanDeFoto()
    const opnieuw = vi.fn()
    render(<SlotOpslagFout opnieuw={opnieuw} />)
    expect(screen.getByText(APP_OPSLAG_HERSTEL_KOP, { selector: 'b' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).not.toHaveTextContent('neem contact op met het kantoor')
    // De diagnoseregel noemt de kluisfout — handeling + sleutelnaam + reden, geen waarde.
    expect(screen.getByTestId('acc-diagnose').textContent).toContain('verwijder appslot_slot')
    expect(screen.getByTestId('acc-diagnose').textContent).toContain('Opslag-verwijderfout: null')
    await userEvent.click(screen.getByRole('button', { name: 'App-opslag opnieuw instellen' }))
    await waitFor(() => expect(opnieuw).toHaveBeenCalledTimes(1))
    expect(herstel).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('appslot_audit') ?? '').toContain('app_opslag_hersteld')
    expect(localStorage.getItem(SLOTFOUT_OPSLAG_SLEUTEL)).toBeNull()
  })

  it('herstel mislukt: eerlijke melding, scherm blijft staan, "Opnieuw proberen zonder wissen" werkt nog', async () => {
    stubNatief({ ...kluisZonderHerstel(), herstel: () => Promise.reject(new Error('Opslag-herstelfout: kluis opnieuw aangemaakt maar niet leesbaar')) })
    noteerKluisfoutVanDeFoto()
    const opnieuw = vi.fn()
    render(<SlotOpslagFout opnieuw={opnieuw} />)
    await userEvent.click(screen.getByRole('button', { name: 'App-opslag opnieuw instellen' }))
    expect(await screen.findByText(APP_OPSLAG_HERSTEL_MISLUKT_MELDING)).toBeInTheDocument()
    expect(opnieuw).not.toHaveBeenCalled()
    expect(screen.getByTestId('acc-diagnose').textContent).toContain('herstel appslot_slot')
    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw proberen zonder wissen' }))
    expect(opnieuw).toHaveBeenCalledTimes(1)
  })

  it('afwezig-pad web (geen plugin): de melding van 10-09, geen herstelknop', () => {
    noteerKluisfoutVanDeFoto()
    render(<SlotOpslagFout opnieuw={() => undefined} />)
    expect(screen.getByRole('alert')).toHaveTextContent(SLOT_OPSLAG_MISLUKT_MELDING)
    expect(screen.queryByRole('button', { name: 'App-opslag opnieuw instellen' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Opnieuw proberen' })).toBeInTheDocument()
  })

  it('afwezig-pad schil < 1.3 (plugin zonder herstel) en afwezig-pad controle-fout mét herstel: oude melding', () => {
    stubNatief(kluisZonderHerstel())
    noteerKluisfoutVanDeFoto()
    const { unmount } = render(<SlotOpslagFout opnieuw={() => undefined} />)
    expect(screen.queryByText(APP_OPSLAG_HERSTEL_KOP, { selector: "b" })).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent(SLOT_OPSLAG_MISLUKT_MELDING)
    unmount()
    stubNatief({ ...kluisZonderHerstel(), herstel: () => Promise.resolve({ hersteld: true }) })
    bewaarLaatsteSlotfout({ handeling: 'instellen', sleutel: 'appslot_slot', reden: 'ontsleutelcontrole mislukt ná schrijven' })
    render(<SlotOpslagFout opnieuw={() => undefined} />)
    expect(screen.queryByText(APP_OPSLAG_HERSTEL_KOP, { selector: "b" })).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent(SLOT_OPSLAG_MISLUKT_MELDING)
  })
})
