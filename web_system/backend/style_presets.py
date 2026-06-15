from __future__ import annotations

from typing import Any, Dict, List


STYLE_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "business_clean",
        "name": "商务简洁",
        "description": "适合内部评审、项目汇报、产品方案，强调清晰、稳重、可读性。",
        "style_prompt": "商务简洁，高级留白，深青绿色强调色，白底卡片，适合内部评审和项目汇报",
        "keywords": ["商务", "简洁", "评审", "项目汇报"],
    },
    {
        "id": "tech_ai",
        "name": "科技 AI",
        "description": "适合 AI、平台、系统架构、技术方案，强调蓝紫科技感和结构图。",
        "style_prompt": "科技 AI 高级 Codex 风格，蓝紫配色，强信息层级，流程图、架构图和指标卡片",
        "keywords": ["科技", "AI", "智能", "系统", "平台", "Codex"],
    },
    {
        "id": "black_gold",
        "name": "高端黑金",
        "description": "适合战略汇报、管理层材料、商业计划，强调质感、克制和高端感。",
        "style_prompt": "高端 黑金 战略风格，黑金配色，强对比，大标题，适合管理层战略汇报",
        "keywords": ["高端", "黑金", "战略", "管理层", "金融"],
    },
    {
        "id": "warm_growth",
        "name": "温暖增长",
        "description": "适合增长、运营、营销、用户研究，强调暖色、活力和行动感。",
        "style_prompt": "温暖 增长 营销风格，橙色暖调，活泼但不花哨，适合运营增长和用户研究",
        "keywords": ["温暖", "增长", "营销", "运营", "用户"],
    },
    {
        "id": "minimal_mono",
        "name": "极简黑白",
        "description": "适合研究报告、深度分析、知识分享，强调黑白灰、留白和文字秩序。",
        "style_prompt": "极简 黑白灰 杂志风格，大留白，强文字秩序，少色彩，适合研究报告和知识分享",
        "keywords": ["极简", "黑白", "研究", "报告", "杂志"],
    },
    {
        "id": "brand_colorful",
        "name": "活力品牌",
        "description": "适合品牌展示、产品发布、活动宣讲，强调鲜明色块和视觉冲击。",
        "style_prompt": "活力 品牌 发布会风格，鲜明色块，强视觉冲击，适合产品发布和活动宣讲",
        "keywords": ["品牌", "发布", "活动", "产品", "活力"],
    },
]


def get_style_preset(preset_id: str) -> Dict[str, Any] | None:
    preset_id = (preset_id or "").strip()
    for preset in STYLE_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None


def compose_style_prompt(preset_id: str, custom_style: str, legacy_style: str = "") -> str:
    custom_style = (custom_style or "").strip()
    legacy_style = (legacy_style or "").strip()
    preset = get_style_preset(preset_id)
    if preset and custom_style:
        return f"{preset['style_prompt']}；自定义要求：{custom_style}"
    if preset:
        return str(preset["style_prompt"])
    if custom_style:
        return custom_style
    return legacy_style or "商务简洁"

