#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import fitz
except ImportError:  # pragma: no cover - handled at runtime
    fitz = None


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine a PDF and per-page audio files into a single MP4 video.")
    parser.add_argument("pdf", help="Input PDF file.")
    parser.add_argument(
        "--audio-dir",
        help="Directory containing per-page audio files. Default: same directory as the PDF.",
    )
    parser.add_argument(
        "--audio-glob",
        default="*",
        help="Glob pattern used when collecting audio files from --audio-dir. Default: *",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Final MP4 path. Default: <pdf_dir>/<pdf_stem>.mp4",
    )
    parser.add_argument(
        "--work-dir",
        help="Temporary working directory. Default: <pdf_dir>/.pdf_video_work/<pdf_stem>",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="Render scale for PDF pages. Default: 2.0",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep rendered images, segments, and concat list in the work directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output MP4 if it already exists.",
    )
    return parser.parse_args()


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def resolve_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover - handled at runtime
        raise RuntimeError("ffmpeg is not installed, and imageio-ffmpeg is not available.") from exc

    return imageio_ffmpeg.get_ffmpeg_exe()


def natural_sort_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def collect_audio_files(audio_dir: Path, audio_glob: str) -> list[Path]:
    files = [
        path
        for path in audio_dir.glob(audio_glob)
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and not path.name.startswith(".")
    ]
    return sorted(files, key=natural_sort_key)


def prepare_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def render_pdf_pages_to_png(pdf_path: Path, images_dir: Path, scale: float) -> list[Path]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Run: python3 -m pip install pymupdf")
    if scale <= 0:
        raise RuntimeError("--scale must be greater than 0.")

    doc = fitz.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise RuntimeError(f"PDF contains no pages: {pdf_path}")

        matrix = fitz.Matrix(scale, scale)
        image_paths: list[Path] = []
        for index, page in enumerate(doc, start=1):
            image_path = images_dir / f"slide_{index:03d}.png"
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(image_path)
            image_paths.append(image_path)
        return image_paths
    finally:
        doc.close()


def make_segment(ffmpeg: str, image_path: Path, audio_path: Path, output_path: Path) -> None:
    run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-i",
            str(audio_path),
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def concat_escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", r"'\''")


def concat_segments(ffmpeg: str, parts: list[Path], output_path: Path, concat_list: Path) -> None:
    concat_list.write_text("".join(f"file '{concat_escape(part)}'\n" for part in parts), encoding="utf-8")
    run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
    )


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        return fail(f"Missing PDF: {pdf_path}")

    audio_dir = Path(args.audio_dir).expanduser().resolve() if args.audio_dir else pdf_path.parent
    if not audio_dir.is_dir():
        return fail(f"Missing audio directory: {audio_dir}")

    audio_files = collect_audio_files(audio_dir, args.audio_glob)
    if not audio_files:
        return fail(f"No audio files found in {audio_dir} matching glob '{args.audio_glob}'")

    output_path = Path(args.output).expanduser().resolve() if args.output else pdf_path.parent / f"{pdf_path.stem}.mp4"
    if output_path.exists() and not args.overwrite:
        return fail(f"Output already exists, use --overwrite to replace it: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    work_dir = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else pdf_path.parent / ".pdf_video_work" / pdf_path.stem
    )
    images_dir = work_dir / "images"
    parts_dir = work_dir / "parts"
    concat_list = work_dir / "concat.txt"

    try:
        ffmpeg = resolve_ffmpeg()
        prepare_clean_dir(images_dir)
        prepare_clean_dir(parts_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        if concat_list.exists():
            concat_list.unlink()

        image_paths = render_pdf_pages_to_png(pdf_path, images_dir, args.scale)
        if len(image_paths) != len(audio_files):
            return fail(
                f"PDF page count {len(image_paths)} does not match audio count {len(audio_files)}.\n"
                f"Audio files:\n" + "\n".join(str(path) for path in audio_files)
            )

        parts: list[Path] = []
        for index, (image_path, audio_path) in enumerate(zip(image_paths, audio_files), start=1):
            part_path = parts_dir / f"part_{index:03d}.mp4"
            make_segment(ffmpeg, image_path, audio_path, part_path)
            parts.append(part_path)

        concat_segments(ffmpeg, parts, output_path, concat_list)
    except subprocess.CalledProcessError as exc:
        return fail(f"ffmpeg failed with exit code {exc.returncode}")
    except Exception as exc:
        return fail(str(exc))
    finally:
        if not args.keep_temp and output_path.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    print(f"pdf={pdf_path}")
    print(f"audio_dir={audio_dir}")
    print(f"audio_count={len(audio_files)}")
    print(f"output_video={output_path}")
    if args.keep_temp:
        print(f"work_dir={work_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
