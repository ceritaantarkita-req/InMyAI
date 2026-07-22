"""Optional low-memory image generation plugin.

This file is intentionally not imported by the core API. Install
services/api/requirements-image.txt and download a compatible model only when the
user enables image generation. The core app remains usable without these large
packages or weights.
"""
from __future__ import annotations

import torch
from diffusers import AutoPipelineForText2Image


def generate(
    prompt: str,
    output_path: str,
    model_id: str = 'stabilityai/sd-turbo',
    *,
    width: int = 512,
    height: int = 512,
    steps: int = 4,
    seed: int | None = None,
    negative_prompt: str = '',
) -> str:
    """Run a low-memory text-to-image pipeline and save the PNG.

    Defaults target SD-Turbo (a 4-step distilled model). `width`/`height`/`steps`
    override the defaults; `seed` makes the run reproducible; `negative_prompt`
    is forwarded when the pipeline supports it. Returns the output_path.
    """
    import random

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=dtype)
    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
        pipe.enable_attention_slicing()
    generator = None
    if seed is not None:
        generator = torch.Generator(device='cuda' if torch.cuda.is_available() else 'cpu')
        generator = generator.manual_seed(int(seed))
    kwargs = dict(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0, height=height, width=width)
    if generator is not None:
        kwargs['generator'] = generator
    if negative_prompt:
        kwargs['negative_prompt'] = negative_prompt
    image = pipe(**kwargs).images[0]
    image.save(output_path)
    del pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    # keep `random` referenced for parity with callers that may seed
    _ = random
    return output_path
