import sys
from huggingface_hub import snapshot_download

MODELS = [
    ("stable-diffusion-v1-5/stable-diffusion-v1-5", "SD 1.5 (text-to-image)"),
    ("facebook/musicgen-small", "MusicGen Small (text-to-music)"),
]


def main():
    print("=" * 50)
    print("MODEL DOWNLOADER")
    print("=" * 50)
    print("Eenmalig internet nodig. Daarna volledig offline.\n")

    for model_id, label in MODELS:
        print(f"[{label}]")
        print(f"  Download: {model_id}")
        try:
            snapshot_download(repo_id=model_id)
            print(f"  Gereed\n")
        except Exception as e:
            print(f"  Fout: {e}\n")
            return False

    print("Alle modellen gedownload!")
    print("Je kunt nu offline genereren met:")
    print("   python3 generate.py photo \"een prompt\"")
    print("   python3 generate.py audio \"een prompt\"")
    print("   Of via de Electron app")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
