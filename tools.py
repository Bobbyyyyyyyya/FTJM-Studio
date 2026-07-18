"""
Tools voor de LLM chat assistent.
Internet search, code execution, file operations, terminal commands, systeem info, model management.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

WORKSPACE = Path(__file__).parent
SAFE_DIR = WORKSPACE / "workspace"
SAFE_DIR.mkdir(exist_ok=True)


def internet_search(query, max_results=5):
    """Zoek op het internet via DuckDuckGo."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return {"results": [], "message": "Geen resultaten gevonden."}
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("href", r.get("link", "")),
                "snippet": r.get("body", r.get("snippet", "")),
            })
        return {"results": formatted}
    except Exception as e:
        return {"error": f"Zoekfout: {str(e)}"}


def execute_code(code, timeout=30):
    """Voer Python code uit in een sandboxed omgeving."""
    try:
        script = f"""
import sys
import io

# Beperkte omgeving - blokkeer gevaarlijke builtins
__builtins__.__dict__['open'] = None
__builtins__.__dict__['exec'] = None
__builtins__.__dict__['eval'] = None
__builtins__.__dict__['compile'] = None
__builtins__.__dict__['__import__'] = None

# Sta alleen veilige modules toe (geen os/pathlib/subprocess/sys)
import json
import math
import random
import datetime
import re
import collections
import itertools
import functools
import statistics
import string

# Herstel __import__ voor veilige modules
def __safe_import__(name, *args, **kwargs):
    allowed = ['json', 'math', 'random', 'datetime', 're', 'collections',
               'itertools', 'functools', 'statistics', 'string']
    if name in allowed:
        return __import__(name, *args, **kwargs)
    raise ImportError(f"Module '{{name}}' is niet toegestaan")

__builtins__.__dict__['__import__'] = __safe_import__

#vang output op
output = io.StringIO()
old_stdout = sys.stdout
sys.stdout = output

try:
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    result = output.getvalue()
except Exception as e:
    result = f"Fout: {{type(e).__name__}}: {{e}}"
finally:
    sys.stdout = old_stdout

if not result.strip():
    result = "(geen output)"
print(result)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SAFE_DIR),
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return {"output": stdout, "error": stderr or "Code gefaald"}
        return {"output": stdout or "(geen output)"}
    except subprocess.TimeoutExpired:
        return {"error": f"Code duurde langer dan {timeout} seconden"}
    except Exception as e:
        return {"error": f"Uitvoeringsfout: {str(e)}"}


def file_read(path, max_lines=500):
    """Lees een bestand van de Mac."""
    try:
        filepath = Path(path).expanduser().resolve()
        if not filepath.exists():
            return {"error": f"Bestand niet gevonden: {path}"}
        if not filepath.is_file():
            return {"error": f"Dit is geen bestand: {path}"}
        if filepath.stat().st_size > 1_000_000:
            return {"error": "Bestand te groot (>1MB)"}
        content = filepath.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines]) + f"\n\n... ({len(lines) - max_lines} regels overgeslagen)"
        return {"content": content, "path": str(filepath)}
    except Exception as e:
        return {"error": f"Leesfout: {str(e)}"}


def file_write(path, content):
    """Schrijf een bestand naar de workspace."""
    try:
        filepath = SAFE_DIR / Path(path).name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        return {"path": str(filepath), "message": f"Bestand geschreven: {filepath.name}"}
    except Exception as e:
        return {"error": f"Schrijffout: {str(e)}"}


def file_list(directory=None):
    """Lijst bestanden op in een map."""
    try:
        if directory:
            dirpath = Path(directory).expanduser().resolve()
        else:
            dirpath = SAFE_DIR
        if not dirpath.exists():
            return {"error": f"Map niet gevonden: {directory}"}
        if not dirpath.is_dir():
            return {"error": f"Dit is geen map: {directory}"}
        items = []
        for item in sorted(dirpath.iterdir()):
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return {"directory": str(dirpath), "items": items}
    except Exception as e:
        return {"error": f"Fout: {str(e)}"}


def run_command(command, timeout=15):
    """Voer een terminal command uit (beveiligd)."""
    import re as _re
    blocked_patterns = [
        r"rm\s+-rf\s+/", r"rm\s+-rf\s+~", r"rm\s+-rf\s+\.",
        r"mkfs", r"dd\s+if=", r">\s*/dev/",
        r":\(\)\{", r"shutdown", r"reboot", r"halt", r"init\s+0",
        r"curl.*\|\s*bash", r"wget.*\|\s*bash",
        r"chmod\s+-R\s+777\s+/", r"chown\s+-R",
        r"format\s+[a-z]:", r"del\s+/[sS]\s+/q", r"rmdir\s+/[sS]\s+/q",
        r"rd\s+/[sS]\s+/q", r"ren\s+.*\s*\*",
    ]
    for pattern in blocked_patterns:
        if _re.search(pattern, command.lower()):
            return {"error": "Dit commando is geblokkeerd om veiligheidsredenen."}
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        output = stdout
        if stderr:
            output += ("\n\nSTDERR:\n" + stderr) if output else stderr
        if len(output) > 5000:
            output = output[:5000] + "\n\n... (output afgekapt)"
        return {"output": output or "(geen output)", "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Commando duurde langer dan {timeout} seconden"}
    except Exception as e:
        return {"error": f"Uitvoeringsfout: {str(e)}"}


def get_system_info():
    """Krijg informatie over het systeem (RAM, CPU, schijf)."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk_path = os.environ.get("SystemDrive", "C:") + "\\" if sys.platform == "win32" else "/"
        disk = psutil.disk_usage(disk_path)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()

        return {
            "platform": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_cores": cpu_count,
            "cpu_freq_ghz": round(cpu_freq.max / 1000, 2) if cpu_freq else None,
            "ram_total_gb": round(mem.total / (1024**3), 1),
            "ram_available_gb": round(mem.available / (1024**3), 1),
            "ram_used_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "disk_free_gb": round(disk.free / (1024**3), 1),
        }
    except ImportError:
        return {"error": "psutil niet beschikbaar"}


def get_model_status():
    """Krijg overzicht van alle AI modellen en hun installatie status."""
    try:
        from model_manager import get_all_models
        models = get_all_models()
        categories = {}
        for m in models:
            cat = m["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(m)
        return {"models": models, "categories": categories}
    except Exception as e:
        return {"error": f"Fout bij ophalen model status: {str(e)}"}


def web_fetch(url, max_chars=5000):
    """Haal de inhoud van een webpagina op."""
    try:
        import requests
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
                self._skip = False
                self._skip_tags = {"script", "style", "noscript"}

            def handle_starttag(self, tag, attrs):
                if tag in self._skip_tags:
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in self._skip_tags:
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    stripped = data.strip()
                    if stripped:
                        self.text.append(stripped)

        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return {"content": resp.text[:max_chars], "type": content_type, "url": url}

        extractor = TextExtractor()
        extractor.feed(resp.text)
        text = "\n".join(extractor.text)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... ({len(resp.text)} tekens totaal, afgekapt)"
        return {"content": text, "url": url, "status": resp.status_code}
    except Exception as e:
        return {"error": f"Ophaalfout: {str(e)}"}


def gallery_list(gallery_type="photos"):
    """Lijst items op in de media gallery."""
    try:
        from pathlib import Path as _P
        gallery_dir = _P(WORKSPACE) / "gallery" / gallery_type
        if not gallery_dir.exists():
            return {"items": [], "gallery_type": gallery_type}
        ext_map = {
            "photos": (".png", ".jpg", ".jpeg", ".webp"),
            "video": (".mp4", ".avi", ".mov", ".gif"),
            "audio": (".wav", ".mp3", ".flac", ".ogg"),
        }
        exts = ext_map.get(gallery_type, ())
        items = []
        for f in sorted(gallery_dir.glob("*")):
            if f.suffix.lower() in exts:
                size = f.stat().st_size
                items.append({
                    "name": f.name,
                    "size_mb": round(size / (1024 * 1024), 1),
                })
        return {"items": items, "gallery_type": gallery_type, "count": len(items)}
    except Exception as e:
        return {"error": f"Fout: {str(e)}"}


TOOL_DEFINITIONS = {
    "internet_search": {
        "description": "Zoek op het internet. Geeft titels, URLs en snippets terug.",
        "execute": internet_search,
        "params": ["query", "max_results"],
    },
    "execute_code": {
        "description": "Voer Python code uit. Geeft output terug.",
        "execute": execute_code,
        "params": ["code"],
    },
    "file_read": {
        "description": "Lees de inhoud van een bestand op de Mac.",
        "execute": file_read,
        "params": ["path", "max_lines"],
    },
    "file_write": {
        "description": "Schrijf een bestand naar de workspace map.",
        "execute": file_write,
        "params": ["path", "content"],
    },
    "file_list": {
        "description": "Lijst bestanden op in een map.",
        "execute": file_list,
        "params": ["directory"],
    },
    "run_command": {
        "description": "Voer een terminal command uit (ls, cat, pwd, etc).",
        "execute": run_command,
        "params": ["command"],
    },
    "get_system_info": {
        "description": "Krijg informatie over het systeem: RAM, CPU, schijfruimte.",
        "execute": get_system_info,
        "params": [],
    },
    "get_model_status": {
        "description": "Krijg overzicht van alle AI modellen: welke zijn geinstalleerd en hun grootte.",
        "execute": get_model_status,
        "params": [],
    },
    "web_fetch": {
        "description": "Haal de inhoud van een webpagina op. Geeft tekst terug.",
        "execute": web_fetch,
        "params": ["url", "max_chars"],
    },
    "gallery_list": {
        "description": "Lijst opgeslagen media op in de gallery (photos, video, audio).",
        "execute": gallery_list,
        "params": ["gallery_type"],
    },
}
