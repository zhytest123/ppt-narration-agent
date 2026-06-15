# ChatTTS-OpenVoice-Tools

这是一个命令行工具包，用于文本转语音和声纹提取。项目已包含运行所需的源码、ChatTTS 模型、OpenVoice checkpoint 和默认声纹。

## 目录结构

```text
ChatTTS-OpenVoice-Tools/
  ChatTTS/                         # ChatTTS 源码
  ChatTTS_Model/                   # ChatTTS 本地模型文件
  OpenVoice/                       # OpenVoice 源码和 checkpoint
  voiceprints/
    sty.pt                         # 默认声纹
  outputs/                         # 输出音频目录
  tmp/                             # 临时文件目录
  extract_voiceprint.py            # 工具 1：音频 -> 声纹特征
  text_to_speech.py                # 工具 2：文本 -> 使用声纹生成音频
  extract_voiceprint.sh            # macOS/Linux 入口
  text_to_speech.sh                # macOS/Linux 入口
  requirements.txt                 # Python 依赖
  tools_common.py                  # 公共工具函数
```

## 环境要求

- Python 3.10
- PyTorch 2.12+
- ffmpeg
- macOS (Apple Silicon 或 Intel)

## 安装步骤

### 1. 创建 conda 环境

```bash
conda create -n chattts-openvoice python=3.10 -y
conda activate chattts-openvoice
```

### 2. 安装 ffmpeg

```bash
conda install -c conda-forge ffmpeg -y
```

### 3. 安装 PyTorch

使用清华镜像源加速下载：

```bash
pip install torch torchvision torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 安装项目依赖

```bash
cd /path/to/ChatTTS-OpenVoice-Tools
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 5. 设置脚本执行权限

```bash
chmod +x extract_voiceprint.sh text_to_speech.sh
```

## 使用方法

### 工具 1：提取声纹

从音频文件提取声纹特征：

```bash
./extract_voiceprint.sh /path/to/audio.m4a -o voiceprints/my_voice.pt --device cpu
```

参数说明：
- `audio`: 输入音频文件（支持 wav/mp3/m4a 等格式）
- `-o, --output`: 输出声纹文件路径
- `--device`: 推理设备（auto/cuda/cpu），macOS 建议使用 cpu
- `--force`: 覆盖已有输出并刷新缓存

参考音频建议：
- 单人说话，背景安静
- 无音乐或多人对话
- 5-30 秒时长

### 工具 2：文本转语音

使用声纹生成语音：

```bash
./text_to_speech.sh --text "你好，这是测试语音。" -o outputs/demo.wav --device cpu
```

从文件读取文本：

```bash
./text_to_speech.sh --text-file input.txt -o outputs/output.wav --device cpu
```

使用自定义声纹：

```bash
./text_to_speech.sh --text "使用自定义声音。" --voiceprint voiceprints/my_voice.pt -o outputs/custom.wav --device cpu
```

常用参数：
- `--text`: 直接输入文本
- `--text-file`: 从 UTF-8 文本文件读取
- `-o, --output`: 输出 wav 路径
- `--voiceprint`: 声纹文件（默认 voiceprints/sty.pt）
- `--device`: 推理设备（默认 auto，macOS 上会自动选择 cpu）
- `--speaker-seed`: ChatTTS 说话人 seed（默认 42）
- `--text-seed`: ChatTTS 文本 seed（默认 42）
- `--temperature`: 默认 0.3
- `--top-p`: 默认 0.7
- `--top-k`: 默认 20
- `--no-refine`: 关闭文本润色
- `--keep-temp`: 保留中间 ChatTTS 源 wav

## 性能说明

### macOS CPU 模式

- **提取声纹**: OpenVoice converter 约占用 126 MB 内存
- **文本转语音**: ChatTTS 模型约占用 1038 MB 内存，OpenVoice 约 126 MB
- **推荐配置**: 至少 8 GB RAM，16 GB 更佳
- **速度**: CPU 模式比 GPU 慢，短句通常几十秒，长文本可能需要数分钟

### 设备选择

- macOS 上 `--device auto` 会自动选择 CPU
- 当前工具未启用 MPS（Metal Performance Shaders）加速
- 如需 GPU 加速，建议在配备 NVIDIA GPU 的 Linux/Windows 机器上运行

## 注意事项

1. **模型文件**: 项目已包含所有必需的模型文件，无需额外下载
2. **网络依赖**: 首次运行可能需要下载一些 Python 包的依赖
3. **兼容性**: 已修复 PyTorch 2.12+ 的 `weights_only` 兼容性问题
4. **缓存清理**: 运行过程中会在 `tmp/` 目录生成缓存，可定期清理

## 故障排除

### 如果遇到 PyTorch 加载错误

确保已修复 `ChatTTS/core.py` 中的 `torch.load` 调用，添加 `weights_only=False` 参数。

### 如果音频生成失败

1. 检查 ffmpeg 是否正确安装：`ffmpeg -version`
2. 确认声纹文件存在且格式正确
3. 查看错误日志，确认是否有依赖缺失

### 如果速度太慢

CPU 模式速度较慢是正常现象。如需加速：
1. 使用较短的文本
2. 在配备 NVIDIA GPU 的机器上使用 `--device cuda`

## 许可证

请参考 `LICENSE.upstream` 文件了解原项目的许可证信息。

## 致谢

本项目基于以下开源项目：
- [ChatTTS](https://github.com/2noise/ChatTTS)
- [OpenVoice](https://github.com/myshell-ai/OpenVoice)
