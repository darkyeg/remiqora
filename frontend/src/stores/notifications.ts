import { defineStore } from 'pinia'
import { i18n } from '../i18n'

const KEY = 'remiqora.notifications.v1'

interface SavedSettings { desktopEnabled: boolean; unread: number }

function savedSettings(): SavedSettings {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || '{}')
    return {
      desktopEnabled: value.desktopEnabled === true,
      unread: Number.isInteger(value.unread) ? Math.max(0, value.unread) : 0,
    }
  } catch {
    return { desktopEnabled: false, unread: 0 }
  }
}

declare global {
  interface Window {
    remiqora?: {
      notifyTrack?: (title: string, body: string) => Promise<boolean>
    }
  }
}

export const useNotificationsStore = defineStore('notifications', {
  state: () => savedSettings(),
  actions: {
    save() {
      try {
        localStorage.setItem(KEY, JSON.stringify({ desktopEnabled: this.desktopEnabled, unread: this.unread }))
      } catch {
        // A disabled or full browser store must not affect finished audio.
      }
    },
    setDesktopEnabled(enabled: boolean) {
      this.desktopEnabled = enabled
      this.save()
    },
    markRead() {
      this.unread = 0
      this.save()
    },
    trackDone(model: 'ace_step' | 'yue2', title: string) {
      this.unread += 1
      this.save()
      const notify = window.remiqora?.notifyTrack
      if (this.desktopEnabled && notify) {
        const label = model === 'yue2' ? 'YuE2' : 'ACE-Step'
        void notify(
          i18n.global.t('notifications.completed'),
          `${label}: ${title.slice(0, 100)}`,
        ).catch(() => {})
      }
    },
  },
})
