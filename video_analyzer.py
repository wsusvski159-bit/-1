from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
REPORTS_DIR = DATA_DIR / "reports"
TMP_DIR = DATA_DIR / "tmp"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpg",
    ".mov": "video/mov",
    ".avi": "video/avi",
    ".flv": "video/x-flv",
    ".webm": "video/webm",
    ".wmv": "video/wmv",
    ".3gp": "video/3gpp",
    ".3gpp": "video/3gpp",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ensure_ffmpeg() -> None:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("没有检测到 ffprobe。Render 版请确认使用仓库里的 Dockerfile。")


def probe_duration(video_path: Path) -> float:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]).stdout.strip()
    try:
        return max(0.0, float(out))
    except Exception:
        return 0.0


def guess_video_mime(video_path: Path, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or video_path.suffix.lower()
    if suffix in SUPPORTED_VIDEO_MIME:
        return SUPPORTED_VIDEO_MIME[suffix]
    guessed, _ = mimetypes.guess_type(original_name)
    if guessed and guessed.startswith("video/"):
        return guessed
    raise RuntimeError("暂时不认识这个视频格式。建议先用 MP4、MOV 或 WebM。")


def gemini_watch_video(video_path: Path, original_name: str, duration: float, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("还没有配置 GEMINI_API_KEY。请在 Render 的 Environment 里添加。")

    mime_type = guess_video_mime(video_path, original_name)
    video_bytes = video_path.read_bytes()
    b64 = base64.b64encode(video_bytes).decode("ascii")
    client = genai.Client(api_key=api_key)

    prompt = f"""
你正在替一个用户的亲密 AI 伙伴观看一段短视频。视频时长约 {duration:.1f} 秒。
请同时利用视觉和音频信息，严格基于视频本身，不要脑补没有出现的内容。

请用中文输出一份“观察底稿”，尽量保留具体时间点（MM:SS），结构如下：
1. 一句话概括
2. 时间线：按发生顺序写关键事件，尽量标注时间
3. 画面：人物/物体/动作/场景/屏幕文字中明确可见的内容
4. 声音：能听清的说话内容、音乐、环境声、语气；听不清就明确说听不清
5. 氛围与可能让分享者想聊的点
6. 不确定项：快速动作、模糊文字、身份等不能确定的地方

重要：不要把推测写成事实；如果字幕/台词无法准确辨认，宁可注明不确定。
""".strip()

    interaction = client.interactions.create(
        model=model,
        input=[
            {
                "type": "video",
                "data": b64,
                "mime_type": mime_type,
            },
            {"type": "text", "text": prompt},
        ],
    )
    text = getattr(interaction, "output_text", "") or ""
    if not text.strip():
        raise RuntimeError("Gemini 没有返回可读的视频分析。")
    return text.strip()


def deepseek_polish(gemini_notes: str, model: str) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return gemini_notes

    client = OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是视频观察报告的整理员。你不能看到原视频，只能依据 Gemini 的观察底稿。"
                    "绝对不要新增底稿中没有的信息，也不要把不确定内容改成确定事实。"
                    "把内容整理得自然、清楚、适合另一个 AI 伙伴随后和用户聊视频。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面的观察底稿整理成中文最终报告。结构：\n"
                    "1. 我看到了什么（简短）\n"
                    "2. 关键时间线\n"
                    "3. 说了什么/声音线索\n"
                    "4. 最值得一起聊的地方\n"
                    "5. 我不确定的地方\n\n"
                    "观察底稿：\n" + gemini_notes
                ),
            },
        ],
        temperature=0.2,
    )
    text = response.choices[0].message.content or ""
    return text.strip() or gemini_notes


def analyze_video(video_path: Path, original_name: str) -> dict[str, Any]:
    ensure_ffmpeg()

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError("还没有配置 GEMINI_API_KEY。请在 Render 的 Environment 里添加。")

    gemini_model = os.getenv("GEMINI_VIDEO_MODEL", "gemini-3.6-flash")
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    max_duration = float(os.getenv("MAX_DURATION_SECONDS", "60"))
    max_inline_mb = float(os.getenv("GEMINI_INLINE_MAX_MB", "80"))

    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > max_inline_mb:
        raise RuntimeError(f"视频约 {size_mb:.1f}MB，超过当前 {max_inline_mb:.0f}MB 上限。先压小一点再给我看。")

    duration = probe_duration(video_path)
    if duration > max_duration:
        raise RuntimeError(f"视频约 {duration:.1f} 秒，超过当前 {max_duration:.0f} 秒上限。先剪短一点再给我看。")

    gemini_notes = gemini_watch_video(video_path, original_name, duration, gemini_model)
    final_analysis = deepseek_polish(gemini_notes, deepseek_model)

    video_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    ds_enabled = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    report = {
        "video_id": video_id,
        "original_name": original_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3),
        "size_mb": round(size_mb, 3),
        "analysis": final_analysis,
        "gemini_observation": gemini_notes,
        "transcript": "",
        "models": {
            "video_understanding": gemini_model,
            "text_refinement": deepseek_model if ds_enabled else None,
        },
        "pipeline": "Gemini 直接读取视频音画 → DeepSeek 整理（若已配置）",
    }
    (REPORTS_DIR / f"{video_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def list_reports(limit: int = 10) -> list[dict[str, Any]]:
    files = sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({k: data.get(k) for k in ["video_id", "original_name", "created_at", "duration_seconds"]})
        except Exception:
            pass
    return out


def get_report(video_id: str) -> dict[str, Any] | None:
    path = REPORTS_DIR / f"{video_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
