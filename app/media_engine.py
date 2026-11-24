# ==============================================================================
# AI Video Production Studio - Real AI Media & Pixel Gatekeeper Engine (Part C3)
# Covers: Real Multi-Provider AI Image Gen, T2V/I2V Video Gen, Photo Editing,
#         & Strict Pillow + NumPy Pixel-Level Integrity Verification
# ==============================================================================

from __future__ import annotations

import asyncio
import base64
import io
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from app.config import OUTPUTS_DIR, TEMP_DIR, get_provider_by_id
from app.models import AgentSlot
from app.provider_engine import build_auth_headers

MEDIA_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


# ------------------------------------------------------------------------------
# 1. RESOLUTION & ASPECT RATIO MAPPER
# ------------------------------------------------------------------------------
def aspect_ratio_to_dimensions(
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
) -> Tuple[int, int]:
    """Return even (width, height) dimensions suitable for FFmpeg & AI generators."""
    scale_map = {"720p": 720, "1080p": 1080, "4K": 2160}
    short_side = scale_map.get(resolution, 1080)

    if aspect_ratio == "9:16":
        w, h = short_side, int(short_side * 16 / 9)
    elif aspect_ratio == "1:1":
        w, h = short_side, short_side
    elif aspect_ratio == "4:5":
        w, h = short_side, int(short_side * 5 / 4)
    else:  # default 16:9
        w, h = int(short_side * 16 / 9), short_side

    # Ensure dimensions are divisible by 2 for H.264/yuv420p compatibility
    return (w - (w % 2), h - (h % 2))


# ------------------------------------------------------------------------------
# 2. STRICT PILLOW + NUMPY PIXEL-LEVEL MEDIA GATEKEEPER
# ------------------------------------------------------------------------------
def verify_real_image(image_path: Path, min_size: int = 256) -> Tuple[bool, str]:
    """
    Zero-Hallucination Media Gatekeeper:
    Verifies the file is a genuine, non-corrupt, non-blank high-variance raster image.
    """
    if not image_path.exists() or image_path.stat().st_size < 2048:
        return False, "Image file is missing or too small (<2KB)."

    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            if w < min_size or h < min_size:
                return False, f"Image resolution too low: {w}x{h}."

            # Check pixel standard deviation to reject blank/solid-color error frames
            arr = np.asarray(rgb.resize((128, 128)), dtype=np.float32)
            std_dev = float(np.std(arr))
            if std_dev < 4.5:
                return False, f"Image rejected as flat/blank frame (std={std_dev:.2f})."
        return True, f"Verified real image ({w}x{h}, variance={std_dev:.1f})"
    except Exception as exc:
        return False, f"Corrupt image file: {exc}"


def smart_fit_image(
    image_path: Path,
    target_w: int,
    target_h: int,
    out_path: Optional[Path] = None,
) -> Path:
    """Center-crop and upscale/resize image cleanly to exact video frame dimensions."""
    dest = out_path or image_path
    with Image.open(image_path) as img:
        rgb = img.convert("RGB")
        fitted = ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.LANCZOS)
        fitted.save(dest, format="PNG", optimize=True)
    return dest


def edit_photo_enhance(
    image_path: Path,
    prompt: str,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    out_path: Optional[Path] = None,
) -> Path:
    """Apply studio color/contrast/sharpness grading and framing for Photo Edit mode."""
    w, h = aspect_ratio_to_dimensions(aspect_ratio, resolution)
    dest = out_path or (OUTPUTS_DIR / f"edited_{uuid.uuid4().hex[:8]}.png")
    low = (prompt or "").lower()

    with Image.open(image_path) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")
        rgb = ImageOps.fit(rgb, (w, h), method=Image.Resampling.LANCZOS)

        if any(k in low for k in ("black and white", "b&w", "monochrome", "সাদা কালো")):
            rgb = ImageOps.grayscale(rgb).convert("RGB")
        else:
            color_factor = 1.25 if any(k in low for k in ("vibrant", "anime", "colorful", "রঙিন")) else 1.12
            rgb = ImageEnhance.Color(rgb).enhance(color_factor)

        contrast_factor = 1.18 if any(k in low for k in ("cinematic", "dramatic", "dark", "সিনেমা")) else 1.08
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast_factor)
        rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
        rgb.save(dest, format="PNG", optimize=True)
    return dest


# ------------------------------------------------------------------------------
# 3. BINARY DOWNLOAD & BASE64 DECODER HELPERS
# ------------------------------------------------------------------------------
async def _download_binary(
    url: str,
    dest_path: Path,
    headers: Optional[Dict[str, str]] = None,
) -> Path:
    """Download a remote image or video asset reliably to disk."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=MEDIA_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)
    return dest_path


def _save_base64_image(b64_data: str, dest_path: Path) -> Path:
    """Decode base64 image string (with or without data URI prefix) and save as PNG."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    raw_b64 = b64_data.split(",", 1)[1] if "," in b64_data else b64_data
    img_bytes = base64.b64decode(raw_b64)
    with Image.open(io.BytesIO(img_bytes)) as img:
        img.convert("RGB").save(dest_path, format="PNG")
    return dest_path
  # ------------------------------------------------------------------------------
# 4. MULTI-PROVIDER REAL AI IMAGE GENERATION (ZERO FAKE SVG / STRICT VERIFIED)
# ------------------------------------------------------------------------------
async def generate_real_image(
    slot: AgentSlot,
    prompt: str,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    negative_prompt: str = "blurry, distorted, watermark, stick figure, svg cartoon",
    out_dir: Optional[Path] = None,
) -> Path:
    """
    Generate a genuine AI raster image via the configured provider slot,
    verify it with Pillow + NumPy Pixel Gatekeeper, and fit to target dimensions.
    """
    target_w, target_h = aspect_ratio_to_dimensions(aspect_ratio, resolution)
    save_dir = out_dir or TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    dest_path = save_dir / f"img_{uuid.uuid4().hex[:10]}.png"

    provider = get_provider_by_id(slot.provider_id) or {
        "id": slot.provider_id,
        "base_url": slot.base_url or "https://api.openai.com/v1",
        "auth_type": "bearer",
    }
    pid = provider["id"]
    base_url = (slot.base_url or provider.get("base_url") or "").rstrip("/")
    model_id = slot.model_id
    api_key = slot.api_key
    headers = build_auth_headers(provider, api_key)

    async with httpx.AsyncClient(timeout=MEDIA_TIMEOUT, follow_redirects=True) as client:
        # 1) Google Gemini / Imagen Native Image Generation
        if pid == "google_gemini":
            if "imagen" in model_id.lower():
                url = f"{base_url}/models/{model_id}:predict"
                payload = {
                    "instances": [{"prompt": prompt}],
                    "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
                }
                resp = await client.post(url, params={"key": api_key}, json=payload)
                resp.raise_for_status()
                b64 = resp.json()["predictions"][0]["bytesBase64Encoded"]
                _save_base64_image(b64, dest_path)
            else:
                url = f"{base_url}/models/{model_id}:generateContent"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": f"Generate high-detail image: {prompt}"}]}],
                    "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
                }
                resp = await client.post(url, params={"key": api_key}, json=payload)
                resp.raise_for_status()
                parts = resp.json()["candidates"][0]["content"]["parts"]
                img_b64 = next(
                    (p["inlineData"]["data"] for p in parts if "inlineData" in p and p["inlineData"].get("data")),
                    None,
                )
                if not img_b64:
                    raise RuntimeError("Gemini did not return inline image data.")
                _save_base64_image(img_b64, dest_path)

        # 2) Fal.ai Image Generation (FLUX, SDXL, etc.)
        elif pid == "fal_ai":
            url = f"https://fal.run/{model_id.lstrip('/')}"
            size_map = {
                "16:9": "landscape_16_9",
                "9:16": "portrait_16_9",
                "1:1": "square_hd",
                "4:5": "portrait_4_3",
            }
            payload = {
                "prompt": prompt,
                "image_size": size_map.get(aspect_ratio, "landscape_16_9"),
                "num_images": 1,
            }
            resp = await client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
            resp.raise_for_status()
            data = resp.json()
            img_url = (data.get("images") or [{}])[0].get("url") or (data.get("image") or {}).get("url")
            if not img_url:
                raise RuntimeError("Fal.ai response missing image URL.")
            await _download_binary(img_url, dest_path)

        # 3) Hugging Face Serverless Inference API
        elif pid == "huggingface":
            url = f"https://router.huggingface.co/hf-inference/models/{model_id.lstrip('/')}"
            payload = {"inputs": prompt, "parameters": {"negative_prompt": negative_prompt}}
            resp = await client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)

        # 4) Stability AI v2beta
        elif pid == "stability":
            endpoint = model_id if model_id in ("core", "ultra", "sd3") else "core"
            url = f"{base_url}/stable-image/generate/{endpoint}"
            st_headers = {"Authorization": f"Bearer {api_key}", "Accept": "image/*"}
            files = {"prompt": (None, prompt), "aspect_ratio": (None, aspect_ratio), "output_format": (None, "png")}
            resp = await client.post(url, headers=st_headers, files=files)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)

        # 5) OpenAI-Compatible /images/generations (OpenAI, Together, Fireworks, xAI, NVIDIA, Custom)
        else:
            url = f"{base_url}/images/generations"
            size_str = "1792x1024" if aspect_ratio == "16:9" else ("1024x1792" if aspect_ratio == "9:16" else "1024x1024")
            payload: Dict[str, Any] = {"model": model_id, "prompt": prompt, "n": 1, "size": size_str}
            resp = await client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
            resp.raise_for_status()
            item = (resp.json().get("data") or [{}])[0]
            if item.get("b64_json"):
                _save_base64_image(item["b64_json"], dest_path)
            elif item.get("url"):
                await _download_binary(item["url"], dest_path)
            else:
                raise RuntimeError(f"Provider {pid} returned neither image URL nor base64.")

    ok, reason = verify_real_image(dest_path)
    if not ok:
        raise RuntimeError(f"Media Gatekeeper rejected generated frame: {reason}")

    return smart_fit_image(dest_path, target_w, target_h, dest_path)


# ------------------------------------------------------------------------------
# 5. MULTI-PROVIDER REAL AI VIDEO GENERATION (T2V & I2V)
# ------------------------------------------------------------------------------
async def generate_real_video_clip(
    slot: AgentSlot,
    prompt: str,
    image_path: Optional[Path] = None,
    aspect_ratio: str = "16:9",
    duration_sec: int = 5,
    out_dir: Optional[Path] = None,
) -> Path:
    """
    Generate a genuine AI motion video clip (.mp4) via Fal.ai, Replicate, or Luma.
    """
    save_dir = out_dir or TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    dest_path = save_dir / f"vid_{uuid.uuid4().hex[:10]}.mp4"

    provider = get_provider_by_id(slot.provider_id) or {
        "id": slot.provider_id,
        "base_url": slot.base_url or "https://fal.run",
        "auth_type": "bearer",
    }
    pid = provider["id"]
    headers = build_auth_headers(provider, slot.api_key)
    headers["Content-Type"] = "application/json"

    img_data_uri: Optional[str] = None
    if image_path and image_path.exists():
        b64_img = base64.b64encode(image_path.read_bytes()).decode("ascii")
        img_data_uri = f"data:image/png;base64,{b64_img}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0), follow_redirects=True) as client:
        # 1) Fal.ai Video Generation (Kling, Minimax, LTX-Video)
        if pid == "fal_ai":
            url = f"https://fal.run/{slot.model_id.lstrip('/')}"
            payload: Dict[str, Any] = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "duration": str(5 if duration_sec <= 6 else 10),
            }
            if img_data_uri:
                payload["image_url"] = img_data_uri
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            video_url = (data.get("video") or {}).get("url") or data.get("video_url")
            if not video_url:
                raise RuntimeError("Fal.ai video response missing .mp4 URL.")
            await _download_binary(video_url, dest_path)

        # 2) Replicate Async Prediction Polling
        elif pid == "replicate":
            url = f"https://api.replicate.com/v1/models/{slot.model_id.lstrip('/')}/predictions"
            rep_input: Dict[str, Any] = {"prompt": prompt}
            if img_data_uri:
                rep_input["first_frame_image"] = img_data_uri
            resp = await client.post(url, headers=headers, json={"input": rep_input})
            resp.raise_for_status()
            pred = resp.json()
            poll_url = (pred.get("urls") or {}).get("get")
            for _ in range(45):
                if pred.get("status") in ("succeeded", "failed", "canceled"):
                    break
                await asyncio.sleep(3)
                pred = (await client.get(poll_url, headers=headers)).json()
            if pred.get("status") != "succeeded":
                raise RuntimeError(f"Replicate video job failed: {pred.get('error')}")
            out_val = pred.get("output")
            video_url = out_val[0] if isinstance(out_val, list) else out_val
            await _download_binary(str(video_url), dest_path)

        # 3) Luma Dream Machine
        elif pid == "luma":
            url = "https://api.lumalabs.ai/dream-machine/v1/generations"
            payload = {"prompt": prompt, "model": slot.model_id or "ray-2", "aspect_ratio": aspect_ratio}
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            gen = resp.json()
            gen_id = gen.get("id")
            for _ in range(45):
                if gen.get("state") in ("completed", "failed"):
                    break
                await asyncio.sleep(3)
                gen = (await client.get(f"{url}/{gen_id}", headers=headers)).json()
            video_url = (gen.get("assets") or {}).get("video")
            if not video_url:
                raise RuntimeError(f"Luma video generation failed: {gen.get('failure_reason')}")
            await _download_binary(video_url, dest_path)

        else:
            raise RuntimeError(f"Direct AI video generation not natively mapped for provider '{pid}'.")

    if not dest_path.exists() or dest_path.stat().st_size < 10_000:
        raise RuntimeError("Generated video clip is empty or corrupt.")
    return dest_path
              
