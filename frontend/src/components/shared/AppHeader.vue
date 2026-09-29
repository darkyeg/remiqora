<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { useNotificationsStore } from '../../stores/notifications'
import { MODEL_LABELS, MODEL_ROUTES, useModelSwitch } from '../../composables/useModelSwitch'
import { setLocale, currentLocale, type LocaleCode } from '../../i18n'
import { languageLabel } from '../../utils/languageLabel'
import type { ModelId, ModelRuntimeStatus } from '../../types'

const orchestrator = useOrchestratorStore()
const notifications = useNotificationsStore()
const notificationsOpen = ref(false)
const route = useRoute()
const { selectModel } = useModelSwitch()
const { t, locale } = useI18n()

const LOCALES: { code: LocaleCode; label: string }[] = [
  { code: 'ru', label: 'Русский' },
  { code: 'en', label: 'English' },
]

function onLocaleChange(e: Event) {
  setLocale((e.target as HTMLSelectElement).value as LocaleCode)
}

const MODEL_IDS: ModelId[] = ['ace_step', 'yue2']

function statusOf(id: ModelId): ModelRuntimeStatus {
  return orchestrator.statuses[id]?.status ?? 'stopped'
}

const LED_CLASSES: Record<ModelRuntimeStatus, string> = {
  stopped: 'bg-gray-500',
  starting: 'bg-status-queued animate-pulse',
  running: 'bg-status-done',
  stopping: 'bg-status-queued animate-pulse',
  error: 'bg-status-failed',
}

const STATUS_LABEL_KEYS: Record<ModelRuntimeStatus, string> = {
  stopped: 'modelStatus.stopped',
  starting: 'modelStatus.starting',
  running: 'modelStatus.running',
  stopping: 'modelStatus.stopping',
  error: 'modelStatus.error',
}

async function onSelect(id: ModelId) {
  try {
    await selectModel(id)
  } catch {
    // orchestrator.switchError already holds the message, rendered below.
  }
}
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border bg-bg/90 backdrop-blur">
    <div class="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
      <router-link to="/" class="flex items-center gap-2 text-text">
        <span class="accent-gradient flex h-6 w-6 shrink-0 items-center justify-center rounded-md">
          <svg viewBox="0 0 32 32" width="16" height="16" aria-hidden="true">
            <text x="16" y="23" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-weight="800" font-size="21" fill="white">R</text>
          </svg>
        </span>
        <span class="flex flex-col leading-tight">
          <span class="text-lg font-semibold">Remiqora</span>
          <span class="text-[10px] text-text-dim">{{ t('header.tagline') }}</span>
        </span>
      </router-link>

      <nav class="ml-auto flex flex-wrap gap-2">
        <router-link
          to="/editor"
          class="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors"
          :class="route.path.startsWith('/editor') ? 'border-accent1/60 bg-panel text-text' : 'border-border bg-panel-2 text-text-dim hover:text-text'"
        >
          {{ t('header.editor') }}
        </router-link>
        <router-link
          v-if="statusOf('ace_step') === 'running'"
          to="/ace-step/lora"
          class="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors"
          :class="route.path.startsWith('/ace-step/lora') ? 'border-accent1/60 bg-panel text-text' : 'border-border bg-panel-2 text-text-dim hover:text-text'"
        >
          {{ t('header.lora') }}
        </router-link>
        <button
          v-for="id in MODEL_IDS"
          :key="id"
          type="button"
          class="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors"
          :class="route.name === MODEL_ROUTES[id] ? 'border-accent1/60 bg-panel text-text' : 'border-border bg-panel-2 text-text-dim hover:text-text'"
          @click="onSelect(id)"
        >
          <span class="h-2 w-2 rounded-full" :class="LED_CLASSES[statusOf(id)]"></span>
          <span>{{ MODEL_LABELS[id] }}</span>
          <span class="text-xs text-text-dim">{{ t(STATUS_LABEL_KEYS[statusOf(id)]) }}</span>
        </button>
        <select
          class="rounded-lg border border-border bg-panel-2 px-2 py-2 text-sm text-text"
          :value="currentLocale()"
          @change="onLocaleChange"
        >
          <option v-for="loc in LOCALES" :key="loc.code" :value="loc.code">{{ languageLabel(loc.code, loc.label, locale) }}</option>
        </select>
        <div class="relative">
          <button type="button" class="relative rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm text-text hover:border-accent1/60"
            :aria-label="t('notifications.settings')" :aria-expanded="notificationsOpen" @click="notificationsOpen = !notificationsOpen">
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" />
            </svg>
            <span v-if="notifications.unread" class="absolute -right-2 -top-2 min-w-5 rounded-full bg-accent1 px-1 text-center text-xs font-semibold text-white">
              {{ notifications.unread > 99 ? '99+' : notifications.unread }}
            </span>
          </button>
          <div v-if="notificationsOpen" class="absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-border bg-panel p-4 text-sm text-text shadow-xl">
            <p class="mb-3 font-semibold">{{ t('notifications.settings') }}</p>
            <label class="flex cursor-pointer items-start gap-2">
              <input type="checkbox" class="mt-1 accent-accent1" :checked="notifications.desktopEnabled"
                @change="notifications.setDesktopEnabled(($event.target as HTMLInputElement).checked)">
              <span>{{ t('notifications.desktopToggle') }}</span>
            </label>
            <div class="mt-3 flex items-center justify-between border-t border-border pt-3 text-text-dim">
              <span>{{ t('notifications.unread', { count: notifications.unread }) }}</span>
              <button v-if="notifications.unread" type="button" class="text-accent1 hover:underline" @click="notifications.markRead()">
                {{ t('notifications.markRead') }}
              </button>
            </div>
          </div>
        </div>
      </nav>
    </div>
    <p v-if="orchestrator.switchError" class="border-t border-status-failed/30 bg-status-failed/10 px-4 py-2 text-xs whitespace-pre-line text-status-failed sm:px-6">
      {{ orchestrator.switchError }}
    </p>
  </header>
</template>
