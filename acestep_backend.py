"""
ACE-Step 1.5 Backend – lokale muziekgeneratie voor Windows/Linux/macOS.
Gebruikt wanneer MLX niet beschikbaar is (geen Apple Silicon).
"""

import gc
import os
import sys
import subprocess
import importlib
import numpy as np


_acestep_model = None
_acestep_pipe = None
_acestep_loaded = False
_acestep_dir = os.path.join(os.path.dirname(__file__), "ACE-Step-1.5")


def _ensure_acestep_installed():
    """Clone en installeer ACE-Step als het niet aanwezig is."""
    if os.path.exists(_acestep_dir) and os.path.isfile(os.path.join(_acestep_dir, "pyproject.toml")):
        return _acestep_dir

    print("[ACE-Step] Niet gevonden, downloaden...")
    print("[ACE-Step] Dit kan even duren (eerste keer, ~2GB)...")

    repo_url = "https://github.com/ACE-Step/ACE-Step-1.5.git"
    result = subprocess.run(
        ["git", "clone", repo_url, _acestep_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git clone mislukt: {result.stderr}")

    print("[ACE-Step] Installeren van dependencies...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
    result = subprocess.run(
        pip_cmd, capture_output=True, text=True, cwd=_acestep_dir
    )
    if result.returncode != 0:
        print(f"[ACE-Step] Waarschuwing: {result.stderr[:300]}")

    return _acestep_dir


def _load_acestep_model(progress_callback=None):
    """Laad het ACE-Step 1.5 model."""
    global _acestep_model, _acestep_pipe, _acestep_loaded

    if _acestep_loaded:
        return

    if progress_callback:
        progress_callback(5, "ACE-Step controleren...")

    _ensure_acestep_installed()

    if progress_callback:
        progress_callback(15, "ACE-Step dependencies laden...")

    if _acestep_dir not in sys.path:
        sys.path.insert(0, _acestep_dir)

    try:
        import torch
        from acestep.acestep_v15_pipeline import ACEStepPipeline
    except ImportError as e:
        raise RuntimeError(
            f"ACE-Step dependencies niet gevonden. "
            f"Voer uit: cd {_acestep_dir} && pip install -e .\nFout: {e}"
        )

    if progress_callback:
        progress_callback(25, "ACE-Step model downloaden (eerste keer ~2GB)...")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    print(f"[ACE-Step] Model laden op {device} ({dtype})...")

    _acestep_pipe = ACEStepPipeline(
        model_name="ACE-Step/Ace-Step1.5",
        torch_dtype=dtype,
        device=device,
    )

    if progress_callback:
        progress_callback(60, "ACE-Step model geladen, voorbereiden...")

    _acestep_pipe.load()

    _acestep_loaded = True
    gc.collect()

    if progress_callback:
        progress_callback(70, "ACE-Step gereed!")


def generate_audio(prompt, duration_seconds=30, lyrics=None,
                   genre=None, progress_callback=None):
    """
    Genereer muziek met ACE-Step 1.5.

    Args:
        prompt: Tekstbeschrijving van de gewenste muziek
        duration_seconds: Duur in seconden
        lyrics: Optionele lyrics (tekst of None)
        genre: Optioneel genre
        progress_callback: Functie(progress_pct, status_msg=None)

    Returns:
        (audio_numpy, sample_rate)
    """
    if progress_callback:
        progress_callback(5, "Model laden...")

    _load_acestep_model(progress_callback)

    if progress_callback:
        progress_callback(75, "Muziek genereren...")

    import torch

    style = prompt
    if genre:
        style = f"{genre}, {prompt}"

    tag = ""
    if lyrics:
        tag = f"[verse]\n{lyrics}\n[chorus]"

    print(f"[ACE-Step] Genereren: '{style}' ({duration_seconds}s)")

    with torch.no_grad():
        result = _acestep_pipe.generate(
            prompt=style,
            lyrics=tag,
            duration=duration_seconds,
        )

    if progress_callback:
        progress_callback(90, "Audio verwerken...")

    audio = result.get("audio", None)
    sample_rate = result.get("sample_rate", 44100)

    if audio is None:
        raise RuntimeError("ACE-Step geen audio teruggegeven")

    if isinstance(audio, torch.Tensor):
        audio = audio.cpu().numpy()

    if audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
        audio = audio.T
    elif audio.ndim == 1:
        audio = audio[:, None]

    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.95

    gc.collect()

    if progress_callback:
        progress_callback(95, "Genereren voltooid!")

    return audio, sample_rate


def text_to_audio(prompt, duration_seconds=30, guidance_scale=3.0,
                  seed=None, lyrics=None, genre=None,
                  output_dir="output", progress_callback=None):
    """
    Volledige text-naar-audio pipeline met ACE-Step.
    Interface compatibel met audio_pipeline.py.

    Returns:
        (audio_path, audio_numpy, sample_rate)
    """
    import scipy.io.wavfile as wavfile
    import datetime

    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("TEXT-TO-AUDIO (ACE-Step 1.5)")
    print("=" * 60)
    print(f"Prompt:  {prompt}")
    print(f"Duration: {duration_seconds}s")
    print()

    if seed is not None:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    if progress_callback:
        progress_callback(0)

    audio_arr, sample_rate = generate_audio(
        prompt=prompt,
        duration_seconds=duration_seconds,
        lyrics=lyrics,
        genre=genre,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(100)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_slug = prompt[:30].replace(" ", "_").lower()
    filename = f"audio_{timestamp}_{prompt_slug}.wav"
    audio_path = os.path.join(output_dir, filename)

    wav_data = (audio_arr * 32767).astype(np.int16) if audio_arr.dtype != np.int16 else audio_arr
    wavfile.write(audio_path, sample_rate, wav_data)

    print(f"  -> Audio: {audio_path} ({len(audio_arr)/sample_rate:.1f}s, {sample_rate}Hz)")

    return audio_path, audio_arr, sample_rate
