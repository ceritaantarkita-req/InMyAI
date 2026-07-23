# How to Add a Model Provider

1. Add a provider class under `services/api/app/providers.py` or a dedicated module.
2. Expose `chat(messages, model)` and optional `models()`/`unload()` methods.
3. Never place API keys in source or browser state.
4. Add a provider availability check with a short timeout.
5. Define safe fallback behavior.
6. Update the router and response transparency fields.
7. Add unit tests using mocked HTTP transport; CI must not call a paid/cloud service.
8. Document model licensing and whether data leaves the device.
9. Measure RAM, latency, and output quality before calling the provider recommended.
10. Update `docs/log.md`.
11. If the provider has an install/run state a user can be stuck in (like Ollama: not installed → not running → no model pulled), extend `get_*_install_state()` and the `/api/models/onboarding` phase classification (`services/api/app/providers.py`, `main.py`) instead of adding a second, provider-specific onboarding flow — the wizard in `apps/web/src/components/Workspace.tsx` renders off that one endpoint.
