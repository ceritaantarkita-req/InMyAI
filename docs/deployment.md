# Deployment and Distribution

InMyAI is designed primarily as a local application. Public cloud deployment is not recommended for the filesystem-capable P0 API.

## Native development

```bash
npm run setup
npm run dev
```

During the additive G3 migration, the default remains web `127.0.0.1:3000` and API `127.0.0.1:8000`. To test the reviewed canonical pair without changing those defaults:

```powershell
$env:INMYAI_WEB_PORT='17001'
$env:INMYAI_API_PORT='17002'
npm run dev
```

Both overrides must be integers from 1 through 65535. Invalid values fail before either listener starts; occupied ports fail without selecting a fallback. The web launcher follows `INMYAI_API_PORT` unless `NEXT_PUBLIC_API_URL` was explicitly set. Remove the two overrides to roll back to the legacy topology. Changing these process-local ports does not rewrite product data or user configuration.

The Tauri development shell intentionally remains on the legacy web port during this opt-in phase. A default or desktop-shell cutover requires a later reviewed gate.

## Docker

Docker isolates the API, so host projects must be explicitly mounted:

```env
INMYAI_HOST_PROJECTS_DIR=/absolute/host/projects
```

```bash
docker compose up --build
```

Register mounted project paths using `/projects/<folder>` inside the UI.

## Future desktop distribution

P1 adds a Tauri shell, native folder picker, OS capability scopes, installer signing, and controlled sidecar lifecycle for FastAPI.
