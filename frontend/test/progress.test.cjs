const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

const file = path.resolve(__dirname, '../src/utils/progressTime.ts')
const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const progress = {}
new Function('exports', source)(progress)

test('YuE2 forecast uses the effective eight-step default and does not scale full runtime by acoustic steps', () => {
  const song = { lyrics: 'long song lyrics', style: 'J-pop', cot: 'full', precision: 'q8_0' }
  const history = [{ ...song, wallSec: 1030.5 }]
  assert.equal(progress.estimateYue2TotalSeconds({ ...song, steps: 8 }, history), 1030.5)
  assert.equal(progress.estimateYue2TotalSeconds({ ...song, steps: 32 }, history), null)
})

test('unrelated COT and precision do not produce a misleading estimate', () => {
  const song = { lyrics: 'long song lyrics', style: 'J-pop', cot: 'full', precision: 'q8_0' }
  assert.equal(progress.estimateYue2TotalSeconds(song, [
    { ...song, cot: 'off', wallSec: 100 },
    { ...song, precision: 'q4_0', wallSec: 200 },
  ]), null)
})
