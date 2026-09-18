import { describe, expect, it, vi } from 'vitest'
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import {
  aantalHerkansbaar,
  classificeerFout,
  filterToegestaan,
  maakItems,
  markeerVoorHerkansing,
  samenvatting,
  verzamelBestanden,
  voerWachtrijUit,
  voortgangTekst,
  type UploadItem,
} from './uploadWachtrij'

/** Guard bulk-upload (Peter 18-09): wachtrij max 4 gelijktijdig, statusvertaling per fout, Stoppen (lopende af, rest
 * niet gestart), Mislukte opnieuw, samenvatting, map-drop recursief. Puur — geen DOM. */

const f = (naam: string) => new File(['x'], naam, { type: 'application/pdf' })

function uitgesteld() {
  let los!: () => void
  const p = new Promise<void>((ok) => (los = ok))
  return { p, los }
}

describe('uploadWachtrij — wachtrij', () => {
  it('start maximaal 4 tegelijk en werkt de rest daarna af', async () => {
    const items = maakItems(Array.from({ length: 10 }, (_, i) => f(`f${i}.pdf`)))
    const open: (() => void)[] = []
    let piek = 0
    let lopend = 0
    const uploader = vi.fn(() => {
      lopend += 1
      piek = Math.max(piek, lopend)
      const { p, los } = uitgesteld()
      open.push(() => {
        lopend -= 1
        los()
      })
      return p.then(() => ({ status: 'klaar' as const, melding: null }))
    })
    const stand: UploadItem[][] = []
    const b = voerWachtrijUit(items, uploader, (s) => stand.push(s))
    await Promise.resolve()
    expect(uploader).toHaveBeenCalledTimes(4)
    expect(stand.at(-1)!.filter((i) => i.status === 'bezig')).toHaveLength(4)
    while (open.length) {
      open.shift()!()
      await new Promise((r) => setTimeout(r, 0))
    }
    const eind = await b.klaar
    expect(piek).toBe(4)
    expect(uploader).toHaveBeenCalledTimes(10)
    expect(eind.every((i) => i.status === 'klaar')).toBe(true)
    expect(samenvatting(eind)).toBe('10 aangeboden · 10 nieuw')
  })

  it('Stoppen: lopende ronden af, wachtende worden "niet gestart" en zijn herkansbaar', async () => {
    const items = maakItems(Array.from({ length: 6 }, (_, i) => f(`f${i}.pdf`)))
    const open: (() => void)[] = []
    const uploader = vi.fn(() => {
      const { p, los } = uitgesteld()
      open.push(los)
      return p.then(() => ({ status: 'klaar' as const, melding: null }))
    })
    const b = voerWachtrijUit(items, uploader, () => {})
    await Promise.resolve()
    b.stop()
    while (open.length) {
      open.shift()!()
      await new Promise((r) => setTimeout(r, 0))
    }
    const eind = await b.klaar
    expect(uploader).toHaveBeenCalledTimes(4)
    expect(eind.filter((i) => i.status === 'klaar')).toHaveLength(4)
    expect(eind.filter((i) => i.status === 'gestopt')).toHaveLength(2)
    expect(samenvatting(eind)).toBe('6 aangeboden · 4 nieuw · 2 niet gestart (gestopt)')
    expect(aantalHerkansbaar(eind)).toBe(2)
    const herkansing = markeerVoorHerkansing(eind)
    expect(herkansing.filter((i) => i.status === 'wachten')).toHaveLength(2)
  })

  it('fouten per bestand: 409 = al aanwezig (geen fout), 413 = te groot, netwerk = opnieuw; alleen herkansbare gaan opnieuw', async () => {
    const items = maakItems([f('ok.pdf'), f('dubbel.pdf'), f('groot.pdf'), f('offline.pdf'), f('kapot.pdf')])
    const uploader = vi.fn(async (bestand: File) => {
      switch (bestand.name) {
        case 'dubbel.pdf':
          throw new ApiError(409, 'Factuur 123.pdf')
        case 'groot.pdf':
          throw new ApiError(413, 'Bestand te groot')
        case 'offline.pdf':
          throw new BackendOnbereikbaarError('netwerk', 'Failed to fetch')
        case 'kapot.pdf':
          throw new ApiError(422, 'Afbeelding onbruikbaar: te klein')
        default:
          return { status: 'klaar' as const, melding: 'in verwerking' }
      }
    })
    const eind = await voerWachtrijUit(items, uploader, () => {}).klaar
    const per = Object.fromEntries(eind.map((i) => [i.bestand.name, i]))
    expect(per['dubbel.pdf'].status).toBe('al_aanwezig')
    expect(per['dubbel.pdf'].melding).toBe('al aanwezig: Factuur 123.pdf')
    expect(per['groot.pdf']).toMatchObject({ status: 'fout', opnieuw: false })
    expect(per['groot.pdf'].melding).toMatch(/te groot/)
    expect(per['offline.pdf']).toMatchObject({ status: 'fout', opnieuw: true })
    expect(per['kapot.pdf']).toMatchObject({ status: 'fout', opnieuw: false })
    expect(voortgangTekst(eind)).toBe('5 van 5 · 3 fouten')
    expect(samenvatting(eind)).toBe('5 aangeboden · 1 nieuw · 1 al aanwezig · 3 fouten')
    expect(aantalHerkansbaar(eind)).toBe(1)
    expect(markeerVoorHerkansing(eind).filter((i) => i.status === 'wachten').map((i) => i.bestand.name)).toEqual(['offline.pdf'])
  })

  it('timeout = onzeker (nooit opnieuw aanbieden), 429 = leesbaar + opnieuw, 5xx = opnieuw', () => {
    expect(classificeerFout(new BackendOnbereikbaarError('timeout', 'timer'))).toMatchObject({ status: 'onzeker', opnieuw: false })
    expect(classificeerFout(new BackendOnbereikbaarError('timeout', 'timer')).melding).toMatch(/niet opnieuw aanbieden/)
    expect(classificeerFout(new ApiError(429, 'Too Many Requests'))).toMatchObject({ status: 'fout', opnieuw: true })
    expect(classificeerFout(new ApiError(429, 'x')).melding).toMatch(/even te wachten/)
    expect(classificeerFout(new ApiError(500, 'Internal'))).toMatchObject({ status: 'fout', opnieuw: true })
    expect(classificeerFout(new Error('boem'))).toMatchObject({ status: 'fout', melding: 'boem', opnieuw: true })
  })
})

describe('uploadWachtrij — bestanden', () => {
  it('filtert op de accept-lijst en laat verborgen OS-bestanden weg', () => {
    const { toegestaan, geweigerd } = filterToegestaan([f('a.PDF'), f('b.xml'), f('c.eml'), f('d.heic'), f('e.docx'), f('.DS_Store')])
    expect(toegestaan.map((b) => b.name)).toEqual(['a.PDF', 'b.xml', 'c.eml', 'd.heic'])
    expect(geweigerd.map((b) => b.name)).toEqual(['e.docx'])
  })

  it('leest een gesleepte map recursief uit (webkitGetAsEntry, readEntries in porties)', async () => {
    const bestandEntry = (naam: string): FileSystemFileEntry =>
      ({ isFile: true, isDirectory: false, name: naam, file: (ok: (f: File) => void) => ok(f(naam)) }) as unknown as FileSystemFileEntry
    const mapEntry = (kinderen: FileSystemEntry[]): FileSystemDirectoryEntry => {
      let gelezen = false
      return {
        isFile: false,
        isDirectory: true,
        createReader: () => ({
          readEntries: (ok: (e: FileSystemEntry[]) => void) => {
            if (gelezen) return ok([])
            gelezen = true
            ok(kinderen)
          },
        }),
      } as unknown as FileSystemDirectoryEntry
    }
    const boom = mapEntry([bestandEntry('1.pdf'), mapEntry([bestandEntry('2.pdf'), bestandEntry('3.xml')])])
    const dt = {
      items: [{ webkitGetAsEntry: () => boom }, { webkitGetAsEntry: () => bestandEntry('los.pdf') }],
      files: [],
    } as unknown as DataTransfer
    const uit = await verzamelBestanden(dt)
    expect(uit.map((b) => b.name).sort()).toEqual(['1.pdf', '2.pdf', '3.xml', 'los.pdf'])
  })

  it('zonder mappen: gewoon alle dataTransfer.files', async () => {
    const dt = { items: [], files: [f('a.pdf'), f('b.pdf')] } as unknown as DataTransfer
    expect((await verzamelBestanden(dt)).map((b) => b.name)).toEqual(['a.pdf', 'b.pdf'])
  })
})
