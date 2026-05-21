#!/usr/bin/env python3
"""Download all required models for the story-to-image pipeline.

Models:
  - Juggernaut XL v9 (SDXL checkpoint)
  - IP-Adapter FaceID Plus v2 (SDXL)
  - CLIP-ViT-H-14-laion2B-s32B-b79K
  - InsightFace buffalo_l (auto-downloaded by insightface)

Usage:
  python scripts/download_models.py
"""

import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional


MODELS = [
    {
        "name": "Juggernaut XL v9",
        "url": "https://huggingface.co/RunDiffusion/Juggernaut-XL-v9/resolve/main/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "path": "ComfyUI/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "output_path": "ComfyUI/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "size_gb": 6.5,
    },
    {
        "name": "IP-Adapter FaceID Plus v2 (SDXL)",
        "url": "https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin",
        "path": "ComfyUI/models/ipadapter/ip-adapter-faceid-plusv2_sdxl.bin",
        "size_gb": 1.2,
    },
    {
        "name": "CLIP-ViT-H-14-laion2B-s32B-b79K",
        "url": "https://huggingface.co/laion/CLIP-ViT-H-14-laion2B-s32B-b79K/resolve/main/open_clip_pytorch_model.safetensors",
        "path": "ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "size_gb": 1.5,
    },
]


def download_file(url: str, dest_path: str, expected_gb: Optional[float] = None) -> bool:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        file_size_gb = dest.stat().st_size / (1024**3)
        if expected_gb and abs(file_size_gb - expected_gb) < 0.5:
            print(f"  Already exists: {dest.name} ({file_size_gb:.1f} GB)")
            return True
        else:
            print(f"  Re-downloading: {dest.name}")

    print(f"  Downloading {dest.name}...")
    if expected_gb:
        print(f"    Size: ~{expected_gb:.1f} GB, this may take a while")

    def report_hook(count, block_size, total_size):
        if total_size > 0:
            percent = min(count * block_size * 100 / total_size, 100)
            downloaded_gb = count * block_size / (1024**3)
            total_gb = total_size / (1024**3)
            bar_len = 40
            filled = int(bar_len * percent / 100)
            bar = "=" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\r    [{bar}] {percent:.1f}% ({downloaded_gb:.2f}/{total_gb:.2f} GB)")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, str(dest), reporthook=report_hook)
        sys.stdout.write("\n")
        return True
    except Exception as e:
        sys.stdout.write("\n")
        print(f"    Error downloading {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def download_insightface_models():
    print("\n  InsightFace models (buffalo_l):")
    try:
        import insightface
        from insightface.model_zoo import get_model
        model = get_model("buffalo_l")
        print("    Auto-downloaded by insightface library")
    except ImportError:
        print("    insightface not installed. Install with: pip install insightface")
        print("    Models will auto-download on first use.")


def main():
    print("=" * 60)
    print("Model Downloader for Story-to-Image Pipeline")
    print("=" * 60)
    print()

    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)

    success_count = 0
    fail_count = 0

    for model in MODELS:
        print(f"\n[{MODELS.index(model) + 1}/{len(MODELS)}] {model['name']}")
        if download_file(model["url"], model["path"], model.get("size_gb")):
            success_count += 1
        else:
            fail_count += 1

    print(f"\nInsightFace:")
    download_insightface_models()

    print(f"\n{'=' * 60}")
    print(f"Download complete: {success_count} succeeded, {fail_count} failed")
    if fail_count > 0:
        print("Some downloads failed. You can re-run this script to retry.")
        print("Alternatively, download manually from the HuggingFace URLs above.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
