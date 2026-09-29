import { acceptHMRUpdate, defineStore } from 'pinia'
import * as api from '../api/aceStep'
import type { GenerateMusicRequest } from '../api/aceStep'
import * as tracksApi from '../api/tracks'
import { useNotificationsStore } from './notifications'
import type { JobStatus } from '../types'
import { i18n } from '../i18n'

const t = i18n.global.t

const POLL_MS = 3000
const HEALTH_MS = 15000
const STALE_JOB_MS = 5 * 60_000

export interface AceJob {
  id: string
  status: JobStatus
  createdAt: number
  startedAt?: number
  title: string
  lyrics: string
  model?: string
  audioFormat: string
  batchSize: number
  error?: string
  progress: number
  stage?: string
  audioUrls: string[]
  dbIds: number[]
  finalized: boolean
  durationSec?: number | null
  params?: Record<string, any>
}

interface RawResultEntry {
  file?: string
  stage?: string
  progress?: number
  error?: string | null
  metas?: { duration?: number }
}

export const useAceStepStore = defineStore('aceStep', {
  state: () => ({
    jobs: [] as AceJob[],
    historyLoaded: false,
    inventory: null as api.ModelInventory | null,
    health: null as api.HealthResponse | null,
    healthError: false,
    pendingParamsInsert: null as Record<string, any> | null,
    _pollTimer: null as ReturnType<typeof setTimeout> | null,
    _healthTimer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    activeJobs(state): AceJob[] {
      return state.jobs.filter((j) => j.status === 'queued' || j.status === 'running')
    },
  },
  actions: {
    requestInsertParams(params: Record<string, any>) {
      this.pendingParamsInsert = { ...params }
    },
    clearPendingParamsInsert() {
      this.pendingParamsInsert = null
    },
    async loadHistory() {
      try {
        const tracks = await tracksApi.listTracks('ace_step')
        const savedJobs: AceJob[] = tracks.map((t) => ({
          id: `saved_${t.id}`,
          status: 'done',
          createdAt: new Date(t.created_at).getTime() || Date.now(),
          title: t.title,
          lyrics: t.lyrics,
          model: (t.params.model as string) || undefined,
          audioFormat: (t.params.audio_format as string) || 'mp3',
          batchSize: 1,
          progress: 100,
          audioUrls: [t.audio_url],
          dbIds: [t.id],
          finalized: true,
          durationSec: t.duration_ms ? t.duration_ms / 1000 : null,
          params: t.params,
        }))
        // Keep any jobs still in-flight this session (not yet reflected in the saved list).
        const inFlightIds = new Set(this.jobs.filter((j) => !j.finalized).map((j) => j.id))
        this.jobs = [...this.jobs.filter((j) => inFlightIds.has(j.id)), ...savedJobs].sort((a, b) => b.createdAt - a.createdAt)
      } finally {
        this.historyLoaded = true
      }
    },
    async loadInventory() {
      try {
        this.inventory = await api.modelInventory()
      } catch {
        this.inventory = null
      }
    },
    async refreshHealth() {
      try {
        this.health = await api.health()
        this.healthError = false
      } catch {
        this.healthError = true
      }
    },
    startBackgroundTasks() {
      if (!this._healthTimer) {
        const healthTick = async () => {
          await this.refreshHealth()
          this._healthTimer = setTimeout(healthTick, HEALTH_MS)
        }
        void healthTick()
      }
      this._ensurePolling()
    },
    stopBackgroundTasks() {
      if (this._healthTimer) clearTimeout(this._healthTimer)
      this._healthTimer = null
      if (this._pollTimer) clearTimeout(this._pollTimer)
      this._pollTimer = null
    },
    _ensurePolling() {
      if (this._pollTimer || this.activeJobs.length === 0) return
      const tick = async () => {
        await this._pollActive()
        this._pollTimer = this.activeJobs.length > 0 ? setTimeout(tick, POLL_MS) : null
      }
      this._pollTimer = setTimeout(tick, POLL_MS)
    },
    async _pollActive() {
      const ids = this.activeJobs.map((j) => j.id)
      if (ids.length === 0) return
      let results
      try {
        results = await api.queryResult(ids)
      } catch {
        return
      }
      for (const entry of results) {
        const job = this.jobs.find((j) => j.id === entry.task_id)
        if (job) this._applyResult(job, entry)
      }
    },
    _applyResult(job: AceJob, entry: api.QueryResultEntry) {
      if (job.finalized) return
      let parsed: RawResultEntry[]
      try {
        parsed = JSON.parse(entry.result)
      } catch {
        parsed = []
      }
      const first = parsed[0] || {}
      if (entry.status === 1) {
        job.status = 'done'
        job.progress = 100
        job.audioUrls = parsed.filter((p) => p.file).map((p) => `/api/ace${p.file}`)
        job.durationSec = first.metas?.duration ?? null
        job.finalized = true
        useNotificationsStore().trackDone('ace_step', job.title)
        void this._persistJob(job)
      } else if (entry.status === 2) {
        job.status = first.error === 'Cancelled by user' ? 'cancelled' : 'failed'
        job.error = first.error || t('storeErrors.unknownError')
        job.finalized = true
      } else if (!first.stage && Date.now() - job.createdAt > STALE_JOB_MS) {
        // No stage at all after several minutes means the server no longer
        // knows this task_id (its in-memory job store doesn't survive a
        // process restart), not that it's still queued.
        job.status = 'failed'
        job.error = t('storeErrors.taskNotFound')
        job.finalized = true
      } else {
        job.status = first.stage === 'queued' ? 'queued' : 'running'
        if (job.status === 'running' && !job.startedAt) job.startedAt = Date.now()
        job.progress = Math.min(99, Math.max(0, Math.round((first.progress || 0) * 100)))
        job.stage = first.stage
      }
    },
    // Copies each finished audio candidate from ACE-Step's own (ephemeral,
    // temp-dir-backed) storage into our shared DB/files store, then repoints
    // the job at the persisted copy so playback/download survive a reload
    // and a server restart.
    async _persistJob(job: AceJob) {
      const persistedUrls: string[] = []
      const dbIds: number[] = []
      for (const url of job.audioUrls) {
        try {
          const resp = await fetch(url)
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          const blob = await resp.blob()
          const saved = await tracksApi.saveTrack(
            {
              model: 'ace_step',
              title: job.title,
              lyrics: job.lyrics,
              duration_ms: job.durationSec != null ? job.durationSec * 1000 : undefined,
              params: job.params || { model: job.model, audio_format: job.audioFormat },
            },
            blob,
            job.audioFormat,
          )
          persistedUrls.push(saved.audio_url)
          dbIds.push(saved.id)
        } catch {
          // Saving failed (e.g. model already stopped) - keep serving from
          // the original (still-working for now) URL instead of losing it.
          persistedUrls.push(url)
        }
      }
      job.audioUrls = persistedUrls
      job.dbIds = dbIds
    },
    async submit(req: GenerateMusicRequest, sourceAudioFile: File | null, title: string, styleAudioFile: File | null = null): Promise<AceJob> {
      const res = await api.releaseTask(req, sourceAudioFile, styleAudioFile)
      const job: AceJob = {
        id: res.task_id,
        status: 'queued',
        createdAt: Date.now(),
        title,
        lyrics: req.lyrics || '',
        model: req.model,
        audioFormat: req.audio_format || 'mp3',
        batchSize: req.batch_size || 1,
        progress: 0,
        audioUrls: [],
        dbIds: [],
        finalized: false,
        params: { ...req },
      }
      this.jobs.unshift(job)
      this._ensurePolling()
      return job
    },
    async cancel(jobId: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      try {
        await api.cancelTask(jobId)
      } catch {
        // Server may have already finished the job - local update below still applies.
      }
      if (job && !job.finalized) {
        job.status = 'cancelled'
        job.finalized = true
      }
    },
    async cancelAll() {
      try {
        await api.cancelAllTasks()
      } catch {
        // ignore
      }
      for (const job of this.activeJobs) {
        job.status = 'cancelled'
        job.finalized = true
      }
    },
    async removeJob(jobId: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      if (job) {
        for (const id of job.dbIds) {
          try {
            await tracksApi.deleteTrack(id)
          } catch {
            // ignore - still remove locally so the UI doesn't get stuck
          }
        }
      }
      this.jobs = this.jobs.filter((j) => j.id !== jobId)
    },
    async renameJob(jobId: string, title: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      if (!job) return
      await Promise.all(job.dbIds.map((id) => tracksApi.renameTrack(id, title)))
      job.title = title
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useAceStepStore, import.meta.hot))
}
