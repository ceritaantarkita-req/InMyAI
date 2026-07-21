# Browser Verification Method

Browser navigation to local URLs was blocked by the managed Chromium policy in the build environment (`ERR_BLOCKED_BY_ADMINISTRATOR`).

Fallback used:

- actual Next.js development and production servers were started and checked by HTTP;
- actual FastAPI routes were exercised through a smoke workflow;
- Playwright Chromium under Xvfb rendered production CSS and representative application markup with `page.set_content`;
- screenshots were inspected at 1536×1024 and 390×844.

This fallback validates CSS, layout, typography, responsive behavior, and visual fidelity. It does not replace live browser interaction testing on the user's Windows machine, which remains part of the manual acceptance checklist.
