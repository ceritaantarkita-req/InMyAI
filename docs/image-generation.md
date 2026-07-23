# Local Image Generation

## Honest P0 behavior

The core includes a deterministic workflow simulator. Its output is clearly labeled **not AI-generated**. This verifies UI, jobs, artifacts, path handling, and resource guards without forcing multi-gigabyte dependencies and model downloads on every contributor.

## Real backend options

### Optional Diffusers backend

The Diffusers plugin is wired into the API as `provider='diffusers'` (selectable
from the Studio tab). It imports torch/diffusers lazily at request time, so the
core still starts and runs without them installed.

To enable real local generation:

```bash
.venv/bin/pip install -r services/api/requirements-image.txt
```

Then set the model id (optional; defaults to SD-Turbo, a 4-step distilled model):

```env
INMYAI_DIFFUSERS_MODEL_ID=stabilityai/sd-turbo
```

If the optional packages are not installed, a request with `provider='diffusers'`
returns HTTP 400 with a pointer to `requirements-image.txt` rather than a 500.
The plugin runs a low-step 512×512 workflow and unloads the pipeline after
generation. Model download and license acceptance remain the user's responsibility.

### ComfyUI

Run ComfyUI locally and configure:

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=/absolute/path/to/workflow.json
```

The production adapter and workflow substitution are P1.

## 8–16 GB policy

- batch size 1
- 512×512 default
- low inference steps
- one heavy engine active
- unload chat model before image model
- block generation if free RAM is below threshold
