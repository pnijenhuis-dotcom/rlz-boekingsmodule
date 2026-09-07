import * as Popover from '@radix-ui/react-popover'
import { nl } from 'date-fns/locale'
import { useEffect, useId, useRef, useState } from 'react'
import { DayPicker } from 'react-day-picker'
import 'react-day-picker/style.css'
import {
  binnenGrenzen,
  dateNaarIso,
  isoNaarDate,
  isoNaarWeergave,
  maskeerDatumInvoer,
  parseSoepeleDatum,
  weergaveNaarIso,
} from './datum'

/** Scheidingsteken (-, / of .) getypt/geplakt door de gebruiker: dat is een geldige soepele vorm
 * (zie datum.ts::parseSoepeleDatum, bv. 7-9-2026, 7/9/2026, 07.09.2026). */
const HEEFT_SCHEIDINGSTEKEN = /[-/.]/

function grenzenMelding(min?: string, max?: string): string {
  if (min && max) return `Datum moet tussen ${isoNaarWeergave(min)} en ${isoNaarWeergave(max)} liggen`
  if (min) return `Datum moet op of na ${isoNaarWeergave(min)} liggen`
  if (max) return `Datum moet op of vóór ${isoNaarWeergave(max)} liggen`
  return 'Ongeldige datum'
}

interface DatePickerProps {
  id?: string
  /** ISO jjjj-mm-dd of null — exact wat de API in/uit gaat (payload blijft ISO). */
  value: string | null
  onChange: (value: string | null) => void
  disabled?: boolean
  min?: string
  max?: string
  placeholder?: string
  'aria-label'?: string
}

/** Gethematiseerde date-picker (Vastly-port e, 2026-08-07): gemaskeerd dd-mm-jjjj-typen +
 * kalender-popover (react-day-picker, NL, week start maandag). Thematisering via de bestaande
 * design-tokens in src/styles (zie .rdp-root in components.css) — volgt licht/donker vanzelf. */
export function DatePicker({
  id,
  value,
  onChange,
  disabled,
  min,
  max,
  placeholder = 'dd-mm-jjjj',
  'aria-label': ariaLabel,
}: DatePickerProps) {
  const [tekst, setTekst] = useState(isoNaarWeergave(value))
  const [open, setOpen] = useState(false)
  // Bugfix 07-09 ("Tab/blur wist ingevulde datum"): ongeldige of buiten-grenzen-invoer wordt
  // NOOIT meer stil teruggezet — de tekst blijft staan, deze melding legt uit waarom.
  const [foutmelding, setFoutmelding] = useState<string | null>(null)
  const autoId = useId()
  const foutId = `${id ?? autoId}-fout`

  // Zodra de gebruiker zelf een scheidingsteken typt/plakt, schakelt het veld PER EDIT-SESSIE om
  // naar "soepele modus" (geen digit-only automask meer, alleen het tekenbereik bewaken — parsen
  // gebeurt pas bij commitTekst). Een ref (niet state) omdat dit al bij de EERSTE druk op de
  // scheidingsteken-toets moet gelden, vóórdat de resulterende change-event verwerkt wordt (state
  // is dan nog niet ge-hercomponeerd) — keydown/paste lopen altijd vóór het change-event van
  // dezelfde toetsaanslag. Reset bij een lege invoer en bij een verse `value` van de aanroeper. */
  const soepelModus = useRef(false)

  useEffect(() => {
    setTekst(isoNaarWeergave(value))
    setFoutmelding(null)
    soepelModus.current = false
  }, [value])

  function handmatigTypen(ruw: string) {
    setFoutmelding(null)
    if (soepelModus.current) {
      // Eigen scheidingsteken (7-9-2026, 7/9/2026, 07.09.2026, …): niet door de digit-only
      // automask husselen — committen gebeurt bij blur/Enter (`commitTekst`).
      const schoon = ruw.replace(/[^\d\-/.]/g, '').slice(0, 10)
      setTekst(schoon)
      if (schoon === '') {
        soepelModus.current = false
        onChange(null)
      }
      return
    }
    const gemaskeerd = maskeerDatumInvoer(ruw)
    setTekst(gemaskeerd)
    if (gemaskeerd === '') {
      onChange(null)
      return
    }
    if (gemaskeerd.length === 10) {
      const iso = weergaveNaarIso(gemaskeerd)
      if (iso && binnenGrenzen(iso, min, max)) onChange(iso)
    }
  }

  /** Commit bij blur én Enter (zelfde gedrag): soepel parsen, geldig + binnen de grenzen →
   * onChange + genormaliseerde weergave; leeg → onChange(null); anders blijft de invoer
   * onaangeroerd staan en verschijnt de foutmelding — niets verdwijnt stil. */
  function commitTekst() {
    const ruw = tekst.trim()
    if (ruw === '') {
      setFoutmelding(null)
      if (value !== null) onChange(null)
      return
    }
    const iso = parseSoepeleDatum(ruw)
    if (iso && binnenGrenzen(iso, min, max)) {
      setFoutmelding(null)
      soepelModus.current = false
      setTekst(isoNaarWeergave(iso))
      if (iso !== value) onChange(iso)
      return
    }
    setFoutmelding(iso ? grenzenMelding(min, max) : 'Ongeldige datum')
  }

  const kalenderGrenzen = [
    ...(min ? [{ before: isoNaarDate(min) }] : []),
    ...(max ? [{ after: isoNaarDate(max) }] : []),
  ]

  return (
    <div className="datepicker-wrap">
      <div className="datepicker" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <input
          id={id}
          type="text"
          inputMode="numeric"
          aria-label={ariaLabel}
          aria-invalid={foutmelding ? true : undefined}
          aria-describedby={foutmelding ? foutId : undefined}
          value={tekst}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => handmatigTypen(e.target.value)}
          onBlur={commitTekst}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commitTekst()
              return
            }
            if (HEEFT_SCHEIDINGSTEKEN.test(e.key)) soepelModus.current = true
          }}
          onPaste={(e) => {
            const geplakt = e.clipboardData.getData('text')
            if (HEEFT_SCHEIDINGSTEKEN.test(geplakt)) soepelModus.current = true
          }}
        />
        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger asChild>
            <button
              type="button"
              className="datepicker-knop"
              aria-label="Kalender openen"
              disabled={disabled}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content className="datepicker-popover" align="start" sideOffset={6}>
              <DayPicker
                mode="single"
                locale={nl}
                weekStartsOn={1}
                selected={value ? isoNaarDate(value) : undefined}
                defaultMonth={value ? isoNaarDate(value) : undefined}
                disabled={kalenderGrenzen.length > 0 ? kalenderGrenzen : undefined}
                onSelect={(d) => {
                  if (d) {
                    setFoutmelding(null)
                    onChange(dateNaarIso(d))
                    setOpen(false)
                  }
                }}
              />
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      {foutmelding && (
        <div id={foutId} className="datepicker-fout" role="alert">
          {foutmelding}
        </div>
      )}
    </div>
  )
}
