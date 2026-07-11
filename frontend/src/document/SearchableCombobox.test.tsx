import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SearchableCombobox } from './SearchableCombobox'

/** jsdom geeft altijd een nul-rect — voor de positioneringstests prikken we een echte plek in
 * de viewport op het invoerveld (jsdom: window.innerHeight = 768, innerWidth = 1024). */
function zetVeldRect(veld: HTMLElement, top: number, opties?: { left?: number; width?: number; hoogte?: number }) {
  const { left = 40, width = 200, hoogte = 30 } = opties ?? {}
  veld.getBoundingClientRect = () =>
    ({
      top,
      bottom: top + hoogte,
      left,
      right: left + width,
      width,
      height: hoogte,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect
}

const OPTIES = [
  { id: '1', label: 'Aap' },
  { id: '2', label: 'Beer' },
  { id: '3', label: 'Cavia' },
]

describe('SearchableCombobox', () => {
  it('rendert de opties-lijst buiten een table-container met overflow: hidden (portal)', async () => {
    const gebruiker = userEvent.setup()
    const { container } = render(
      <table style={{ overflow: 'hidden' }}>
        <tbody>
          <tr>
            <td>
              <SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />
            </td>
          </tr>
        </tbody>
      </table>,
    )

    await gebruiker.click(screen.getByRole('combobox', { name: 'Grootboek' }))

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    // De listbox mag geen DOM-afstammeling van de (clippende) table zijn — anders zou
    // `overflow: hidden` op de table 'm nog steeds kunnen afknippen.
    expect(container.contains(listbox)).toBe(false)
    expect(document.body.contains(listbox)).toBe(true)
    expect(screen.getByText('Aap')).toBeInTheDocument()
  })

  it('opent met de eerste resultaten zodra het veld focus krijgt, zonder eerst te moeten typen', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde={null} onWijzig={() => {}} />)

    await gebruiker.click(screen.getByRole('combobox', { name: 'Crediteur' }))

    expect(screen.getByText('Aap')).toBeInTheDocument()
    expect(screen.getByText('Beer')).toBeInTheDocument()
  })

  it('opnieuw klikken op een al-gefocust, nog steeds ingevuld veld heropent de lijst', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde="2" onWijzig={() => {}} />)

    const veld = screen.getByRole('combobox', { name: 'Crediteur' })
    await gebruiker.click(veld) // opent + focust
    await gebruiker.keyboard('{Escape}') // sluit, veld blijft focused
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await gebruiker.click(veld) // zelfde, al-focused veld opnieuw aanklikken
    expect(screen.getByRole('listbox', { name: 'Crediteur' })).toBeInTheDocument()
  })

  it('toetsenbordnavigatie: pijltjes + enter kiezen een optie, escape sluit zonder te kiezen', async () => {
    const gebruiker = userEvent.setup()
    const onWijzig = vi.fn()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde={null} onWijzig={onWijzig} />)

    const veld = screen.getByRole('combobox', { name: 'Crediteur' })
    await gebruiker.click(veld)
    await gebruiker.keyboard('{ArrowDown}{Enter}')

    expect(onWijzig).toHaveBeenCalledWith('2')
  })

  it('toont code+naam (het volledige label) van de gekozen waarde na selectie', async () => {
    const gebruiker = userEvent.setup()
    function Wrapper() {
      const [waarde, setWaarde] = useState<string | null>(null)
      return (
        <SearchableCombobox
          label="Grootboek"
          opties={[{ id: '1', label: '4699 · Diverse algemene kosten' }]}
          waarde={waarde}
          onWijzig={setWaarde}
        />
      )
    }
    render(<Wrapper />)
    await gebruiker.click(screen.getByRole('combobox', { name: 'Grootboek' }))
    // Rol-query: het aria-hidden breedte-anker herhaalt deze tekst, de echte optie heeft de rol.
    await gebruiker.click(screen.getByRole('option', { name: '4699 · Diverse algemene kosten' }))
    expect(screen.getByRole('combobox', { name: 'Grootboek' })).toHaveValue('4699 · Diverse algemene kosten')
  })

  it('optie met een code toont die vet vóór de omschrijving, en zet ze samen als invoerwaarde', async () => {
    const gebruiker = userEvent.setup()
    function Wrapper() {
      const [waarde, setWaarde] = useState<string | null>(null)
      return (
        <SearchableCombobox
          label="Btw-code"
          opties={[{ id: '1', code: '21%', label: 'NL, Hoog Tarief' }]}
          waarde={waarde}
          onWijzig={setWaarde}
        />
      )
    }
    render(<Wrapper />)
    await gebruiker.click(screen.getByRole('combobox', { name: 'Btw-code' }))

    // Binnen de échte optie (rol-query — het aria-hidden breedte-anker herhaalt dezelfde tekst).
    const optie = screen.getByRole('option', { name: /21%.*NL, Hoog Tarief/ })
    const code = optie.querySelector('.combobox-optie-code')
    expect(code).not.toBeNull()
    expect(code!.textContent).toBe('21%')

    await gebruiker.click(screen.getByRole('option', { name: /21%.*NL, Hoog Tarief/ }))
    expect(screen.getByRole('combobox', { name: 'Btw-code' })).toHaveValue('21% · NL, Hoog Tarief')
  })

  it('toonLabel=false verbergt het zichtbare label maar behoudt de aria-label', () => {
    render(
      <SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} toonLabel={false} />,
    )
    expect(screen.queryByText('Grootboek')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /Grootboek/ })).toBeInTheDocument()
  })

  // ————— Positionering (bugfix 2026-07-11): flip, viewport-clamp, herpositioneren, uit beeld —————

  it('opent naar beneden met ruimte onder het veld, met de hoogte op de standaard acht rijen', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    const veld = screen.getByRole('combobox', { name: 'Grootboek' })
    zetVeldRect(veld, 100) // ruim 600px onder het veld (innerHeight 768)

    await gebruiker.click(veld)

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    expect(listbox.style.top).toBe('130px') // rect.bottom
    expect(listbox.style.bottom).toBe('')
    expect(listbox.style.maxHeight).toBe('264px') // 8 rijen × 32 + 8
  })

  it('flipt naar boven als er onder het veld onvoldoende ruimte is', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    const veld = screen.getByRole('combobox', { name: 'Grootboek' })
    zetVeldRect(veld, 700) // onderin: ~30px ruimte onder, ~692px boven

    await gebruiker.click(veld)

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    // Naar boven verankerd aan de bovenkant van het veld (CSS bottom op position: fixed).
    expect(listbox.style.bottom).toBe(`${768 - 700}px`)
    expect(listbox.style.top).toBe('')
  })

  it('clampt de hoogte op de beschikbare ruimte zodat de lijst binnen de viewport blijft', async () => {
    // Kleine viewport: aan géén van beide kanten past de volle lijst — hij opent dan naar de
    // ruimste kant (onder) met de hoogte geclampt op wat daar past, en scrolt intern.
    const origineleHoogte = window.innerHeight
    window.innerHeight = 400
    try {
      const gebruiker = userEvent.setup()
      render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
      const veld = screen.getByRole('combobox', { name: 'Grootboek' })
      zetVeldRect(veld, 180) // boven 172px, onder 400−210−8 = 182px → onder wint, geclampt

      await gebruiker.click(veld)

      const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
      expect(listbox.style.top).toBe('210px')
      expect(listbox.style.bottom).toBe('')
      expect(listbox.style.maxHeight).toBe('182px')
    } finally {
      window.innerHeight = origineleHoogte
    }
  })

  it('herpositioneert bij scroll en sluit zodra het veld uit beeld raakt', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    const veld = screen.getByRole('combobox', { name: 'Grootboek' })
    zetVeldRect(veld, 100)
    await gebruiker.click(veld)
    expect(screen.getByRole('listbox', { name: 'Grootboek' }).style.top).toBe('130px')

    // De pagina scrolt: het veld schuift omhoog → de lijst schuift mee (geen "zwevende" lijst).
    zetVeldRect(veld, 60)
    fireEvent.scroll(window)
    expect(screen.getByRole('listbox', { name: 'Grootboek' }).style.top).toBe('90px')

    // Het veld scrolt (vrijwel) uit beeld → de lijst sluit in plaats van los te zweven.
    zetVeldRect(veld, -40)
    fireEvent.scroll(window)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  // ————— Breedte (UI-polish 2026-07-11): leesbare opties, binnen de viewport —————

  it('mag breder worden dan het veld voor leesbare opties: tot 1,6× de veldbreedte', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    const veld = screen.getByRole('combobox', { name: 'Grootboek' })
    zetVeldRect(veld, 100, { width: 200 })

    await gebruiker.click(veld)

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    expect(listbox.style.minWidth).toBe('200px') // nooit smaller dan het veld
    expect(listbox.style.maxWidth).toBe('320px') // 1,6 × 200, ruim binnen de viewport (1024)
  })

  it('valt op een smalle viewport terug op de veldbreedte (ellipsis is dan het vangnet)', async () => {
    const origineleBreedte = window.innerWidth
    window.innerWidth = 200
    try {
      const gebruiker = userEvent.setup()
      render(<SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
      const veld = screen.getByRole('combobox', { name: 'Grootboek' })
      zetVeldRect(veld, 100, { left: 8, width: 184 })

      await gebruiker.click(veld)

      // Beschikbaar (200 − 16 = 184) < 1,6×veld → terug naar de veldbreedte, nooit smaller.
      expect(screen.getByRole('listbox', { name: 'Grootboek' }).style.maxWidth).toBe('184px')
    } finally {
      window.innerWidth = origineleBreedte
    }
  })

  it('schuift naar links als de gerenderde lijst rechts buiten de viewport zou steken', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    const veld = screen.getByRole('combobox', { name: 'Btw-code' })
    zetVeldRect(veld, 100, { left: 800, width: 200 }) // veld tegen de rechterrand (viewport 1024)

    await gebruiker.click(veld)
    const listbox = screen.getByRole('listbox', { name: 'Btw-code' })
    expect(listbox.style.left).toBe('800px') // jsdom meet offsetWidth 0 → nog geen verschuiving

    // De echte gerenderde breedte (max-content, geclampt op maxWidth) wordt pas ná de render
    // gemeten — simuleer een lijst van 320px breed en laat de herpositionering draaien.
    Object.defineProperty(listbox, 'offsetWidth', { value: 320, configurable: true })
    fireEvent.scroll(window)

    // 800 + 320 steekt buiten 1024 → naar links geschoven tot hij past: 1024 − 8 − 320 = 696.
    expect(screen.getByRole('listbox', { name: 'Btw-code' }).style.left).toBe('696px')
  })

  it('rendert een in-flow breedte-anker met de langste optie, zodat max-content echt werkt', async () => {
    // Bugfix 2026-07-11: de gevirtualiseerde optierijen zijn position:absolute en dragen niet
    // bij aan de max-content-breedte — de lijst klapte dicht naar veldbreedte. Het anker (één
    // onzichtbaar, in-flow exemplaar van de langste optie) herstelt dat.
    //
    // LET OP — wat deze test wél en niet bewijst: jsdom doet geen layout en rekent geen
    // max-content, dus de echte gerenderde breedte is hier NIET te asserten. Die is geverifieerd
    // in echt Chrome via het visuele harnas (harness.html?splitsen=1&focusgb=1 — de badge meet
    // veld- vs lijstbreedte: 82px veld → 202px lijst). Hier borgen we het mechanisme: het anker
    // bestaat, is in-flow (geen position:absolute zoals de virtualisatierijen), bevat de langste
    // optie en lekt niet naar screenreaders of de optietelling.
    const gebruiker = userEvent.setup()
    const opties = [
      { id: '1', code: '4699', label: 'Kort' },
      { id: '2', code: '7000', label: 'Inkoop onderaanneming — de langste omschrijving van allemaal' },
      { id: '3', code: '4001', label: 'Middellange omschrijving' },
    ]
    render(<SearchableCombobox label="Grootboek" opties={opties} waarde={null} onWijzig={() => {}} />)

    await gebruiker.click(screen.getByRole('combobox', { name: 'Grootboek' }))

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    const anker = listbox.querySelector<HTMLElement>('[aria-hidden="true"].combobox-optie')
    expect(anker).not.toBeNull()
    expect(anker!.textContent).toContain('Inkoop onderaanneming — de langste omschrijving van allemaal')
    expect(anker!.style.position).toBe('') // in-flow: dít element bepaalt de max-content-breedte
    expect(anker!.style.visibility).toBe('hidden')

    // De echte optierijen blijven gevirtualiseerd (absolute) en het anker telt niet mee als optie.
    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(screen.getByRole('option', { name: /Kort/ }).style.position).toBe('absolute')
  })
})
