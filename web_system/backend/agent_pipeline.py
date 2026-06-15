from __future__ import annotations

import html
import json
import re
import textwrap
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
OUTPUTS = WORKSPACE / "outputs"
STABLE_TEMPLATE = ROOT / "templates" / "base.pptx"


@dataclass
class AgentLLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.4
    timeout: int = 120
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip() and self.model.strip())


@dataclass
class ReferenceDocument:
    filename: str
    path: Path
    reference_type: str
    usage: str
    text: str

    def to_public_dict(self, excerpt_chars: int = 500) -> Dict[str, Any]:
        excerpt = self.text[:excerpt_chars].strip()
        return {
            "filename": self.filename,
            "type": self.reference_type,
            "usage": self.usage,
            "chars": len(self.text),
            "excerpt": excerpt,
        }


def sanitize_filename(name: str, fallback: str) -> str:
    value = (name or "").strip()
    if not value:
        return fallback
    safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in ("-", "_", "."))) else "_" for ch in value)
    safe = safe.strip("._")
    return safe or fallback


def parse_reference_specs(raw_json: str) -> Dict[str, Dict[str, str]]:
    raw_json = (raw_json or "").strip()
    if not raw_json:
        return {}
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"参考文件说明 JSON 格式不正确: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("references"), list):
        payload = payload["references"]
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]

    result: Dict[str, Dict[str, str]] = {}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or item.get("name") or "").strip()
            if not filename:
                continue
            result[filename] = {
                "type": str(item.get("type") or item.get("reference_type") or "material").strip() or "material",
                "usage": str(item.get("usage") or item.get("description") or "").strip(),
            }
        return result

    if isinstance(payload, dict):
        for filename, item in payload.items():
            key = str(filename).strip()
            if not key:
                continue
            if isinstance(item, dict):
                result[key] = {
                    "type": str(item.get("type") or item.get("reference_type") or "material").strip() or "material",
                    "usage": str(item.get("usage") or item.get("description") or "").strip(),
                }
            else:
                result[key] = {"type": str(item or "material").strip() or "material", "usage": ""}
        return result

    raise ValueError("参考文件说明 JSON 需要是对象、数组，或包含 references/items 数组的对象")


class ReferenceExtractor:
    TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".html", ".htm"}

    def extract(self, path: Path, max_chars: int = 16000) -> str:
        suffix = path.suffix.lower()
        if suffix in self.TEXT_SUFFIXES:
            return self._truncate(self._read_text(path), max_chars)
        if suffix == ".pdf":
            return self._truncate(self._read_pdf(path), max_chars)
        if suffix == ".pptx":
            return self._truncate(self._read_office_zip(path, ["ppt/slides/", "ppt/notesSlides/"]), max_chars)
        if suffix == ".docx":
            return self._truncate(self._read_office_zip(path, ["word/document.xml"]), max_chars)
        if suffix == ".xlsx":
            return self._truncate(self._read_office_zip(path, ["xl/sharedStrings.xml", "xl/worksheets/"]), max_chars)
        return self._truncate(f"无法直接抽取该格式内容，仅记录文件名：{path.name}", max_chars)

    def _read_text(self, path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    def _read_pdf(self, path: Path) -> str:
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("读取 PDF 需要安装 PyMuPDF") from exc
        chunks: List[str] = []
        doc = fitz.open(path)
        try:
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                if text:
                    chunks.append(f"[PDF 第{index}页]\n{text}")
        finally:
            doc.close()
        return "\n\n".join(chunks)

    def _read_office_zip(self, path: Path, prefixes: List[str]) -> str:
        chunks: List[str] = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist(), key=self._natural_key):
                if not name.endswith(".xml"):
                    continue
                if not any(name == prefix or name.startswith(prefix) for prefix in prefixes):
                    continue
                xml_text = archive.read(name).decode("utf-8", errors="ignore")
                plain = self._xml_to_text(xml_text)
                if plain:
                    chunks.append(f"[{name}]\n{plain}")
        return "\n\n".join(chunks)

    def _xml_to_text(self, xml_text: str) -> str:
        xml_text = re.sub(r"</(?:a:p|w:p|row|xdr:row)>", "\n", xml_text)
        xml_text = re.sub(r"<[^>]+>", " ", xml_text)
        xml_text = html.unescape(xml_text)
        lines = [re.sub(r"\s+", " ", line).strip() for line in xml_text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _natural_key(self, value: str) -> List[object]:
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]

    def _truncate(self, text: str, max_chars: int) -> str:
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[内容过长，已截断]"


class OpenAICompatibleClient:
    def complete_json(self, config: AgentLLMConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        url = self._chat_completions_url(config.base_url)
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PPT-Voice-Agent/1.0",
        }
        if config.api_key.strip():
            headers["Authorization"] = f"Bearer {config.api_key.strip()}"
        headers.update({key: value for key, value in config.headers.items() if key and value})
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1, int(config.timeout))) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 403:
                raise RuntimeError(
                    "LLM 接口返回 HTTP 403，通常是 API Key、模型权限、网关白名单、Base URL、"
                    f"或反爬/防火墙策略导致。原始返回：{detail[:1000]}"
                ) from exc
            raise RuntimeError(f"LLM 接口返回 HTTP {exc.code}: {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM 接口请求失败: {exc.reason}") from exc

        try:
            data = json.loads(raw)
            content = data["choices"][0].get("message", {}).get("content") or data["choices"][0].get("text", "")
        except Exception as exc:
            raise RuntimeError(f"LLM 响应不是兼容的 chat/completions 格式: {raw[:1000]}") from exc
        return self._parse_json_content(content)

    def _chat_completions_url(self, base_url: str) -> str:
        base = base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _parse_json_content(self, content: str) -> Dict[str, Any]:
        content = (content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
            content = re.sub(r"```$", "", content).strip()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError(f"LLM 未返回可解析 JSON: {content[:1000]}")
            payload = json.loads(content[start : end + 1])
        if not isinstance(payload, dict):
            raise RuntimeError("LLM JSON 根节点必须是对象")
        return payload


class PresentationAgent:
    def __init__(self) -> None:
        self.extractor = ReferenceExtractor()
        self.llm_client = OpenAICompatibleClient()

    def run(
        self,
        job_id: str,
        instruction: str,
        reference_files: List[Dict[str, Any]],
        reference_specs: Dict[str, Dict[str, str]],
        llm_config: AgentLLMConfig,
        output_name: str = "",
        slide_count: int = 6,
        language: str = "中文",
        audience: str = "业务评审 / 内部分享",
        style: str = "商务简洁",
        max_reference_chars: int = 16000,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        self._progress(on_progress, "读取和抽取参考资料")
        references = self._load_references(reference_files, reference_specs, max_reference_chars)
        self._progress(on_progress, "规划 PPT 结构与口播文本")
        raw_plan = self._generate_plan(
            instruction=instruction,
            references=references,
            llm_config=llm_config,
            slide_count=slide_count,
            language=language,
            audience=audience,
            style=style,
        )
        plan = self._normalize_plan(raw_plan, instruction, references, slide_count, language, audience, style)

        safe_output = self._safe_output_stem(output_name, plan.get("title") or "agent_presentation")
        pptx_path = OUTPUTS / f"{job_id}_{safe_output}.pptx"
        scripts_path = OUTPUTS / f"{job_id}_{safe_output}_scripts.json"
        plan_path = OUTPUTS / f"{job_id}_{safe_output}_plan.json"
        bundle_path = OUTPUTS / f"{job_id}_{safe_output}_bundle.zip"

        self._progress(on_progress, "生成 PPTX 文件")
        self._render_pptx(plan, pptx_path)
        self._progress(on_progress, "生成口播 scripts.json")
        scripts = self._build_scripts(plan)
        scripts_path.write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_text = self._build_manifest(plan, references, pptx_path, scripts_path)
        manifest_path = OUTPUTS / f"{job_id}_{safe_output}_manifest.md"
        manifest_path.write_text(manifest_text, encoding="utf-8")
        self._write_bundle(bundle_path, [pptx_path, scripts_path, plan_path, manifest_path])
        return {
            "output_pptx": str(pptx_path),
            "output_scripts": str(scripts_path),
            "output_bundle": str(bundle_path),
            "plan": plan,
            "references": [item.to_public_dict() for item in references],
        }

    def _load_references(
        self,
        reference_files: List[Dict[str, Any]],
        specs: Dict[str, Dict[str, str]],
        max_chars: int,
    ) -> List[ReferenceDocument]:
        documents: List[ReferenceDocument] = []
        for item in reference_files:
            original_name = str(item.get("filename") or Path(item["path"]).name)
            path = Path(item["path"])
            spec = specs.get(original_name) or specs.get(path.name) or {}
            reference_type = str(spec.get("type") or self._infer_reference_type(original_name, path)).strip() or "material"
            usage = str(spec.get("usage") or "").strip()
            text = self.extractor.extract(path, max_chars=max_chars)
            documents.append(
                ReferenceDocument(
                    filename=original_name,
                    path=path,
                    reference_type=reference_type,
                    usage=usage,
                    text=text,
                )
            )
        return documents

    def _infer_reference_type(self, filename: str, path: Path) -> str:
        lower = filename.lower()
        suffix = path.suffix.lower()
        if any(word in lower for word in ("brand", "品牌", "视觉", "规范")):
            return "brand"
        if suffix in {".csv", ".tsv", ".xlsx", ".json"}:
            return "data"
        if suffix in {".pptx", ".ppt"}:
            return "source_ppt"
        if any(word in lower for word in ("outline", "大纲", "提纲", "脚本", "文案")):
            return "outline"
        return "material"

    def _generate_plan(
        self,
        instruction: str,
        references: List[ReferenceDocument],
        llm_config: AgentLLMConfig,
        slide_count: int,
        language: str,
        audience: str,
        style: str,
    ) -> Dict[str, Any]:
        if not llm_config.enabled:
            return self._fallback_plan(instruction, references, slide_count, language, audience, style, "未配置 LLM，使用本地规则生成")
        messages = self._build_messages(instruction, references, slide_count, language, audience, style)
        try:
            payload = self.llm_client.complete_json(llm_config, messages)
            payload.setdefault("generation_mode", "llm")
            return payload
        except Exception as exc:
            fallback = self._fallback_plan(instruction, references, slide_count, language, audience, style, f"LLM 失败，使用本地规则生成：{exc}")
            fallback["llm_error"] = str(exc)
            return fallback

    def _build_messages(
        self,
        instruction: str,
        references: List[ReferenceDocument],
        slide_count: int,
        language: str,
        audience: str,
        style: str,
    ) -> List[Dict[str, str]]:
        reference_blocks: List[str] = []
        for index, ref in enumerate(references, start=1):
            usage = f"；用途：{ref.usage}" if ref.usage else ""
            reference_blocks.append(
                f"### 参考资料 {index}: {ref.filename}\n类型：{ref.reference_type}{usage}\n内容摘录：\n{ref.text}"
            )
        references_text = "\n\n".join(reference_blocks) or "无参考文件。"
        schema = {
            "title": "PPT标题",
            "subtitle": "可选副标题",
            "theme": {
                "tone": style,
                "audience": audience,
                "language": language,
                "design_rationale": "结合主题、受众、品牌或行业选择该视觉方向的原因",
                "palette_hint": "例如 tech_blue / warm_orange / emerald / burgundy / black_gold",
            },
            "slides": [
                {
                    "title": "页面标题",
                    "layout": "cover|section|bullets|two_column|quote|summary|cards|numbered|big_number|process|architecture|comparison|metrics|timeline",
                    "bullets": ["要点1", "要点2", "要点3"],
                    "kicker": "页面左上角短标签，可选",
                    "highlight": "本页最重要的短句或数字，可选",
                    "visual_spec": {
                        "type": "process|architecture|comparison|metrics|timeline|cards",
                        "items": ["图示节点1", "图示节点2", "图示节点3"],
                        "left_label": "对比左侧标签，可选",
                        "right_label": "对比右侧标签，可选",
                        "metrics": [{"label": "指标名", "value": "80%", "note": "指标说明"}]
                    },
                    "speaker_notes": "这一页完整口播文本，适合直接朗读。",
                    "visual_hint": "建议视觉元素或配图方向，例如数据卡片、流程、对比、时间线、品牌色块",
                }
            ],
        }
        user_prompt = f"""
请根据任务说明和参考资料，生成一份“像 Codex 能做出的高质量演示稿”的结构化 PPT 方案，并为每页写对应口播文本。

任务说明：
{instruction or "用户未填写自然语言说明，请主要根据参考资料生成。"}

生成要求：
- 页数：{slide_count} 页左右，必须结构完整。
- 语言：{language}。
- 受众：{audience}。
- 风格：{style}。
- 先理解主题、行业、受众和资料性质，再选择匹配的视觉情绪，不要机械套模板。
- 每页必须有明确的信息层级：kicker/标签、title/标题、highlight/强调点、bullets/支撑点。
- 每页 bullets 控制在 3-5 条，每条尽量短，避免堆满文字。
- layout 要根据内容选择：封面用 cover，章节切换用 section，三到四个并列点用 cards，步骤/路径用 process 或 numbered，系统组成用 architecture，指标表现用 metrics 或 big_number，对比差异用 comparison，路线规划用 timeline，拆解说明用 two_column。
- 每页要“图文并茂”：至少一半页面使用 process / architecture / comparison / metrics / timeline / cards 等图示化版式，不要全是文字 bullets。
- visual_spec 要把图里的节点、指标、标签写清楚，便于渲染成流程图、架构图、指标卡或对比图。
- visual_hint 要具体到视觉表达方式，例如“4 步流程箭头”“三层架构图”“左右对比矩阵”“3 张指标卡片”“时间线里程碑”。
- speaker_notes 是完整口播稿，不要只是 bullets 重复，建议 80-180 字。
- 严格只输出 JSON，不要输出 Markdown 包裹，不要输出解释文字。

JSON Schema 示例：
{json.dumps(schema, ensure_ascii=False, indent=2)}

参考资料：
{references_text}
""".strip()
        return [
            {
                "role": "system",
                "content": "你是一个顶级 PPT 设计与口播 Agent，擅长像 Codex 一样把需求和参考资料转成结构清晰、视觉高级、可直接制作的演示稿。你会先判断主题气质和受众，再给出内容、版式、视觉提示和逐页口播稿。",
            },
            {"role": "user", "content": user_prompt},
        ]

    def _fallback_plan(
        self,
        instruction: str,
        references: List[ReferenceDocument],
        slide_count: int,
        language: str,
        audience: str,
        style: str,
        reason: str,
    ) -> Dict[str, Any]:
        count = min(12, max(3, int(slide_count or 6)))
        title = self._derive_title(instruction, references)
        reference_names = [ref.filename for ref in references]
        reference_summary = "、".join(reference_names) if reference_names else "自然语言需求"
        base_topics = [
            ("封面", "cover", [title, f"面向：{audience}", f"风格：{style}"]),
            ("为什么需要 Agent 化", "comparison", ["资料整理、写稿、排版、配音割裂", "PPT 与口播文本经常不同步", "一个入口统一理解需求与资料", "自动生成 PPTX、讲稿和结构化计划"]),
            ("核心能力地图", "architecture", ["Web 配置层", "Agent 编排层", "资料解析", "LLM 规划", "PPT 渲染", "口播输出"]),
            ("生成链路", "process", ["输入需求", "解析资料", "规划页面", "渲染 PPT", "输出讲稿"]),
            ("效果指标", "metrics", ["效率提升：从小时到分钟", "一致性：PPT 与讲稿同步", "可编辑：保留人工复核空间", "可扩展：继续接入视频链路"]),
            ("参考资料解读", "two_column", [f"资料来源：{reference_summary}", "提取可用于 PPT 的核心事实", "区分背景、数据、品牌、案例等内容"]),
            ("核心观点", "cards", self._derive_points(instruction, references)),
            ("内容结构", "numbered", ["从问题进入", "用证据支撑观点", "给出方案或行动建议", "结尾强调下一步"]),
            ("落地路线图", "timeline", ["先生成初稿", "人工复核内容", "导出页面图片", "生成音频", "合成视频"]),
            ("风险与注意事项", "comparison", ["引用资料需核对来源", "敏感数据需要脱敏", "LLM 生成内容应人工复核", "模板和图表能力可继续增强"]),
            ("总结", "summary", ["回顾核心目标", "强调最重要结论", "明确下一步动作"]),
        ]
        if count <= len(base_topics):
            selected = [base_topics[0]] + base_topics[1 : count - 1] + [base_topics[-1]] if count > 3 else base_topics[:count]
        else:
            selected = base_topics[:]
            for index in range(len(base_topics) + 1, count + 1):
                selected.insert(-1, (f"补充页面 {index - len(base_topics)}", "bullets", ["补充细节", "展开案例", "完善论证"]))
        slides = []
        for index, (slide_title, layout, bullets) in enumerate(selected, start=1):
            if index == 1:
                script = f"大家好，今天分享的主题是《{title}》。这份内容基于{reference_summary}整理，目标是帮助{audience}快速理解背景、重点和后续行动。"
            else:
                joined = "，".join(bullets[:3])
                script = f"这一页我们重点说明{slide_title}。核心包括：{joined}。这里的内容是自动生成的初稿，建议结合业务事实进一步校准。"
            slides.append(
                {
                    "title": slide_title if index > 1 else title,
                    "layout": layout,
                    "bullets": bullets,
                    "kicker": "PPT VOICE AGENT" if index == 1 else f"STEP {index - 1:02d}",
                    "highlight": bullets[0] if bullets else slide_title,
                    "visual_spec": self._fallback_visual_spec(layout, bullets, slide_title),
                    "speaker_notes": script,
                    "visual_hint": "使用大标题、留白、卡片、强调色块和清晰信息层级呈现。",
                }
            )
        return {
            "title": title,
            "subtitle": f"由 PPT 口播 Agent 生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "theme": {
                "tone": style,
                "audience": audience,
                "language": language,
                "design_rationale": "本地规则根据受众和风格生成强调层级、留白和卡片化表达的演示稿。",
                "palette_hint": style,
            },
            "slides": slides,
            "generation_mode": "fallback",
            "fallback_reason": reason,
        }

    def _fallback_visual_spec(self, layout: str, bullets: List[str], title: str) -> Dict[str, Any]:
        if layout in {"process", "timeline", "architecture", "cards"}:
            return {"type": layout, "items": bullets}
        if layout == "comparison":
            midpoint = max(1, (len(bullets) + 1) // 2)
            return {
                "type": "comparison",
                "left_label": "传统方式",
                "right_label": "Agent 方式",
                "items": bullets,
                "left_items": bullets[:midpoint],
                "right_items": bullets[midpoint:],
            }
        if layout == "metrics":
            metrics = []
            for item in bullets[:4]:
                if "：" in item:
                    label, note = item.split("：", 1)
                    value = label
                else:
                    label, value, note = item[:6], item[:8], item
                metrics.append({"label": label, "value": value, "note": note})
            return {"type": "metrics", "metrics": metrics}
        return {"type": layout, "items": bullets or [title]}

    def _normalize_plan(
        self,
        payload: Dict[str, Any],
        instruction: str,
        references: List[ReferenceDocument],
        slide_count: int,
        language: str,
        audience: str,
        style: str,
    ) -> Dict[str, Any]:
        fallback = self._fallback_plan(instruction, references, slide_count, language, audience, style, "用于补齐缺失字段")
        title = str(payload.get("title") or fallback["title"]).strip()
        subtitle = str(payload.get("subtitle") or fallback.get("subtitle") or "").strip()
        slides_payload = payload.get("slides") if isinstance(payload.get("slides"), list) else []
        if not slides_payload:
            slides_payload = fallback["slides"]
        target_count = min(30, max(1, int(slide_count or len(slides_payload))))
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(slides_payload[:target_count], start=1):
            if not isinstance(item, dict):
                continue
            slide_title = str(item.get("title") or f"第{index}页").strip()
            layout = str(item.get("layout") or ("cover" if index == 1 else "bullets")).strip()
            if layout not in {
                "cover",
                "section",
                "bullets",
                "two_column",
                "quote",
                "summary",
                "cards",
                "numbered",
                "big_number",
                "process",
                "architecture",
                "comparison",
                "metrics",
                "timeline",
            }:
                layout = "bullets"
            bullets = item.get("bullets") or item.get("points") or item.get("key_points") or []
            bullets = self._normalize_bullets(bullets)
            if not bullets:
                bullets = fallback["slides"][min(index - 1, len(fallback["slides"]) - 1)]["bullets"]
            speaker_notes = str(item.get("speaker_notes") or item.get("script") or "").strip()
            if not speaker_notes:
                speaker_notes = f"这一页介绍{slide_title}。主要包括：{'，'.join(bullets[:3])}。"
            normalized.append(
                {
                    "page_index": index,
                    "title": slide_title,
                    "layout": layout,
                    "bullets": bullets[:6],
                    "kicker": str(item.get("kicker") or item.get("label") or "").strip(),
                    "highlight": str(item.get("highlight") or item.get("key_message") or "").strip(),
                    "visual_spec": item.get("visual_spec") if isinstance(item.get("visual_spec"), dict) else {},
                    "speaker_notes": speaker_notes,
                    "visual_hint": str(item.get("visual_hint") or "").strip(),
                }
            )
        while len(normalized) < target_count:
            index = len(normalized) + 1
            fallback_slide = fallback["slides"][min(index - 1, len(fallback["slides"]) - 1)]
            normalized.append({"page_index": index, **fallback_slide})
        return {
            "title": title,
            "subtitle": subtitle,
            "theme": payload.get("theme") if isinstance(payload.get("theme"), dict) else {"tone": style, "audience": audience, "language": language},
            "slides": normalized,
            "generation_mode": payload.get("generation_mode", "llm"),
            "fallback_reason": payload.get("fallback_reason"),
            "llm_error": payload.get("llm_error"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _normalize_bullets(self, bullets: Any) -> List[str]:
        if isinstance(bullets, str):
            parts = re.split(r"[\n；;]+", bullets)
        elif isinstance(bullets, list):
            parts = [str(item) for item in bullets]
        else:
            parts = []
        result: List[str] = []
        for part in parts:
            value = re.sub(r"^[-*•\d.、\s]+", "", str(part)).strip()
            if value:
                result.append(value)
        return result

    def _derive_title(self, instruction: str, references: List[ReferenceDocument]) -> str:
        for line in (instruction or "").splitlines():
            line = line.strip(" #，。,.\t")
            if line:
                return line[:42]
        if references:
            return f"基于{references[0].filename}的口播 PPT"
        return "AI 生成口播 PPT"

    def _derive_points(self, instruction: str, references: List[ReferenceDocument]) -> List[str]:
        source = instruction.strip()
        if not source and references:
            source = "\n".join(ref.text[:800] for ref in references[:2])
        sentences = [item.strip() for item in re.split(r"[。！？!?\n]+", source) if item.strip()]
        points = [sentence[:42] for sentence in sentences[:4]]
        while len(points) < 4:
            points.append(["聚焦核心问题", "用资料支撑结论", "形成清晰行动建议", "便于后续合成口播视频"][len(points)])
        return points

    def _safe_output_stem(self, output_name: str, title: str) -> str:
        stem = Path(output_name or "").stem or title or "agent_presentation"
        return sanitize_filename(stem, "agent_presentation")

    def _render_pptx(self, plan: Dict[str, Any], output_path: Path) -> None:
        self._render_pptx_ooxml(plan, output_path)

    def _render_pptx_ooxml(self, plan: Dict[str, Any], output_path: Path) -> None:
        palette = self._palette(str(plan.get("theme", {}).get("tone") or ""))
        slides = list(plan.get("slides") or [])
        if not slides:
            slides = [{"title": plan.get("title") or "Agent PPT", "layout": "cover", "bullets": [], "speaker_notes": ""}]

        if STABLE_TEMPLATE.is_file():
            self._render_pptx_from_template(plan, slides, palette, output_path, STABLE_TEMPLATE)
            return

        files: Dict[str, str] = {
            "[Content_Types].xml": self._pptx_content_types(len(slides)),
            "_rels/.rels": self._pptx_root_rels(),
            "docProps/core.xml": self._pptx_core_props(str(plan.get("title") or "Agent PPT")),
            "docProps/app.xml": self._pptx_app_props(len(slides)),
            "ppt/presentation.xml": self._pptx_presentation_xml(len(slides)),
            "ppt/_rels/presentation.xml.rels": self._pptx_presentation_rels(len(slides)),
            "ppt/theme/theme1.xml": self._pptx_theme_xml(),
            "ppt/slideMasters/slideMaster1.xml": self._pptx_slide_master_xml(),
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": self._pptx_slide_master_rels(),
            "ppt/slideLayouts/slideLayout1.xml": self._pptx_slide_layout_xml(),
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": self._pptx_slide_layout_rels(),
        }
        for index, slide in enumerate(slides, start=1):
            files[f"ppt/slides/slide{index}.xml"] = self._pptx_slide_xml(plan, slide, index, palette)
            files[f"ppt/slides/_rels/slide{index}.xml.rels"] = self._pptx_slide_rels()

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content.encode("utf-8"))

    def _render_pptx_from_template(
        self,
        plan: Dict[str, Any],
        slides: List[Dict[str, Any]],
        palette: Dict[str, str],
        output_path: Path,
        template_path: Path,
    ) -> None:
        skip_prefixes = (
            "ppt/slides/",
            "ppt/notesSlides/",
            "ppt/comments/",
            "ppt/tags/",
        )
        skip_names = {
            "[Content_Types].xml",
            "ppt/presentation.xml",
            "ppt/_rels/presentation.xml.rels",
            "ppt/commentAuthors.xml",
        }
        with zipfile.ZipFile(template_path) as src, zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as dst:
            written: set[str] = set()
            for item in src.infolist():
                name = item.filename
                if name in skip_names or any(name.startswith(prefix) for prefix in skip_prefixes):
                    continue
                dst.writestr(item, src.read(name))
                written.add(name)

            presentation_rels, slide_rel_ids = self._pptx_presentation_rels_from_template(src, len(slides))
            generated: Dict[str, str] = {
                "[Content_Types].xml": self._pptx_content_types_from_template(src, len(slides)),
                "ppt/presentation.xml": self._pptx_presentation_xml_from_template(src, len(slides), slide_rel_ids),
                "ppt/_rels/presentation.xml.rels": presentation_rels,
            }
            for index, slide in enumerate(slides, start=1):
                generated[f"ppt/slides/slide{index}.xml"] = self._pptx_slide_xml(plan, slide, index, palette)
                generated[f"ppt/slides/_rels/slide{index}.xml.rels"] = self._pptx_slide_rels("../slideLayouts/slideLayout7.xml")
            for name, content in generated.items():
                if name not in written:
                    dst.writestr(name, content.encode("utf-8"))
                    written.add(name)

    def _pptx_content_types_from_template(self, archive: zipfile.ZipFile, slide_count: int) -> str:
        root = self._et_from_zip(archive, "[Content_Types].xml")
        ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        for elem in list(root):
            part_name = elem.attrib.get("PartName", "")
            if part_name.startswith("/ppt/slides/") or part_name.startswith("/ppt/notesSlides/") or part_name.startswith("/ppt/comments/") or part_name == "/ppt/commentAuthors.xml" or part_name.startswith("/ppt/tags/"):
                root.remove(elem)
        for index in range(1, slide_count + 1):
            override = self._et_element(
                f"{ns}Override",
                {
                    "PartName": f"/ppt/slides/slide{index}.xml",
                    "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
                },
            )
            root.append(override)
        return self._et_to_xml(root)

    def _pptx_presentation_rels_from_template(self, archive: zipfile.ZipFile, slide_count: int) -> tuple[str, List[str]]:
        root = self._et_from_zip(archive, "ppt/_rels/presentation.xml.rels")
        ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        for elem in list(root):
            rel_type = elem.attrib.get("Type", "")
            if rel_type.endswith("/slide") or rel_type.endswith("/commentAuthors") or rel_type.endswith("/tags"):
                root.remove(elem)
        used_ids = {elem.attrib.get("Id") for elem in root}
        next_id = 1
        slide_rel_ids: List[str] = []
        for index in range(1, slide_count + 1):
            while f"rId{next_id}" in used_ids:
                next_id += 1
            rel_id = f"rId{next_id}"
            used_ids.add(rel_id)
            slide_rel_ids.append(rel_id)
            root.append(
                self._et_element(
                    f"{ns}Relationship",
                    {
                        "Id": rel_id,
                        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                        "Target": f"slides/slide{index}.xml",
                    },
                )
            )
            next_id += 1
        return self._et_to_xml(root), slide_rel_ids

    def _pptx_presentation_xml_from_template(self, archive: zipfile.ZipFile, slide_count: int, slide_rel_ids: List[str]) -> str:
        root = self._et_from_zip(archive, "ppt/presentation.xml")
        ns = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
        custom_data = root.find(f"{ns}custDataLst")
        if custom_data is not None:
            root.remove(custom_data)
        slide_list = root.find(f"{ns}sldIdLst")
        if slide_list is None:
            slide_master_list = root.find(f"{ns}sldMasterIdLst")
            insert_index = list(root).index(slide_master_list) + 1 if slide_master_list is not None else 0
            slide_list = self._et_element(f"{ns}sldIdLst", {})
            root.insert(insert_index, slide_list)
        for elem in list(slide_list):
            slide_list.remove(elem)
        for index in range(1, slide_count + 1):
            slide_list.append(
                self._et_element(
                    f"{ns}sldId",
                    {"id": str(255 + index), "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": slide_rel_ids[index - 1]},
                )
            )
        return self._et_to_xml(root)

    def _et_from_zip(self, archive: zipfile.ZipFile, name: str):
        import xml.etree.ElementTree as ET

        return ET.fromstring(archive.read(name))

    def _et_element(self, tag: str, attrib: Dict[str, str]):
        import xml.etree.ElementTree as ET

        return ET.Element(tag, attrib)

    def _et_to_xml(self, root: Any) -> str:
        import xml.etree.ElementTree as ET

        if isinstance(root.tag, str) and root.tag.startswith("{"):
            uri = root.tag[1:].split("}", 1)[0]
            ET.register_namespace("", uri)
            if uri == "http://schemas.openxmlformats.org/presentationml/2006/main":
                ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
                ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
        return "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n" + ET.tostring(root, encoding="unicode", short_empty_elements=True)

    def _pptx_slide_xml(self, plan: Dict[str, Any], slide: Dict[str, Any], index: int, palette: Dict[str, str]) -> str:
        shape_id = 1

        def next_id() -> int:
            nonlocal shape_id
            shape_id += 1
            return shape_id

        def rect(x: float, y: float, w: float, h: float, color: str, radius: str = "rect", line: str = "none") -> str:
            sid = next_id()
            line_xml = '<a:ln><a:noFill/></a:ln>' if line == "none" else f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"Rectangle {sid}\"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"{radius}\"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill>{line_xml}</p:spPr>
          <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
        </p:sp>"""

        def ellipse(x: float, y: float, w: float, h: float, color: str) -> str:
            sid = next_id()
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"Ellipse {sid}\"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"ellipse\"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>
          <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
        </p:sp>"""

        def text_box(
            text: str,
            x: float,
            y: float,
            w: float,
            h: float,
            size: int,
            color: str,
            bold: bool = False,
            align: str = "l",
        ) -> str:
            sid = next_id()
            paragraphs = self._pptx_paragraphs([text], size=size, color=color, bold=bold, align=align)
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"TextBox {sid}\"/><p:cNvSpPr txBox=\"1\"/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
          <p:txBody><a:bodyPr wrap=\"square\" anchor=\"t\"/><a:lstStyle/>{paragraphs}</p:txBody>
        </p:sp>"""

        def bullet_box(bullets: List[str], x: float, y: float, w: float, h: float, size: int, color: Optional[str] = None) -> str:
            sid = next_id()
            lines = [f"• {item}" for item in bullets if str(item).strip()]
            paragraphs = self._pptx_paragraphs(lines or [""], size=size, color=color or palette["text"], bold=False, align="l")
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"Bullets {sid}\"/><p:cNvSpPr txBox=\"1\"/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
          <p:txBody><a:bodyPr wrap=\"square\" anchor=\"t\"/><a:lstStyle/>{paragraphs}</p:txBody>
        </p:sp>"""

        def card(x: float, y: float, w: float, h: float, title_text: str, body_text: str, number: str = "") -> List[str]:
            content = [rect(x, y, w, h, palette["card"], "roundRect", palette["line"])]
            if number:
                content.append(ellipse(x + 0.25, y + 0.25, 0.46, 0.46, palette["accent_soft"]))
                content.append(text_box(number, x + 0.31, y + 0.32, 0.34, 0.18, 10, palette["accent"], True, "ctr"))
                content.append(text_box(title_text, x + 0.82, y + 0.22, w - 1.05, 0.34, 15, palette["title"], True))
            else:
                content.append(text_box(title_text, x + 0.3, y + 0.24, w - 0.6, 0.34, 15, palette["title"], True))
            content.append(text_box(body_text, x + 0.3, y + 0.82, w - 0.6, h - 1.0, 12, palette["muted"]))
            return content

        def arrow(x: float, y: float, w: float, h: float, color: str) -> str:
            sid = next_id()
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"Arrow {sid}\"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"rightArrow\"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>
          <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
        </p:sp>"""

        def chevron(x: float, y: float, w: float, h: float, color: str) -> str:
            sid = next_id()
            return f"""
        <p:sp>
          <p:nvSpPr><p:cNvPr id=\"{sid}\" name=\"Chevron {sid}\"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x=\"{self._emu(x)}\" y=\"{self._emu(y)}\"/><a:ext cx=\"{self._emu(w)}\" cy=\"{self._emu(h)}\"/></a:xfrm><a:prstGeom prst=\"chevron\"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>
          <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
        </p:sp>"""

        def connector(x1: float, y1: float, x2: float, y2: float, color: str, width: int = 19050) -> str:
            x = min(x1, x2)
            y = min(y1, y2)
            thickness = max(0.018, min(0.08, width / 914400 / 2))
            w = abs(x2 - x1)
            h = abs(y2 - y1)
            if w >= h:
                return rect(x, y - thickness / 2, max(w, 0.02), thickness, color)
            return rect(x - thickness / 2, y, thickness, max(h, 0.02), color)

        def visual_items() -> List[str]:
            spec = slide.get("visual_spec") if isinstance(slide.get("visual_spec"), dict) else {}
            items = spec.get("items") if isinstance(spec.get("items"), list) else []
            return [str(item) for item in items if str(item).strip()] or bullets

        def metric_items() -> List[Dict[str, str]]:
            spec = slide.get("visual_spec") if isinstance(slide.get("visual_spec"), dict) else {}
            metrics = spec.get("metrics") if isinstance(spec.get("metrics"), list) else []
            result: List[Dict[str, str]] = []
            for metric in metrics:
                if isinstance(metric, dict):
                    result.append({
                        "label": str(metric.get("label") or "指标"),
                        "value": str(metric.get("value") or "—"),
                        "note": str(metric.get("note") or ""),
                    })
            if result:
                return result
            fallback_metrics = bullets[:4] or [highlight or title]
            return [{"label": f"指标 {idx}", "value": item.split("：", 1)[0][:10], "note": item} for idx, item in enumerate(fallback_metrics, start=1)]

        layout = str(slide.get("layout") or "bullets")
        title = str(slide.get("title") or f"第{index}页")
        bullets = [str(item) for item in slide.get("bullets") or []]
        kicker = str(slide.get("kicker") or "").strip() or f"SECTION {index:02d}"
        highlight = str(slide.get("highlight") or "").strip()
        if not highlight and bullets:
            highlight = bullets[0]
        shapes = [
            rect(0, 0, 13.333, 7.5, palette["bg"]),
            ellipse(10.75, -0.85, 3.0, 3.0, palette["wash"]),
            ellipse(-1.05, 5.85, 2.45, 2.45, palette["wash2"]),
            rect(0.62, 6.9, 12.1, 0.018, palette["line"]),
        ]
        if layout == "cover" or index == 1:
            shapes.extend(
                [
                    rect(0.65, 0.58, 12.0, 6.25, palette["cover_panel"], "roundRect"),
                    rect(8.92, 0.58, 3.73, 6.25, palette["accent"], "roundRect"),
                    ellipse(9.42, 1.16, 2.75, 2.75, palette["accent_deep"]),
                    ellipse(10.35, 4.35, 1.3, 1.3, palette["accent_soft"]),
                    text_box(kicker.upper(), 1.02, 1.02, 4.9, 0.28, 11, palette["accent"], True),
                    text_box(str(plan.get("title") or title), 1.0, 1.58, 7.35, 1.45, 40, palette["title"], True),
                    text_box(str(plan.get("subtitle") or title), 1.04, 3.15, 7.0, 0.58, 17, palette["muted"]),
                    bullet_box(bullets[:3], 1.05, 4.05, 6.9, 1.65, 18),
                    text_box("PPT\nAGENT", 9.48, 2.38, 2.55, 0.96, 28, palette["accent_text"], True, "ctr"),
                    text_box("Story · Design · Script", 9.35, 3.38, 2.88, 0.26, 10, palette["accent_text"], False, "ctr"),
                ]
            )
        elif layout == "section":
            shapes.extend(
                [
                    rect(1.0, 1.35, 11.3, 4.55, palette["card"], "roundRect", palette["line"]),
                    rect(1.0, 1.35, 0.14, 4.55, palette["accent"], "rect"),
                    text_box(kicker.upper(), 1.55, 2.12, 3.8, 0.28, 11, palette["accent"], True),
                    text_box(title, 1.5, 2.55, 10.1, 0.95, 35, palette["title"], True),
                    text_box(highlight or " / ".join(bullets[:2]), 1.54, 3.68, 9.7, 0.6, 18, palette["muted"]),
                ]
            )
        elif layout == "two_column":
            midpoint = max(1, (len(bullets) + 1) // 2)
            shapes.extend(
                [
                    text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                    text_box(title, 0.78, 0.82, 8.3, 0.6, 28, palette["title"], True),
                    text_box(highlight, 9.3, 0.82, 3.1, 0.58, 15, palette["muted"], False, "r"),
                    rect(0.85, 1.72, 5.7, 4.65, palette["card"], "roundRect", palette["line"]),
                    rect(6.8, 1.72, 5.7, 4.65, palette["card_alt"], "roundRect", palette["line"]),
                    rect(1.18, 2.02, 1.25, 0.08, palette["accent"]),
                    rect(7.13, 2.02, 1.25, 0.08, palette["accent2"]),
                    bullet_box(bullets[:midpoint], 1.18, 2.38, 5.02, 3.45, 18),
                    bullet_box(bullets[midpoint:] or bullets[:midpoint], 7.13, 2.38, 5.02, 3.45, 18),
                ]
            )
        elif layout == "cards":
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.6, 0.62, 29, palette["title"], True),
                text_box(highlight, 9.45, 0.84, 2.9, 0.52, 14, palette["muted"], False, "r"),
            ])
            card_items = bullets[:4] or [highlight or title]
            positions = [(0.86, 1.78), (6.82, 1.78), (0.86, 4.18), (6.82, 4.18)]
            for item_index, item in enumerate(card_items[:4], start=1):
                x, y = positions[item_index - 1]
                shapes.extend(card(x, y, 5.68, 1.78, item, slide.get("visual_hint") or "围绕该要点展开讲解。", f"{item_index}"))
        elif layout == "numbered":
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                rect(0.9, 1.82, 0.05, 4.35, palette["line"]),
            ])
            for item_index, item in enumerate((bullets or [highlight])[:5], start=1):
                y = 1.62 + (item_index - 1) * 0.88
                shapes.append(ellipse(0.68, y + 0.03, 0.48, 0.48, palette["accent"] if item_index == 1 else palette["accent_soft"]))
                shapes.append(text_box(str(item_index), 0.78, y + 0.15, 0.28, 0.15, 10, palette["accent_text"] if item_index == 1 else palette["accent"], True, "ctr"))
                shapes.append(text_box(item, 1.32, y, 10.5, 0.45, 18, palette["text"], item_index == 1))
        elif layout == "big_number":
            big = highlight or (bullets[0] if bullets else title)
            rest = bullets[1:] if bullets and big == bullets[0] else bullets
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                rect(0.92, 1.82, 5.0, 4.45, palette["accent"], "roundRect"),
                ellipse(4.8, 1.38, 1.75, 1.75, palette["accent_deep"]),
                text_box(big, 1.25, 2.66, 4.25, 0.86, 38, palette["accent_text"], True, "ctr"),
                bullet_box(rest or bullets, 6.55, 2.02, 5.55, 3.7, 20),
            ])
        elif layout == "process":
            items = visual_items()[:5]
            if len(items) < 3:
                items = (items + bullets + ["输入", "理解", "生成", "输出"])[:4]
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                text_box(highlight, 9.25, 0.84, 3.05, 0.52, 14, palette["muted"], False, "r"),
            ])
            start_x = 0.9
            gap = 0.22
            step_w = (11.55 - gap * (len(items) - 1)) / len(items)
            for item_index, item in enumerate(items, start=1):
                x = start_x + (item_index - 1) * (step_w + gap)
                shapes.append(rect(x, 2.05, step_w, 2.05, palette["card"], "roundRect", palette["line"]))
                shapes.append(ellipse(x + 0.28, 2.33, 0.56, 0.56, palette["accent"] if item_index == 1 else palette["accent_soft"]))
                shapes.append(text_box(str(item_index), x + 0.39, 2.47, 0.32, 0.16, 10, palette["accent_text"] if item_index == 1 else palette["accent"], True, "ctr"))
                shapes.append(text_box(item, x + 0.28, 3.08, step_w - 0.56, 0.72, 16, palette["title"], True, "ctr"))
                if item_index < len(items):
                    shapes.append(chevron(x + step_w - 0.03, 2.82, 0.35, 0.46, palette["accent2"]))
            shapes.append(rect(1.15, 4.82, 10.9, 0.9, palette["card_alt"], "roundRect", palette["line"]))
            shapes.append(text_box("输出结果", 1.45, 5.08, 1.55, 0.24, 12, palette["accent"], True))
            shapes.append(text_box("PPTX · scripts.json · plan.json · bundle.zip", 3.0, 5.03, 7.7, 0.32, 19, palette["title"], True))
        elif layout == "architecture":
            items = visual_items()[:6]
            while len(items) < 6:
                items.append(["Web 配置层", "Agent 编排层", "参考资料解析", "LLM 规划", "PPT 渲染", "口播输出"][len(items)])
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                text_box(highlight, 9.25, 0.84, 3.05, 0.52, 14, palette["muted"], False, "r"),
                rect(0.92, 1.72, 11.55, 4.85, palette["card"], "roundRect", palette["line"]),
                rect(1.28, 2.05, 10.83, 0.84, palette["accent"], "roundRect"),
                text_box(items[0], 1.55, 2.28, 10.2, 0.22, 15, palette["accent_text"], True, "ctr"),
                rect(1.28, 3.25, 3.15, 1.25, palette["card_alt"], "roundRect", palette["line"]),
                rect(5.08, 3.25, 3.15, 1.25, palette["card_alt"], "roundRect", palette["line"]),
                rect(8.9, 3.25, 3.15, 1.25, palette["card_alt"], "roundRect", palette["line"]),
                connector(2.85, 2.9, 2.85, 3.25, palette["accent2"]),
                connector(6.65, 2.9, 6.65, 3.25, palette["accent2"]),
                connector(10.45, 2.9, 10.45, 3.25, palette["accent2"]),
                text_box(items[1], 1.55, 3.68, 2.6, 0.22, 14, palette["title"], True, "ctr"),
                text_box(items[2], 5.35, 3.68, 2.6, 0.22, 14, palette["title"], True, "ctr"),
                text_box(items[3], 9.17, 3.68, 2.6, 0.22, 14, palette["title"], True, "ctr"),
                rect(2.1, 5.05, 3.45, 0.82, palette["accent_soft"], "roundRect"),
                rect(7.78, 5.05, 3.45, 0.82, palette["accent_soft"], "roundRect"),
                connector(4.43, 4.5, 4.0, 5.05, palette["accent2"]),
                connector(8.23, 4.5, 9.5, 5.05, palette["accent2"]),
                text_box(items[4], 2.36, 5.3, 2.95, 0.2, 13, palette["accent"], True, "ctr"),
                text_box(items[5], 8.04, 5.3, 2.95, 0.2, 13, palette["accent"], True, "ctr"),
            ])
        elif layout == "comparison":
            spec = slide.get("visual_spec") if isinstance(slide.get("visual_spec"), dict) else {}
            left_label = str(spec.get("left_label") or "传统方式")
            right_label = str(spec.get("right_label") or "Agent 方式")
            left_items = spec.get("left_items") if isinstance(spec.get("left_items"), list) else []
            right_items = spec.get("right_items") if isinstance(spec.get("right_items"), list) else []
            left_items = [str(item) for item in left_items if str(item).strip()]
            right_items = [str(item) for item in right_items if str(item).strip()]
            if not left_items or not right_items:
                midpoint = max(1, (len(bullets) + 1) // 2)
                left_items = bullets[:midpoint]
                right_items = bullets[midpoint:] or bullets[:midpoint]
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                rect(0.9, 1.75, 5.55, 4.75, palette["card"], "roundRect", palette["line"]),
                rect(6.85, 1.75, 5.55, 4.75, palette["card_alt"], "roundRect", palette["line"]),
                rect(0.9, 1.75, 5.55, 0.72, palette["muted"], "roundRect"),
                rect(6.85, 1.75, 5.55, 0.72, palette["accent"], "roundRect"),
                text_box(left_label, 1.22, 1.98, 4.9, 0.2, 14, palette["accent_text"], True, "ctr"),
                text_box(right_label, 7.17, 1.98, 4.9, 0.2, 14, palette["accent_text"], True, "ctr"),
                bullet_box(left_items, 1.25, 2.82, 4.8, 2.9, 17),
                bullet_box(right_items, 7.2, 2.82, 4.8, 2.9, 17),
                arrow(6.28, 3.48, 0.42, 0.38, palette["accent2"]),
            ])
        elif layout == "metrics":
            metrics = metric_items()[:4]
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                text_box(highlight, 9.25, 0.84, 3.05, 0.52, 14, palette["muted"], False, "r"),
            ])
            positions = [(0.9, 1.8), (6.8, 1.8), (0.9, 4.05), (6.8, 4.05)]
            for item_index, metric in enumerate(metrics, start=1):
                x, y = positions[item_index - 1]
                shapes.append(rect(x, y, 5.55, 1.72, palette["card"], "roundRect", palette["line"]))
                shapes.append(rect(x, y, 0.12, 1.72, palette["accent"] if item_index % 2 else palette["accent2"]))
                shapes.append(text_box(metric["value"], x + 0.38, y + 0.34, 1.8, 0.42, 26, palette["accent"], True))
                shapes.append(text_box(metric["label"], x + 2.15, y + 0.36, 2.8, 0.25, 15, palette["title"], True))
                shapes.append(text_box(metric["note"], x + 2.15, y + 0.82, 2.9, 0.32, 11, palette["muted"]))
        elif layout == "timeline":
            items = visual_items()[:5]
            while len(items) < 4:
                items.append(["启动", "生成", "复核", "发布"][len(items)])
            shapes.extend([
                text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                connector(1.35, 3.62, 11.7, 3.62, palette["line"], 25400),
            ])
            start_x = 1.2
            step = 10.2 / max(1, len(items) - 1)
            for item_index, item in enumerate(items, start=1):
                x = start_x + (item_index - 1) * step
                shapes.append(ellipse(x - 0.22, 3.4, 0.44, 0.44, palette["accent"] if item_index == 1 else palette["accent_soft"]))
                shapes.append(text_box(str(item_index), x - 0.1, 3.52, 0.2, 0.12, 8, palette["accent_text"] if item_index == 1 else palette["accent"], True, "ctr"))
                y = 2.1 if item_index % 2 else 4.25
                shapes.append(rect(x - 1.05, y, 2.1, 0.78, palette["card"], "roundRect", palette["line"]))
                shapes.append(text_box(item, x - 0.88, y + 0.22, 1.75, 0.18, 12, palette["title"], True, "ctr"))
                shapes.append(connector(x, y + (0.78 if item_index % 2 else 0), x, 3.4 if item_index % 2 else 3.84, palette["line"], 12700))
        elif layout == "quote":
            quote = textwrap.shorten(str(slide.get("speaker_notes") or " ".join(bullets)), width=180, placeholder="...")
            shapes.extend(
                [
                    text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                    text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                    rect(1.12, 1.85, 11.05, 3.9, palette["card"], "roundRect", palette["line"]),
                    text_box("“", 1.55, 2.1, 0.8, 0.7, 44, palette["accent"], True),
                    text_box(quote, 2.35, 2.18, 8.6, 1.95, 25, palette["text"], False, "ctr"),
                    text_box("— 口播重点", 8.95, 4.85, 2.45, 0.25, 12, palette["muted"], False, "r"),
                ]
            )
        else:
            shapes.extend(
                [
                    text_box(kicker.upper(), 0.82, 0.5, 4.2, 0.25, 10, palette["accent"], True),
                    text_box(title, 0.78, 0.82, 8.8, 0.62, 29, palette["title"], True),
                    rect(0.9, 1.7, 11.6, 4.85, palette["card"], "roundRect", palette["line"]),
                    text_box(highlight, 1.22, 2.02, 10.6, 0.5, 21, palette["title"], True),
                    bullet_box(bullets[1:] if bullets and highlight == bullets[0] else bullets, 1.3, 2.85, 10.4, 3.1, 20),
                ]
            )
        shapes.append(text_box(f"{index:02d}", 12.25, 6.85, 0.55, 0.25, 11, palette["muted"], False, "r"))
        if slide.get("visual_hint"):
            shapes.append(text_box(f"视觉建议：{slide['visual_hint']}", 0.82, 6.77, 8.7, 0.28, 10, palette["muted"]))

        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:sld xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    def _pptx_paragraphs(self, lines: List[str], size: int, color: str, bold: bool = False, align: str = "l") -> str:
        bold_attr = ' b="1"' if bold else ""
        paragraphs: List[str] = []
        for line in lines:
            parts = str(line).splitlines() or [""]
            for part in parts:
                paragraphs.append(
                    f"<a:p><a:pPr algn=\"{align}\"/><a:r><a:rPr lang=\"zh-CN\" sz=\"{int(size) * 100}\"{bold_attr}><a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill><a:latin typeface=\"Arial\"/><a:ea typeface=\"Microsoft YaHei\"/></a:rPr><a:t>{self._xml_text(part)}</a:t></a:r></a:p>"
                )
        return "".join(paragraphs)

    def _emu(self, inches: float) -> int:
        return int(float(inches) * 914400)

    def _xml_text(self, value: Any) -> str:
        return html.escape(str(value), quote=False)

    def _pptx_content_types(self, slide_count: int) -> str:
        slide_overrides = "".join(
            f'<Override PartName=\"/ppt/slides/slide{index}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slide+xml\"/>'
            for index in range(1, slide_count + 1)
        )
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>
  <Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>
  <Override PartName=\"/ppt/presentation.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml\"/>
  <Override PartName=\"/ppt/slideMasters/slideMaster1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml\"/>
  <Override PartName=\"/ppt/slideLayouts/slideLayout1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml\"/>
  <Override PartName=\"/ppt/theme/theme1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.theme+xml\"/>
  {slide_overrides}
</Types>"""

    def _pptx_root_rels(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"ppt/presentation.xml\"/>
  <Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>
  <Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/>
</Relationships>"""

    def _pptx_core_props(self, title: str) -> str:
        created = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">
  <dc:title>{self._xml_text(title)}</dc:title>
  <dc:creator>PPT Voice Agent</dc:creator>
  <cp:lastModifiedBy>PPT Voice Agent</cp:lastModifiedBy>
  <dcterms:created xsi:type=\"dcterms:W3CDTF\">{created}</dcterms:created>
  <dcterms:modified xsi:type=\"dcterms:W3CDTF\">{created}</dcterms:modified>
</cp:coreProperties>"""

    def _pptx_app_props(self, slide_count: int) -> str:
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">
  <Application>PPT Voice Agent</Application>
  <PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides>
  <Notes>0</Notes>
  <HiddenSlides>0</HiddenSlides>
  <MMClips>0</MMClips>
  <ScaleCrop>false</ScaleCrop>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0000</AppVersion>
</Properties>"""

    def _pptx_presentation_xml(self, slide_count: int, slide_rel_ids: Optional[List[str]] = None) -> str:
        rel_ids = slide_rel_ids or [f"rId{index + 1}" for index in range(1, slide_count + 1)]
        slide_ids = "".join(f'<p:sldId id=\"{255 + index}\" r:id=\"{rel_ids[index - 1]}\"/>' for index in range(1, slide_count + 1))
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:presentation xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" saveSubsetFonts=\"1\">
  <p:sldMasterIdLst><p:sldMasterId id=\"2147483648\" r:id=\"rId1\"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx=\"12192000\" cy=\"6858000\" type=\"screen16x9\"/>
  <p:notesSz cx=\"6858000\" cy=\"9144000\"/>
</p:presentation>"""

    def _pptx_presentation_rels(self, slide_count: int) -> str:
        slide_rels = "".join(
            f'<Relationship Id=\"rId{index + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide\" Target=\"slides/slide{index}.xml\"/>'
            for index in range(1, slide_count + 1)
        )
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster\" Target=\"slideMasters/slideMaster1.xml\"/>
  {slide_rels}
</Relationships>"""

    def _pptx_slide_rels(self, layout_target: str = "../slideLayouts/slideLayout1.xml") -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout\" Target=\"__LAYOUT_TARGET__\"/>
</Relationships>""".replace("__LAYOUT_TARGET__", layout_target)

    def _pptx_slide_master_rels(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout\" Target=\"../slideLayouts/slideLayout1.xml\"/>
  <Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme\" Target=\"../theme/theme1.xml\"/>
</Relationships>"""

    def _pptx_slide_layout_rels(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster\" Target=\"../slideMasters/slideMaster1.xml\"/>
</Relationships>"""

    def _pptx_slide_master_xml(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:sldMaster xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1=\"lt1\" tx1=\"dk1\" bg2=\"lt2\" tx2=\"dk2\" accent1=\"accent1\" accent2=\"accent2\" accent3=\"accent3\" accent4=\"accent4\" accent5=\"accent5\" accent6=\"accent6\" hlink=\"hlink\" folHlink=\"folHlink\"/>
  <p:sldLayoutIdLst><p:sldLayoutId id=\"2147483649\" r:id=\"rId1\"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>"""

    def _pptx_slide_layout_xml(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:sldLayout xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" type=\"blank\" preserve=\"1\">
  <p:cSld name=\"Blank\"><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

    def _pptx_theme_xml(self) -> str:
        return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<a:theme xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" name=\"PPT Voice Agent Theme\">
  <a:themeElements>
    <a:clrScheme name=\"Agent\"><a:dk1><a:srgbClr val=\"1F2937\"/></a:dk1><a:lt1><a:srgbClr val=\"FFFFFF\"/></a:lt1><a:dk2><a:srgbClr val=\"334155\"/></a:dk2><a:lt2><a:srgbClr val=\"F8FAFC\"/></a:lt2><a:accent1><a:srgbClr val=\"0F766E\"/></a:accent1><a:accent2><a:srgbClr val=\"2563EB\"/></a:accent2><a:accent3><a:srgbClr val=\"D97706\"/></a:accent3><a:accent4><a:srgbClr val=\"7C3AED\"/></a:accent4><a:accent5><a:srgbClr val=\"DB2777\"/></a:accent5><a:accent6><a:srgbClr val=\"059669\"/></a:accent6><a:hlink><a:srgbClr val=\"2563EB\"/></a:hlink><a:folHlink><a:srgbClr val=\"7C3AED\"/></a:folHlink></a:clrScheme>
    <a:fontScheme name=\"Agent\"><a:majorFont><a:latin typeface=\"Arial\"/><a:ea typeface=\"Microsoft YaHei\"/><a:cs typeface=\"Arial\"/></a:majorFont><a:minorFont><a:latin typeface=\"Arial\"/><a:ea typeface=\"Microsoft YaHei\"/><a:cs typeface=\"Arial\"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name=\"Agent\"><a:fillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w=\"6350\"><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
  <a:objectDefaults/><a:extraClrSchemeLst/>
</a:theme>"""

    def _palette(self, style: str) -> Dict[str, str]:
        lower = style.lower()
        if any(word in lower for word in ("科技", "tech", "ai", "智能", "系统", "平台", "codex", "深色", "dark")):
            return {
                "bg": "F7F8FF",
                "cover_panel": "FFFFFF",
                "card": "FFFFFF",
                "card_alt": "EEF2FF",
                "line": "DDE3F8",
                "title": "101828",
                "text": "25304D",
                "muted": "667085",
                "accent": "4F46E5",
                "accent2": "06B6D4",
                "accent_deep": "312E81",
                "accent_soft": "DDE7FF",
                "accent_text": "FFFFFF",
                "wash": "E0E7FF",
                "wash2": "D8F3FF",
            }
        if any(word in lower for word in ("温暖", "活泼", "增长", "营销", "运营", "用户", "warm", "orange")):
            return {
                "bg": "FFF8EF",
                "cover_panel": "FFFFFF",
                "card": "FFFFFF",
                "card_alt": "FFF0D9",
                "line": "F1DEC7",
                "title": "3D2614",
                "text": "5A371E",
                "muted": "8A6A50",
                "accent": "EA580C",
                "accent2": "F59E0B",
                "accent_deep": "9A3412",
                "accent_soft": "FED7AA",
                "accent_text": "FFFFFF",
                "wash": "FFE7CC",
                "wash2": "FFE1B8",
            }
        if any(word in lower for word in ("高端", "黑金", "金融", "战略", "管理层", "luxury", "gold")):
            return {
                "bg": "F8F5EE",
                "cover_panel": "111111",
                "card": "FFFFFF",
                "card_alt": "F1E7D2",
                "line": "E3D3B4",
                "title": "141414",
                "text": "2E2A24",
                "muted": "766B5D",
                "accent": "A77A2B",
                "accent2": "7C5A1E",
                "accent_deep": "4A3513",
                "accent_soft": "E8D7B1",
                "accent_text": "FFFFFF",
                "wash": "F0E4C8",
                "wash2": "E8D7B1",
            }
        if any(word in lower for word in ("极简", "黑白", "灰", "研究", "报告", "杂志", "minimal", "mono")):
            return {
                "bg": "F7F7F5",
                "cover_panel": "FFFFFF",
                "card": "FFFFFF",
                "card_alt": "EFEFEC",
                "line": "D8D8D2",
                "title": "111111",
                "text": "2B2B2B",
                "muted": "6F6F69",
                "accent": "111111",
                "accent2": "6F6F69",
                "accent_deep": "000000",
                "accent_soft": "E7E7E2",
                "accent_text": "FFFFFF",
                "wash": "EDEDE8",
                "wash2": "E2E2DC",
            }
        if any(word in lower for word in ("品牌", "发布", "活动", "产品", "活力", "colorful", "brand")):
            return {
                "bg": "FFF7FB",
                "cover_panel": "FFFFFF",
                "card": "FFFFFF",
                "card_alt": "FCE7F3",
                "line": "F8CBE0",
                "title": "3D2F68",
                "text": "4B3B70",
                "muted": "7A6A93",
                "accent": "F8275B",
                "accent2": "7C3AED",
                "accent_deep": "3D2F68",
                "accent_soft": "FFD4E1",
                "accent_text": "FFFFFF",
                "wash": "FFE0EA",
                "wash2": "EDE2FF",
            }
        return {
            "bg": "F7FAF9",
            "cover_panel": "FFFFFF",
            "card": "FFFFFF",
            "card_alt": "EAF7F4",
            "line": "D6E8E3",
            "title": "16312F",
            "text": "263F3C",
            "muted": "667A76",
            "accent": "0F766E",
            "accent2": "14B8A6",
            "accent_deep": "134E4A",
            "accent_soft": "CCFBF1",
            "accent_text": "FFFFFF",
            "wash": "D9F8F0",
            "wash2": "E5F5ED",
        }

    def _build_scripts(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": plan.get("title"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "pages": [
                {
                    "page_index": index,
                    "image": f"slide_{index:03d}.png",
                    "slide_title": slide.get("title"),
                    "script": slide.get("speaker_notes") or "",
                }
                for index, slide in enumerate(plan.get("slides") or [], start=1)
            ],
        }

    def _build_manifest(self, plan: Dict[str, Any], references: List[ReferenceDocument], pptx_path: Path, scripts_path: Path) -> str:
        lines = [
            f"# {plan.get('title') or 'Agent PPT'}",
            "",
            f"- PPTX：`{pptx_path.name}`",
            f"- 口播文本：`{scripts_path.name}`",
            f"- 生成模式：`{plan.get('generation_mode')}`",
            "",
            "## 参考资料",
        ]
        if references:
            for ref in references:
                lines.append(f"- `{ref.filename}`：{ref.reference_type}，{len(ref.text)} 字")
        else:
            lines.append("- 无参考文件")
        lines.extend(["", "## 页面清单"])
        for slide in plan.get("slides") or []:
            lines.append(f"- 第{slide.get('page_index')}页：{slide.get('title')}")
        return "\n".join(lines) + "\n"

    def _write_bundle(self, bundle_path: Path, files: List[Path]) -> None:
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)

    def _progress(self, callback: Optional[Callable[[str], None]], message: str) -> None:
        if callback:
            callback(message)
