/**
 * Generates Capacitor icon + splash assets from the SVG source.
 * Run once:  node scripts/generate-assets.mjs
 *
 * Outputs:
 *   assets/icon-only.png          1024×1024  (icon, transparent-friendly)
 *   assets/icon-background.png    1024×1024  (adaptive icon background)
 *   assets/icon-foreground.png    1024×1024  (adaptive icon foreground, padded 50%)
 *   assets/splash.png             2732×2732  (light splash)
 *   assets/splash-dark.png        2732×2732  (dark splash)
 *
 * Then run:  npx capacitor-assets generate
 */

import sharp from 'sharp'
import { readFileSync, existsSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dir = dirname(fileURLToPath(import.meta.url))
const root  = join(__dir, '..')

function out(name) {
  return join(root, 'assets', name)
}

if (!existsSync(join(root, 'assets'))) mkdirSync(join(root, 'assets'))

const svgBuf = readFileSync(join(root, 'public', 'icons', 'icon.svg'))

// ── 1. icon-only.png — 1024×1024, navy bg ─────────────────────────────────
await sharp(svgBuf)
  .resize(1024, 1024, { fit: 'contain', background: { r: 15, g: 23, b: 42, alpha: 1 } })
  .png()
  .toFile(out('icon-only.png'))
console.log('✓ icon-only.png')

// ── 2. icon-background.png — solid navy ───────────────────────────────────
await sharp({
  create: { width: 1024, height: 1024, channels: 4,
             background: { r: 15, g: 23, b: 42, alpha: 1 } },
})
  .png()
  .toFile(out('icon-background.png'))
console.log('✓ icon-background.png')

// ── 3. icon-foreground.png — icon centred at 75% to respect safe zone ─────
await sharp(svgBuf)
  .resize(768, 768, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
  .extend({ top: 128, bottom: 128, left: 128, right: 128,
             background: { r: 0, g: 0, b: 0, alpha: 0 } })
  .png()
  .toFile(out('icon-foreground.png'))
console.log('✓ icon-foreground.png')

// ── Helper: build a splash at WxH with centred icon ───────────────────────
async function splash(filename, W, H, bg) {
  const iconSize  = Math.round(Math.min(W, H) * 0.25)
  const iconLayer = await sharp(svgBuf)
    .resize(iconSize, iconSize, { fit: 'contain', background: { ...bg, alpha: 0 } })
    .png()
    .toBuffer()

  await sharp({ create: { width: W, height: H, channels: 4, background: { ...bg, alpha: 1 } } })
    .composite([{
      input: iconLayer,
      gravity: 'centre',
    }])
    .png()
    .toFile(out(filename))
  console.log(`✓ ${filename}`)
}

// ── 4. splash.png — light (white bg) ──────────────────────────────────────
await splash('splash.png', 2732, 2732, { r: 248, g: 250, b: 252 })

// ── 5. splash-dark.png — dark bg ──────────────────────────────────────────
await splash('splash-dark.png', 2732, 2732, { r: 15, g: 23, b: 42 })

console.log('\nAll assets generated in assets/')
console.log('Next: npx capacitor-assets generate')
