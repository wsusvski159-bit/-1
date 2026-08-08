# 阿屿看视频 v1.1

短视频上传 → FFmpeg 抽帧/提音频 → OpenAI 转写与视觉分析 → 保存可读报告。

## Render 部署

优先阅读 `手机部署_照着点.md`。

Dockerfile 已安装 FFmpeg，并使用 Render 的 `$PORT` 启动 FastAPI。

### 必填环境变量
- `OPENAI_API_KEY`
- `APP_PASSWORD`（公网部署强烈要求）

### 默认模型
- 视觉分析：`gpt-5`
- 音频转写：`gpt-4o-mini-transcribe`

### 本地运行
```bash
pip install -r requirements.txt
# 安装 FFmpeg
cp .env.example .env
uvicorn app:app --reload
```

### 数据
默认保存在 `./data`。Render 免费服务的本地文件系统可能在重启/部署后丢失；v1.1 暂时用于验证流程。
