#!/usr/bin/env node
// Pixelvergelijking voor de gouden-set-screenshots (blok 0 herstelrun 08-09) — zonder npm-dependency: een minimale
// PNG-decoder (zlib uit Node, alle vijf filtertypes, 8-bit RGB/RGBA/grijs, niet-interlaced — wat headless Chrome
// schrijft) en een tolerante vergelijking. Gebruik:
//   node scripts/keten_compare.mjs <baseline.png> <nieuw.png> [--tolerantie=24] [--max-afwijking=0.5]
// Exit 0 = gelijk binnen de tolerantie (per-kanaal verschil ≤ tolerantie telt als gelijk; hooguit max-afwijking %
// van de pixels mag afwijken), exit 1 = afwijking of andere afmetingen, exit 2 = leesfout. Print altijd de meting.
import { readFileSync } from 'node:fs'
import { inflateSync } from 'node:zlib'

function decodePng(buffer) {
  const sig = [137, 80, 78, 71, 13, 10, 26, 10]
  for (let i = 0; i < 8; i++) if (buffer[i] !== sig[i]) throw new Error('geen PNG-bestand')
  let pos = 8
  let breedte = 0
  let hoogte = 0
  let bitdiepte = 0
  let kleurtype = 0
  let interlace = 0
  const idat = []
  while (pos < buffer.length) {
    const lengte = buffer.readUInt32BE(pos)
    const type = buffer.toString('latin1', pos + 4, pos + 8)
    const data = buffer.subarray(pos + 8, pos + 8 + lengte)
    if (type === 'IHDR') {
      breedte = data.readUInt32BE(0)
      hoogte = data.readUInt32BE(4)
      bitdiepte = data[8]
      kleurtype = data[9]
      interlace = data[12]
    } else if (type === 'IDAT') {
      idat.push(data)
    } else if (type === 'IEND') {
      break
    }
    pos += 12 + lengte
  }
  if (bitdiepte !== 8) throw new Error(`bitdiepte ${bitdiepte} niet ondersteund`)
  if (interlace !== 0) throw new Error('interlaced PNG niet ondersteund')
  const kanalen = { 0: 1, 2: 3, 4: 2, 6: 4 }[kleurtype]
  if (!kanalen) throw new Error(`kleurtype ${kleurtype} niet ondersteund`)
  const ruw = inflateSync(Buffer.concat(idat))
  const bpp = kanalen
  const rijlengte = breedte * bpp
  const uit = Buffer.alloc(rijlengte * hoogte)
  let vorige = Buffer.alloc(rijlengte)
  let bron = 0
  for (let y = 0; y < hoogte; y++) {
    const filter = ruw[bron++]
    const rij = Buffer.from(ruw.subarray(bron, bron + rijlengte))
    bron += rijlengte
    for (let x = 0; x < rijlengte; x++) {
      const links = x >= bpp ? rij[x - bpp] : 0
      const boven = vorige[x]
      const linksboven = x >= bpp ? vorige[x - bpp] : 0
      let waarde = rij[x]
      switch (filter) {
        case 0:
          break
        case 1:
          waarde += links
          break
        case 2:
          waarde += boven
          break
        case 3:
          waarde += (links + boven) >> 1
          break
        case 4: {
          const p = links + boven - linksboven
          const pa = Math.abs(p - links)
          const pb = Math.abs(p - boven)
          const pc = Math.abs(p - linksboven)
          waarde += pa <= pb && pa <= pc ? links : pb <= pc ? boven : linksboven
          break
        }
        default:
          throw new Error(`onbekend filtertype ${filter}`)
      }
      rij[x] = waarde & 0xff
    }
    rij.copy(uit, y * rijlengte)
    vorige = rij
  }
  // Naar RGBA normaliseren zodat grijs/RGB/RGBA onderling vergelijkbaar zijn.
  const rgba = Buffer.alloc(breedte * hoogte * 4)
  for (let i = 0; i < breedte * hoogte; i++) {
    const b = i * bpp
    if (kanalen === 1) rgba.set([uit[b], uit[b], uit[b], 255], i * 4)
    else if (kanalen === 2) rgba.set([uit[b], uit[b], uit[b], uit[b + 1]], i * 4)
    else if (kanalen === 3) rgba.set([uit[b], uit[b + 1], uit[b + 2], 255], i * 4)
    else rgba.set([uit[b], uit[b + 1], uit[b + 2], uit[b + 3]], i * 4)
  }
  return { breedte, hoogte, rgba }
}

function argWaarde(naam, standaard) {
  const arg = process.argv.find((a) => a.startsWith(`--${naam}=`))
  return arg ? Number(arg.split('=')[1]) : standaard
}

const [, , baselinePad, nieuwPad] = process.argv
if (!baselinePad || !nieuwPad) {
  console.error('gebruik: keten_compare.mjs <baseline.png> <nieuw.png> [--tolerantie=24] [--max-afwijking=0.5]')
  process.exit(2)
}
const tolerantie = argWaarde('tolerantie', 24)
const maxAfwijkingPct = argWaarde('max-afwijking', 0.5)

let a
let b
try {
  a = decodePng(readFileSync(baselinePad))
  b = decodePng(readFileSync(nieuwPad))
} catch (fout) {
  console.error(`leesfout: ${fout.message}`)
  process.exit(2)
}
if (a.breedte !== b.breedte || a.hoogte !== b.hoogte) {
  console.log(`AFWIJKING afmetingen: baseline ${a.breedte}×${a.hoogte}, nieuw ${b.breedte}×${b.hoogte}`)
  process.exit(1)
}
let afwijkend = 0
const totaal = a.breedte * a.hoogte
for (let i = 0; i < totaal * 4; i += 4) {
  if (
    Math.abs(a.rgba[i] - b.rgba[i]) > tolerantie ||
    Math.abs(a.rgba[i + 1] - b.rgba[i + 1]) > tolerantie ||
    Math.abs(a.rgba[i + 2] - b.rgba[i + 2]) > tolerantie
  ) {
    afwijkend++
  }
}
const pct = (afwijkend / totaal) * 100
const status = pct <= maxAfwijkingPct ? 'gelijk' : 'AFWIJKING'
console.log(`${status}: ${afwijkend} van ${totaal} pixels (${pct.toFixed(3)} %) verschillen > ${tolerantie} (grens ${maxAfwijkingPct} %)`)
process.exit(pct <= maxAfwijkingPct ? 0 : 1)
