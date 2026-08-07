import * as Popover from '@radix-ui/react-popover'
import { nl } from 'date-fns/locale'
import { useEffect, useState } from 'react'
import { DayPicker } from 'react-day-picker'
import 'react-day-picker/style.css'
import {
  binnenGrenzen,
  dateNaarIso,
  isoNaarDate,
  isoNaarWeergave,
  maskeerDatumInvoer,
  weergaveNaarIso,
} from './datum'

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

  useEffect(() => {
    setTekst(isoNaarWeergave(value))
  }, [value])

  function handmatigTypen(ruw: string) {
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

  const kalenderGrenzen = [
    ...(min ? [{ before: isoNaarDate(min) }] : []),
    ...(max ? [{ after: isoNaarDate(max) }] : []),
  ]

  return (
    <div className="datepicker" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        aria-label={ariaLabel}
        value={tekst}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => handmatigTypen(e.target.value)}
        onBlur={() => setTekst(isoNaarWeergave(value))}
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
                  onChange(dateNaarIso(d))
                  setOpen(false)
                }
              }}
            />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}
