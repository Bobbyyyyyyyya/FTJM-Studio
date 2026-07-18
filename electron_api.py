import gc
import json
import os
import sys
import threading
import time
import uuid
import socket
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
import mimetypes

OUTPUT_DIR = Path("output")
PHOTO_GALLERY_DIR = Path("gallery/photos")
AUDIO_GALLERY_DIR = Path("gallery/audio")
OUTPUT_DIR.mkdir(exist_ok=True)
PHOTO_GALLERY_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}


class APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _serve_file(self, filepath, media_type=None):
        if not filepath.exists():
            self._send_json({"error": "Bestand niet gevonden"}, 404)
            return
        if media_type is None:
            media_type, _ = mimetypes.guess_type(str(filepath))
            if media_type is None:
                media_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Disposition", f'inline; filename="{filepath.name}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(filepath, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return json.loads(self.rfile.read(length))
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "/api/status":
            job_id = query.get("job_id", [None])[0]
            if job_id and job_id in jobs:
                self._send_json(jobs[job_id])
            else:
                self._send_json({"error": "Job niet gevonden"}, 404)

        elif path == "/api/gallery/photos":
            items = []
            for f in sorted(PHOTO_GALLERY_DIR.glob("*")):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    size_kb = f.stat().st_size / 1024
                    items.append({
                        "name": f.name,
                        "size_kb": round(size_kb, 1),
                        "path": str(f),
                    })
            self._send_json(items)

        elif path == "/api/gallery/audio":
            items = []
            for f in sorted(AUDIO_GALLERY_DIR.glob("*")):
                if f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg"):
                    size_mb = f.stat().st_size / (1024 * 1024)
                    items.append({
                        "name": f.name,
                        "size_mb": round(size_mb, 1),
                        "path": str(f),
                    })
            self._send_json(items)

        elif path.startswith("/api/output/photo/"):
            filename = unquote(path[len("/api/output/photo/"):])
            filepath = OUTPUT_DIR / filename
            self._serve_file(filepath, "image/png")

        elif path.startswith("/api/output/audio/"):
            filename = unquote(path[len("/api/output/audio/"):])
            filepath = OUTPUT_DIR / filename
            self._serve_file(filepath, "audio/wav")

        elif path.startswith("/api/gallery/photos/"):
            filename = unquote(path[len("/api/gallery/photos/"):])
            filepath = PHOTO_GALLERY_DIR / filename
            self._serve_file(filepath)

        elif path.startswith("/api/gallery/audio/"):
            filename = unquote(path[len("/api/gallery/audio/"):])
            filepath = AUDIO_GALLERY_DIR / filename
            self._serve_file(filepath)

        elif path == "/api/health":
            self._send_json({"status": "ok"})

        else:
            self._send_json({"error": "Niet gevonden"}, 404)

    def do_POST(self):
        data = self._read_body()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/generate/photo":
            prompt = data.get("prompt", "").strip()
            if not prompt:
                self._send_json({"error": "Geen prompt opgegeven"}, 400)
                return

            job_id = str(uuid.uuid4())[:8]
            jobs[job_id] = {"status": "queued", "message": "Wachten...", "type": "photo"}
            thread = threading.Thread(
                target=self._photo_worker,
                args=(job_id, prompt, data),
                daemon=True,
            )
            thread.start()
            self._send_json({"job_id": job_id})

        elif path == "/api/generate/audio":
            prompt = data.get("prompt", "").strip()
            if not prompt:
                self._send_json({"error": "Geen prompt opgegeven"}, 400)
                return

            job_id = str(uuid.uuid4())[:8]
            jobs[job_id] = {"status": "queued", "message": "Wachten...", "type": "audio"}
            thread = threading.Thread(
                target=self._audio_worker,
                args=(job_id, prompt, data),
                daemon=True,
            )
            thread.start()
            self._send_json({"job_id": job_id})

        elif path == "/api/gallery/photos/save":
            job_id = data.get("job_id")
            if not job_id or job_id not in jobs:
                self._send_json({"error": "Geen foto om op te slaan"}, 400)
                return
            job = jobs[job_id]
            if job["status"] != "done" or not job.get("file_path"):
                self._send_json({"error": "Foto niet klaar"}, 400)
                return
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            prompt_short = job.get("prompt", "photo")[:40].replace(" ", "_")
            ext = Path(job["file_path"]).suffix
            dest = PHOTO_GALLERY_DIR / f"photo_{timestamp}_{prompt_short}{ext}"
            shutil.copy2(job["file_path"], dest)
            self._send_json({"saved": dest.name})

        elif path == "/api/gallery/audio/save":
            job_id = data.get("job_id")
            if not job_id or job_id not in jobs:
                self._send_json({"error": "Geen audio om op te slaan"}, 400)
                return
            job = jobs[job_id]
            if job["status"] != "done" or not job.get("file_path"):
                self._send_json({"error": "Audio niet klaar"}, 400)
                return
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            prompt_short = job.get("prompt", "audio")[:40].replace(" ", "_")
            ext = Path(job["file_path"]).suffix
            dest = AUDIO_GALLERY_DIR / f"audio_{timestamp}_{prompt_short}{ext}"
            shutil.copy2(job["file_path"], dest)
            self._send_json({"saved": dest.name})

        elif path == "/api/gallery/photos/delete":
            filename = data.get("filename")
            if not filename:
                self._send_json({"error": "Geen bestandsnaam"}, 400)
                return
            filepath = PHOTO_GALLERY_DIR / filename
            if filepath.exists():
                filepath.unlink()
                self._send_json({"deleted": filename})
            else:
                self._send_json({"error": "Bestand niet gevonden"}, 404)

        elif path == "/api/gallery/audio/delete":
            filename = data.get("filename")
            if not filename:
                self._send_json({"error": "Geen bestandsnaam"}, 400)
                return
            filepath = AUDIO_GALLERY_DIR / filename
            if filepath.exists():
                filepath.unlink()
                self._send_json({"deleted": filename})
            else:
                self._send_json({"error": "Bestand niet gevonden"}, 404)

        else:
            self._send_json({"error": "Niet gevonden"}, 404)

    def do_DELETE(self):
        data = self._read_body()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/gallery/photos/delete":
            filename = data.get("filename")
            if not filename:
                self._send_json({"error": "Geen bestandsnaam"}, 400)
                return
            filepath = PHOTO_GALLERY_DIR / filename
            if filepath.exists():
                filepath.unlink()
                self._send_json({"deleted": filename})
            else:
                self._send_json({"error": "Bestand niet gevonden"}, 404)

        elif path == "/api/gallery/audio/delete":
            filename = data.get("filename")
            if not filename:
                self._send_json({"error": "Geen bestandsnaam"}, 400)
                return
            filepath = AUDIO_GALLERY_DIR / filename
            if filepath.exists():
                filepath.unlink()
                self._send_json({"deleted": filename})
            else:
                self._send_json({"error": "Bestand niet gevonden"}, 404)
        else:
            self._send_json({"error": "Niet gevonden"}, 404)

    def _photo_worker(self, job_id, prompt, data):
        jobs[job_id] = {"status": "running", "message": "Model laden...", "prompt": prompt, "type": "photo", "progress": 0}
        try:
            from photo_pipeline import text_to_photo

            def cb(pct):
                jobs[job_id]["progress"] = pct
                if pct < 50:
                    jobs[job_id]["message"] = "Model laden..."
                else:
                    jobs[job_id]["message"] = f"Genereren... {min(pct, 99)}%"

            photo_path, image = text_to_photo(
                prompt=prompt,
                negative_prompt=data.get("negative_prompt"),
                width=data.get("width", 512),
                height=data.get("height", 512),
                num_inference_steps=data.get("num_inference_steps", 25),
                guidance_scale=data.get("guidance_scale", 7.5),
                seed=data.get("seed"),
                output_dir=str(OUTPUT_DIR),
                progress_callback=cb,
            )
            jobs[job_id].update({
                "status": "done",
                "message": "Foto gegenereerd!",
                "file_path": Path(photo_path).name,
                "progress": 100,
            })
        except Exception as e:
            jobs[job_id].update({
                "status": "error",
                "message": str(e),
                "error": str(e),
            })

    def _audio_worker(self, job_id, prompt, data):
        jobs[job_id] = {"status": "running", "message": "Model laden...", "prompt": prompt, "type": "audio", "progress": 0}
        try:
            from audio_pipeline import text_to_audio

            def cb(pct):
                jobs[job_id]["progress"] = pct
                if pct < 10:
                    jobs[job_id]["message"] = "Model laden..."
                elif pct < 92:
                    jobs[job_id]["message"] = f"Instrumental genereren... {pct}%"
                elif pct < 100:
                    jobs[job_id]["message"] = f"Audio genereren... {pct}%"

            audio_path, audio_arr, sample_rate = text_to_audio(
                prompt=prompt,
                duration_seconds=data.get("duration_seconds", 30),
                guidance_scale=data.get("guidance_scale", 5.0),
                seed=data.get("seed"),
                model=data.get("model", "small"),
                output_dir=str(OUTPUT_DIR),
                progress_callback=cb,
            )
            duration = len(audio_arr) / sample_rate
            jobs[job_id].update({
                "status": "done",
                "message": "Audio gegenereerd!",
                "file_path": Path(audio_path).name,
                "duration": round(duration, 1),
                "sample_rate": sample_rate,
                "progress": 100,
            })
        except Exception as e:
            jobs[job_id].update({
                "status": "error",
                "message": str(e),
                "error": str(e),
            })
        finally:
            gc.collect()

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = find_free_port()
    print(f"PORT:{port}", flush=True)
    server = HTTPServer(("127.0.0.1", port), APIHandler)
    server.timeout = 0.5
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
