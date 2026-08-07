import { useState } from 'react'
import { verzamelFormulierFouten, type FormulierFout } from './formulierFouten'

/** Samenvattingsblok van alle validatiefouten (Vastly-port f, 2026-08-07). */
export function FormFouten({ fouten }: { fouten: FormulierFout[] }) {
  if (fouten.length === 0) return null
  return (
    <div className="fout" role="alert">
      <p style={{ margin: 0, fontWeight: 600 }}>Versturen kan nog niet — controleer:</p>
      <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
        {fouten.map((f) => (
          <li key={f.veld}>{f.bericht}</li>
        ))}
      </ul>
    </div>
  )
}

/** Hook voor het native-formulier-vangnet: zet `noValidate` op het formulier en laat de
 * submit-handler eerst door `controleer(form)` — die verzamelt bij fouten de volledige
 * NL-samenvatting (i.p.v. de éérste browser-bubble) en focust het eerste invalide veld. */
export function useFormFouten(labels: Record<string, string>) {
  const [fouten, setFouten] = useState<FormulierFout[]>([])

  const controleer = (form: HTMLFormElement): boolean => {
    if (form.checkValidity()) {
      setFouten([])
      return true
    }
    setFouten(verzamelFormulierFouten(form, labels))
    const eerste = Array.from(form.elements).find(
      (el): el is HTMLInputElement => el instanceof HTMLInputElement && !el.checkValidity(),
    )
    eerste?.focus()
    return false
  }

  return { fouten, controleer }
}
