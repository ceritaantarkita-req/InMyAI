// Pure sizing logic for the resizable sidebar/context-rail panels in
// Workspace.tsx, pulled out into its own module so it's testable without a
// browser (dragging a real mouse can't be exercised in `node --test`, but
// the clamping math it depends on can be).

export const SIDEBAR_MIN = 180
export const SIDEBAR_MAX = 420
export const SIDEBAR_DEFAULT = 232

export const RAIL_MIN = 220
export const RAIL_MAX = 440
export const RAIL_DEFAULT = 268

export function clampPanelWidth(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min
  return Math.min(max, Math.max(min, value))
}
