<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useYue2Store } from '../../stores/yue2'
import type { Yue2Job } from '../../stores/yue2'
import { getProgress } from '../../api/yue2'
import type { Yue2Progress } from '../../api/yue2'
import * as tracksApi from '../../api/tracks'
import { formatDuration } from '../../composables/formatDuration'
import { estimateYue2TotalSeconds, formatClock } from '../../utils/progressTime'
import StatusBadge from '../../components/shared/StatusBadge.vue'
import WaveformPlayer from '../../components/shared/WaveformPlayer.vue'
import StemsPanel from '../../components/shared/StemsPanel.vue'
import MidiPanel from '../../components/shared/MidiPanel.vue'
import EditableTitle from '../../components/shared/EditableTitle.vue'

const props = defineProps<{ job: Yue2Job }>()
const store = useYue2Store()
const { t, locale } = useI18n()
const showDetails = ref(false)
const showAbc = ref(false)
const abcText = ref<string | null>(null)
const loadingAbc = ref(false)
const copied = ref(false)
const recoveryError = ref('')
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null
let progressTimer: ReturnType<typeof setInterval> | null = null
const nativeProgress = ref<Yue2Progress | null>(null)

async function pollProgress() {
  const job = props.job
  if (job.status !== 'running' || job.phase !== 'generating' || !job.runStartedAt) return
  try {
    const snapshot = await getProgress()
    if (snapshot && snapshot.seed === job.seed && snapshot.started_ms >= job.runStartedAt - 2000
      && snapshot.started_ms <= Date.now() && Number.isFinite(snapshot.current) && Number.isFinite(snapshot.total)) {
      nativeProgress.value = snapshot
    }
  } catch {
    // Older engines have no progress side channel; keep the elapsed clock visible.
  }
}

watch(() => [props.job.status, props.job.phase, props.job.runStartedAt], () => {
  nativeProgress.value = null
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = null
  if (props.job.status === 'running' && props.job.phase === 'generating') {
    void pollProgress()
    progressTimer = setInterval(() => { void pollProgress() }, 1000)
  }
}, { immediate: true })
watch(() => props.job.status, (status) => {
  if (status === 'queued' || status === 'running') {
    if (!clock) clock = setInterval(() => { now.value = Date.now() }, 1000)
  } else if (clock) {
    clearInterval(clock)
    clock = null
  }
}, { immediate: true })
onBeforeUnmount(() => { if (clock) clearInterval(clock); if (progressTimer) clearInterval(progressTimer) })

const elapsed = computed(() => Math.max(0, Math.floor((now.value - (props.job.startedAt || props.job.createdAt)) / 1000)))
const typical = computed(() => estimateYue2TotalSeconds({
  lyrics: props.job.lyrics, style: props.job.style, cot: props.job.cot, precision: props.job.precision,
  steps: Number(props.job.params?.num_inference_steps) || 8,
}, store.jobs.filter((job) => job.id !== props.job.id && job.status === 'done').map((job) => ({
  lyrics: job.lyrics, style: job.style, cot: job.cot, precision: job.precision, wallSec: job.wallSec,
  steps: Number(job.params?.num_inference_steps) || 8,
}))))
const generationElapsed = computed(() => Math.max(0, Math.floor((now.value - (props.job.runStartedAt || now.value)) / 1000)))
const remainingRange = computed(() => typical.value == null || !props.job.runStartedAt ? null : {
  low: Math.max(0, Math.round(typical.value * 0.7 - generationElapsed.value)),
  high: Math.max(0, Math.round(typical.value * 1.4 - generationElapsed.value)),
})
const phaseLabel = computed(() => props.job.status === 'queued' ? t('progress.queued')
  : props.job.phase === 'generating' && nativeProgress.value && nativeProgress.value.phase !== 'done'
    ? t(`progress.${nativeProgress.value.phase}`)
    : t(`progress.${props.job.phase || 'generating'}`))
const exactStageProgress = computed(() => nativeProgress.value?.phase === 'acoustic' || nativeProgress.value?.phase === 'decoding')
const stagePercent = computed(() => exactStageProgress.value && nativeProgress.value && nativeProgress.value.total > 0
  ? Math.min(100, Math.round(100 * nativeProgress.value.current / nativeProgress.value.total)) : null)
const stageRemaining = computed(() => {
  const progress = nativeProgress.value
  if (!exactStageProgress.value || !progress || progress.current < 2 || progress.total <= progress.current) return null
  const phaseElapsed = (now.value - progress.phase_started_ms) / 1000
  if (!Number.isFinite(phaseElapsed) || phaseElapsed < 5) return null
  return Math.round(phaseElapsed / progress.current * (progress.total - progress.current))
})

const createdLabel = computed(() => new Date(props.job.createdAt).toLocaleString(locale.value === 'ru' ? 'ru-RU' : 'en-US'))

function cancel() {
  store.cancel(props.job.id)
}
async function recover() {
  recoveryError.value = ''
  try {
    await store.resetEngine()
  } catch (err) {
    recoveryError.value = err instanceof Error ? err.message : String(err)
  }
}
async function remove() {
  await store.deleteJob(props.job)
}
async function toggleAbc() {
  showAbc.value = !showAbc.value
  if (showAbc.value && abcText.value == null) {
    if (props.job.abcPlan) {
      abcText.value = props.job.abcPlan
    } else if (props.job.dbId != null) {
      loadingAbc.value = true
      try {
        abcText.value = await tracksApi.trackAbc(props.job.dbId)
      } catch {
        abcText.value = ''
      } finally {
        loadingAbc.value = false
      }
    } else {
      abcText.value = ''
    }
  }
}
function insertIntoForm() {
  if (abcText.value) store.requestInsertAbc(abcText.value)
}
function download(format: 'mp3' | 'wav') {
  if (!props.job.audioUrl) return
  const a = document.createElement('a')
  a.href = format === 'mp3' && props.job.dbId != null ? tracksApi.trackMp3Url(props.job.dbId) : props.job.audioUrl
  const name = props.job.savedFilename || `yue2_${props.job.seed}.wav`
  a.download = format === 'mp3' && props.job.dbId != null ? name.replace(/\.[^.]+$/, '.mp3') : name
  a.click()
}
function copyParamsToForm() {
  const p = props.job.params || {}
  store.requestInsertParams({
    ...p,
    lyrics: props.job.lyrics || p.lyrics || '',
    style: props.job.style || p.style || '',
    cot: props.job.cot || p.cot || 'off',
    precision: props.job.precision || p.precision || 'q8_0',
    seed: props.job.seed ?? p.seed,
    abc: props.job.abcPlan || p.abc || '',
  })
  window.scrollTo({ top: 0, behavior: 'smooth' })
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}
</script>

<template>
  <div class="space-y-3 rounded-xl border border-border bg-panel p-4">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <EditableTitle
          :model-value="job.style"
          :placeholder="t('yueTrack.noStyle')"
          :editable="job.dbId != null"
          @rename="(title) => store.renameJob(job, title)"
        />
        <p class="text-xs text-text-dim">{{ createdLabel }} · cot: {{ job.cot }} · {{ job.precision }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <StatusBadge :status="job.status" />
        <button v-if="job.status === 'queued' || job.status === 'running'" type="button" class="text-text-dim hover:text-status-failed disabled:opacity-40" :disabled="job.phase === 'stopping'" :title="t('aceJob.cancel')" @click="cancel">⏹</button>
        <button v-else type="button" class="text-text-dim hover:text-status-failed" :title="t('aceJob.delete')" @click="remove">✕</button>
      </div>
    </div>

    <div v-if="job.status === 'queued' || job.status === 'running'" class="space-y-1">
      <div class="h-2 w-full overflow-hidden rounded-full bg-panel-2" role="progressbar" :aria-label="phaseLabel"
        :aria-valuenow="stagePercent ?? undefined" :aria-valuemin="stagePercent == null ? undefined : 0" :aria-valuemax="stagePercent == null ? undefined : 100">
        <div v-if="stagePercent != null" class="h-full accent-gradient rounded-full transition-[width] duration-500" :style="{ width: `${stagePercent}%` }"></div>
        <div v-else class="h-full w-1/4 accent-gradient animate-pulse rounded-full"></div>
      </div>
      <p class="text-xs text-text-dim">{{ phaseLabel }} · {{ t('progress.elapsed', { time: formatClock(elapsed) }) }}</p>
      <p v-if="nativeProgress && nativeProgress.phase !== 'done' && nativeProgress.total > 0" class="text-xs text-text-dim">
        {{ t('progress.stageCount', { current: nativeProgress.current, total: nativeProgress.total }) }}
        <template v-if="stagePercent != null"> · {{ stagePercent }}%</template>
        <template v-else> · {{ t('progress.tokenLimit') }}</template>
      </p>
      <p v-if="stageRemaining != null" class="text-xs text-text-dim">{{ t('progress.stageRemaining', { time: formatClock(stageRemaining) }) }}</p>
      <p v-if="job.status === 'running' && job.phase === 'generating' && typical != null" class="text-xs text-text-dim">
        {{ remainingRange && remainingRange.high > 0
          ? remainingRange.low > 0
            ? t('progress.remainingRange', { low: formatClock(remainingRange.low), high: formatClock(remainingRange.high) })
            : t('progress.remainingUpTo', { high: formatClock(remainingRange.high) })
          : t('progress.longerThanTypical') }}
        · {{ t('progress.basedOnHistory') }}
      </p>
      <p v-else-if="job.status === 'running' && job.phase === 'generating'" class="text-xs text-text-dim">{{ t('progress.noHistory') }}</p>
      <p class="text-xs text-text-dim">seed: {{ job.seed }}</p>
    </div>

    <div v-else-if="job.status === 'failed'" class="space-y-2 rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">
      <p>{{ job.error }}</p>
      <button v-if="job.error?.includes('is busy')" type="button" :disabled="store.isBusy" class="text-accent1 hover:underline disabled:opacity-40" @click="recover">
        {{ store.resetting ? t('progress.stopping') : t('yueTrack.resetEngine') }}
      </button>
      <p v-if="recoveryError">{{ recoveryError }}</p>
    </div>
    <div v-else-if="job.status === 'cancelled'" class="rounded-lg bg-panel-2 p-2 text-xs text-text-dim">{{ t('aceJob.cancelled') }}</div>

    <div v-else-if="job.status === 'done' && job.audioUrl" class="space-y-2">
      <p v-if="job.phase === 'saving'" class="text-xs text-text-dim">{{ t('progress.saving') }}</p>
      <WaveformPlayer :src="job.audioUrl" />
      <div class="flex flex-wrap items-center gap-3 text-xs text-text-dim">
        <span v-if="job.durationSec">{{ formatDuration(job.durationSec) }}</span>
        <span v-if="job.wallSec">{{ t('yueTrack.generationTime', { value: job.wallSec.toFixed(1) }) }}</span>
        <span>seed: {{ job.seed }}</span>
        <button v-if="job.dbId != null" type="button" class="text-accent1 hover:underline" @click="download('mp3')">{{ t('aceJob.downloadMp3') }}</button>
        <button type="button" class="text-accent1 hover:underline" @click="download('wav')">{{ t('aceJob.downloadWav') }}</button>
        <span v-if="job.savedFilename" class="break-all">💾 {{ job.savedFilename }}</span>
        <span v-else-if="job.saveError" class="text-status-failed" :title="job.saveError">{{ t('yueTrack.notSaved') }}</span>
      </div>
      <div v-if="job.dbId != null" class="space-y-1.5 pt-1">
        <StemsPanel :track-id="job.dbId" :title="job.style" :lyrics="job.lyrics" model="yue2" />
        <MidiPanel :track-id="job.dbId" />
      </div>
      <button type="button" class="text-xs text-text-dim hover:underline" @click="toggleAbc">
        {{ showAbc ? t('yueTrack.hideAbc') : t('yueTrack.showAbc') }}
      </button>
      <div v-if="showAbc">
        <p v-if="loadingAbc" class="text-xs text-text-dim">{{ t('yueTrack.loading') }}</p>
        <template v-else>
          <pre class="whitespace-pre-wrap rounded-lg bg-panel-2 p-2 text-xs text-text-dim">{{ abcText || t('yueTrack.noScore') }}</pre>
          <button v-if="abcText" type="button" class="mt-1 text-xs text-accent1 hover:underline" @click="insertIntoForm">{{ t('yueTrack.insertIntoForm') }}</button>
        </template>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <button type="button" class="text-xs text-accent hover:underline" @click="copyParamsToForm">
        {{ copied ? t('aceJob.copied') : t('aceJob.copyParams') }}
      </button>
      <button v-if="job.lyrics" type="button" class="text-xs text-text-dim hover:underline" @click="showDetails = !showDetails">
        {{ showDetails ? t('aceJob.hideDetails') : t('aceJob.showDetails') }}
      </button>
    </div>
    <div v-if="showDetails" class="space-y-1 rounded-lg bg-panel-2 p-2 text-xs text-text-dim">
      <p><b>{{ t('aceJob.style') }}</b> {{ job.style }}</p>
      <p class="whitespace-pre-wrap"><b>{{ t('aceJob.lyrics') }}</b> {{ job.lyrics }}</p>
    </div>
  </div>
</template>
