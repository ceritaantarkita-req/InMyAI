# InMyAI Design System

## Direction

The interface follows the accepted usage concept: a quiet desktop productivity environment with neutral white surfaces, compact typography, restrained blue selection states, and visible context/safety information. It avoids neon AI gradients and decorative “AI slop.”

## Primary surfaces

1. Chat
2. Files
3. Memory
4. Graph
5. Studio
6. Git (read-only repository inspection: status/log/diff/branches/blame)

Settings remains a utility modal, not a primary work surface. Git was added as
a sixth surface rather than folded into Files because repository state is a
distinct dev-workflow concern and deserves equal discoverability. Git tools are
strictly read-only — no commits, pushes, or branch mutations go through InMyAI.

## Tokens

- background: `#f5f6f8`
- surface: `#ffffff`
- secondary surface: `#f7f8fa`
- text: `#171b22`
- muted: `#687281`
- border: `#e2e6eb`
- accent: `#2368e8`
- success: `#16845b`
- radius: 7–10px for application panels
- shadow: low-opacity neutral shadow only for overlays

## Layout

Desktop:

- 232px project/navigation sidebar
- flexible main workspace
- 268px context rail

Medium desktop:

- context rail collapses
- change proposal panel can float

Mobile:

- desktop sidebar removed
- five-item bottom navigation
- single-column work surfaces
- contextual panels become overlays

## Typography

Use native/system sans-serif fonts to reduce download size and improve Windows rendering. Code uses system monospace. UI labels are intentionally compact, but primary body content remains readable.

## Interaction rules

- no inert controls
- selected state is always visible
- long-running actions expose loading state
- errors appear in a dismissible notice
- file writes require explicit Apply
- source citations appear under AI responses
- router reason and RAM estimate are visible
- animations use opacity/transform only and respect reduced-motion preferences

## Fidelity notes

The reference concept used seven sidebar labels. The implementation consolidates them into five primary surfaces to reduce navigation density: Search is integrated into Files/Graph, Tasks are represented by suggested tasks and future task data, Settings is a modal.
