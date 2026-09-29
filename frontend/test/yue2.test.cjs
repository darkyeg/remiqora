const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

function loadApi() {
  const cache = new Map()
  function load(file) {
    if (cache.has(file)) return cache.get(file)
    const exports = {}
    cache.set(file, exports)
    const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    })
    new Function('require', 'exports', outputText)((name) => load(path.resolve(path.dirname(file), `${name}.ts`)), exports)
    return exports
  }
  return load(path.resolve(__dirname, '../src/api/yue2.ts'))
}

const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function server(t, handlers = {}) {
  const original = global.fetch
  const loads = []
  let loaded = false
  let sessionOptions = {}
  global.fetch = async (url, init = {}) => {
    if (url === '/api/orchestrator/config') return json({ yue2_specs: { yue2: { id: 'yue2', family: 'yue2', path: '/models', task: 'gen', mode: 'offline' } } })
    if (url.includes('/models?')) return json({ data: [{ id: 'yue2', loaded, session_options: sessionOptions }] })
    if (url.endsWith('/models/load')) {
      loads.push(JSON.parse(init.body))
      sessionOptions = loads.at(-1).session_options
      loaded = true
      return handlers.load ? handlers.load(init) : json({})
    }
    if (url.endsWith('/tasks/run')) return handlers.run ? handlers.run(init) : json({ audio: 'AAAA' })
    if (url === '/api/orchestrator/yue2/reset') {
      loaded = false
      return handlers.reset ? handlers.reset() : json({})
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  t.after(() => { global.fetch = original })
  return loads
}

test('cancellation waits for GPU reset before the next generation can start', async (t) => {
  const running = deferred(), resetting = deferred(), resetFinished = deferred()
  let requests = 0
  const loads = server(t, {
    run: ({ signal }) => {
      if (++requests > 1) return json({ audio: 'AAAA' })
      running.resolve()
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }))
    },
    reset: () => { resetting.resolve(); return resetFinished.promise },
  })
  const api = loadApi()
  const aborter = new AbortController()
  const phases = []
  let settled = false
  const pending = api.generateTrack('lyrics', 1, { style: 'pop', cot: 'full' }, 'q8_0', aborter.signal, (phase) => phases.push(phase))
  const rejected = assert.rejects(pending, { name: 'AbortError' }).then(() => { settled = true })
  await running.promise
  aborter.abort()
  await resetting.promise
  assert.equal(settled, false)
  assert.deepEqual(phases, ['loading', 'generating', 'stopping'])
  resetFinished.resolve(json({}))
  await rejected
  await api.generateTrack('lyrics', 2, { style: 'pop', cot: 'full' }, 'q8_0')
  assert.equal(loads.length, 2)
})

test('cancellation during model loading also resets the native process', async (t) => {
  const loading = deferred()
  let resets = 0
  server(t, {
    load: ({ signal }) => {
      loading.resolve()
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }))
    },
    reset: () => { resets++; return json({}) },
  })
  const api = loadApi(), aborter = new AbortController()
  const rejected = assert.rejects(api.generateTrack('lyrics', 1, { style: 'pop', cot: 'full' }, 'q8_0', aborter.signal), { name: 'AbortError' })
  await loading.promise
  aborter.abort()
  await rejected
  assert.equal(resets, 1)
})

test('a reset failure is reported instead of pretending the GPU work was cancelled', async (t) => {
  const running = deferred()
  server(t, {
    run: ({ signal }) => {
      running.resolve()
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }))
    },
    reset: () => json({ detail: 'process did not stop' }, 502),
  })
  const api = loadApi(), aborter = new AbortController()
  const rejected = assert.rejects(api.generateTrack('lyrics', 1, { style: 'pop', cot: 'full' }, 'q8_0', aborter.signal), /process did not stop/)
  await running.promise
  aborter.abort()
  await rejected
})

test('repeated q8 requests reuse the loaded model without changing precision', async (t) => {
  const loads = server(t)
  const api = loadApi()
  await api.generateTrack('lyrics', 1, { style: 'pop', cot: 'full' }, 'q8_0')
  await api.generateTrack('lyrics', 2, { style: 'pop', cot: 'full' }, 'q8_0')
  assert.equal(loads.length, 1)
  assert.equal(loads[0].session_options['yue2.model_gguf'], 'yue2-3b-q8_0.gguf')
  assert.equal(loads[0].session_options['yue2.nar_graph_arena_mb'], '256')
})

test('chunked audio decoding preserves every byte across base64 slice boundaries', async () => {
  const api = loadApi()
  const bytes = Buffer.alloc(3 * 1024 * 1024 + 17)
  for (let i = 0; i < bytes.length; i++) bytes[i] = i % 251
  const actual = Buffer.from(await api.base64AudioBlob(bytes.toString('base64')).arrayBuffer())
  assert.deepEqual(actual, bytes)
})
