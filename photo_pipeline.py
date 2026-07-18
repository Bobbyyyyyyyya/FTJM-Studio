import torch
import gc
import os
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
from PIL import Image
import numpy as np

os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

_cached_device = None


def get_device():
    global _cached_device
    if _cached_device is None:
        if torch.cuda.is_available():
            _cached_device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            _cached_device = "mps"
        else:
            _cached_device = "cpu"
    return _cached_device


def free_memory(device):
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


_pipes = {}

MODEL_OPTIONS = {
    "sd15": {
        "id": "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "name": "Stable Diffusion 1.5",
    },
    "sdxl": {
        "id": "stabilityai/stable-diffusion-xl-base-1.0",
        "name": "Stable Diffusion XL",
    },
}


def _load_pipe(model="sd15", device=None):
    global _pipes
    if model in _pipes:
        return _pipes[model]
    if device is None:
        device = get_device()
    dtype = torch.float16
    info = MODEL_OPTIONS.get(model, MODEL_OPTIONS["sd15"])
    model_id = info["id"]

    if model in _pipes:
        del _pipes[model]
        gc.collect()
        if device == "mps":
            torch.mps.empty_cache()

    print(f"[Photo] Laden {info['name']} ({device}, {dtype})...")
    pipe = StableDiffusionPipeline.from_pretrained(
        model_id, torch_dtype=dtype,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()
    if model == "sdxl":
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    _pipes[model] = pipe
    return pipe


def generate_photo(
    prompt,
    negative_prompt=None,
    width=512,
    height=512,
    num_inference_steps=30,
    guidance_scale=10.0,
    seed=None,
    model="sd15",
    device=None,
    progress_callback=None,
):
    if device is None:
        device = get_device()

    pipe = _load_pipe(model, device)

    if negative_prompt is None:
        negative_prompt = (
            "low quality, blurry, deformed, ugly, bad quality, distorted, "
            " watermark, text, logo, signature, extra fingers, mutated hands, "
            " poorly drawn hands, poorly drawn face, mutation, deformed, "
            " ugly, duplicate, morbid, mutilated, extra limbs, gross proportions, "
            " missing arms, missing legs, floating limbs, disconnected limbs, "
            " malformed limbs, blurry, out of focus, jpeg artifacts, "
            " multiple cats, multiple animals, merged, fused, extra heads"
        )

    enhanced = prompt + ", high quality"
    words = enhanced.split()
    if len(words) > 40:
        enhanced = " ".join(words[:40])

    free_memory(device)

    if seed is not None:
        torch.manual_seed(seed)
        if device == "mps":
            torch.mps.manual_seed(seed)
        generator = torch.Generator(device="cpu").manual_seed(seed)
    else:
        generator = None

    print(f"[Photo] Genereren ({width}x{height}, {num_inference_steps} stappen)...")
    print(f"[Photo] Prompt: {enhanced}")

    def _callback(pipe, i, t, callback_kwargs):
        pct = int((i + 1) / num_inference_steps * 100)
        preview = None
        if progress_callback and callback_kwargs.get("latents") is not None:
            every_n = max(1, num_inference_steps // 6)
            if (i + 1) % every_n == 0 or i == num_inference_steps - 1:
                try:
                    latents = callback_kwargs["latents"]
                    latents = 1 / 0.18215 * latents
                    with torch.no_grad():
                        decoded = pipe.vae.decode(latents).sample
                    decoded = (decoded / 2 + 0.5).clamp(0, 1)
                    decoded = decoded.cpu().permute(0, 2, 3, 1).float().numpy()
                    img = Image.fromarray((decoded[0] * 255).round().astype(np.uint8))
                    img.thumbnail((256, 256))
                except Exception:
                    img = None
                preview = img
        if progress_callback:
            progress_callback(pct, preview)
        return callback_kwargs

    try:
        result = pipe(
            prompt=enhanced,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator,
            callback_on_step_end=_callback,
            callback_on_step_end_tensor_inputs=["latents"],
        )
        if result is None or not hasattr(result, 'images') or not result.images:
            raise RuntimeError("Model kon geen afbeelding genereren")
        image = result.images[0]
    except Exception as e:
        print(f"[Photo] Fout bij genereren: {e}")
        if model == "sdxl":
            print("[Photo] SDXL gefaald, fallback naar SD 1.5...")
            del _pipes["sdxl"]
            gc.collect()
            return generate_photo(
                prompt=prompt, negative_prompt=negative_prompt,
                width=width, height=height,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale, seed=seed,
                model="sd15", device=device,
                progress_callback=progress_callback,
            )
        raise

    return image


def text_to_photo(
    prompt,
    negative_prompt=None,
    width=512,
    height=512,
    num_inference_steps=30,
    guidance_scale=10.0,
    seed=None,
    model="sd15",
    output_dir="output",
    progress_callback=None,
):
    device = get_device()
    os.makedirs(output_dir, exist_ok=True)

    info = MODEL_OPTIONS.get(model, MODEL_OPTIONS["sd15"])
    print("=" * 50)
    print(f"TEXT-TO-PHOTO ({info['name']})")
    print("=" * 50)
    print(f"Device:  {device}")
    print(f"Prompt:  {prompt}")
    print(f"Size:    {width}x{height}")
    print(f"Steps:   {num_inference_steps}")
    print()

    if progress_callback:
        progress_callback(0)

    image = generate_photo(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        seed=seed,
        model=model,
        device=device,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(100)

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_slug = prompt[:30].replace(" ", "_").lower()
    filename = f"photo_{timestamp}_{prompt_slug}.png"
    photo_path = os.path.join(output_dir, filename)
    image.save(photo_path)
    print(f"  -> Photo: {photo_path}")

    return photo_path, image
