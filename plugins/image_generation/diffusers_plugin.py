"""Optional low-memory image generation plugin.

This file is intentionally not imported by the core API. Install
services/api/requirements-image.txt and download a compatible model only when the
user enables image generation. The core app remains usable without these large
packages or weights.
"""
from __future__ import annotations

import torch
from diffusers import AutoPipelineForText2Image


def generate(prompt: str, output_path: str, model_id: str = 'stabilityai/sd-turbo') -> str:
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=dtype)
    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
        pipe.enable_attention_slicing()
    image = pipe(prompt=prompt, num_inference_steps=4, guidance_scale=0.0, height=512, width=512).images[0]
    image.save(output_path)
    del pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return output_path
