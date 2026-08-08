from __future__ import annotations

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

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "80"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()

app = FastAPI(title="阿屿看视频 v1.2")
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
            headers={"WWW-Authenticate": "Basic realm=\"Ayu Video\""},
        )


def page(message: str = "") -> str:
    reports = list_reports(8)
    items = "".join(
        f'<li><a href="/report/{html.escape(r["video_id"])}">{html.escape(r.get("original_name") or r["video_id"])}</a>'
        f' <small>({float(r.get("duration_seconds") or 0):.1f}s)</small></li>'
        for r in reports
    ) or "<li>还没有分析记录</li>"
    msg = f'<div class="msg">{html.escape(message)}</div>' if message else ""

    gemini_ok = bool(os.getenv("GEMINI_API_KEY", "").strip())
    deepseek_ok = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    setup = (
        ("✅" if gemini_ok else "❌") + " Gemini 眼睛　" +
        ("✅" if deepseek_ok else "○") + " DeepSeek 整理　" +
        ("✅" if APP_PASSWORD else "⚠️") + " 网页密码"
    )

    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>阿屿看视频 v1.2</title><style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:720px;margin:36px auto;padding:0 18px;line-height:1.6;background:#f7f3e9;color:#243329}}
.card{{background:#fffdf7;padding:22px;border-radius:20px;box-shadow:0 8px 25px #0001;margin:16px 0}}button{{padding:11px 18px;border:0;border-radius:12px;background:#536b57;color:white;font-size:16px}}input{{max-width:100%}}.msg{{background:#eef5ec;padding:12px;border-radius:12px}}.status{{background:#eef5ec;padding:12px;border-radius:12px}}pre{{white-space:pre-wrap;word-break:break-word;background:#f5f5f2;padding:14px;border-radius:12px}}a{{color:#385a42}}small{{color:#667066}}</style></head><body>
<h1>阿屿看视频 v1.2</h1><p>Gemini 直接看视频的画面和声音，DeepSeek 再把观察整理成适合阿屿读取的报告。</p>
<div class='status'>{html.escape(setup)}</div>{msg}
<div class='card'><form action='/upload' method='post' enctype='multipart/form-data'><input type='file' name='video' accept='video/*' required><br><br><button type='submit'>给阿屿看</button></form></div>
<div class='card'><h3>最近的视频</h3><ul>{items}</ul></div>
<p><small>建议先用 30–60 秒、80MB 以内短视频。Gemini API 与 ChatGPT 订阅独立；DeepSeek Key 可选，不填时直接使用 Gemini 的观察报告。</small></p>
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
        return HTMLResponse(page(f"看完了：{report['original_name']}。报告 ID：{report['video_id']}"))
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
    raw = html.escape(r.get("gemini_observation") or "")
    return HTMLResponse(f"<meta name='viewport' content='width=device-width,initial-scale=1'><body style='font-family:system-ui;max-width:760px;margin:30px auto;padding:0 18px;line-height:1.65'><a href='/'>← 返回</a><h2>{html.escape(r.get('original_name') or video_id)}</h2><p>ID: <code>{html.escape(video_id)}</code></p><h3>阿屿可读分析</h3><pre style='white-space:pre-wrap'>{analysis}</pre><h3>Gemini 原始观察底稿</h3><pre style='white-space:pre-wrap'>{raw}</pre></body>")


@app.get("/api/recent", dependencies=[Depends(require_auth)])
def api_recent():
    return JSONResponse(list_reports(20))


@app.get("/api/report/{video_id}", dependencies=[Depends(require_auth)])
def api_report(video_id: str):
    r = get_report(video_id)
    if not r:
        raise HTTPException(404, "report not found")
    return JSONResponse(r)
