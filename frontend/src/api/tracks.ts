import { apiFetch, apiJson } from './http'
import type { TrackOrigin } from '../types'

export interface SavedTrack {
  id: number
  model: TrackOrigin
  created_at: string
  title: string
  lyrics: string
  seed: number | null
  duration_ms: number | null
  wall_ms: number | null
  params: Record<string, unknown>
  filename: string
  audio_url: string
  abc_url: string | null
  stems: Record<string, string> | null
  midi: Record<string, string> | null
}

export interface SaveTrackMeta {
  model: TrackOrigin
  title: string
  lyrics: string
  seed?: number
  duration_ms?: number
  wall_ms?: number
  params?: Record<string, unknown>
}

export async function saveTrack(meta: SaveTrackMeta, audio: Blob, audioExt: string, abcText?: string | null): Promise<SavedTrack> {
  const form = new FormData()
  form.append('model', meta.model)
  form.append('title', meta.title)
  form.append('lyrics', meta.lyrics)
  if (meta.seed != null) form.append('seed', String(meta.seed))
  if (meta.duration_ms != null) form.append('duration_ms', String(meta.duration_ms))
  if (meta.wall_ms != null) form.append('wall_ms', String(meta.wall_ms))
  form.append('params', JSON.stringify(meta.params || {}))
  if (abcText) form.append('abc', abcText)
  form.append('audio', audio, `track.${audioExt}`)
  return apiFetch<SavedTrack>('/api/tracks', { method: 'POST', body: form })
}

export async function uploadTrack(file: File, title?: string): Promise<SavedTrack> {
  const form = new FormData()
  form.append('audio', file)
  if (title) form.append('title', title)
  return apiFetch<SavedTrack>('/api/tracks/upload', { method: 'POST', body: form })
}

export async function listTracks(model?: TrackOrigin): Promise<SavedTrack[]> {
  const qs = model ? `?model=${encodeURIComponent(model)}` : ''
  const json = await apiFetch<{ data: SavedTrack[] }>(`/api/tracks${qs}`)
  return json.data
}

export function renameTrack(id: number, title: string): Promise<SavedTrack> {
  return apiJson<SavedTrack>(`/api/tracks/${id}`, { title }, 'PUT')
}

export async function deleteTrack(id: number): Promise<void> {
  await apiFetch(`/api/tracks/${id}`, { method: 'DELETE' })
}

export function trackAudioUrl(id: number): string {
  return `/api/tracks/${id}/audio`
}

export function trackMp3Url(id: number): string {
  return `/api/tracks/${id}/download.mp3`
}

export async function trackAbc(id: number): Promise<string> {
  const resp = await fetch(`/api/tracks/${id}/abc`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.text()
}
