#!/usr/bin/env python3
"""
Electron Backend - directe communicatie via stdin/stdout (geen HTTP server).
Leest JSON commands van stdin, schrijft results naar stdout, progress naar stderr.
"""
import gc
import json
import os
import sys
import threading
import traceback
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUTPUT_DIR = Path("output")
PHOTO_GALLERY_DIR = Path("gallery/photos")
VIDEO_GALLERY_DIR = Path("gallery/video")
AUDIO_GALLERY_DIR = Path("gallery/audio")
OUTPUT_DIR.mkdir(exist_ok=True)
PHOTO_GALLERY_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_GALLERY_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

_ai_lock = threading.Lock()
MIN_RAM_GB = 6
_executor = ThreadPoolExecutor(max_workers=4)
_active_futures = {}
_cancel_flags = {}

_TOOL_MODULES = {
    "internet_search": ("tools", "internet_search"),
    "execute_code": ("tools", "execute_code"),
    "file_read": ("tools", "file_read"),
    "file_write": ("tools", "file_write"),
    "file_list": ("tools", "file_list"),
    "run_command": ("tools", "run_command"),
    "get_system_info": ("tools", "get_system_info"),
    "get_model_status": ("tools", "get_model_status"),
    "web_fetch": ("tools", "web_fetch"),
    "gallery_list": ("tools", "gallery_list"),
}

_tool_cache = {}


def _import_tool(tool_name):
    if tool_name in _tool_cache:
        return _tool_cache[tool_name]
    module_path, func_name = _TOOL_MODULES[tool_name]
    import importlib
    mod = importlib.import_module(module_path)
    func = getattr(mod, func_name)
    _tool_cache[tool_name] = func
    return func


def check_ram():
    try:
        import psutil
        avail = psutil.virtual_memory().available / (1024**3)
        return avail >= MIN_RAM_GB, avail
    except ImportError:
        return True, 0


def send_result(data):
    print(json.dumps(data), file=sys.stdout, flush=True)


def send_progress(job_id, pct, message):
    msg = {"type": "progress", "job_id": job_id, "progress": pct, "message": message}
    print(json.dumps(msg), file=sys.stderr, flush=True)


def send_error(job_id, error):
    err_msg = {"type": "error", "job_id": job_id, "error": str(error)}
    print(json.dumps(err_msg), file=sys.stderr, flush=True)
    print(json.dumps({"job_id": job_id, "error": str(error)}), file=sys.stdout, flush=True)


def send_done(job_id, data):
    done_msg = {"type": "done", "job_id": job_id, **data}
    print(json.dumps(done_msg), file=sys.stderr, flush=True)
    print(json.dumps({"job_id": job_id, **data}), file=sys.stdout, flush=True)


def send_preview(job_id, preview_b64, media_type="photo"):
    msg = {"type": "preview", "job_id": job_id, "image": preview_b64, "media_type": media_type}
    print(json.dumps(msg), file=sys.stderr, flush=True)


def send_thinking_token(job_id, token):
    msg = {"type": "thinking_token", "job_id": job_id, "token": token}
    print(json.dumps(msg), file=sys.stderr, flush=True)


def _acquire_ai_lock(job_id):
    ok, avail = check_ram()
    if not ok:
        send_error(job_id, f"Niet genoeg geheugen ({avail:.1f}GB beschikbaar, minimaal {MIN_RAM_GB}GB nodig)")
        return False
    if not _ai_lock.acquire(blocking=False):
        send_error(job_id, "Er draait al een AI model. Wacht tot deze klaar is.")
        return False
    return True


def handle_generate_photo(cmd):
    job_id = cmd.get("job_id", "unknown")
    prompt = cmd.get("prompt", "")
    try:
        if _cancel_flags.pop(job_id, None):
            return
        if not _acquire_ai_lock(job_id):
            return
        try:
            from photo_pipeline import text_to_photo

            def cb(pct, preview_img=None):
                msg = "Model laden..." if pct < 50 else f"Genereren... {pct}%"
                send_progress(job_id, pct, msg)
                if preview_img is not None:
                    import io, base64
                    buf = io.BytesIO()
                    preview_img.save(buf, format="JPEG", quality=70)
                    send_preview(job_id, base64.b64encode(buf.getvalue()).decode(), "photo")

            photo_path, image = text_to_photo(
                prompt=prompt,
                negative_prompt=cmd.get("negative_prompt"),
                width=cmd.get("width", 512),
                height=cmd.get("height", 512),
                num_inference_steps=cmd.get("num_inference_steps", 30),
                guidance_scale=cmd.get("guidance_scale", 10.0),
                seed=cmd.get("seed"),
                model=cmd.get("model", "sd15"),
                output_dir=str(OUTPUT_DIR),
                progress_callback=cb,
            )
            send_done(job_id, {
                "file_path": Path(photo_path).name,
                "prompt": prompt,
            })
        finally:
            _ai_lock.release()
    except Exception as e:
        send_error(job_id, str(e))


def handle_generate_video(cmd):
    job_id = cmd.get("job_id", "unknown")
    prompt = cmd.get("prompt", "")
    try:
        if _cancel_flags.pop(job_id, None):
            return
        if not _acquire_ai_lock(job_id):
            return
        try:
            from video_pipeline import text_to_video

            def cb(pct, msg=None, preview_img=None):
                if msg:
                    send_progress(job_id, pct, msg)
                elif pct < 20:
                    send_progress(job_id, pct, "Video model laden...")
                elif pct < 65:
                    send_progress(job_id, pct, "Motion adapter laden...")
                elif pct < 95:
                    send_progress(job_id, pct, f"Video genereren... {pct}%")
                else:
                    send_progress(job_id, pct, "Video opslaan...")
                if preview_img is not None:
                    import io, base64
                    buf = io.BytesIO()
                    preview_img.save(buf, format="JPEG", quality=70)
                    send_preview(job_id, base64.b64encode(buf.getvalue()).decode(), "video")

            video_path, num_frames, fps = text_to_video(
                prompt=prompt,
                negative_prompt=cmd.get("negative_prompt"),
                num_frames=cmd.get("num_frames", 16),
                num_inference_steps=cmd.get("num_inference_steps", 4),
                guidance_scale=cmd.get("guidance_scale", 2.0),
                fps=cmd.get("fps", 8),
                width=cmd.get("width", 512),
                height=cmd.get("height", 512),
                seed=cmd.get("seed"),
                adapter=cmd.get("adapter", "fast"),
                model=cmd.get("model", "small"),
                output_dir=str(OUTPUT_DIR),
                progress_callback=cb,
            )
            send_done(job_id, {
                "file_path": Path(video_path).name,
                "num_frames": num_frames,
                "fps": fps,
            })
        finally:
            _ai_lock.release()
    except Exception as e:
        send_error(job_id, str(e))


def handle_generate_audio(cmd):
    job_id = cmd.get("job_id", "unknown")
    prompt = cmd.get("prompt", "")
    try:
        if _cancel_flags.pop(job_id, None):
            return
        if not _acquire_ai_lock(job_id):
            return
        try:
            from audio_pipeline import text_to_audio

            def cb(pct):
                msg = "Model laden..." if pct < 10 else f"Genereren... {pct}%"
                send_progress(job_id, pct, msg)

            audio_path, audio_arr, sample_rate = text_to_audio(
                prompt=prompt,
                duration_seconds=cmd.get("duration_seconds", 30),
                guidance_scale=cmd.get("guidance_scale", 7.0),
                seed=cmd.get("seed"),
                model=cmd.get("model", "small"),
                output_dir=str(OUTPUT_DIR),
                progress_callback=cb,
            )
            duration = len(audio_arr) / sample_rate
            send_done(job_id, {
                "file_path": Path(audio_path).name,
                "duration": round(duration, 1),
                "sample_rate": sample_rate,
            })
        finally:
            _ai_lock.release()
    except Exception as e:
        send_error(job_id, str(e))


def handle_gallery(cmd):
    action = cmd.get("action", "")
    gallery_type = cmd.get("gallery_type", "photos")
    job_id = cmd.get("job_id", "")

    if gallery_type == "photos":
        gallery_dir = PHOTO_GALLERY_DIR
    elif gallery_type == "video":
        gallery_dir = VIDEO_GALLERY_DIR
    else:
        gallery_dir = AUDIO_GALLERY_DIR

    if action == "list":
        items = []
        exts = (".png", ".jpg", ".jpeg", ".webp") if gallery_type == "photos" else (".mp4", ".avi", ".mov", ".gif") if gallery_type == "video" else (".wav", ".mp3", ".flac", ".ogg")
        for f in sorted(gallery_dir.glob("*")):
            if f.suffix.lower() in exts:
                size = f.stat().st_size
                items.append({
                    "name": f.name,
                    "size": round(size / (1024 * 1024), 1) if gallery_type == "audio" else round(size / 1024, 1),
                    "size_unit": "MB" if gallery_type == "audio" else "KB",
                })
        send_result({"job_id": job_id, "items": items})

    elif action == "save":
        source_file = cmd.get("file_path")
        if source_file:
            src = OUTPUT_DIR / source_file
            if src.exists():
                import shutil
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                prompt_slug = cmd.get("prompt", gallery_type)[:40].replace(" ", "_")
                dest = gallery_dir / f"{gallery_type.rstrip('s')}_{timestamp}_{prompt_slug}{src.suffix}"
                shutil.copy2(src, dest)
                send_result({"job_id": job_id, "saved": dest.name})
            else:
                send_result({"job_id": job_id, "error": "Bestand niet gevonden"})
        else:
            send_result({"job_id": job_id, "error": "Geen bestand opgegeven"})

    elif action == "delete":
        filename = cmd.get("filename")
        if filename:
            filepath = gallery_dir / filename
            if filepath.exists():
                filepath.unlink()
                send_result({"job_id": job_id, "deleted": filename})
            else:
                send_result({"job_id": job_id, "error": "Bestand niet gevonden"})

    elif action == "serve":
        filename = cmd.get("filename")
        subpath = cmd.get("subpath", "")
        if gallery_type == "photos":
            filepath = OUTPUT_DIR / filename if not subpath else PHOTO_GALLERY_DIR / filename
        elif gallery_type == "video":
            filepath = OUTPUT_DIR / filename if not subpath else VIDEO_GALLERY_DIR / filename
        else:
            filepath = OUTPUT_DIR / filename if not subpath else AUDIO_GALLERY_DIR / filename
        send_result({"job_id": job_id, "path": str(filepath.resolve()) if filepath.exists() else None})


def handle_chat(cmd):
    job_id = cmd.get("job_id", "unknown")
    try:
        if _cancel_flags.pop(job_id, None):
            return
        from llm_backend import chat_completion_with_tools

        messages = cmd.get("messages", [])
        if not messages:
            msg = cmd.get("message", "")
            if msg:
                messages = [{"role": "user", "content": msg}]

        if not messages:
            send_error(job_id, "Geen bericht opgegeven")
            return

        def cb(pct, msg=None):
            if msg:
                send_progress(job_id, pct, msg)

        def on_token(token):
            send_thinking_token(job_id, token)

        def execute_tool(tool_name, args):
            if tool_name == "generate_photo":
                return _execute_photo_tool(args, job_id, cb)
            elif tool_name == "generate_video":
                return _execute_video_tool(args, job_id, cb)
            elif tool_name == "generate_audio":
                return _execute_audio_tool(args, job_id, cb)
            elif tool_name in _TOOL_MODULES:
                return _execute_generic_tool(tool_name, args)
            else:
                return {"error": f"Onbekende tool: {tool_name}"}

        result = chat_completion_with_tools(
            messages=messages,
            model_size=cmd.get("model", "medium"),
            max_tokens=cmd.get("max_tokens", 1024),
            temperature=cmd.get("temperature", 0.7),
            tool_executor=execute_tool,
            progress_callback=cb,
            token_callback=on_token,
        )

        generated_files = []
        for tr in result.get("tool_results", []):
            if isinstance(tr, dict) and "file_path" in tr:
                generated_files.append(tr)

        send_done(job_id, {
            "thinking": result.get("thinking", ""),
            "response": result["content"],
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "generated_files": generated_files,
        })
    except Exception as e:
        traceback.print_exc()
        send_error(job_id, str(e))


def _execute_photo_tool(args, job_id, progress_cb):
    try:
        from photo_pipeline import text_to_photo

        def cb(pct, preview_img=None):
            msg = "Model laden..." if pct < 50 else f"Foto genereren... {min(pct, 99)}%"
            progress_cb(pct, msg)
            if preview_img is not None:
                import io, base64
                buf = io.BytesIO()
                preview_img.save(buf, format="JPEG", quality=70)
                send_preview(job_id, base64.b64encode(buf.getvalue()).decode(), "photo")

        photo_path, image = text_to_photo(
            prompt=args.get("prompt", ""),
            width=args.get("width", 512),
            height=args.get("height", 512),
            num_inference_steps=args.get("num_inference_steps", 30),
            guidance_scale=args.get("guidance_scale", 10.0),
            model=args.get("model", "sd15"),
            output_dir=str(OUTPUT_DIR),
            progress_callback=cb,
        )
        return {"file_path": Path(photo_path).name, "type": "photo"}
    except Exception as e:
        return {"error": str(e)}


def _execute_video_tool(args, job_id, progress_cb):
    try:
        from video_pipeline import text_to_video

        def cb(pct, msg=None):
            if msg:
                progress_cb(pct, msg)
            elif pct < 20:
                progress_cb(pct, "Video model laden...")
            elif pct < 65:
                progress_cb(pct, "Video genereren...")
            else:
                progress_cb(pct, "Video opslaan...")

        video_path, num_frames, fps = text_to_video(
            prompt=args.get("prompt", ""),
            num_frames=args.get("num_frames", 8),
            num_inference_steps=args.get("num_inference_steps", 4),
            guidance_scale=args.get("guidance_scale", 2.0),
            fps=args.get("fps", 8),
            width=args.get("width", 384),
            height=args.get("height", 384),
            output_dir=str(OUTPUT_DIR),
            progress_callback=cb,
        )
        return {"file_path": Path(video_path).name, "type": "video"}
    except Exception as e:
        return {"error": str(e)}


def _execute_audio_tool(args, job_id, progress_cb):
    try:
        from audio_pipeline import text_to_audio

        def cb(pct):
            msg = "Audio model laden..." if pct < 10 else f"Audio genereren... {pct}%"
            progress_cb(pct, msg)

        audio_path, audio_arr, sample_rate = text_to_audio(
            prompt=args.get("prompt", ""),
            duration_seconds=args.get("duration_seconds", 30),
            guidance_scale=args.get("guidance_scale", 5.0),
            output_dir=str(OUTPUT_DIR),
            progress_callback=cb,
        )
        duration = len(audio_arr) / sample_rate
        return {"file_path": Path(audio_path).name, "type": "audio", "duration": round(duration, 1)}
    except Exception as e:
        return {"error": str(e)}


def _execute_generic_tool(tool_name, args):
    try:
        func = _import_tool(tool_name)
        sig = func.__code__.co_varnames[:func.__code__.co_argcount]
        call_args = {k: v for k, v in args.items() if k in sig}
        return func(**call_args)
    except Exception as e:
        return {"error": str(e)}


def handle_model_management(cmd):
    action = cmd.get("action", "")
    job_id = cmd.get("job_id", "")

    if action == "list":
        try:
            from model_manager import get_all_models
            models = get_all_models()
            send_result({"job_id": job_id, "models": models})
        except Exception as e:
            send_result({"job_id": job_id, "error": str(e)})

    elif action == "uninstall":
        model_id = cmd.get("model_id", "")
        if not model_id:
            send_result({"job_id": job_id, "error": "Geen model_id opgegeven"})
            return
        try:
            from model_manager import uninstall_model
            result = uninstall_model(model_id)
            send_result({"job_id": job_id, **result})
        except Exception as e:
            send_result({"job_id": job_id, "error": str(e)})

    else:
        send_result({"job_id": job_id, "error": f"Onbekende actie: {action}"})


def handle_command(cmd):
    cmd_type = cmd.get("type", "")

    if cmd_type == "cancel":
        job_id = cmd.get("job_id", "")
        if job_id in _active_futures:
            _cancel_flags[job_id] = True
            future = _active_futures[job_id]
            future.cancel()
            send_error(job_id, "Generatie geannuleerd")
        return

    if cmd_type == "generate_photo":
        future = _executor.submit(handle_generate_photo, cmd)
        _active_futures[cmd.get("job_id", "")] = future
    elif cmd_type == "generate_video":
        future = _executor.submit(handle_generate_video, cmd)
        _active_futures[cmd.get("job_id", "")] = future
    elif cmd_type == "generate_audio":
        future = _executor.submit(handle_generate_audio, cmd)
        _active_futures[cmd.get("job_id", "")] = future
    elif cmd_type == "chat":
        future = _executor.submit(handle_chat, cmd)
        _active_futures[cmd.get("job_id", "")] = future
    elif cmd_type == "gallery":
        handle_gallery(cmd)
    elif cmd_type == "health":
        send_result({"status": "ok", "job_id": cmd.get("job_id", "")})
    elif cmd_type == "model_management":
        handle_model_management(cmd)
    else:
        job_id = cmd.get("job_id", "")
        send_result({"job_id": job_id, "error": f"Onbekend commando: {cmd_type}"})


def main():
    send_result({"status": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            _executor.submit(handle_command, cmd)
        except json.JSONDecodeError as e:
            send_result({"error": f"Ongeldige JSON: {e}"})


if __name__ == "__main__":
    main()
