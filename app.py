from __future__ import annotations

import contextlib
import html
import os
import secrets
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from video_analyzer import analyze_video, get_report, list_reports
from mcp_bridge import mcp as video_mcp

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "80"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
MCP_PATH_TOKEN = os.getenv("MCP_PATH_TOKEN", "").strip()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with video_mcp.session_manager.run():
        yield


app = FastAPI(title="阿屿看视频 v1.6", lifespan=lifespan)

# MCP 端点故意放在一条随机路径后面。它是只读桥接，不提供上传、删除或修改工具。
if MCP_PATH_TOKEN:
    video_mcp.settings.streamable_http_path = "/"
    app.mount(f"/mcp-{MCP_PATH_TOKEN}", video_mcp.streamable_http_app())
security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    if not APP_PASSWORD:
        return
    ok_user = credentials is not None and secrets.compare_digest(credentials.username, "xiaoyu")
    ok_pass = credentials is not None and secrets.compare_digest(credentials.password, APP_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要密码",
            headers={"WWW-Authenticate": 'Basic realm="Ayu Video"'},
        )


def page(message: str = "") -> str:
    reports = list_reports(8)
    items = "".join(
        f'<li><a href="/report/{html.escape(r["video_id"])}">{html.escape(r.get("original_name") or r["video_id"])}</a>'
        f' <small>({float(r.get("duration_seconds") or 0):.1f}s)</small></li>'
        for r in reports
    ) or "<li>还没有分析记录</li>"
    msg = f'<div class="msg">{html.escape(message)}</div>' if message else ""

    api_ok = bool(os.getenv("NEWAPI_API_KEY", "").strip())
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
    setup = (
        ("✅" if api_ok else "❌") + " Gemini 看+听　" +
        ("✅" if APP_PASSWORD else "⚠️") + " 网页密码　" +
        "主模型：" + model
    )

    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>阿屿看视频 v1.6</title><style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:720px;margin:36px auto;padding:0 18px;line-height:1.6;background:#f7f3e9;color:#243329}}
.card{{background:#fffdf7;padding:22px;border-radius:20px;box-shadow:0 8px 25px #0001;margin:16px 0}}button{{padding:11px 18px;border:0;border-radius:12px;background:#536b57;color:white;font-size:16px}}input{{max-width:100%}}.msg{{background:#eef5ec;padding:12px;border-radius:12px}}.status{{background:#eef5ec;padding:12px;border-radius:12px}}pre{{white-space:pre-wrap;word-break:break-word;background:#f5f5f2;padding:14px;border-radius:12px}}a{{color:#385a42}}small{{color:#667066}}</style></head><body>
<h1>阿屿看视频 v1.6</h1><p>Gemini 直接读取短视频：同一次请求里看画面、听原始音轨，再生成一份阿屿可读的音画报告。</p>
<div class='status'>{html.escape(setup)}</div>{msg}
<div class='card'><form action='/upload' method='post' enctype='multipart/form-data'><input type='file' name='video' accept='video/*' required><br><br><button type='submit'>给阿屿看</button></form></div>
<div class='card'><h3>最近的视频</h3><ul>{items}</ul></div>
<p><small>建议 60 秒以内。网页可收 80MB 以内视频，服务器会先自动转成适合 Gemini inline_data 的小体积 MP4；原视频分析结束后删除。</small></p>
</body></html>"""


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def home():
    return page()


@app.post("/upload", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def upload(video: UploadFile = File(...)):
    suffix = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
    temp_path = UPLOADS_DIR / f"upload-{uuid.uuid4().hex}{suffix}"
    try:
        size = 0
        max_bytes = MAX_UPLOAD_MB * 1024 * 1024
        with temp_path.open("wb") as f:
            while True:
                chunk = video.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"视频超过 {MAX_UPLOAD_MB}MB 上限")
                f.write(chunk)

        report = analyze_video(temp_path, video.filename or "video")
        used = (report.get("models") or {}).get("video_audio_understanding") or "Gemini"
        note = ""
        first_error = report.get("primary_model_error_before_fallback")
        if first_error:
            note = f"（主模型失败后已自动改用备用模型 {used}。）"
        return HTMLResponse(page(f"看完了：{report['original_name']}。报告 ID：{report['video_id']} {note}"))
    except HTTPException:
        raise
    except Exception as e:
        return HTMLResponse(page(f"分析失败：{e}"), status_code=500)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/report/{video_id}", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def report_page(video_id: str):
    r = get_report(video_id)
    if not r:
        raise HTTPException(404, "report not found")
    analysis = html.escape(r.get("analysis") or "")
    transcript = html.escape(r.get("transcript") or "")
    audio = html.escape(r.get("audio_observation") or "")
    model = html.escape(str((r.get("models") or {}).get("video_audio_understanding") or ""))
    return HTMLResponse(
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<body style='font-family:system-ui;max-width:760px;margin:30px auto;padding:0 18px;line-height:1.65'>"
        f"<a href='/'>← 返回</a><h2>{html.escape(r.get('original_name') or video_id)}</h2>"
        f"<p>ID: <code>{html.escape(video_id)}</code>　模型：<code>{model}</code></p>"
        f"<h3>阿屿可读音画分析</h3><pre style='white-space:pre-wrap'>{analysis}</pre>"
        f"<h3>语音转写</h3><pre style='white-space:pre-wrap'>{transcript}</pre>"
        f"<h3>声音观察</h3><pre style='white-space:pre-wrap'>{audio}</pre></body>"
    )


@app.get("/api/recent", dependencies=[Depends(require_auth)])
def api_recent():
    return JSONResponse(list_reports(20))


@app.get("/api/report/{video_id}", dependencies=[Depends(require_auth)])
def api_report(video_id: str):
    r = get_report(video_id)
    if not r:
        raise HTTPException(404, "report not found")
    return JSONResponse(r)
