# ==============================================================================
# AI Video Production Studio - Audio DSP Beat-Sync & Dubbing Engine (Part C4)
# Covers: FFmpeg PCM Extraction, NumPy/SciPy Bass-Drop & Treble Peak Analyzer,
#         BPM Detection, Multi-Provider TTS & Bangla/Hindi/EN Neural Dubbing
# ==============================================================================

from __future__ import annotations

import asyncio
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

import edge_tts
import httpx
import numpy as np
from scipy.signal import butter, find_peaks, lfilter

from app.config import TEMP_DIR
from app.models import AgentSlot, BeatEnergyMap


# ------------------------------------------------------------------------------
# 1. AUDIO DURATION PROBE & WAV EXTRACTION VIA FFMPEG
# ------------------------------------------------------------------------------
def probe_media_duration(media_path: Path) -> float:
    """Return exact duration in seconds of any audio or video file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=15).decode().strip()
        return round(float(out), 3)
    except Exception:
        return 0.0


def _decode_to_mono_pcm(audio_path: Path, sample_rate: int = 22050) -> np.ndarray:
    """Convert any audio/video file into a normalized float32 mono waveform array."""
    wav_tmp = TEMP_DIR / f"pcm_{uuid.uuid4().hex[:8]}.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "wav",
        str(wav_tmp),
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=45)
        with wave.open(str(wav_tmp), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        return samples
    finally:
        if wav_tmp.exists():
            wav_tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------------------
# 2. DSP FREQUENCY ANALYZER (BASS DROPS, TREBLE PEAKS & BPM MAP)
# ------------------------------------------------------------------------------
def _butter_bandpass(samples: np.ndarray, lowcut: float, highcut: float, fs: int) -> np.ndarray:
    """Apply zero-hassle Butterworth bandpass filter for bass vs treble isolation."""
    nyq = 0.5 * fs
    low = max(0.001, lowcut / nyq)
    high = min(0.99, highcut / nyq)
    b, a = butter(3, [low, high], btype="band")
    return lfilter(b, a, samples)


def analyze_audio_beats_sync(audio_path: Path) -> BeatEnergyMap:
    """
    Analyze music/audio waveform to extract:
      - Exact BPM tempo
      - Beat timestamps
      - Heavy Bass-Drop timestamps (20Hz - 160Hz) for dramatic zoom/cut hits
      - High Treble-Peak timestamps (2500Hz - 8000Hz) for flash/spark transitions
      - Per-second energy curve
    """
    fs = 22050
    samples = _decode_to_mono_pcm(audio_path, sample_rate=fs)
    if samples.size < fs:
        return BeatEnergyMap(bpm=120.0, duration_sec=round(samples.size / fs, 2))

    duration_sec = round(samples.size / fs, 2)
    hop = 512  # ~23.2ms per envelope frame
    frame_rate = fs / hop

    # Isolate Bass (20-160Hz) and Treble (2500-8000Hz)
    bass_sig = _butter_bandpass(samples, 20.0, 160.0, fs)
    treble_sig = _butter_bandpass(samples, 2500.0, 8000.0, fs)

    n_frames = len(samples) // hop
    trimmed = samples[: n_frames * hop].reshape(n_frames, hop)
    bass_trimmed = bass_sig[: n_frames * hop].reshape(n_frames, hop)
    treble_trimmed = treble_sig[: n_frames * hop].reshape(n_frames, hop)

    rms_total = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-9)
    rms_bass = np.sqrt(np.mean(bass_trimmed ** 2, axis=1) + 1e-9)
    rms_treble = np.sqrt(np.mean(treble_trimmed ** 2, axis=1) + 1e-9)

    # Onset strength (positive energy flux)
    onset_all = np.maximum(0.0, np.diff(rms_total, prepend=rms_total[0]))
    onset_bass = np.maximum(0.0, np.diff(rms_bass, prepend=rms_bass[0]))
    onset_treble = np.maximum(0.0, np.diff(rms_treble, prepend=rms_treble[0]))

    min_dist = int(frame_rate * 0.32)  # minimum 320ms between beats
    beat_peaks, _ = find_peaks(onset_all, distance=min_dist, prominence=np.percentile(onset_all, 75))
    bass_peaks, _ = find_peaks(onset_bass, distance=int(frame_rate * 0.8), prominence=np.percentile(onset_bass, 85))
    treble_peaks, _ = find_peaks(onset_treble, distance=int(frame_rate * 0.6), prominence=np.percentile(onset_treble, 85))

    beat_times = [round(float(p / frame_rate), 3) for p in beat_peaks]
    bass_times = [round(float(p / frame_rate), 3) for p in bass_peaks]
    treble_times = [round(float(p / frame_rate), 3) for p in treble_peaks]

    # Estimate BPM from median inter-beat interval
    bpm = 120.0
    if len(beat_times) >= 4:
        intervals = np.diff(beat_times)
        valid = intervals[(intervals >= 0.28) & (intervals <= 1.2)]
        if valid.size > 0:
            bpm = round(float(60.0 / np.median(valid)), 1)
            while bpm < 70:
                bpm *= 2
            while bpm > 175:
                bpm /= 2

    # Build 1-second energy timeline
    sec_step = max(1, int(frame_rate))
    energy_curve: List[Dict[str, float]] = []
    max_e = float(np.max(rms_total)) or 1.0
    for idx in range(0, n_frames, sec_step):
        energy_curve.append({
            "sec": round(idx / frame_rate, 1),
            "energy": round(float(np.mean(rms_total[idx : idx + sec_step]) / max_e), 3),
        })

    mood = "high_energy_drop" if len(bass_times) >= 4 and bpm >= 115 else "cinematic_melodic"
    return BeatEnergyMap(
        bpm=bpm,
        duration_sec=duration_sec,
        beat_timestamps=beat_times[:120],
        bass_drop_timestamps=bass_times[:40],
        treble_peak_timestamps=treble_times[:40],
        energy_curve=energy_curve[:90],
        mood_summary=mood,
    )


async def analyze_audio_beats(audio_path: Path) -> BeatEnergyMap:
    """Async wrapper for DSP beat and frequency analysis."""
    return await asyncio.to_thread(analyze_audio_beats_sync, audio_path)
  # ------------------------------------------------------------------------------
# 3. MULTI-PROVIDER NEURAL TTS & MULTI-LINGUAL DUBBING ENGINE (VERIFIED)
# ------------------------------------------------------------------------------
async def _synthesize_edge_tts(
    text: str,
    voice: str,
    out_path: Path,
    rate: str = "+0%",
) -> Path:
    """High-clarity neural speech synthesis using Edge-TTS with safe voice fallback."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_voice = (voice or "bn-IN-BashkarNeural").strip()
    try:
        communicate = edge_tts.Communicate(text=text, voice=safe_voice, rate=rate)
        await communicate.save(str(out_path))
        if out_path.exists() and out_path.stat().st_size > 512:
            return out_path
    except Exception:
        pass

    # Fallback to universally available English/Neural voice if selected voice fails
    fallback_voice = "en-US-GuyNeural" if safe_voice != "en-US-GuyNeural" else "bn-IN-BashkarNeural"
    communicate = edge_tts.Communicate(text=text, voice=fallback_voice, rate=rate)
    await communicate.save(str(out_path))
    return out_path


async def _synthesize_elevenlabs(
    slot: AgentSlot,
    text: str,
    out_path: Path,
) -> Path:
    """Synthesize expressive multilingual voice via ElevenLabs API."""
    voice_id = "21m00Tcm4TlvDq8ikWAM"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": slot.api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": slot.model_id or "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=12.0)) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        if len(resp.content) < 512:
            raise RuntimeError("ElevenLabs returned empty audio bytes.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
    return out_path


async def _synthesize_openai_tts(
    slot: AgentSlot,
    text: str,
    out_path: Path,
) -> Path:
    """Synthesize studio voice via OpenAI /v1/audio/speech."""
    base_url = (slot.base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/audio/speech"
    headers = {
        "Authorization": f"Bearer {slot.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": slot.model_id or "tts-1",
        "voice": "onyx",
        "input": text,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=12.0)) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        if len(resp.content) < 512:
            raise RuntimeError("OpenAI TTS returned empty audio bytes.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
    return out_path


async def generate_narration_audio(
    text: str,
    voice_profile: str = "bn-IN-BashkarNeural",
    audio_slot: Optional[AgentSlot] = None,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Generate voiceover/dubbing audio using the active Audio Agent slot if available
    (ElevenLabs / OpenAI), with automatic fallback to Edge-TTS neural voices so
    narration never stalls.
    Returns: {"path": Optional[Path], "duration_sec": float, "engine": str}
    """
    clean_text = (text or "").strip()
    save_dir = out_dir or TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    out_path = save_dir / f"nar_{uuid.uuid4().hex[:10]}.mp3"

    if not clean_text:
        return {"path": None, "duration_sec": 0.0, "engine": "none"}

    used_engine = "edge_tts"
    try:
        if audio_slot and audio_slot.api_key:
            try:
                if audio_slot.provider_id == "elevenlabs":
                    await _synthesize_elevenlabs(audio_slot, clean_text, out_path)
                    used_engine = "elevenlabs"
                elif audio_slot.provider_id == "openai" and "tts" in audio_slot.model_id.lower():
                    await _synthesize_openai_tts(audio_slot, clean_text, out_path)
                    used_engine = "openai_tts"
                else:
                    await _synthesize_edge_tts(clean_text, voice_profile, out_path)
            except Exception:
                await _synthesize_edge_tts(clean_text, voice_profile, out_path)
                used_engine = "edge_tts_fallback"
        else:
            await _synthesize_edge_tts(clean_text, voice_profile, out_path)
    except Exception:
        return {
            "path": None,
            "duration_sec": max(2.5, len(clean_text.split()) * 0.42),
            "engine": "silent_fallback",
        }

    dur = await asyncio.to_thread(probe_media_duration, out_path)
    valid_path = out_path if (out_path.exists() and out_path.stat().st_size > 512) else None
    return {
        "path": valid_path,
        "duration_sec": dur if dur > 0 else max(2.5, len(clean_text.split()) * 0.42),
        "engine": used_engine if valid_path else "silent_fallback",
  }
  
