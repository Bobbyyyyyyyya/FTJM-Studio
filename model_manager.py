"""
Centraal model management systeem.
Biedt overzicht van alle AI modellen, hun status en卸载 functionaliteit.
"""
import os
import platform
import shutil
from pathlib import Path

HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
LLM_DIR = Path("models/llm")
ACESTEP_DIR = Path("ACE-Step-1.5")
_dir_size_cache = {}

_IS_APPLE_SILICON = platform.system() == "Darwin" and platform.machine() == "arm64"

MODELS = [
    {
        "id": "sd15",
        "name": "FTJM Flash",
        "description": "Foto generatie - snel & licht",
        "category": "photo",
        "hf_repo": "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "size_gb": 5.0,
    },
    {
        "id": "sdxl",
        "name": "FTJM Ultra",
        "description": "Foto generatie - hoge kwaliteit",
        "category": "photo",
        "hf_repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "size_gb": 27.0,
    },
    {
        "id": "animatediff",
        "name": "FTJM Motion",
        "description": "Video generatie - standaard",
        "category": "video",
        "hf_repo": "guoyww/animatediff-motion-adapter-v1-5-3",
        "size_gb": 7.0,
    },
    {
        "id": "animatediff_lightning",
        "name": "FTJM Lightning",
        "description": "Video generatie - supersnel",
        "category": "video",
        "hf_repo": "ByteDance/AnimateDiff-Lightning",
        "size_gb": 2.0,
    },
    {
        "id": "musicgen_small",
        "name": "FTJM Beat Mini",
        "description": "Muziek generatie - compact",
        "category": "audio",
        "hf_repo": "facebook/musicgen-small",
        "size_gb": 2.0,
    },
    {
        "id": "musicgen_medium",
        "name": "FTJM Beat",
        "description": "Muziek generatie - gebalanceerd",
        "category": "audio",
        "hf_repo": "facebook/musicgen-medium",
        "size_gb": 7.5,
    },
    {
        "id": "musicgen_large",
        "name": "FTJM Beat Pro",
        "description": "Muziek generatie - premium kwaliteit",
        "category": "audio",
        "hf_repo": "facebook/musicgen-large",
        "size_gb": 12.0,
    },
    {
        "id": "acestep_1_5",
        "name": "FTJM Music",
        "description": "Muziek generatie - songs met vocals (Windows/Linux/macOS)",
        "category": "audio",
        "hf_repo": "ACE-Step/Ace-Step1.5",
        "size_gb": 5.0,
        "platforms": ["win32", "linux", "darwin"],
    },
    {
        "id": "llm_small",
        "name": "FTJM Chat Mini",
        "description": "Chat LLM - snel & efficiënt",
        "category": "chat",
        "hf_repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "llm_file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_gb": 1.0,
    },
    {
        "id": "llm_medium",
        "name": "FTJM Chat",
        "description": "Chat LLM - gebalanceerd",
        "category": "chat",
        "hf_repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "llm_file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_gb": 1.8,
    },
    {
        "id": "llm_large",
        "name": "FTJM Chat Pro",
        "description": "Chat LLM - beste kwaliteit",
        "category": "chat",
        "hf_repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "llm_file": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size_gb": 2.2,
    },
]


def _get_hf_cache_path(hf_repo):
    """Converteer HF repo naar cache pad."""
    cache_name = "models--" + hf_repo.replace("/", "--")
    return HF_CACHE / cache_name


def _get_dir_size_gb(path):
    """Bereken grootte van een map in GB (gecached)."""
    path_str = str(path)
    if path_str in _dir_size_cache:
        return _dir_size_cache[path_str]
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except (OSError, ValueError):
                pass
    result = round(total / (1024**3), 2)
    _dir_size_cache[path_str] = result
    return result


def _get_file_size_gb(filepath):
    """Bereken grootte van een bestand in GB."""
    try:
        return round(os.path.getsize(filepath) / (1024**3), 2)
    except (OSError, ValueError):
        return 0


def is_model_installed(model_id):
    """Controleer of een model geinstalleerd is."""
    model = next((m for m in MODELS if m["id"] == model_id), None)
    if not model:
        return False

    if model_id == "acestep_1_5":
        return ACESTEP_DIR.exists() and (ACESTEP_DIR / "pyproject.toml").exists()

    if "llm_file" in model:
        llm_path = LLM_DIR / model["llm_file"]
        return llm_path.exists()

    cache_path = _get_hf_cache_path(model["hf_repo"])
    if not cache_path.exists():
        return False

    snapshots = cache_path / "snapshots"
    if snapshots.exists():
        for snap in snapshots.iterdir():
            if any(snap.iterdir()):
                return True
    return False


def get_model_size(model_id):
    """Krijg de daadwerkelijke grootte van een geinstalleerd model."""
    model = next((m for m in MODELS if m["id"] == model_id), None)
    if not model:
        return 0

    if model_id == "acestep_1_5":
        if ACESTEP_DIR.exists():
            return _get_dir_size_gb(ACESTEP_DIR)
        return 0

    if "llm_file" in model:
        llm_path = LLM_DIR / model["llm_file"]
        if llm_path.exists():
            return _get_file_size_gb(llm_path)
        return 0

    cache_path = _get_hf_cache_path(model["hf_repo"])
    if cache_path.exists():
        return _get_dir_size_gb(cache_path)
    return 0


def get_all_models():
    """Krijg status van alle modellen (gefilterd op platform)."""
    current_platform = platform.system().lower()
    if current_platform == "darwin":
        current_platform = "darwin"
    elif current_platform == "windows":
        current_platform = "win32"
    elif current_platform == "linux":
        current_platform = "linux"

    result = []
    for model in MODELS:
        supported_platforms = model.get("platforms", None)
        if supported_platforms and current_platform not in supported_platforms:
            continue

        installed = is_model_installed(model["id"])
        actual_size = get_model_size(model["id"]) if installed else 0
        result.append({
            "id": model["id"],
            "name": model["name"],
            "description": model["description"],
            "category": model["category"],
            "installed": installed,
            "estimated_size_gb": model["size_gb"],
            "actual_size_gb": actual_size,
        })
    return result


def uninstall_model(model_id):
    """Verwijder een model van schijf."""
    model = next((m for m in MODELS if m["id"] == model_id), None)
    if not model:
        return {"success": False, "error": f"Onbekend model: {model_id}"}

    if not is_model_installed(model_id):
        return {"success": False, "error": f"Model {model['name']} is niet geinstalleerd"}

    freed = get_model_size(model_id)

    if model_id == "acestep_1_5":
        if ACESTEP_DIR.exists():
            shutil.rmtree(ACESTEP_DIR)
    elif "llm_file" in model:
        llm_path = LLM_DIR / model["llm_file"]
        if llm_path.exists():
            llm_path.unlink()
    else:
        cache_path = _get_hf_cache_path(model["hf_repo"])
        if cache_path.exists():
            shutil.rmtree(cache_path)
            _dir_size_cache.pop(str(cache_path), None)

    return {
        "success": True,
        "message": f"{model['name']} verwijderd ({freed} GB vrijgemaakt)",
        "freed_gb": freed,
    }
