# Web System

这是一个本地可运行的口播 PPT Agent 工作台，包含 Agent 生成 PPT、声纹提取、PDF 切图、图片 + 口播稿合成视频等能力。运行时代码随项目提供，模型资产由下载脚本按需获取。

当前提供四个模块：

1. 输入自然语言或参考文件，生成 PPTX 与逐页口播文本
2. 上传音频，提取声纹
3. 上传 PDF，分割成图片并下载
4. 上传图片序列和 `scripts.json`，选择声纹，合成视频

## 一、运行时说明

项目默认从下面目录读取 TTS / 声纹运行时：

```text
web_system/runtime/ChatTTS-OpenVoice-Tools/
```

该目录中的运行时代码随仓库提交；模型权重不直接提交到 GitHub，可通过 `runtime/download_assets.py` 下载。运行时生成的 `tmp/`、`outputs/` 不提交。

声纹提取和视频合成功能需要该目录中至少包含：

- `extract_voiceprint.py`
- `text_to_speech.py`
- `tools_common.py`
- `ChatTTS/`
- `OpenVoice/`
- `ChatTTS_Model/`
- `voiceprints/`

也可以通过环境变量显式指定外部运行时：

```bash
CHAT_TTS_SOURCE_ROOT=/your/runtime/ChatTTS-OpenVoice-Tools ./run.sh
```

首次克隆后如需声纹提取或视频合成，请执行 `python3 runtime/download_assets.py` 下载真实权重。只使用“Agent 生成 PPT + 口播文本”功能时，不依赖这些模型权重。

## 二、当前能力

### 1. Agent 生成 PPT + 口播文本

- 支持输入自然语言需求
- 支持上传参考资料：`txt / md / csv / json / yaml / html / pdf / pptx / docx / xlsx`
- 支持在 Web 端配置 OpenAI 兼容 LLM 接口：`base_url / model / api_key / headers / temperature / timeout`
- 支持给每个参考文件指定类型和用途，例如 `outline / material / data / brand / source_ppt`
- 输出 `.pptx`、逐页口播 `scripts.json`、完整打包 ZIP
- 如果未配置 LLM，会使用本地规则生成可编辑初稿，便于先跑通流程

### 2. 声纹提取

- 支持上传 `m4a / mp3 / wav / aac / flac / ogg`
- 调用内置 `extract_voiceprint.py`
- 可将提取出的声纹保存到工作区
- 前端可直接选择已有声纹或新提取的声纹

### 3. PDF 切图

- 支持上传 PDF
- 按页渲染成图片
- 可下载切图结果 ZIP
- 可指定渲染倍率、导出格式、页码范围、输出文件名前缀

### 4. 图片文稿合成视频

- 上传一组图片和一个 `scripts.json`
- 选择声纹
- 调用内置 `text_to_speech.py` 逐页生成音频
- 使用 `ffmpeg` 将图片和音频拼接为 MP4

### 5. 图生文占位接口

- 当前未接入真实视觉大模型
- 已定义输入输出格式
- 后续只需要替换占位实现即可

## 三、目录结构

当前项目核心结构如下：

```text
web_system/
├── backend/
│   ├── agent_pipeline.py
│   ├── app.py
│   ├── pipeline.py
│   └── vision_to_script.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── runtime/
│   ├── README.md
│   └── ChatTTS-OpenVoice-Tools/  # 本地放置，默认不提交
├── workspace/
│   ├── jobs/
│   ├── outputs/
│   └── voiceprints/
├── requirements.txt
├── run.sh
└── README.md
```

### 目录职责

- `backend/`
  - FastAPI 接口、Agent 生成链路和视频处理流程
- `frontend/`
  - 静态页面和前端交互
- `runtime/README.md`
  - 说明如何在本地放置 TTS / 声纹运行时
- `runtime/ChatTTS-OpenVoice-Tools/`
  - 本地 TTS / 声纹运行时目录，默认不提交 GitHub
- `workspace/voiceprints/`
  - Web 页面新提取出的声纹
- `workspace/jobs/`
  - 每次任务的中间目录
- `workspace/outputs/`
  - 最终生成的 PPTX、口播 JSON、打包 ZIP 和视频

## 四、运行环境要求

运行 Web 服务和 Agent PPT 生成功能只需要普通 Python 依赖。声纹提取和视频合成额外有两个运行前提：

### 1. Python 环境

Web 服务层依赖普通 Python 即可运行。

当前默认启动脚本里：

- Web 服务通过 `uvicorn` 启动
- 声纹提取和 TTS 子进程默认使用当前 `python3`
- 如需使用独立 TTS 环境，可通过 `CHAT_TTS_PYTHON` 和 `CHAT_TTS_BIN` 覆盖

示例：

```bash
CHAT_TTS_PYTHON=/path/to/env/bin/python CHAT_TTS_BIN=/path/to/env/bin ./run.sh
```

### 2. ffmpeg / ffprobe

必须可用。否则：

- 声纹提取可能失败
- 视频合成一定失败

如果设置了 `CHAT_TTS_BIN`，`run.sh` 会优先把它加入 `PATH`，便于找到 `ffmpeg` 和 `ffprobe`。

## 五、安装

安装 Web 层依赖：

```bash
cd web_system
python3 -m pip install -r requirements.txt
```

当前依赖：

- `fastapi`
- `uvicorn`
- `python-multipart`
- `PyMuPDF`
- `imageio-ffmpeg`

## 六、启动

### 1. 正常启动

```bash
cd web_system
./run.sh
```

默认地址：

```text
http://127.0.0.1:8000
```

### 2. 开发热重载

```bash
cd web_system
DEV_RELOAD=1 ./run.sh
```

### 3. 自定义端口

```bash
cd web_system
PORT=9000 ./run.sh
```

### 4. 自定义默认设备

```bash
CHAT_TTS_DEVICE=cpu ./run.sh
```

或者：

```bash
CHAT_TTS_DEVICE=auto ./run.sh
```

### 5. 自定义运行时目录

如果运行时没有放在默认目录，也可以显式指定：

```bash
CHAT_TTS_SOURCE_ROOT=/your/runtime/ChatTTS-OpenVoice-Tools ./run.sh
```

## 七、页面使用流程

### 场景 0：用 Agent 生成 PPT 与口播文本

1. 打开页面
2. 在“Agent 生成 PPT + 口播文本”模块填写自然语言需求
3. 可选上传参考文件，例如需求文档、旧 PPT、品牌规范、数据表、案例资料
4. 可选填写“参考文件类型与用途 JSON”
5. 可选配置 LLM 接口；如果留空，系统会用本地规则生成初稿
6. 设置页数、语言、目标受众和设计风格
7. 点击“生成 PPT 与口播文本”
8. 等待任务完成后下载 PPTX、口播 JSON 或完整 ZIP

参考文件类型与用途 JSON 示例：

```json
[
  { "filename": "brand.pdf", "type": "brand", "usage": "作为品牌和视觉规范" },
  { "filename": "data.xlsx", "type": "data", "usage": "作为指标事实来源" },
  { "filename": "outline.md", "type": "outline", "usage": "作为页面结构优先参考" }
]
```

LLM 接口要求：

- 使用 OpenAI 兼容的 `POST /v1/chat/completions`
- `base_url` 可以填写到域名或 `/v1`，系统会自动拼接 `/chat/completions`
- `api_key` 只用于本次请求，不写入配置文件或数据库
- 模型返回需要是 JSON；如果 LLM 返回不可解析内容，系统会降级成本地规则初稿

### 场景 A：先提取声纹

1. 打开页面
2. 在“提取声纹”模块上传音频
3. 填声纹名称，或者留空使用原音频文件名
4. 点击“提取声纹”
5. 成功后，新的声纹会自动出现在下拉框

推荐：

- 上传 10 到 60 秒的单人音频
- 背景噪音越少越好
- 一般直接选 `cpu`

### 场景 B：先把 PDF 拆成图片

1. 在“PDF 分割图片”模块上传 PDF
2. 设置渲染倍率或页码范围
3. 点击“分割并下载图片 ZIP”
4. 下载并解压图片

推荐：

- `render_scale=2.0`
- `image_format=png`
- `end_page=0`

### 场景 C：上传图片和文稿直接合成视频

1. 准备图片序列
2. 准备 `scripts.json`
3. 在“图片 + scripts.json + 声纹合成视频”模块上传文件
4. 选择声纹
5. 保持默认参数或按需调整
6. 点击“开始合成视频”
7. 等待任务完成
8. 下载生成的视频

## 八、内置声纹与工作区声纹

系统会自动扫描两个位置的声纹：

### 1. 内置声纹

目录：

```text
web_system/runtime/ChatTTS-OpenVoice-Tools/voiceprints/
```

当前默认包含：

- `mzh.pt`
- `sty.pt`
- `zhy.pt`

### 2. 工作区声纹

目录：

```text
web_system/workspace/voiceprints/
```

通过 Web 页面提取出的新声纹会保存在这里。

## 九、参数说明

### 0. Agent 生成参数

当前前端支持：

- `instruction`
- `reference_files`
- `reference_specs_json`
- `llm_base_url`
- `llm_model`
- `llm_api_key`
- `llm_temperature`
- `llm_timeout`
- `custom_headers_json`
- `output_name`
- `slide_count`
- `language`
- `audience`
- `style_preset`
- `custom_style`
- `style`
- `max_reference_chars`

说明：

- `instruction`
  - 自然语言任务说明，例如“生成 8 页产品宣讲 PPT，面向内部评审”
- `reference_files`
  - 可上传多个参考文件，系统会抽取文本作为生成依据
- `reference_specs_json`
  - 指定每个文件的内容类型和使用方式
- `llm_base_url / llm_model / llm_api_key`
  - OpenAI 兼容接口配置；不填时走本地规则生成
- `custom_headers_json`
  - 用于网关或内部代理需要的额外请求头
- `slide_count`
  - 目标页数，范围 `1` 到 `30`
- `style_preset`
  - PPT 风格预设 ID，Web 页面会展示为下拉选项
- `custom_style`
  - 自定义风格补充，可描述品牌色、参考对象、版式偏好、图示偏好
- `style`
  - 兼容旧接口的风格字段；新页面会根据 `style_preset` 自动写入隐藏字段
  - 生成器会参考 Codex 风格 PPT 的原则：强信息层级、充足留白、大标题、强调色块、卡片化内容、两栏拆解和数字化表达
- `max_reference_chars`
  - 单个参考文件最多抽取字符数，防止超长文档拖慢生成

当前内置风格预设：

- `business_clean`：商务简洁，适合内部评审、项目汇报、产品方案
- `tech_ai`：科技 AI，适合 AI、平台、系统架构、技术方案
- `black_gold`：高端黑金，适合战略汇报、管理层材料、商业计划
- `warm_growth`：温暖增长，适合增长、运营、营销、用户研究
- `minimal_mono`：极简黑白，适合研究报告、深度分析、知识分享
- `brand_colorful`：活力品牌，适合品牌展示、产品发布、活动宣讲

当前内置版式：

- `cover`
  - 封面，大标题 + 大色块 + 右侧品牌区域
- `section`
  - 章节页，适合承上启下
- `cards`
  - 2x2 卡片，适合 3-4 个并列观点
- `numbered`
  - 步骤页，适合流程、路径、行动计划
- `big_number`
  - 大数字/大结论页，适合关键指标或主张
- `process`
  - 横向流程图，适合从输入到输出的链路说明
- `architecture`
  - 架构图，适合系统分层、模块关系和生成链路
- `comparison`
  - 左右对比图，适合传统方式 vs Agent 方式、方案 A vs 方案 B
- `metrics`
  - 指标卡片，适合效率、一致性、成本、质量等价值展示
- `timeline`
  - 路线图/时间线，适合里程碑和后续规划
- `two_column`
  - 双栏拆解，适合对比、资料解读、方案拆分
- `quote / summary / bullets`
  - 观点页、总结页和通用要点页

推荐值：

- `slide_count=6`
- `language=中文`
- `audience=业务评审 / 内部分享`
- `style_preset=business_clean`
- `custom_style=按需填写，例如“多用架构图，品牌主色 #FF6600”`
- `max_reference_chars=16000`

### 1. 声纹提取参数

当前前端支持：

- `device`
- `force`

说明：

- `device`
  - 可选 `auto / cpu / cuda`
  - 兼容性最好的是 `cpu`
- `force`
  - 允许覆盖同名声纹

推荐值：

- `device=cpu`
- `force=开启`

### 2. PDF 切图参数

当前前端支持：

- `render_scale`
- `image_format`
- `image_prefix`
- `start_page`
- `end_page`

说明：

- `render_scale`
  - 渲染倍率，越大越清晰，但文件更大
- `image_format`
  - 推荐 `png`
- `image_prefix`
  - 输出文件名前缀
- `start_page`
  - 起始页，从 `1` 开始
- `end_page`
  - 结束页，`0` 表示直到最后一页

推荐值：

- `render_scale=2.0`
- `image_format=png`
- `image_prefix=page`
- `start_page=1`
- `end_page=0`

### 3. TTS 参数

当前前端支持：

- `tts_device`
- `speaker_seed`
- `text_seed`
- `temperature`
- `top_p`
- `top_k`
- `max_new_token`
- `no_refine`
- `refine_prompt`
- `keep_temp_audio`

说明：

- `tts_device`
  - 推理设备
- `speaker_seed`
  - 说话风格随机种子
- `text_seed`
  - 文本生成随机种子
- `temperature`
  - 随机性强度
- `top_p`
  - 采样截断阈值
- `top_k`
  - 采样候选数量
- `max_new_token`
  - 超长文案才需要调大
- `no_refine`
  - 关闭文案润色
- `refine_prompt`
  - 控制口语化、停顿等风格
- `keep_temp_audio`
  - 保留 TTS 中间源音频

推荐值：

- `tts_device=cpu`
- `speaker_seed=42`
- `text_seed=42`
- `temperature=0.3`
- `top_p=0.7`
- `top_k=20`
- `max_new_token=2048`
- `no_refine=关闭`
- `refine_prompt=[oral_2][laugh_0][break_6]`

### 4. 视频参数

当前前端支持：

- `video_fps`
- `video_crf`
- `video_preset`
- `audio_bitrate`
- `keep_temp`

说明：

- `video_fps`
  - 输出帧率
- `video_crf`
  - 画质参数，越小越清晰
- `video_preset`
  - 编码速度和压缩率权衡
- `audio_bitrate`
  - 音频码率
- `keep_temp`
  - 保留任务中间文件

推荐值：

- `video_fps=25`
- `video_crf=23`
- `video_preset=medium`
- `audio_bitrate=128k`
- `keep_temp=关闭`

## 十、输入文件格式

### 0. Agent 生成输入

至少提供以下两类输入之一：

- 自然语言需求 `instruction`
- 参考文件 `reference_files`

支持的参考文件格式：

- 文本类：`.txt / .md / .csv / .tsv / .json / .yaml / .yml / .html`
- 文档类：`.pdf / .pptx / .docx / .xlsx`

Agent 输出：

- `*.pptx`
  - 可编辑 PPT 文件
- `*_scripts.json`
  - 逐页口播文本，后续可人工改写，也可作为视频合成上游材料
- `*_plan.json`
  - Agent 生成的结构化中间计划
- `*_bundle.zip`
  - 包含 PPTX、口播 JSON、计划 JSON 和清单 Markdown

注意：Agent 生成的 `scripts.json` 中图片名默认是 `slide_001.png`、`slide_002.png`。如果要继续走“图片 + scripts.json + 声纹合成视频”，需要先把 PPTX 导出成对应命名的图片，或手动把 JSON 里的 `image` 改成实际图片文件名。

### 1. 声纹提取输入

上传一个支持的音频文件即可。

### 2. PDF 切图输入

上传一个 `.pdf` 文件即可。

### 3. 视频合成输入

需要同时提供：

- 一个 `scripts.json`
- 一组图片文件
- 一个选中的声纹

### scripts.json 格式

```json
{
  "pages": [
    { "image": "page_001.png", "script": "第1页口播文案" },
    { "image": "page_002.png", "script": "第2页口播文案" }
  ]
}
```

要求：

- `pages` 必须是非空数组
- 顺序就是最终视频顺序
- `image` 必须与上传图片文件名完全一致
- `script` 必须是非空字符串

推荐图片命名方式：

```text
page_001.png
page_002.png
page_003.png
```

## 十一、图生文模块输入输出约定

代码位置：

- `backend/vision_to_script.py`

### 输入格式

```json
{
  "page_index": 1,
  "image_path": "/abs/path/page_001.png",
  "image_format": "png",
  "prompt": "根据这页PPT图片生成适合口播的中文讲解文本",
  "constraints": ["中文", "适合口播", "不超过120字"]
}
```

### 输出格式

```json
{
  "page_index": 1,
  "prompt": "根据这页PPT图片生成适合口播的中文讲解文本",
  "script": "第1页的口播文本待外部大模型生成。",
  "raw_response": {
    "provider": "placeholder",
    "model": "vision-to-text",
    "input": {
      "page_index": 1,
      "image_path": "/abs/path/page_001.png",
      "image_format": "png",
      "prompt": "根据这页PPT图片生成适合口播的中文讲解文本",
      "constraints": ["中文", "适合口播", "不超过120字"]
    },
    "output": {
      "script": "..."
    }
  }
}
```

当前只是占位协议，后续接真实模型时建议保持该结构不变。

## 十二、输出目录

### 1. 声纹输出

```text
web_system/workspace/voiceprints/
```

### 2. Agent / 视频输出

```text
web_system/workspace/outputs/
```

包含：

- Agent 生成的 PPTX
- Agent 生成的口播 JSON
- Agent 生成的打包 ZIP
- 视频合成输出 MP4

### 3. 任务中间文件

```text
web_system/workspace/jobs/
```

如果开启 `keep_temp`，会保留：

- 上传图片
- 生成音频
- 分段视频
- 拼接列表

## 十三、接口说明

### 0. 获取 Agent 输入协议

```text
GET /api/contracts/agent-input
```

### 0.1 获取 PPT 风格预设

```text
GET /api/style-presets
```

返回：

- `id`
- `name`
- `description`
- `style_prompt`
- `keywords`

### 1. 创建 Agent 生成任务

```text
POST /api/agent-jobs
```

表单字段：

- `instruction`
- `reference_files`
- `reference_specs_json`
- `llm_base_url`
- `llm_api_key`
- `llm_model`
- `llm_temperature`
- `llm_timeout`
- `custom_headers_json`
- `output_name`
- `slide_count`
- `language`
- `audience`
- `style_preset`
- `custom_style`
- `style`
- `max_reference_chars`

### 2. 查询 Agent 任务状态

```text
GET /api/agent-jobs/{job_id}
```

### 3. 下载 Agent 生成结果

```text
GET /api/agent-jobs/{job_id}/pptx
GET /api/agent-jobs/{job_id}/scripts
GET /api/agent-jobs/{job_id}/bundle
```

### 4. 获取声纹列表

```text
GET /api/voiceprints
```

### 5. 提取声纹

```text
POST /api/voiceprints/extract
```

表单字段：

- `audio`
- `output_name`
- `device`
- `force`

### 6. PDF 切图

```text
POST /api/pdf/split
```

表单字段：

- `pdf`
- `render_scale`
- `image_format`
- `image_prefix`
- `start_page`
- `end_page`

返回：

- 图片 ZIP 文件流

### 7. 获取 scripts.json 协议

```text
GET /api/contracts/scripts-json
```

### 8. 创建视频任务

```text
POST /api/video-jobs
```

表单字段：

- `scripts_file`
- `images`
- `voiceprint_id`
- `output_name`
- `keep_temp`
- `tts_device`
- `speaker_seed`
- `text_seed`
- `temperature`
- `top_p`
- `top_k`
- `max_new_token`
- `no_refine`
- `refine_prompt`
- `keep_temp_audio`
- `video_fps`
- `video_crf`
- `video_preset`
- `audio_bitrate`

### 9. 查询视频任务状态

```text
GET /api/video-jobs/{job_id}
```

### 10. 下载视频

```text
GET /api/video-jobs/{job_id}/video
```

## 十四、模型资产与本地文件

Agent 生成 PPT 与口播稿只依赖 Web 服务层。声纹提取、TTS 和视频合成需要额外模型资产，首次使用前执行：

```bash
cd web_system
python3 runtime/download_assets.py
```

下载脚本会读取：

```text
web_system/runtime/assets_manifest.json
```

并把 ChatTTS 与 OpenVoice 所需模型放到运行时目录。

模型与运行时参考：

- ChatTTS：`https://huggingface.co/2Noise/ChatTTS`
- OpenVoice：`https://huggingface.co/myshell-ai/OpenVoice`
- ChatTTS-OpenVoice：`https://github.com/HKoon/ChatTTS-OpenVoice`

本地任务、输出视频、临时音频和新提取声纹会保存在 `web_system/workspace/` 或运行时临时目录中。

## 十五、常见问题

### 1. `uvicorn: command not found`

先安装依赖：

```bash
cd web_system
python3 -m pip install -r requirements.txt
```

然后重新执行：

```bash
./run.sh
```

### 2. `ffprobe` 或 `ffmpeg` 找不到

说明当前环境的多媒体工具不可用。

需要确认：

- `ffmpeg`
- `ffprobe`

是否在当前 `PATH` 中可用。若它们在独立环境中，可通过 `CHAT_TTS_BIN=/path/to/env/bin ./run.sh` 指定。

### 3. 声纹提取失败

排查方向：

- 音频格式是否支持
- 音频是否损坏
- 是否多人说话
- `ffmpeg/ffprobe` 是否可用
- 同名文件是否冲突

### 4. PDF 切图失败

排查方向：

- 是否真的是 PDF
- PDF 是否损坏
- 页码范围是否非法
- `render_scale` 是否填写错误

### 5. 视频合成失败

排查方向：

- `scripts.json` 是否是合法 JSON
- 图片文件名是否和 `scripts.json` 完全一致
- 声纹是否存在
- `ffmpeg` 是否可用
- 输出参数是否异常

### 6. Agent 生成失败

排查方向：

- 是否至少填写了自然语言需求或上传参考文件
- `reference_specs_json` 是否是合法 JSON
- `slide_count` 是否在 `1` 到 `30` 之间
- 如果配置了 LLM，`base_url / model / api_key` 是否正确
- LLM 服务是否兼容 `/v1/chat/completions`
- 如果 LLM 失败，系统通常会降级生成本地规则初稿，并在任务详情里返回 `llm_error`

### 7. 页面改了但看不到变化

尝试：

1. 强制刷新浏览器
2. 重新打开页面
3. 重启 `./run.sh`

## 十六、当前限制

- Agent 生成 PPT 已升级为 Codex 风格的高颜值基础模板，但还不是完整设计系统
- Agent 生成的 PPTX 是可编辑初稿，复杂品牌模板、真实图表、自动配图和图片占位还需要继续扩展
- 图生文模块尚未接真实外部视觉模型
- 当前视频是静态图片 + 配音拼接
- 没有字幕、转场、片头片尾模板
- 更适合本地单机使用

## 十七、后续可继续扩展

- 自动完成：PDF -> 切图 -> 图生文 -> TTS -> 视频
- 自动完成：自然语言 / 参考文件 -> PPTX -> 导出图片 -> TTS -> 视频
- 支持 PPTX 自动导出图片并一键接入视频合成
- 支持品牌模板、图表、封面模板和页面视觉策略
- 增加高级参数折叠面板
- 支持任务历史
- 支持字幕、水印、封面、片头片尾
