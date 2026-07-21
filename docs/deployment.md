# Deployment and Distribution

InMyAI is designed primarily as a local application. Public cloud deployment is not recommended for the filesystem-capable P0 API.

## Native development

```bash
npm run setup
npm run dev
```

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
