from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from tools_common import (
    PROJECT_DIR,
    build_converter,
    configure_runtime,
    default_output_path,
    load_chattts,
    load_voiceprint,
    resolve_device,
    resolve_source_root,
)


DEFAULT_REFINE_PROMPT = "[oral_2][laugh_0][break_6]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate speech from text using ChatTTS and a saved OpenVoice voiceprint.")
    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text", help="Text to synthesize.")
    text_group.add_argument("--text-file", help="UTF-8 text file to synthesize.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output wav path. Default: outputs/tts_<timestamp>.wav",
    )
    parser.add_argument(
        "--voiceprint",
        default=str(PROJECT_DIR / "voiceprints" / "sty.pt"),
        help="Input .pt voiceprint. Default: voiceprints/sty.pt",
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
    parser.add_argument("--speaker-seed", type=int, default=42)
    parser.add_argument("--text-seed", type=int, default=42)
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--top-p", type=float, default=0.7)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-new-token", type=int, default=2048)
    parser.add_argument("--no-refine", action="store_true", help="Disable ChatTTS refine-text pass.")
    parser.add_argument("--refine-prompt", default=DEFAULT_REFINE_PROMPT)
    parser.add_argument("--keep-temp", action="store_true", help="Keep the intermediate ChatTTS source wav.")
    return parser.parse_args()


def read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    return Path(args.text_file).expanduser().read_text(encoding="utf-8")


def synthesize_source_wav(chat, text: str, src_path: Path, args: argparse.Namespace) -> str:
    torch.manual_seed(args.speaker_seed)
    rand_spk = torch.randn(768)
    params_infer_code = {
        "spk_emb": rand_spk,
        "temperature": args.temperature,
        "top_P": args.top_p,
        "top_K": args.top_k,
        "max_new_token": args.max_new_token,
    }
    params_refine_text = {"prompt": args.refine_prompt}

    torch.manual_seed(args.text_seed)
    if args.no_refine:
        text_for_tts = [text]
        refined_text = text
    else:
        text_for_tts = chat.infer(
            [text],
            skip_refine_text=False,
            refine_text_only=True,
            params_refine_text=params_refine_text,
            params_infer_code=params_infer_code.copy(),
        )
        refined_text = text_for_tts[0] if isinstance(text_for_tts, list) else str(text_for_tts)

    wav = chat.infer(
        text_for_tts,
        skip_refine_text=True,
        params_refine_text=params_refine_text,
        params_infer_code=params_infer_code,
    )
    audio_data = np.array(wav[0]).flatten()
    sf.write(src_path, audio_data, 24000)
    return refined_text


def main() -> None:
    args = parse_args()
    configure_runtime()
    source_root = resolve_source_root(args.source_root)
    device = resolve_device(args.device)

    text = read_text(args).strip()
    if not text:
        raise ValueError("Input text is empty.")

    voiceprint_path = Path(args.voiceprint).expanduser().resolve()
    if not voiceprint_path.is_file():
        raise FileNotFoundError(f"Voiceprint not found: {voiceprint_path}")

    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(PROJECT_DIR / "outputs", "tts", ".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    runtime_dir = PROJECT_DIR / "tmp" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    source_wav = default_output_path(runtime_dir, "source", ".wav")
    source_segments = PROJECT_DIR / "tmp" / "source_segments"

    print(f"device={device}")
    print("loading_chattts=1")
    chat = load_chattts(source_root, device)
    print("loading_openvoice=1")
    converter = build_converter(source_root, device)

    print("synthesizing_source=1")
    refined_text = synthesize_source_wav(chat, text, source_wav, args)

    from OpenVoice.utils import se_extractor

    print("extracting_source_voiceprint=1")
    source_se, _ = se_extractor.get_se(str(source_wav), converter, target_dir=str(source_segments), vad=True)
    target_se = load_voiceprint(voiceprint_path, device)

    print("converting_voice=1")
    converter.convert(
        audio_src_path=str(source_wav),
        src_se=source_se,
        tgt_se=target_se,
        output_path=str(output_path),
    )

    if not args.keep_temp:
        try:
            source_wav.unlink()
        except FileNotFoundError:
            pass

    print(f"voiceprint={voiceprint_path}")
    print(f"refined_text={refined_text}")
    print(f"output_audio={output_path}")


if __name__ == "__main__":
    main()
