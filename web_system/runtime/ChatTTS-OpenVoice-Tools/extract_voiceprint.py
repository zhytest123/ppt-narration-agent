from __future__ import annotations

import argparse
import os
from pathlib import Path

import torch

from tools_common import (
    PROJECT_DIR,
    build_converter,
    configure_runtime,
    resolve_device,
    resolve_source_root,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract an OpenVoice speaker embedding from an audio file.")
    parser.add_argument("audio", help="Input audio path, for example C:\\Users\\zhy\\Desktop\\sty.m4a")
    parser.add_argument(
        "-o",
        "--output",
        help="Output .pt voiceprint path. Default: voiceprints/<audio_stem>.pt",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cuda", "cpu"],
        default="auto",
        help="Inference device. Default: auto",
    )
    parser.add_argument(
        "--source-root",
        help="Path to a self-contained ChatTTS-OpenVoice runtime. Default: this tool folder.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output and refresh cached VAD segments for this audio name.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_runtime()
    source_root = resolve_source_root(args.source_root)
    device = resolve_device(args.device)

    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.is_file():
        raise FileNotFoundError(f"Input audio not found: {audio_path}")

    output_path = Path(args.output).expanduser().resolve() if args.output else PROJECT_DIR / "voiceprints" / f"{audio_path.stem}.pt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Output already exists, use --force to overwrite: {output_path}")

    cache_root = PROJECT_DIR / "tmp" / "extract_segments"
    cache_dir = cache_root / audio_path.stem
    if args.force and cache_dir.exists():
        import shutil

        shutil.rmtree(cache_dir)

    converter = build_converter(source_root, device)
    from OpenVoice.utils import se_extractor

    speaker_embedding, audio_name = se_extractor.get_se(str(audio_path), converter, target_dir=str(cache_root), vad=True)
    torch.save(speaker_embedding.detach().cpu(), output_path)

    print(f"input_audio={audio_path}")
    print(f"audio_name={audio_name}")
    print(f"device={device}")
    print(f"shape={tuple(speaker_embedding.shape)}")
    print(f"output_voiceprint={output_path}")


if __name__ == "__main__":
    main()
