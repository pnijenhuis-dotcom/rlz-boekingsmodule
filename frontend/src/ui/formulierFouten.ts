/** Formulier-vangnet (Vastly-port f, 2026-08-07): verzamel álle validatiefouten van een native
 * formulier als Nederlandse meldingen — de browser toont anders per veld één (mogelijk Engelse)
 * bubble en stopt bij de eerste fout; een fout op een niet-zichtbaar veld lijkt dan op "de knop
 * doet niets". Gebruik met `noValidate` op het formulier + checkValidity() in de submit-handler
 * (zie FormFouten.tsx). */

export interface FormulierFout {
  veld: string
  bericht: string
}

function nlBericht(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): string {
  const v = element.validity
  if (v.valueMissing) return 'is verplicht'
  if (v.typeMismatch && element instanceof HTMLInputElement && element.type === 'email') {
    return 'is geen geldig e-mailadres'
  }
  if (v.typeMismatch) return 'heeft een ongeldige waarde'
  if (v.patternMismatch) return 'heeft niet het verwachte formaat'
  if (v.tooShort && 'minLength' in element) return `is te kort (minimaal ${element.minLength} tekens)`
  if (v.tooLong && 'maxLength' in element) return `is te lang (maximaal ${element.maxLength} tekens)`
  if (v.rangeUnderflow || v.rangeOverflow) return 'valt buiten de toegestane grenzen'
  if (v.stepMismatch) return 'heeft een ongeldige stapgrootte'
  if (v.badInput) return 'heeft een onleesbare waarde'
  if (v.customError) return element.validationMessage || 'is ongeldig'
  return 'is ongeldig'
}

/** Alle invalide velden van het formulier, met NL-label uit `labels` (sleutel = element-id of
 * -name; onbekend veld valt terug op die sleutel — beter een rauwe naam dan een gemiste fout). */
export function verzamelFormulierFouten(
  form: HTMLFormElement,
  labels: Record<string, string>,
): FormulierFout[] {
  const fouten: FormulierFout[] = []
  for (const element of Array.from(form.elements)) {
    if (
      !(
        element instanceof HTMLInputElement ||
        element instanceof HTMLTextAreaElement ||
        element instanceof HTMLSelectElement
      )
    ) {
      continue
    }
    if (element.disabled || element.type === 'button' || element.type === 'submit') continue
    if (element.checkValidity()) continue
    const sleutel = element.id || element.name
    fouten.push({ veld: sleutel, bericht: `${labels[sleutel] ?? sleutel} ${nlBericht(element)}` })
  }
  return fouten
}
