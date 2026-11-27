---
license: apache-2.0
tags:
- diffusion-single-file
- comfyui
- distillation
- LoRA
- lora
- Qwen-Image
- Qwen-Image-Edit
base_model:
- Qwen/Qwen-Image-Edit-2511
pipeline_tags:
- image-to-image
- text-to-image
library_name: diffusers
pipeline_tag: image-to-image
---
# Qwen-Image-Edit-2511-Lightning

## Model Overview
Qwen-Image-Edit-2511-Lightning is a collection of optimized models tailored for image editing tasks, leveraging step distillation and quantization techniques to deliver high-efficiency inference performance. This repository hosts three core model files with distinct characteristics:

| Model File Name | Type | Key Features |
|-----------------|------|--------------|
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | 4-step Distilled LoRA | BF16 precision, lightweight, 4-step inference |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors` | 4-step Distilled LoRA | FP32 precision, high accuracy, 4-step inference |
| `qwen_image_edit_2511_fp8_e4m3fn_scaled_lightning.safetensors` | FP8 Quantized | FP8 (e4m3fn scaled) precision, fused with 4-step distilled LoRA, optimized for low-memory deployment |

## Usage Instructions
This model suite supports two mainstream usage frameworks, with detailed guides provided below:

### 1. Qwen-Image-Lightning Framework
For full documentation on model usage within the Qwen-Image-Lightning ecosystem (including environment setup, inference pipelines, and customization), please refer to:
[Qwen-Image-Lightning GitHub Repository](https://github.com/ModelTC/Qwen-Image-Lightning/)

### 2. LightX2V Framework
The models are fully compatible with the LightX2V lightweight video/image generation inference framework. For step-by-step usage examples, configuration templates, and performance optimization tips, see:
[LightX2V Qwen Image Edit Documentation](https://github.com/ModelTC/LightX2V/blob/main/scripts/qwen_image/README.md)

## Key Optimizations
- **Step Distillation**: The LoRA models reduce the original inference steps to just 4 steps, achieving significant speedup (≈10x faster than standard 40-step inference) while preserving image editing quality.
- **FP8 Quantization**: The quantized base model balances performance and resource efficiency, reducing GPU memory usage by ~50% compared to FP32 while maintaining editing fidelity.

## Support
For technical issues, feature requests, or integration questions:
- Open an issue in the [Qwen-Image-Lightning repo](https://github.com/ModelTC/Qwen-Image-Lightning/issues) (for Qwen framework-specific questions)
- Open an issue in the [LightX2V repo](https://github.com/ModelTC/LightX2V/issues) (for LightX2V integration questions)