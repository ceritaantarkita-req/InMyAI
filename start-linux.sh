#!/usr/bin/env bash
set -euo pipefail
[ -f .env ] || cp .env.example .env
[ -d .venv ] || npm run setup
npm run dev
