# Local Image Generation

## Honest P0 behavior

The core includes a deterministic workflow simulator. Its output is clearly labeled **not AI-generated**. This verifies UI, jobs, artifacts, path handling, and resource guards without forcing multi-gigabyte dependencies and model downloads on every contributor.

## Real backend options

### Optional Diffusers plugin

```bash
.venv/bin/pip install -r services/api/requirements-image.txt
```

See `plugins/image_generation/diffusers_plugin.py`. It defaults to a low-step 512×512 workflow and unloads the pipeline after generation. Model download and license acceptance remain the user's responsibility.

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
