import { describe, expect, it } from 'vitest'
import { SNELTOETSEN_CONTROLESCHERM, SNELTOETSEN_LIJST, bepaalSneltoets, toetsInInvoer } from './sneltoetsen'

function toets(key: string, extra: Partial<KeyboardEventInit> = {}): KeyboardEvent {
  return new KeyboardEvent('keydown', { key, ...extra })
}

describe('sneltoetsen (punt 5) — bepaalSneltoets', () => {
  it('B/A (ook hoofdletter), pijltjes, Esc, ? en / mappen op hun actie', () => {
    expect(bepaalSneltoets(toets('b'), SNELTOETSEN_CONTROLESCHERM)).toBe('boeken')
    expect(bepaalSneltoets(toets('B'), SNELTOETSEN_CONTROLESCHERM)).toBe('boeken')
    expect(bepaalSneltoets(toets('a'), SNELTOETSEN_CONTROLESCHERM)).toBe('afwijzen')
    expect(bepaalSneltoets(toets('ArrowLeft'), SNELTOETSEN_CONTROLESCHERM)).toBe('vorige')
    expect(bepaalSneltoets(toets('ArrowRight'), SNELTOETSEN_CONTROLESCHERM)).toBe('volgende')
    expect(bepaalSneltoets(toets('Escape'), SNELTOETSEN_CONTROLESCHERM)).toBe('terug')
    expect(bepaalSneltoets(toets('?', { shiftKey: true }), SNELTOETSEN_CONTROLESCHERM)).toBe('overzicht')
    expect(bepaalSneltoets(toets('/'), SNELTOETSEN_LIJST)).toBe('zoeken')
    expect(bepaalSneltoets(toets('x'), SNELTOETSEN_CONTROLESCHERM)).toBeNull()
  })

  it('modifier-toetsen en herhaling laten de browser zijn werk doen', () => {
    expect(bepaalSneltoets(toets('b', { metaKey: true }), SNELTOETSEN_CONTROLESCHERM)).toBeNull()
    expect(bepaalSneltoets(toets('a', { ctrlKey: true }), SNELTOETSEN_CONTROLESCHERM)).toBeNull()
    expect(bepaalSneltoets(toets('ArrowLeft', { altKey: true }), SNELTOETSEN_CONTROLESCHERM)).toBeNull()
    expect(bepaalSneltoets(toets('b', { repeat: true }), SNELTOETSEN_CONTROLESCHERM)).toBeNull()
  })
})

describe('sneltoetsen — toetsInInvoer (alleen actief zonder focus in een invoerveld)', () => {
  it('input/textarea/select/contenteditable/combobox = invoer; een gewone knop niet', () => {
    const doc = document.implementation.createHTMLDocument('t')
    const input = doc.createElement('input')
    const textarea = doc.createElement('textarea')
    const select = doc.createElement('select')
    const combobox = doc.createElement('div')
    combobox.setAttribute('role', 'combobox')
    const binnenCombobox = doc.createElement('span')
    combobox.appendChild(binnenCombobox)
    const knop = doc.createElement('button')
    for (const el of [input, textarea, select, combobox, knop]) doc.body.appendChild(el)
    expect(toetsInInvoer(input, doc)).toBe(true)
    expect(toetsInInvoer(textarea, doc)).toBe(true)
    expect(toetsInInvoer(select, doc)).toBe(true)
    expect(toetsInInvoer(binnenCombobox, doc)).toBe(true)
    expect(toetsInInvoer(knop, doc)).toBe(false)
    expect(toetsInInvoer(doc.body, doc)).toBe(false)
  })

  it('een open dialoog blokkeert álle sneltoetsen (de dialoog heeft zijn eigen Esc/Enter)', () => {
    const doc = document.implementation.createHTMLDocument('t')
    const knop = doc.createElement('button')
    doc.body.appendChild(knop)
    expect(toetsInInvoer(knop, doc)).toBe(false)
    const dialoog = doc.createElement('div')
    dialoog.setAttribute('role', 'dialog')
    doc.body.appendChild(dialoog)
    expect(toetsInInvoer(knop, doc)).toBe(true)
  })
})
