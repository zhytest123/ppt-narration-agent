from __future__ import annotations

import os
import sys
from pathlib import Path

import torch


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = PROJECT_DIR


def configure_runtime() -> None:
    numba_cache_dir = PROJECT_DIR / ".numba_cache"
    numba_cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(numba_cache_dir))

    path_entries = []
    for conda_prefix in (Path(sys.executable).resolve().parent, Path(os.environ.get("CONDA_PREFIX", ""))):
        for bin_dir in (conda_prefix / "bin", conda_prefix / "Library" / "bin"):
            if bin_dir.is_dir():
                path_entries.append(str(bin_dir))
    if path_entries:
        os.environ["PATH"] = os.pathsep.join(path_entries) + os.pathsep + os.environ.get("PATH", "")


def resolve_source_root(source_root: str | None = None) -> Path:
    root = Path(source_root or os.environ.get("CHATTTS_OPENVOICE_ROOT", "") or DEFAULT_SOURCE_ROOT)
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"ChatTTS-OpenVoice source root not found: {root}")

    required = [
        root / "ChatTTS",
        root / "OpenVoice",
        root / "ChatTTS_Model" / "config" / "path.yaml",
        root / "OpenVoice" / "checkpoints" / "converter" / "config.json",
        root / "OpenVoice" / "checkpoints" / "converter" / "checkpoint.pth",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required ChatTTS-OpenVoice files:\n" + "\n".join(missing))

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested, but torch.cuda.is_available() is False.")
        return "cuda:0"
    if device == "cpu":
        return "cpu"
    raise ValueError(f"Unsupported device: {device}")


def build_converter(source_root: Path, device: str):
    from OpenVoice.api import ToneColorConverter

    ckpt_dir = source_root / "OpenVoice" / "checkpoints" / "converter"
    converter = ToneColorConverter(str(ckpt_dir / "config.json"), device=device, enable_watermark=False)
    converter.load_ckpt(str(ckpt_dir / "checkpoint.pth"))
    return converter


def load_chattts(source_root: Path, device: str):
    import ChatTTS
    from omegaconf import OmegaConf

    model_dir = source_root / "ChatTTS_Model"
    paths = {
        key: str(model_dir / value)
        for key, value in OmegaConf.load(model_dir / "config" / "path.yaml").items()
    }
    chat = ChatTTS.Chat()
    chat._load(**paths, device=device)
    return chat


def load_voiceprint(path: Path, device: str) -> torch.Tensor:
    se = torch.load(path, map_location="cpu")
    if isinstance(se, dict) and "speaker_embedding" in se:
        se = se["speaker_embedding"]
    if not torch.is_tensor(se):
        raise TypeError(f"Voiceprint file does not contain a torch.Tensor: {path}")
    return se.to(device)


def default_output_path(directory: Path, prefix: str, suffix: str) -> Path:
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{stamp}{suffix}"
