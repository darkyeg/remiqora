export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = String(total % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

export function medianSeconds(samples: number[]): number | null {
  const valid = samples.filter((value) => Number.isFinite(value) && value > 0).sort((a, b) => a - b)
  if (!valid.length) return null
  const middle = Math.floor(valid.length / 2)
  return valid.length % 2 ? valid[middle] : (valid[middle - 1] + valid[middle]) / 2
}

export interface ComparableYue2Run {
  lyrics: string
  style: string
  cot: string
  precision: string
  wallSec?: number | null
  steps?: number | null
}

/** Only compare runs with the same solver steps; semantic generation also takes time. */
export function estimateYue2TotalSeconds(current: ComparableYue2Run, history: ComparableYue2Run[]): number | null {
  const currentSteps = current.steps && current.steps > 0 ? current.steps : 8
  const candidates = history
    .filter((run) => run.wallSec && run.wallSec > 0 && run.cot === current.cot && run.precision === current.precision
      && run.lyrics.length > 0 && current.lyrics.length > 0
      && (run.steps && run.steps > 0 ? run.steps : 8) === currentSteps)
    .map((run) => {
      const lengthRatio = run.lyrics.length / current.lyrics.length
      return {
        run,
        distance: (run.lyrics === current.lyrics ? -2 : Math.abs(Math.log(lengthRatio)))
          + (run.style === current.style ? -0.25 : 0),
        lengthRatio,
      }
    })
    .filter(({ lengthRatio }) => lengthRatio >= 0.5 && lengthRatio <= 2)
    .sort((a, b) => a.distance - b.distance)
    .slice(0, 3)
  return medianSeconds(candidates.map(({ run }) => run.wallSec || 0))
}
