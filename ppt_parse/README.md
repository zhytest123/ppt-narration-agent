# PDF Audio Video

把一个 PDF 和每页对应的音频合成为单个 MP4 视频。

核心脚本是 [make_video_from_pdf.py](/Users/didi/Desktop/口播ppt/ppt_parse/make_video_from_pdf.py)。

## 安装

```bash
python3 -m pip install -r requirements.txt
```

## 默认规则

- 输入一个 PDF
- 默认从 PDF 同目录读取音频
- 默认按文件名自然排序音频，例如 `1.m4a`、`2.m4a`、`10.m4a`
- 音频数量必须和 PDF 页数一致
- 支持的音频扩展名：`.m4a`、`.mp3`、`.wav`、`.aac`、`.flac`、`.ogg`

## 基本用法

```bash
python3 make_video_from_pdf.py slides.pdf
```

## 可调参数

- `--audio-dir`：指定音频目录，默认是 PDF 所在目录
- `--audio-glob`：扫描音频时使用的 glob，默认 `*`
- `-o, --output`：指定输出视频路径，默认 `<pdf目录>/<pdf文件名>.mp4`
- `--work-dir`：指定临时工作目录，默认 `<pdf目录>/.pdf_video_work/<pdf文件名>`
- `--scale`：设置 PDF 渲染倍数，默认 `2.0`
- `--keep-temp`：保留中间图片、片段和 `concat.txt`
- `--overwrite`：覆盖已有输出文件

## 示例

从同目录自动读取音频：

```bash
python3 make_video_from_pdf.py 测试.pdf --overwrite
```

指定音频目录：

```bash
python3 make_video_from_pdf.py slides.pdf --audio-dir ./audio
```

只匹配 `.m4a`：

```bash
python3 make_video_from_pdf.py slides.pdf --audio-glob '*.m4a'
```

保留中间文件：

```bash
python3 make_video_from_pdf.py slides.pdf --keep-temp
```

## 输出

- 最终视频默认输出到 `<pdf目录>/<pdf文件名>.mp4`
- 临时文件默认写到 `<pdf目录>/.pdf_video_work/<pdf文件名>/`
- 如果没有传 `--keep-temp`，成功后会自动清理临时目录

## 说明

- 不依赖 PowerPoint、Quartz、AppleScript
- PDF 页面会先渲染为 PNG，再和音频逐页合成
- 脚本会自动把画面补齐到偶数尺寸，避免部分 PDF 页面触发 H.264 编码错误
