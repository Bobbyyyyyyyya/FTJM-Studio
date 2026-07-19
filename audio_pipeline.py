import gc
import os
import sys
import time
import threading
import numpy as np
import scipy.io.wavfile as wavfile
import scipy.signal as signal

MLX_DIR = os.path.join(os.path.dirname(__file__), "musicgen-mlx")
if MLX_DIR not in sys.path:
    sys.path.insert(0, MLX_DIR)

_MLX_AVAILABLE = False
try:
    import mlx.core as mx
    _MLX_AVAILABLE = True
except ImportError:
    mx = None

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    torch = None

_backend = None

if _MLX_AVAILABLE:
    _backend = "mlx"
elif _TORCH_AVAILABLE:
    _backend = "torch"
else:
    _backend = "acestep"

_mg_model = None
_mg_model_name = None

_torch_mg_model = None
_torch_mg_model_name = None

MODEL_OPTIONS = {
    "small": "facebook/musicgen-small",
    "medium": "facebook/musicgen-medium",
    "large": "facebook/musicgen-large",
}

SONG_STYLE_KEYWORDS = {
    "pop": "pop music, catchy melody, clean production, radio-friendly",
    "rock": "rock music, electric guitar, drums, bass, energetic",
    "electronic": "electronic dance music, synthesizer, drum machine, bass drop",
    "hiphop": "hip hop beat, trap drums, 808 bass, hi-hats, rap instrumental",
    "ballad": "piano ballad, emotional, slow tempo, orchestral strings",
    "rnb": "r&b groove, smooth soul, funky bass, warm synths",
    "metal": "heavy metal, distorted guitar, aggressive drums, dark atmosphere",
    "country": "country music, acoustic guitar, steel guitar, fiddle, warm",
    "reggae": "reggae rhythm, offbeat guitar, bass-heavy, island vibe",
    "default": "music, well-produced, balanced mix, professional sound",
}


def _detect_genre(prompt):
    prompt_lower = prompt.lower()
    genre_keywords = {
        "pop": ["pop", "catchy", "mainstream", "radio"],
        "rock": ["rock", "guitar", "band", "drums", "punk"],
        "electronic": ["electronic", "edm", "techno", "house", "dance", "synth", "trance"],
        "hiphop": ["hip hop", "hip-hop", "rap", "trap", "beats"],
        "ballad": ["ballad", "slow", "emotional", "piano", "acoustic"],
        "rnb": ["r&b", "rnb", "soul", "groove", "smooth"],
        "metal": ["metal", "heavy", "death", "thrash"],
        "country": ["country", "folk", "twang"],
        "reggae": ["reggae", "ska", "island"],
    }
    scores = {}
    for genre, keywords in genre_keywords.items():
        scores[genre] = sum(1 for kw in keywords if kw in prompt_lower)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "default"
    return best


def _build_instrumental_prompt(user_prompt):
    genre = _detect_genre(user_prompt)
    genre_style = SONG_STYLE_KEYWORDS.get(genre, SONG_STYLE_KEYWORDS["default"])

    instrumental_prompt = (
        f"{user_prompt}, {genre_style}, "
        f"professional production, high quality, full arrangement"
    )

    return instrumental_prompt


def _postprocess_audio(audio_arr, sample_rate):
    if audio_arr.ndim == 1:
        audio_arr = audio_arr[:, None]

    nyq = sample_rate / 2

    high_freq = max(0.001, min(30 / nyq, 0.999))
    b, a = signal.butter(4, high_freq, btype='high')
    for ch in range(audio_arr.shape[1]):
        audio_arr[:, ch] = signal.filtfilt(b, a, audio_arr[:, ch])

    low_freq = max(0.001, min(16000 / nyq, 0.999))
    b_low, a_low = signal.butter(2, low_freq, btype='low')
    for ch in range(audio_arr.shape[1]):
        audio_arr[:, ch] = signal.filtfilt(b_low, a_low, audio_arr[:, ch])

    attack = int(0.005 * sample_rate)
    release = int(0.03 * sample_rate)

    for ch in range(audio_arr.shape[1]):
        channel = audio_arr[:, ch]
        frame_size = int(0.05 * sample_rate)
        rms = np.sqrt(np.convolve(channel**2, np.ones(frame_size)/frame_size, mode='same'))
        silent = rms < 0.01

        transitions = np.diff(silent.astype(np.int8))
        fade_in_starts = np.where(transitions == -1)[0]
        fade_out_ends = np.where(transitions == 1)[0]

        for idx in fade_in_starts:
            fade_end = min(idx + attack, len(channel))
            channel[idx:fade_end] *= np.linspace(1, 0, fade_end - idx)

        for idx in fade_out_ends:
            fade_start = max(idx - release, 0)
            channel[fade_start:idx] *= np.linspace(0, 1, idx - fade_start)

    peak = np.max(np.abs(audio_arr))
    if peak > 0:
        audio_arr = audio_arr / peak * 0.95

    rms = np.sqrt(np.mean(audio_arr**2))
    if rms > 0:
        gain = min(0.2 / rms, 3.0)
        audio_arr = audio_arr * gain

    peak = np.max(np.abs(audio_arr))
    if peak > 1.0:
        audio_arr = audio_arr / peak

    return audio_arr


# ────────────────────────────────────────────────────────
# MLX Backend (Apple Silicon)
# ────────────────────────────────────────────────────────

def _load_model_mlx(name="small"):
    global _mg_model, _mg_model_name
    if _mg_model is not None and _mg_model_name == name:
        return _mg_model

    if _mg_model is not None:
        del _mg_model
        _mg_model = None
        gc.collect()
        mx.clear_cache()

    from audiocraft_mlx.models.musicgen import MusicGen

    model_id = MODEL_OPTIONS.get(name, name)
    print(f"[Audio] Laden {model_id} (MLX)...")
    _mg_model = MusicGen.get_pretrained(model_id)
    _mg_model_name = name
    gc.collect()
    return _mg_model


def generate_audio_mlx(prompt, duration_seconds=10, guidance_scale=3.0,
                       seed=None, model="small", progress_callback=None):
    mg = _load_model_mlx(model)

    if progress_callback:
        progress_callback(5)

    if seed is not None:
        mx.random.seed(seed)

    max_dur = mg.max_duration or 30.0

    print(f"[Audio] Genereren ({duration_seconds}s, guidance={guidance_scale})...")

    if progress_callback:
        progress_callback(10)

    def _progress(generated, total):
        if progress_callback:
            if total <= 100:
                pct = generated
            else:
                pct = min(10 + int(85 * generated / total), 95)
            progress_callback(pct)

    mg.set_generation_params(
        duration=duration_seconds,
        cfg_coef=guidance_scale,
        use_sampling=True,
        top_k=150,
        temperature=0.7,
    )
    mg.set_custom_progress_callback(_progress)

    audio = mg.generate([prompt], progress=True)

    if progress_callback:
        progress_callback(98)

    audio_arr = np.array(audio[0])
    if audio_arr.ndim == 2:
        audio_arr = audio_arr.T
    del audio

    audio_arr = _postprocess_audio(audio_arr, mg.sample_rate)

    if progress_callback:
        progress_callback(100)

    sample_rate = mg.sample_rate
    gc.collect()
    mx.clear_cache()
    return audio_arr, sample_rate


# ────────────────────────────────────────────────────────
# PyTorch Backend (Windows/Linux/macOS fallback)
# ────────────────────────────────────────────────────────

def _load_model_torch(name="small"):
    global _torch_mg_model, _torch_mg_model_name
    if _torch_mg_model is not None and _torch_mg_model_name == name:
        return _torch_mg_model

    if _torch_mg_model is not None:
        del _torch_mg_model
        _torch_mg_model = None
        gc.collect()

    from audiocraft.models.musicgen import MusicGen

    model_id = MODEL_OPTIONS.get(name, name)
    print(f"[Audio] Laden {model_id} (PyTorch)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    _torch_mg_model = MusicGen.get_pretrained(model_id)
    _torch_mg_model.to(device)
    _torch_mg_model_name = name
    gc.collect()
    return _torch_mg_model


def generate_audio_torch(prompt, duration_seconds=10, guidance_scale=3.0,
                         seed=None, model="small", progress_callback=None):
    mg = _load_model_torch(model)

    if progress_callback:
        progress_callback(5)

    if seed is not None:
        torch.manual_seed(seed)

    max_dur = mg.max_duration or 30.0

    print(f"[Audio] Genereren ({duration_seconds}s, guidance={guidance_scale})...")

    if progress_callback:
        progress_callback(10)

    def _progress(generated, total):
        if progress_callback:
            if total <= 100:
                pct = generated
            else:
                pct = min(10 + int(85 * generated / total), 95)
            progress_callback(pct)

    mg.set_generation_params(
        duration=duration_seconds,
        cfg_coef=guidance_scale,
        use_sampling=True,
        top_k=150,
        temperature=0.7,
    )
    mg.set_custom_progress_callback(_progress)

    audio = mg.generate([prompt], progress=True)

    if progress_callback:
        progress_callback(98)

    audio_arr = np.array(audio[0])
    if audio_arr.ndim == 2:
        audio_arr = audio_arr.T
    del audio

    audio_arr = _postprocess_audio(audio_arr, mg.sample_rate)

    if progress_callback:
        progress_callback(100)

    sample_rate = mg.sample_rate
    gc.collect()
    return audio_arr, sample_rate


# ────────────────────────────────────────────────────────
# ACE-Step Backend (fallback)
# ────────────────────────────────────────────────────────

def _load_acestep():
    from acestep_backend import text_to_audio as acestep_text_to_audio
    return acestep_text_to_audio


# ────────────────────────────────────────────────────────
# Publieke interface (compatibel met beide backends)
# ────────────────────────────────────────────────────────

def generate_audio(prompt, duration_seconds=10, guidance_scale=3.0,
                   seed=None, model="small", progress_callback=None):
    if _backend == "mlx":
        return generate_audio_mlx(
            prompt=prompt,
            duration_seconds=duration_seconds,
            guidance_scale=guidance_scale,
            seed=seed,
            model=model,
            progress_callback=progress_callback,
        )
    elif _backend == "torch":
        return generate_audio_torch(
            prompt=prompt,
            duration_seconds=duration_seconds,
            guidance_scale=guidance_scale,
            seed=seed,
            model=model,
            progress_callback=progress_callback,
        )
    else:
        from acestep_backend import generate_audio as acestep_gen
        return acestep_gen(
            prompt=prompt,
            duration_seconds=duration_seconds,
            progress_callback=progress_callback,
        )


def text_to_audio(prompt, duration_seconds=10, guidance_scale=3.0,
                  seed=None, model="small", output_dir="output",
                  progress_callback=None):
    os.makedirs(output_dir, exist_ok=True)

    backend_label = {"mlx": "MusicGen MLX", "torch": "MusicGen PyTorch", "acestep": "ACE-Step 1.5"}[_backend]
    print("=" * 60)
    print(f"TEXT-TO-AUDIO ({backend_label})")
    print("=" * 60)
    print(f"Prompt:  {prompt}")
    print(f"Duration: {duration_seconds}s")
    print()

    if progress_callback:
        progress_callback(0)

    instrumental_prompt = _build_instrumental_prompt(prompt)

    print(f"[Audio] Instrumental prompt: {instrumental_prompt}")

    if _backend == "mlx":
        audio_arr, sample_rate = generate_audio_mlx(
            prompt=instrumental_prompt,
            duration_seconds=duration_seconds,
            guidance_scale=guidance_scale,
            seed=seed,
            model=model,
            progress_callback=progress_callback,
        )
    elif _backend == "torch":
        audio_arr, sample_rate = generate_audio_torch(
            prompt=instrumental_prompt,
            duration_seconds=duration_seconds,
            guidance_scale=guidance_scale,
            seed=seed,
            model=model,
            progress_callback=progress_callback,
        )
    else:
        from acestep_backend import text_to_audio as acestep_text_to_audio
        return acestep_text_to_audio(
            prompt=instrumental_prompt,
            duration_seconds=duration_seconds,
            guidance_scale=guidance_scale,
            seed=seed,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )

    if progress_callback:
        progress_callback(100)

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_slug = prompt[:30].replace(" ", "_").lower()
    filename = f"audio_{timestamp}_{prompt_slug}.wav"
    audio_path = os.path.join(output_dir, filename)
    wavfile.write(audio_path, sample_rate, audio_arr)
    print(f"  -> Audio: {audio_path} ({len(audio_arr)/sample_rate:.1f}s, {sample_rate}Hz)")

    return audio_path, audio_arr, sample_rate
