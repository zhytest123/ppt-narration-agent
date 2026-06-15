# Runtime 目录说明

`web_system/runtime/` 管理声纹提取、TTS 和 OpenVoice 声音转换所需的运行时代码与模型资产清单。

## 下载模型资产

```bash
cd web_system
python3 runtime/download_assets.py
```

下载脚本读取：

```text
web_system/runtime/assets_manifest.json
```

并把模型放到运行时需要的原始路径中。

## 默认运行时目录

```text
web_system/runtime/ChatTTS-OpenVoice-Tools/
├── extract_voiceprint.py
├── text_to_speech.py
├── tools_common.py
├── ChatTTS/
├── OpenVoice/
├── ChatTTS_Model/
└── voiceprints/
```

## 自定义运行时

也可以在启动时显式指定外部运行时目录：

```bash
CHAT_TTS_SOURCE_ROOT=/your/path/ChatTTS-OpenVoice-Tools ./run.sh
```

## 模型来源

- ChatTTS：`https://huggingface.co/2Noise/ChatTTS`
- OpenVoice：`https://huggingface.co/myshell-ai/OpenVoice`

运行时生成的模型权重、声纹、`tmp/`、`outputs/` 等文件不会提交到 GitHub。
