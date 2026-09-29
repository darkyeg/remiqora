import { apiFetch, apiJson } from './http'
import { getConfig } from './orchestrator'
import type { Yue2ModelSpecConfig } from './orchestrator'

const BASE = '/api/yue2'

export type Yue2ModelSpec = Yue2ModelSpecConfig

// Fallback specifications (overwritten dynamically when orchestrator config loads)
export const YUE2_MODEL: Yue2ModelSpec = {
  id: 'yue2',
  family: 'yue2',
  path: 'E:/AI/YuE2-3B/models/Yue2-3B-GGUF',
  task: 'gen',
  mode: 'offline',
}

export const SHEETSAGE_MODEL: Yue2ModelSpec = {
  id: 'sheetsage2',
  family: 'sheetsage2',
  path: 'E:/AI/YuE2-3B/models/SheetSage2-GGUF/sheetsage2-orig.gguf',
  task: 'midi',
  mode: 'offline',
}

let specsPromise: Promise<Record<string, Yue2ModelSpec>> | null = null

export async function getYue2Specs(): Promise<Record<string, Yue2ModelSpec>> {
  if (!specsPromise) {
    specsPromise = getConfig()
      .then((cfg) => {
        if (cfg?.yue2_specs) {
          if (cfg.yue2_specs.yue2) Object.assign(YUE2_MODEL, cfg.yue2_specs.yue2)
          if (cfg.yue2_specs.sheetsage2) Object.assign(SHEETSAGE_MODEL, cfg.yue2_specs.sheetsage2)
          return cfg.yue2_specs
        }
        return { yue2: YUE2_MODEL, sheetsage2: SHEETSAGE_MODEL }
      })
      .catch(() => {
        specsPromise = null
        return { yue2: YUE2_MODEL, sheetsage2: SHEETSAGE_MODEL }
      })
  }
  return specsPromise
}

export async function getYue2ModelSpec(): Promise<Yue2ModelSpec> {
  const specs = await getYue2Specs()
  return specs.yue2 || YUE2_MODEL
}

export async function getSheetSageModelSpec(): Promise<Yue2ModelSpec> {
  const specs = await getYue2Specs()
  return specs.sheetsage2 || SHEETSAGE_MODEL
}

export type CotMode = 'off' | 'melody' | 'full'

export interface GenerateOptions {
  [key: string]: unknown
  style: string
  cot: CotMode
  cfg_scale?: number
  num_inference_steps?: number
  semantic_temperature?: number
  semantic_top_p?: number
  semantic_top_k?: number
  semantic_repetition_penalty?: number
  semantic_penalty_window?: number
  semantic_min_tokens?: number
  semantic_max_tokens?: number
  abc?: string
  abc_temperature?: number
  abc_top_p?: number
  abc_top_k?: number
  abc_repetition_penalty?: number
  abc_penalty_window?: number
  abc_min_tokens?: number
  abc_max_tokens?: number
}

export interface TaskRunResult {
  audio?: string
  text?: string
  artifacts?: Array<{ id?: string; meta?: { format?: string; extension?: string }; payload?: string }>
  timing?: { wall_ms?: number; audio_duration_ms?: number }
}

export interface HealthResponse {
  status?: string
  backend?: string
}

function modelSessionOptions(precision: 'q8_0' | 'q4_0'): Record<string, string> {
  // These arenas hold graph/tensor metadata, not model weights or audio.
  // The pinned engine's defaults reserve tens of GiB of Windows commit.
  // Keep room above its graph node caps without changing inference math.
  return {
    'yue2.model_gguf': `yue2-3b-${precision}.gguf`,
    'yue2.model_weight_context_mb': '64',
    'yue2.vae_weight_context_mb': '64',
    'yue2.ar_prefill_graph_arena_mb': '256',
    'yue2.ar_decode_graph_arena_mb': '128',
    'yue2.nar_graph_arena_mb': '256',
    'yue2.vae_graph_arena_mb': '128',
  }
}

export interface Yue2Progress {
  seed: number
  started_ms: number
  phase_started_ms: number
  updated_ms: number
  phase: 'preparing' | 'abc' | 'semantic' | 'acoustic' | 'decoding' | 'done'
  current: number
  total: number
}

export function getProgress(): Promise<Yue2Progress | null> {
  return apiFetch<Yue2Progress | null>(`${BASE}/progress`, { cache: 'no-store' })
}

interface ModelState { id: string; loaded: boolean; session_options?: Record<string, string> }

async function getModels(signal?: AbortSignal): Promise<ModelState[]> {
  const json = await apiFetch<{ data?: ModelState[] }>(`${BASE}/v1/models?include_session_options=true`, { signal })
  return json.data || []
}

async function loadModelSpec(spec: Yue2ModelSpec, sessionOptions?: Record<string, string>, signal?: AbortSignal): Promise<void> {
  await apiFetch(`${BASE}/v1/models/load`, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: spec.id,
      path: spec.path,
      family: spec.family,
      task: spec.task,
      mode: spec.mode,
      ...(spec.model_spec_override ? { model_spec_override: spec.model_spec_override } : {}),
      load_options: {},
      session_options: sessionOptions || {},
    }),
  })
}

export async function unloadModelId(id: string): Promise<void> {
  await apiJson(`${BASE}/v1/models/unload`, { id })
}

/**
 * Only reload a resident model when the requested session options change.
 * Read the server's options so a restart or a precision change in another
 * tab cannot leave the UI claiming q8 while the server is using q4.
 */
export async function ensureLoaded(
  specOrId?: Yue2ModelSpec | 'yue2' | 'sheetsage2' | 'muscriptor',
  sessionOptions?: Record<string, string>,
  signal?: AbortSignal,
): Promise<void> {
  let spec: Yue2ModelSpec
  if (!specOrId || specOrId === 'yue2') {
    spec = await getYue2ModelSpec()
  } else if (specOrId === 'sheetsage2') {
    spec = await getSheetSageModelSpec()
  } else if (typeof specOrId === 'string') {
    const specs = await getYue2Specs()
    spec = specs[specOrId] || YUE2_MODEL
  } else {
    const specs = await getYue2Specs()
    if (specs && specs[specOrId.id]) {
      spec = { ...specOrId, path: specs[specOrId.id].path }
    } else {
      spec = specOrId
    }
  }

  if (sessionOptions !== undefined) {
    const list = await getModels(signal)
    const current = list.find((model) => model.id === spec.id && model.loaded)?.session_options
    if (current && Object.keys(current).length === Object.keys(sessionOptions).length
      && Object.entries(sessionOptions).every(([key, value]) => current[key] === value)) return
    await loadModelSpec(spec, sessionOptions, signal)
    return
  }
  const list = await getModels(signal)
  if (list.some((m) => m.id === spec.id && m.loaded)) return
  await loadModelSpec(spec, undefined, signal)
}

export function precisionSessionOptions(precision: 'q8_0' | 'q4_0'): Record<string, string> {
  return modelSessionOptions(precision)
}

export async function uploadFile(file: File): Promise<string> {
  const match = /\.([A-Za-z0-9]{1,8})$/.exec(file.name)
  const filename = `upload.${(match && match[1] && match[1].toLowerCase()) || 'bin'}`
  const json = await apiFetch<{ path: string }>(`${BASE}/v1/ui/upload`, {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-AudioCPP-Filename': filename,
    },
    body: file,
  })
  // The native server's JSON parser mishandles backslash escapes when a
  // Windows path it returned is echoed back in a later request body -
  // forward slashes round-trip fine, so normalize once here.
  return json.path.replace(/\\/g, '/')
}

export async function runTask(model: string, request: unknown, signal?: AbortSignal): Promise<TaskRunResult> {
  return apiFetch<TaskRunResult>(`${BASE}/v1/tasks/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, request }),
    signal,
  })
}

export async function resetEngine(): Promise<void> {
  await apiJson('/api/orchestrator/yue2/reset', {})
}

export async function generateTrack(lyrics: string, seed: number, options: GenerateOptions, precision: 'q8_0' | 'q4_0', signal?: AbortSignal, onPhase?: (phase: 'loading' | 'generating' | 'stopping') => void): Promise<TaskRunResult> {
  let engineRequested = false
  try {
    signal?.throwIfAborted()
    const spec = await getYue2ModelSpec()
    signal?.throwIfAborted()
    onPhase?.('loading')
    engineRequested = true
    await ensureLoaded(spec, precisionSessionOptions(precision), signal)
    signal?.throwIfAborted()
    onPhase?.('generating')
    return await runTask(spec.id, { lyrics, seed, options }, signal)
  } catch (err) {
    if (signal?.aborted) {
      if (engineRequested) {
        onPhase?.('stopping')
        // Keep this promise pending until GPU work has stopped, so the next
        // queued track cannot race the native server's previous inference.
        await resetEngine()
      }
      throw signal.reason
    }
    throw err
  }
}

export async function extractAbcFromAudio(audioPath: string): Promise<TaskRunResult> {
  const spec = await getSheetSageModelSpec()
  await ensureLoaded(spec)
  return runTask(spec.id, { audio: audioPath, options: {} })
}

export function abcFromResult(result: TaskRunResult): string {
  if (typeof result.text === 'string' && result.text.trim()) return result.text
  for (const artifact of result.artifacts || []) {
    const format = String(artifact?.meta?.format || artifact?.meta?.extension || artifact?.id || '')
    if (/abc|score/i.test(format) && typeof artifact.payload === 'string') {
      try {
        return atob(artifact.payload)
      } catch {
        return artifact.payload
      }
    }
  }
  return ''
}

export function base64AudioBlob(data: string): Blob {
  // Decode in slices so a long song never creates another full-sized binary string.
  const chunks: BlobPart[] = []
  const sliceChars = 4 * 1024 * 1024 // divisible by four for base64 boundaries
  for (let offset = 0; offset < data.length; offset += sliceChars) {
    const binary = atob(data.slice(offset, offset + sliceChars))
    const buffer = new ArrayBuffer(binary.length)
    const bytes = new Uint8Array(buffer)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    chunks.push(buffer)
  }
  return new Blob(chunks, { type: 'audio/wav' })
}

export async function health(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>(`${BASE}/health`)
}
