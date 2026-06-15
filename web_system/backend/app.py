from __future__ import annotations

import io
import json
import shutil
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_pipeline import AgentLLMConfig, PresentationAgent, parse_reference_specs
from pipeline import (
    PDFSplitter,
    VideoSynthesisPipeline,
    VoiceprintService,
    list_available_voiceprints,
)
from style_presets import STYLE_PRESETS, compose_style_prompt


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
JOBS = WORKSPACE / "jobs"
VOICEPRINTS = WORKSPACE / "voiceprints"
FRONTEND_DIR = ROOT / "frontend"

for path in (WORKSPACE, JOBS, VOICEPRINTS):
    path.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="PDF Voice Video System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class VoiceprintInfo(BaseModel):
    id: str
    name: str
    path: str
    source: str


class VideoJobCreateResponse(BaseModel):
    job_id: str


class VideoJobInfo(BaseModel):
    job_id: str
    status: str
    message: str
    created_at: str
    updated_at: str
    output_video: Optional[str] = None
    pages: list[dict[str, Any]] = []
    error: Optional[str] = None


class AgentJobCreateResponse(BaseModel):
    job_id: str


class AgentJobInfo(BaseModel):
    job_id: str
    status: str
    message: str
    created_at: str
    updated_at: str
    output_pptx: Optional[str] = None
    output_scripts: Optional[str] = None
    output_bundle: Optional[str] = None
    plan: Optional[dict[str, Any]] = None
    references: list[dict[str, Any]] = []
    error: Optional[str] = None


@dataclass
class VideoJobState:
    job_id: str
    status: str = "queued"
    message: str = ""
    created_at: str = ""
    updated_at: str = ""
    output_video: Optional[str] = None
    pages: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AgentJobState:
    job_id: str
    status: str = "queued"
    message: str = ""
    created_at: str = ""
    updated_at: str = ""
    output_pptx: Optional[str] = None
    output_scripts: Optional[str] = None
    output_bundle: Optional[str] = None
    plan: Optional[dict[str, Any]] = None
    references: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


VOICEPRINT_SERVICE = VoiceprintService()
PDF_SPLITTER = PDFSplitter()
VIDEO_PIPELINE = VideoSynthesisPipeline()
PRESENTATION_AGENT = PresentationAgent()

JOB_LOCK = threading.Lock()
JOB_STORE: Dict[str, VideoJobState] = {}
AGENT_JOB_LOCK = threading.Lock()
AGENT_JOB_STORE: Dict[str, AgentJobState] = {}


def now_str() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def get_job(job_id: str) -> VideoJobState:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def update_job(job_id: str, **changes: Any) -> VideoJobState:
    with JOB_LOCK:
        job = get_job(job_id)
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = now_str()
        return job


def create_job() -> VideoJobState:
    job_id = uuid.uuid4().hex
    job = VideoJobState(
        job_id=job_id,
        status="queued",
        message="job queued",
        created_at=now_str(),
        updated_at=now_str(),
    )
    with JOB_LOCK:
        JOB_STORE[job_id] = job
    return job


def get_agent_job(job_id: str) -> AgentJobState:
    job = AGENT_JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="agent job not found")
    return job


def update_agent_job(job_id: str, **changes: Any) -> AgentJobState:
    with AGENT_JOB_LOCK:
        job = get_agent_job(job_id)
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = now_str()
        return job


def create_agent_job() -> AgentJobState:
    job_id = uuid.uuid4().hex
    job = AgentJobState(
        job_id=job_id,
        status="queued",
        message="agent job queued",
        created_at=now_str(),
        updated_at=now_str(),
    )
    with AGENT_JOB_LOCK:
        AGENT_JOB_STORE[job_id] = job
    return job


def make_zip_from_dir(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(directory))
    buffer.seek(0)
    return buffer.getvalue()


def sanitize_name(name: str, fallback: str) -> str:
    value = (name or "").strip()
    if not value:
        return fallback
    safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in ("-", "_", "."))) else "_" for ch in value)
    return safe or fallback


def ensure_mp4_name(name: str, fallback: str) -> str:
    safe = sanitize_name(name, fallback)
    if not safe.lower().endswith(".mp4"):
        safe = f"{Path(safe).stem}.mp4"
    return safe


def parse_headers_json(raw_json: str) -> Dict[str, str]:
    raw_json = (raw_json or "").strip()
    if not raw_json:
        return {}
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"custom_headers_json is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="custom_headers_json must be a JSON object")
    return {str(key): str(value) for key, value in payload.items() if str(key).strip()}


def build_download_headers(filename: str) -> Dict[str, str]:
    ascii_name = sanitize_name(filename, "download.bin")
    utf8_name = quote(filename)
    return {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/voiceprints", response_model=List[VoiceprintInfo])
def api_voiceprints() -> List[VoiceprintInfo]:
    return [VoiceprintInfo(**item) for item in list_available_voiceprints()]


@app.post("/api/voiceprints/extract")
async def api_extract_voiceprint(
    audio: UploadFile = File(...),
    output_name: str = Form(""),
    device: str = Form("auto"),
    force: bool = Form(True),
) -> JSONResponse:
    suffix = Path(audio.filename).suffix.lower()
    if suffix not in {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}:
        raise HTTPException(status_code=400, detail="unsupported audio format")

    extract_id = uuid.uuid4().hex
    work_dir = JOBS / f"voiceprint_{extract_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / audio.filename
    with audio_path.open("wb") as fh:
        shutil.copyfileobj(audio.file, fh)

    target_name = sanitize_name(output_name, audio_path.stem)
    target_path = VOICEPRINTS / f"{Path(target_name).stem}.pt"
    result = VOICEPRINT_SERVICE.extract(
        audio_path=audio_path,
        output_path=target_path,
        device=device,
        force=bool(force),
    )
    payload = {
        "voiceprint": result,
        "all_voiceprints": list_available_voiceprints(),
    }
    return JSONResponse(payload)


@app.post("/api/pdf/split")
async def api_split_pdf(
    pdf: UploadFile = File(...),
    render_scale: float = Form(2.0),
    image_format: str = Form("png"),
    image_prefix: str = Form("page"),
    start_page: int = Form(1),
    end_page: int = Form(0),
) -> StreamingResponse:
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="pdf file required")

    split_id = uuid.uuid4().hex
    work_dir = JOBS / f"split_{split_id}"
    images_dir = work_dir / "images"
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = work_dir / pdf.filename
    with pdf_path.open("wb") as fh:
        shutil.copyfileobj(pdf.file, fh)

    PDF_SPLITTER.split(
        pdf_path=pdf_path,
        images_dir=images_dir,
        render_scale=render_scale,
        image_format=image_format,
        image_prefix=image_prefix,
        start_page=start_page,
        end_page=None if end_page <= 0 else end_page,
    )
    archive = make_zip_from_dir(images_dir)
    filename = f"{Path(pdf.filename).stem}_images.zip"
    return StreamingResponse(
        io.BytesIO(archive),
        media_type="application/zip",
        headers=build_download_headers(filename),
    )


@app.get("/api/contracts/scripts-json")
def api_scripts_contract() -> JSONResponse:
    contract = {
        "description": "上传图片序列和 scripts.json 后，按 pages 数组顺序合成视频。",
        "required_images": ["page_001.png", "page_002.png"],
        "scripts_json": {
            "pages": [
                {"image": "page_001.png", "script": "第1页口播文案"},
                {"image": "page_002.png", "script": "第2页口播文案"},
            ]
        },
    }
    return JSONResponse(contract)


@app.get("/api/contracts/agent-input")
def api_agent_contract() -> JSONResponse:
    contract = {
        "description": "输入自然语言需求和可选参考文件，生成 PPTX、逐页口播文本和打包 ZIP。",
        "llm_api": {
            "base_url": "OpenAI 兼容地址，例如 https://api.openai.com 或本地网关地址",
            "model": "模型名称，例如 gpt-4.1 / qwen-plus / deepseek-chat",
            "api_key": "可选；后端仅用于本次请求，不落盘保存",
            "custom_headers_json": {"X-Custom-Header": "value"},
        },
        "reference_specs_json": [
            {"filename": "brand.pdf", "type": "brand", "usage": "作为视觉和品牌规范"},
            {"filename": "data.xlsx", "type": "data", "usage": "作为指标和事实来源"},
            {"filename": "outline.md", "type": "outline", "usage": "作为页面结构优先参考"},
        ],
    }
    return JSONResponse(contract)


@app.get("/api/style-presets")
def api_style_presets() -> JSONResponse:
    return JSONResponse({"presets": STYLE_PRESETS})


@app.post("/api/agent-jobs", response_model=AgentJobCreateResponse)
async def api_create_agent_job(
    instruction: str = Form(""),
    reference_files: Optional[List[UploadFile]] = File(None),
    reference_specs_json: str = Form(""),
    llm_base_url: str = Form(""),
    llm_api_key: str = Form(""),
    llm_model: str = Form(""),
    llm_temperature: float = Form(0.4),
    llm_timeout: int = Form(120),
    custom_headers_json: str = Form(""),
    output_name: str = Form("agent_presentation"),
    slide_count: int = Form(6),
    language: str = Form("中文"),
    audience: str = Form("业务评审 / 内部分享"),
    style_preset: str = Form("business_clean"),
    custom_style: str = Form(""),
    style: str = Form("商务简洁"),
    max_reference_chars: int = Form(16000),
) -> AgentJobCreateResponse:
    uploaded_references = reference_files or []
    if not instruction.strip() and not uploaded_references:
        raise HTTPException(status_code=400, detail="请至少填写自然语言需求或上传一个参考文件")
    if slide_count <= 0 or slide_count > 30:
        raise HTTPException(status_code=400, detail="slide_count must be between 1 and 30")
    if max_reference_chars < 1000 or max_reference_chars > 120000:
        raise HTTPException(status_code=400, detail="max_reference_chars must be between 1000 and 120000")

    try:
        reference_specs = parse_reference_specs(reference_specs_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = parse_headers_json(custom_headers_json)

    job = create_agent_job()
    job_dir = JOBS / f"agent_{job.job_id}"
    refs_dir = job_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    stored_references: List[Dict[str, Any]] = []
    for index, upload in enumerate(uploaded_references, start=1):
        filename = sanitize_name(upload.filename, f"reference_{index}")
        if not filename:
            filename = f"reference_{index}"
        target = refs_dir / filename
        with target.open("wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        stored_references.append({"filename": upload.filename or filename, "path": str(target)})

    config = {
        "instruction": instruction,
        "reference_files": stored_references,
        "reference_specs": reference_specs,
        "llm_config": AgentLLMConfig(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=llm_model,
            temperature=llm_temperature,
            timeout=llm_timeout,
            headers=headers,
        ),
        "output_name": output_name,
        "slide_count": slide_count,
        "language": language,
        "audience": audience,
        "style": compose_style_prompt(style_preset, custom_style, style),
        "max_reference_chars": max_reference_chars,
    }
    thread = threading.Thread(target=run_agent_job, args=(job.job_id, config), daemon=True)
    thread.start()
    return AgentJobCreateResponse(job_id=job.job_id)


@app.get("/api/agent-jobs/{job_id}", response_model=AgentJobInfo)
def api_agent_job_detail(job_id: str) -> AgentJobInfo:
    job = get_agent_job(job_id)
    return AgentJobInfo(**asdict(job))


@app.get("/api/agent-jobs/{job_id}/pptx")
def api_agent_job_pptx(job_id: str) -> FileResponse:
    job = get_agent_job(job_id)
    if not job.output_pptx:
        raise HTTPException(status_code=404, detail="pptx not ready")
    return FileResponse(job.output_pptx, filename=Path(job.output_pptx).name)


@app.get("/api/agent-jobs/{job_id}/scripts")
def api_agent_job_scripts(job_id: str) -> FileResponse:
    job = get_agent_job(job_id)
    if not job.output_scripts:
        raise HTTPException(status_code=404, detail="scripts not ready")
    return FileResponse(job.output_scripts, filename=Path(job.output_scripts).name)


@app.get("/api/agent-jobs/{job_id}/bundle")
def api_agent_job_bundle(job_id: str) -> FileResponse:
    job = get_agent_job(job_id)
    if not job.output_bundle:
        raise HTTPException(status_code=404, detail="bundle not ready")
    return FileResponse(job.output_bundle, filename=Path(job.output_bundle).name)


@app.post("/api/video-jobs", response_model=VideoJobCreateResponse)
async def api_create_video_job(
    scripts_file: UploadFile = File(...),
    images: List[UploadFile] = File(...),
    voiceprint_id: str = Form(...),
    output_name: str = Form(""),
    keep_temp: bool = Form(False),
    tts_device: str = Form("auto"),
    speaker_seed: int = Form(42),
    text_seed: int = Form(42),
    temperature: float = Form(0.3),
    top_p: float = Form(0.7),
    top_k: int = Form(20),
    max_new_token: int = Form(2048),
    no_refine: bool = Form(False),
    refine_prompt: str = Form("[oral_2][laugh_0][break_6]"),
    keep_temp_audio: bool = Form(False),
    video_fps: int = Form(25),
    video_crf: int = Form(23),
    video_preset: str = Form("medium"),
    audio_bitrate: str = Form("128k"),
) -> VideoJobCreateResponse:
    if not scripts_file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="scripts_file must be a .json file")

    job = create_job()
    job_dir = JOBS / job.job_id
    images_dir = job_dir / "images"
    job_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    scripts_path = job_dir / scripts_file.filename
    with scripts_path.open("wb") as fh:
        shutil.copyfileobj(scripts_file.file, fh)

    for image in images:
        image_path = images_dir / image.filename
        with image_path.open("wb") as fh:
            shutil.copyfileobj(image.file, fh)

    voiceprints = {item["id"]: item for item in list_available_voiceprints()}
    selected = voiceprints.get(voiceprint_id)
    if selected is None:
        raise HTTPException(status_code=400, detail="voiceprint_id not found")

    config = {
        "scripts_path": scripts_path,
        "images_dir": images_dir,
        "voiceprint_path": Path(selected["path"]),
        "output_name": ensure_mp4_name(output_name, "output.mp4"),
        "keep_temp": bool(keep_temp),
        "tts_options": {
            "device": tts_device,
            "speaker_seed": speaker_seed,
            "text_seed": text_seed,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_new_token": max_new_token,
            "no_refine": bool(no_refine),
            "refine_prompt": refine_prompt,
            "keep_temp_audio": bool(keep_temp_audio),
        },
        "video_options": {
            "fps": video_fps,
            "crf": video_crf,
            "preset": video_preset,
            "audio_bitrate": audio_bitrate,
        },
    }
    thread = threading.Thread(target=run_video_job, args=(job.job_id, config), daemon=True)
    thread.start()
    return VideoJobCreateResponse(job_id=job.job_id)


@app.get("/api/video-jobs/{job_id}", response_model=VideoJobInfo)
def api_video_job_detail(job_id: str) -> VideoJobInfo:
    job = get_job(job_id)
    return VideoJobInfo(**asdict(job))


@app.get("/api/video-jobs/{job_id}/video")
def api_video_job_video(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job.output_video:
        raise HTTPException(status_code=404, detail="video not ready")
    return FileResponse(job.output_video, filename=Path(job.output_video).name)


def store_job_page(job_id: str):
    def _store(page: dict[str, Any]) -> None:
        with JOB_LOCK:
            job = get_job(job_id)
            job.pages.append(page)
            job.updated_at = now_str()

    return _store


def store_agent_progress(job_id: str):
    def _store(message: str) -> None:
        update_agent_job(job_id, message=message)

    return _store


def run_agent_job(job_id: str, config: dict[str, Any]) -> None:
    try:
        update_agent_job(job_id, status="running", message="agent is generating presentation")
        result = PRESENTATION_AGENT.run(
            job_id=job_id,
            instruction=config["instruction"],
            reference_files=config["reference_files"],
            reference_specs=config["reference_specs"],
            llm_config=config["llm_config"],
            output_name=config["output_name"],
            slide_count=config["slide_count"],
            language=config["language"],
            audience=config["audience"],
            style=config["style"],
            max_reference_chars=config["max_reference_chars"],
            on_progress=store_agent_progress(job_id),
        )
        update_agent_job(
            job_id,
            status="done",
            message="completed",
            output_pptx=str(result["output_pptx"]),
            output_scripts=str(result["output_scripts"]),
            output_bundle=str(result["output_bundle"]),
            plan=result["plan"],
            references=result["references"],
        )
    except Exception as exc:
        update_agent_job(job_id, status="failed", message="failed", error=str(exc))


def run_video_job(job_id: str, config: dict[str, Any]) -> None:
    try:
        update_job(job_id, status="running", message="synthesizing video")
        result = VIDEO_PIPELINE.run_from_scripts(
            job_id=job_id,
            scripts_path=config["scripts_path"],
            images_dir=config["images_dir"],
            voiceprint_path=config["voiceprint_path"],
            output_name=config["output_name"],
            keep_temp=config["keep_temp"],
            tts_options=config["tts_options"],
            video_options=config["video_options"],
            on_page=store_job_page(job_id),
        )
        update_job(
            job_id,
            status="done",
            message="completed",
            output_video=str(result["output_video"]),
            pages=result["pages"],
        )
    except Exception as exc:
        update_job(job_id, status="failed", message="failed", error=str(exc))
