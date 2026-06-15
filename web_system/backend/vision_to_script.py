from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class VisionToScriptInput:
    page_index: int
    image_path: str
    image_format: str = "png"
    prompt: str = "根据这页PPT图片生成适合口播的中文讲解文本"
    constraints: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "image_path": self.image_path,
            "image_format": self.image_format,
            "prompt": self.prompt,
            "constraints": self.constraints or ["中文", "适合口播", "不超过120字"],
        }


@dataclass
class VisionToScriptOutput:
    page_index: int
    prompt: str
    script: str
    raw_response: dict[str, Any]


def generate_script(payload: VisionToScriptInput) -> VisionToScriptOutput:
    raw_response = {
        "provider": "placeholder",
        "model": "vision-to-text",
        "input": payload.to_dict(),
        "output": {
            "script": f"第{payload.page_index}页的口播文本待外部大模型生成。",
        },
    }
    return VisionToScriptOutput(
        page_index=payload.page_index,
        prompt=payload.prompt,
        script=raw_response["output"]["script"],
        raw_response=raw_response,
    )
