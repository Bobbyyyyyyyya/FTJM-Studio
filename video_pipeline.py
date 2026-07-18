import gc
import os
import numpy as np
import torch
from PIL import Image

_video_pipe = None
_motion_adapter = None
_video_model_name = None
_video_adapter_name = None

ADAPTER_OPTIONS = {
    "fast": "ByteDance/AnimateDiff-Lightning",
    "quality": "guoyww/animatediff-motion-adapter-v1-5-3",
}

MODEL_OPTIONS = {
    "small": "stable-diffusion-v1-5/stable-diffusion-v1-5",
    "large": "stabilityai/stable-diffusion-xl-base-1.0",
}


def _get_device():
    if torch.cuda.is_available():
        return "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _free_video_memory():
    global _video_pipe, _motion_adapter
    if _video_pipe is not None:
        del _video_pipe
        _video_pipe = None
    if _motion_adapter is not None:
        del _motion_adapter
        _motion_adapter = None
    gc.collect()
    device = _get_device()
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


def _load_video_pipeline(adapter_name="fast", model_name="small", progress_callback=None):
    global _video_pipe, _motion_adapter, _video_model_name, _video_adapter_name

    if (_video_pipe is not None and _video_model_name == model_name
            and _video_adapter_name == adapter_name):
        return _video_pipe

    if _video_pipe is not None:
        _free_video_memory()

    from diffusers import AnimateDiffPipeline, MotionAdapter, DDIMScheduler

    adapter_id = ADAPTER_OPTIONS.get(adapter_name, ADAPTER_OPTIONS["fast"])

    if progress_callback:
        progress_callback(5, "Motion adapter laden...")

    print(f"[Video] Laden motion adapter: {adapter_id}")
    _motion_adapter = MotionAdapter.from_pretrained(
        adapter_id,
        torch_dtype=torch.float16,
    )

    model_id = MODEL_OPTIONS.get(model_name, MODEL_OPTIONS["small"])

    if progress_callback:
        progress_callback(20, "Video model laden...")

    print(f"[Video] Laden model: {model_id}")
    _video_pipe = AnimateDiffPipeline.from_pretrained(
        model_id,
        motion_adapter=_motion_adapter,
        torch_dtype=torch.float16,
    )

    _video_pipe.scheduler = DDIMScheduler.from_config(
        _video_pipe.scheduler.config,
        clip_sample=False,
        timestep_spacing="linspace",
        beta_schedule="linear",
        steps_offset=1,
    )

    device = _get_device()
    print(f"[Video] Model laden ({device} float16)...")
    _video_pipe.enable_attention_slicing("max")

    try:
        _video_pipe.enable_vae_slicing()
    except Exception:
        pass

    _video_pipe = _video_pipe.to(device)
    _video_model_name = model_name
    _video_adapter_name = adapter_name

    if progress_callback:
        progress_callback(60, "Model geladen!")

    gc.collect()
    return _video_pipe


def generate_video(
    prompt,
    negative_prompt=None,
    num_frames=8,
    num_inference_steps=4,
    guidance_scale=2.0,
    fps=8,
    width=384,
    height=384,
    seed=None,
    adapter="fast",
    model="small",
    progress_callback=None,
):
    pipe = _load_video_pipeline(adapter, model, progress_callback)

    if progress_callback:
        progress_callback(65, "Video genereren...")

    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(seed)

    if negative_prompt is None:
        negative_prompt = "low quality, blurry, distorted, deformed, bad anatomy"

    print(f"[Video] Genereren: '{prompt}' ({num_frames} frames, {num_inference_steps} steps)")

    import io as _io
    import base64 as _b64

    def _video_callback(pipe, i, t, callback_kwargs):
        if progress_callback and callback_kwargs.get("latents") is not None:
            every_n = max(1, num_inference_steps // 4)
            if (i + 1) % every_n == 0 or i == num_inference_steps - 1:
                try:
                    latents = callback_kwargs["latents"]
                    decoded = pipe.vae.decode(latents / 0.18215).sample
                    decoded = (decoded / 2 + 0.5).clamp(0, 1)
                    decoded = decoded.cpu().permute(0, 2, 3, 1).float().numpy()
                    frame = Image.fromarray((decoded[0] * 255).round().astype(np.uint8))
                    frame.thumbnail((256, 256))
                    progress_callback(
                        65 + int((i + 1) / num_inference_steps * 30),
                        None,
                        frame,
                    )
                except Exception:
                    pass
        return callback_kwargs

    output = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        width=width,
        height=height,
        generator=generator,
        callback_on_step_end=_video_callback,
        callback_on_step_end_tensor_inputs=["latents"],
    )

    frames = output.frames[0]

    del output
    gc.collect()

    if progress_callback:
        progress_callback(95, "Video opslaan...")

    print(f"[Video] {len(frames)} frames gegenereerd")

    return frames, fps


def _ensure_uint8(frame):
    if isinstance(frame, np.ndarray):
        if frame.dtype != np.uint8:
            return (frame * 255).astype(np.uint8)
        return frame
    return np.array(frame)


def save_video(frames, fps, output_path):
    import imageio

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    frames_np = [_ensure_uint8(f) for f in frames]
    ext = os.path.splitext(output_path)[1].lower()

    if ext == ".gif":
        imageio.mimsave(output_path, frames_np, fps=fps, loop=0)
    else:
        if ext != ".mp4":
            output_path = os.path.splitext(output_path)[0] + ".mp4"
        writer = imageio.get_writer(output_path, fps=fps, codec="libx264", quality=8)
        for frame in frames_np:
            writer.append_data(frame)
        writer.close()

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[Video] Opgeslagen: {output_path} ({size_mb:.1f} MB, {len(frames)} frames @ {fps}fps)")
    return output_path


def text_to_video(
    prompt,
    negative_prompt=None,
    num_frames=8,
    num_inference_steps=4,
    guidance_scale=2.0,
    fps=8,
    width=384,
    height=384,
    seed=None,
    adapter="fast",
    model="small",
    output_dir="output",
    progress_callback=None,
):
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("TEXT-TO-VIDEO (AnimateDiff)")
    print("=" * 60)
    print(f"Prompt:  {prompt}")
    print(f"Frames:  {num_frames} @ {fps}fps")
    print()

    if progress_callback:
        progress_callback(0)

    frames, fps = generate_video(
        prompt=prompt,
        negative_prompt=negative_prompt,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        fps=fps,
        width=width,
        height=height,
        seed=seed,
        adapter=adapter,
        model=model,
        progress_callback=progress_callback,
    )

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_slug = prompt[:30].replace(" ", "_").lower()
    filename = f"video_{timestamp}_{prompt_slug}.mp4"
    video_path = os.path.join(output_dir, filename)

    video_path = save_video(frames, fps, video_path)

    if progress_callback:
        progress_callback(100)

    return video_path, len(frames), fps
