#!/usr/bin/env python3
"""Video Generator GUI – lokaal, geen server."""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import os
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageTk
from t2v_pipeline import text_to_video


OUTPUT_DIR = Path("output")
GALLERY_DIR = Path("gallery")
GALLERY_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


class VideoGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Generator")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)

        self.generated_video = None
        self.generated_frames = None
        self.preview_image = None
        self.is_generating = False

        self._build_ui()
        self._load_gallery()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # ── Prompt ──
        ttk.Label(main, text="Prompt:", font=("", 12, "bold")).pack(anchor=tk.W)
        self.prompt_entry = scrolledtext.ScrolledText(
            main, height=3, font=("", 11), wrap=tk.WORD
        )
        self.prompt_entry.pack(fill=tk.X, pady=(4, 8))
        self.prompt_entry.insert("1.0", "a cinematic shot of a cat walking through a garden, flowers, sunlight, high quality, detailed")

        # ── Instellingen ──
        settings_frame = ttk.LabelFrame(main, text="Instellingen", padding=8)
        settings_frame.pack(fill=tk.X, pady=(0, 8))

        row = ttk.Frame(settings_frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="720p (1280x720)  •  20fps  •  24 frames").pack(side=tk.LEFT)

        self.use_upscale = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Upscale naar 720p", variable=self.use_upscale).pack(side=tk.RIGHT)

        # ── Knoppen ──
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.generate_btn = ttk.Button(
            btn_frame, text="🎬 Genereer Video", command=self._on_generate, width=25
        )
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.preview_btn = ttk.Button(
            btn_frame, text="▶ Preview", command=self._on_preview, state=tk.DISABLED, width=12
        )
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.keep_btn = ttk.Button(
            btn_frame, text="💾 Bewaren", command=self._on_keep, state=tk.DISABLED, width=12
        )
        self.keep_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.delete_btn = ttk.Button(
            btn_frame, text="🗑 Weggooien", command=self._on_delete, state=tk.DISABLED, width=12
        )
        self.delete_btn.pack(side=tk.LEFT)

        # ── Status / Progress ──
        self.status_var = tk.StringVar(value="Klaar om te genereren")
        status_bar = ttk.Label(main, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, pady=(0, 8))

        self.progress = ttk.Progressbar(main, mode="indeterminate")

        # ── Preview ──
        preview_frame = ttk.LabelFrame(main, text="Preview", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.preview_label = ttk.Label(preview_frame, text="(genereer een video om preview te zien)")
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # ── Gallerij ──
        gallery_frame = ttk.LabelFrame(main, text="Opgeslagen video's", padding=4)
        gallery_frame.pack(fill=tk.X, pady=(8, 0))

        self.gallery_listbox = tk.Listbox(gallery_frame, height=4)
        self.gallery_listbox.pack(fill=tk.X, side=tk.LEFT, expand=True)

        gallery_scroll = ttk.Scrollbar(gallery_frame, orient=tk.VERTICAL, command=self.gallery_listbox.yview)
        gallery_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.gallery_listbox.config(yscrollcommand=gallery_scroll.set)

        gallery_btn_frame = ttk.Frame(gallery_frame)
        gallery_btn_frame.pack(side=tk.RIGHT, padx=(4, 0))

        ttk.Button(gallery_btn_frame, text="▶ Afspelen", command=self._on_play_gallery, width=10).pack(pady=2)
        ttk.Button(gallery_btn_frame, text="🗑 Verwijderen", command=self._on_delete_gallery, width=10).pack(pady=2)

    def _set_status(self, msg):
        self.status_var.set(msg)
        self.root.update_idletasks()

    def _on_generate(self):
        if self.is_generating:
            return

        prompt = self.prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showwarning("Geen prompt", "Voer een tekstprompt in.")
            return

        self.is_generating = True
        self.generate_btn.config(state=tk.DISABLED, text="⏳ Bezig...")
        self.preview_btn.config(state=tk.DISABLED)
        self.keep_btn.config(state=tk.DISABLED)
        self.delete_btn.config(state=tk.DISABLED)
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.progress.start()
        self.preview_label.config(image="", text="🔄 Genereren..." if not self.preview_image else "🔄 Genereren...")
        self._set_status("Model laden en video genereren (kan 2-5 min duren)...")

        thread = threading.Thread(target=self._generate_thread, args=(prompt,), daemon=True)
        thread.start()

    def _generate_thread(self, prompt):
        try:
            self._set_status("Stap 1/2: Model laden...")

            video_path, frames = text_to_video(
                prompt=prompt,
                width=384,
                height=384,
                num_frames=16,
                fps=8,
                num_inference_steps=20,
                upscale=self.use_upscale.get(),
                target_width=1280,
                target_height=720,
                output_dir=str(OUTPUT_DIR),
            )

            self.generated_video = video_path
            self.generated_frames = frames

            self.root.after(0, self._on_generation_done)

        except Exception as e:
            self.root.after(0, lambda: self._on_generation_error(str(e)))

    def _on_generation_done(self):
        self.is_generating = False
        self.progress.stop()
        self.progress.pack_forget()
        self.generate_btn.config(state=tk.NORMAL, text="🎬 Genereer Video")
        self._set_status(f"✅ Video gegenereerd: {Path(self.generated_video).name}")

        # Show first frame as preview
        if self.generated_frames:
            frame = self.generated_frames[0].copy()
            frame.thumbnail((760, 300), Image.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(frame)
            self.preview_label.config(image=self.preview_image, text="")

        self.preview_btn.config(state=tk.NORMAL)
        self.keep_btn.config(state=tk.NORMAL)
        self.delete_btn.config(state=tk.NORMAL)

    def _on_generation_error(self, error_msg):
        self.is_generating = False
        self.progress.stop()
        self.progress.pack_forget()
        self.generate_btn.config(state=tk.NORMAL, text="🎬 Genereer Video")
        self.preview_label.config(image="", text=f"❌ Fout: {error_msg}")
        self._set_status("❌ Genereren mislukt")
        messagebox.showerror("Fout", error_msg)

    def _on_preview(self):
        if self.generated_video and os.path.exists(self.generated_video):
            subprocess.run(["open", self.generated_video])

    def _on_keep(self):
        if not self.generated_video or not os.path.exists(self.generated_video):
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        prompt_preview = self.prompt_entry.get("1.0", tk.END).strip()[:40].replace(" ", "_")
        dest = GALLERY_DIR / f"video_{timestamp}_{prompt_preview}.mp4"

        import shutil
        shutil.copy2(self.generated_video, dest)
        self._set_status(f"💾 Bewaard: {dest.name}")
        self._load_gallery()
        self.keep_btn.config(state=tk.DISABLED)

    def _on_delete(self):
        self.generated_video = None
        self.generated_frames = None
        self.preview_label.config(image="", text="(genereer een video om preview te zien)")
        self.preview_btn.config(state=tk.DISABLED)
        self.keep_btn.config(state=tk.DISABLED)
        self.delete_btn.config(state=tk.DISABLED)
        self._set_status("Video verwijderd")

    def _load_gallery(self):
        self.gallery_listbox.delete(0, tk.END)
        videos = sorted(GALLERY_DIR.glob("*.mp4"))
        self.gallery_videos = []
        for v in videos:
            size_mb = v.stat().st_size / (1024 * 1024)
            label = f"{v.stem[:50]}  ({size_mb:.1f}MB)"
            self.gallery_listbox.insert(tk.END, label)
            self.gallery_videos.append(v)

    def _on_play_gallery(self):
        sel = self.gallery_listbox.curselection()
        if sel and sel[0] < len(self.gallery_videos):
            subprocess.run(["open", str(self.gallery_videos[sel[0]])])

    def _on_delete_gallery(self):
        sel = self.gallery_listbox.curselection()
        if not sel or sel[0] >= len(self.gallery_videos):
            return
        path = self.gallery_videos[sel[0]]
        if messagebox.askyesno("Verwijderen", f"Verwijder {path.name}?"):
            path.unlink()
            self._load_gallery()


def main():
    root = tk.Tk()
    app = VideoGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
