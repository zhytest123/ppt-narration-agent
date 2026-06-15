# Runtime 目录说明

`web_system/runtime/` 用于管理 TTS / 声纹运行时。

当前 GitHub 仓库提交运行时代码，但不直接提交大模型权重和默认声纹。大资产请上传到腾讯云 COS，然后回填：

```text
web_system/runtime/assets_manifest.json
```

回填每个资产的 `cos_url` 后执行：

```bash
cd web_system/runtime
python3 download_assets.py
```

下载完成后，默认运行时目录应具备：

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

也可以在启动时显式指定外部运行时目录：

```bash
CHAT_TTS_SOURCE_ROOT=/your/path/ChatTTS-OpenVoice-Tools ./run.sh
```

运行时的模型权重、默认声纹、`tmp/`、`outputs/` 等不会提交到 GitHub。
