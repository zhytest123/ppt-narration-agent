from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from vision_to_script import VisionToScriptInput, generate_script


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
CHAT_TTS_ROOT = Path(
    os.environ.get("CHAT_TTS_SOURCE_ROOT", str(ROOT / "runtime" / "ChatTTS-OpenVoice-Tools"))
).expanduser().resolve()
BUILTIN_VOICEPRINT_DIR = CHAT_TTS_ROOT / "voiceprints"
WORKSPACE_VOICEPRINT_DIR = WORKSPACE / "voiceprints"


def configured_python() -> str:
    return os.environ.get("CHAT_TTS_PYTHON", sys.executable)


def configured_device() -> str:
    return os.environ.get("CHAT_TTS_DEVICE", "auto")


def configured_subprocess_env() -> Dict[str, str]:
    env = os.environ.copy()
    python_bin = Path(configured_python()).expanduser().resolve()
    env_root = python_bin.parent.parent
    path_entries: List[str] = []
    for candidate in (env_root / "bin", env_root / "Library" / "bin"):
        if candidate.is_dir():
            path_entries.append(str(candidate))
    if path_entries:
        env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])
    env.setdefault("CONDA_PREFIX", str(env_root))
    return env


def resolve_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("ffmpeg is not installed, and imageio-ffmpeg is not available.") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def natural_sort_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def list_available_voiceprints() -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for source, directory in (
        ("builtin", BUILTIN_VOICEPRINT_DIR),
        ("workspace", WORKSPACE_VOICEPRINT_DIR),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.pt"), key=natural_sort_key):
            items.append(
                {
                    "id": f"{source}:{path.stem}",
                    "name": path.stem,
                    "path": str(path.resolve()),
                    "source": source,
                }
            )
    return items


class VoiceprintService:
    def extract(
        self,
        audio_path: Path,
        output_path: Path,
        device: str = "auto",
        force: bool = True,
    ) -> Dict[str, str]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            configured_python(),
            str(CHAT_TTS_ROOT / "extract_voiceprint.py"),
            str(audio_path),
            "-o",
            str(output_path),
            "--device",
            device,
        ]
        if force:
            cmd.append("--force")
        subprocess.run(cmd, check=True, env=configured_subprocess_env())
        return {
            "id": f"workspace:{output_path.stem}",
            "name": output_path.stem,
            "path": str(output_path.resolve()),
            "source": "workspace",
        }


class PDFSplitter:
    def split(
        self,
        pdf_path: Path,
        images_dir: Path,
        render_scale: float,
        image_format: str = "png",
        image_prefix: str = "page",
        start_page: int = 1,
        end_page: Optional[int] = None,
    ) -> List[Path]:
        import fitz

        if render_scale <= 0:
            raise RuntimeError("render_scale must be greater than 0")
        image_format = str(image_format or "png").strip().lower()
        if image_format not in {"png", "jpg", "jpeg"}:
            raise RuntimeError("image_format must be one of: png, jpg, jpeg")
        prefix = str(image_prefix or "page").strip() or "page"
        if start_page <= 0:
            raise RuntimeError("start_page must be greater than 0")
        images_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        try:
            page_count = doc.page_count
            if page_count <= 0:
                raise RuntimeError("pdf contains no pages")
            final_end_page = page_count if end_page is None else end_page
            if final_end_page <= 0:
                final_end_page = page_count
            if start_page > page_count:
                raise RuntimeError(f"start_page exceeds page count: {page_count}")
            if final_end_page < start_page:
                raise RuntimeError("end_page must be greater than or equal to start_page")
            final_end_page = min(final_end_page, page_count)
            result: List[Path] = []
            matrix = fitz.Matrix(render_scale, render_scale)
            for page_number in range(start_page, final_end_page + 1):
                page = doc.load_page(page_number - 1)
                image_path = images_dir / f"{prefix}_{page_number:03d}.{image_format}"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(image_path)
                result.append(image_path)
            return result
        finally:
            doc.close()


class VideoSynthesisPipeline:
    def run_from_scripts(
        self,
        job_id: str,
        scripts_path: Path,
        images_dir: Path,
        voiceprint_path: Path,
        output_name: str,
        keep_temp: bool,
        tts_options: Optional[Dict[str, Any]] = None,
        video_options: Optional[Dict[str, Any]] = None,
        on_page: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        job_dir = WORKSPACE / "jobs" / job_id
        audio_dir = job_dir / "audio"
        parts_dir = job_dir / "parts"
        audio_dir.mkdir(parents=True, exist_ok=True)
        parts_dir.mkdir(parents=True, exist_ok=True)

        pages = self.load_scripts_and_images(scripts_path, images_dir)
        audio_files: List[Path] = []
        page_results: List[Dict[str, Any]] = []
        for index, page in enumerate(pages, start=1):
            image_path = page["image_path"]
            script = page["script"]
            audio_path = self.tts_to_audio(script, audio_dir, index, voiceprint_path, tts_options or {})
            audio_files.append(audio_path)
            result = {
                "page_index": index,
                "image_path": str(image_path),
                "script": script,
                "audio_path": str(audio_path),
            }
            page_results.append(result)
            if on_page:
                on_page(result)

        output_video = self.combine_video(
            images=[page["image_path"] for page in pages],
            audio_files=audio_files,
            job_id=job_id,
            output_name=output_name,
            parts_dir=parts_dir,
            video_options=video_options,
        )

        if not keep_temp:
            shutil.rmtree(job_dir, ignore_errors=True)

        return {
            "output_video": str(output_video),
            "pages": page_results,
        }

    def load_scripts_and_images(self, scripts_path: Path, images_dir: Path) -> List[Dict[str, Any]]:
        try:
            payload = json.loads(scripts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"scripts json is invalid: {exc}") from exc

        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages:
            raise RuntimeError("scripts json must contain a non-empty 'pages' array")

        result: List[Dict[str, Any]] = []
        for item in pages:
            image_name = str(item.get("image", "")).strip()
            script = str(item.get("script", "")).strip()
            if not image_name or not script:
                raise RuntimeError("each page item must include non-empty 'image' and 'script'")
            image_path = (images_dir / image_name).resolve()
            if not image_path.is_file():
                raise RuntimeError(f"image not found for script item: {image_name}")
            result.append({"image_path": image_path, "script": script})
        return result

    def tts_to_audio(
        self,
        text: str,
        out_dir: Path,
        page_index: int,
        voiceprint_path: Path,
        tts_options: Dict[str, Any],
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = out_dir / f"page_{page_index:03d}.wav"
        cmd = [
            configured_python(),
            str(CHAT_TTS_ROOT / "text_to_speech.py"),
            "--text",
            text,
            "--voiceprint",
            str(voiceprint_path),
            "-o",
            str(audio_path),
            "--device",
            str(tts_options.get("device") or configured_device()),
        ]
        if tts_options.get("speaker_seed") is not None:
            cmd.extend(["--speaker-seed", str(tts_options["speaker_seed"])])
        if tts_options.get("text_seed") is not None:
            cmd.extend(["--text-seed", str(tts_options["text_seed"])])
        if tts_options.get("temperature") is not None:
            cmd.extend(["--temperature", str(tts_options["temperature"])])
        if tts_options.get("top_p") is not None:
            cmd.extend(["--top-p", str(tts_options["top_p"])])
        if tts_options.get("top_k") is not None:
            cmd.extend(["--top-k", str(tts_options["top_k"])])
        if tts_options.get("max_new_token") is not None:
            cmd.extend(["--max-new-token", str(tts_options["max_new_token"])])
        refine_prompt = str(tts_options.get("refine_prompt") or "").strip()
        if refine_prompt:
            cmd.extend(["--refine-prompt", refine_prompt])
        if tts_options.get("no_refine"):
            cmd.append("--no-refine")
        if tts_options.get("keep_temp_audio"):
            cmd.append("--keep-temp")
        subprocess.run(cmd, check=True, env=configured_subprocess_env())
        return audio_path

    def make_segment(
        self,
        ffmpeg: str,
        image_path: Path,
        audio_path: Path,
        output_path: Path,
        video_options: Dict[str, Any],
    ) -> None:
        fps = max(1, int(video_options.get("fps", 25)))
        crf = max(0, min(51, int(video_options.get("crf", 23))))
        preset = str(video_options.get("preset") or "medium").strip() or "medium"
        audio_bitrate = str(video_options.get("audio_bitrate") or "128k").strip() or "128k"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(fps),
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
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
        )

    def concat_segments(self, ffmpeg: str, parts: List[Path], output_path: Path, concat_list: Path) -> None:
        concat_lines: List[str] = []
        for part in parts:
            normalized = str(part).replace("\\", "/").replace("'", r"'\''")
            concat_lines.append(f"file '{normalized}'\n")
        concat_list.write_text("".join(concat_lines), encoding="utf-8")
        subprocess.run(
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
            ],
            check=True,
        )

    def combine_video(
        self,
        images: List[Path],
        audio_files: List[Path],
        job_id: str,
        output_name: str,
        parts_dir: Path,
        video_options: Optional[Dict[str, Any]] = None,
    ) -> Path:
        if len(images) != len(audio_files):
            raise RuntimeError("image count and audio count mismatch")
        output_dir = WORKSPACE / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_id}_{output_name}"
        ffmpeg = resolve_ffmpeg()
        concat_list = parts_dir.parent / "concat.txt"
        if concat_list.exists():
            concat_list.unlink()
        parts: List[Path] = []
        for index, (image_path, audio_path) in enumerate(zip(images, audio_files), start=1):
            part_path = parts_dir / f"part_{index:03d}.mp4"
            self.make_segment(ffmpeg, image_path, audio_path, part_path, video_options or {})
            parts.append(part_path)
        self.concat_segments(ffmpeg, parts, output_path, concat_list)
        return output_path
