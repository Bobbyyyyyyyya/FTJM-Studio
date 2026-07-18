import argparse
from photo_pipeline import text_to_photo
from audio_pipeline import text_to_audio


def main():
    parser = argparse.ArgumentParser(
        description="AI Photo & Audio Generator (lokaal)"
    )
    parser.add_argument("mode", type=str, choices=["photo", "audio"],
                        help="Wat genereren: photo of audio")
    parser.add_argument("prompt", type=str, help="Tekstprompt")
    parser.add_argument("--negative-prompt", type=str, default=None)
    parser.add_argument("--width", type=int, default=512, help="Breedte (photo)")
    parser.add_argument("--height", type=int, default=512, help="Hoogte (photo)")
    parser.add_argument("--steps", type=int, default=25, help="Inference stappen (photo)")
    parser.add_argument("--guidance-scale", type=float, default=None,
                        help="Guidance scale (photo: 7.5, audio: 3.0)")
    parser.add_argument("--duration", type=int, default=10, help="Duur in seconden (audio)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="output")

    args = parser.parse_args()

    if args.mode == "photo":
        guidance = args.guidance_scale if args.guidance_scale is not None else 7.5
        photo_path, image = text_to_photo(
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            width=args.width,
            height=args.height,
            num_inference_steps=args.steps,
            guidance_scale=guidance,
            seed=args.seed,
            output_dir=args.output_dir,
        )
        print(f"\n✅ Foto: {photo_path}")
    else:
        guidance = args.guidance_scale if args.guidance_scale is not None else 3.0
        audio_path, audio_arr, sample_rate = text_to_audio(
            prompt=args.prompt,
            duration_seconds=args.duration,
            guidance_scale=guidance,
            seed=args.seed,
            output_dir=args.output_dir,
        )
        print(f"\n✅ Audio: {audio_path}")
        print(f"   {len(audio_arr)/sample_rate:.1f}s @ {sample_rate}Hz")


if __name__ == "__main__":
    main()
