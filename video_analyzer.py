from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
REPORTS_DIR = DATA_DIR / "reports"
TMP_DIR = DATA_DIR / "tmp"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("没有检测到 ffmpeg/ffprobe。Render 版请确认使用仓库里的 Dockerfile。")


def probe_duration(video_path: Path) -> float:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]).stdout.strip()
    try:
        return max(0.0, float(out))
    except Exception:
        return 0.0


def extract_audio(video_path: Path, work_dir: Path) -> Path | None:
    audio_path = work_dir / "audio.mp3"
    try:
        _run([
            "ffmpeg", "-y", "-i", str(video_path), "-vn",
            "-ac", "1", "-ar", "16000", "-b:a", "64k", str(audio_path)
        ])
    except subprocess.CalledProcessError:
        return None
    return audio_path if audio_path.exists() and audio_path.stat().st_size > 0 else None


def extract_frames(video_path: Path, work_dir: Path, duration: float, max_frames: int) -> list[tuple[float, Path]]:
    frame_dir = work_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    if duration <= 0:
        timestamps = [0.0]
    else:
        count = max(1, min(max_frames, int(duration // 2) + 1))
        if count == 1:
            timestamps = [duration / 2]
        else:
            margin = min(0.4, duration * 0.05)
            start, end = margin, max(duration - margin, 0.0)
            timestamps = [start + (end - start) * i / (count - 1) for i in range(count)]
    results: list[tuple[float, Path]] = []
    for idx, ts in enumerate(timestamps):
        out = frame_dir / f"frame_{idx:02d}.jpg"
        try:
            _run([
                "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale='min(960,iw)':-2", "-q:v", "3", str(out)
            ])
            if out.exists() and out.stat().st_size > 0:
                results.append((ts, out))
        except subprocess.CalledProcessError:
            continue
    return results


def to_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def transcribe_audio(client: OpenAI, audio_path: Path | None, model: str) -> str:
    if audio_path is None:
        return ""
    with audio_path.open("rb") as f:
        t = client.audio.transcriptions.create(model=model, file=f)
    return getattr(t, "text", "") or ""


def analyze_frames_and_transcript(client: OpenAI, frames: list[tuple[float, Path]], transcript: str, duration: float, model: str) -> str:
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": (
            "你在分析一个用户想分享给亲密 AI 伙伴观看的短视频。"
            "严格依据抽帧画面和音频转写，不要补写看不到或听不到的细节。"
            "输出中文，并按以下结构：\n"
            "1. 一句话概括\n2. 时间线（尽量引用帧时间）\n3. 画面里明确发生了什么\n"
            "4. 说了什么/声音线索\n5. 氛围与值得聊的点\n6. 不确定或可能误读的地方\n"
            f"视频时长约 {duration:.1f} 秒。\n\n音频转写：\n{transcript if transcript else '（无可用音频转写）'}"
        ),
    }]
    for ts, frame_path in frames:
        content.append({"type": "input_text", "text": f"约 {ts:.1f}s 的画面："})
        content.append({"type": "input_image", "image_url": to_data_url(frame_path), "detail": "auto"})

    response = client.responses.create(model=model, input=[{"role": "user", "content": content}])
    return response.output_text


def analyze_video(video_path: Path, original_name: str) -> dict[str, Any]:
    ensure_ffmpeg()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("还没有配置 OPENAI_API_KEY。请在 Render 的 Environment 里添加。")

    vision_model = os.getenv("OPENAI_VISION_MODEL", "gpt-5")
    transcribe_model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    max_frames = int(os.getenv("MAX_FRAMES", "8"))
    max_duration = float(os.getenv("MAX_DURATION_SECONDS", "90"))

    client = OpenAI(api_key=api_key)
    video_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    with tempfile.TemporaryDirectory(dir=TMP_DIR) as td:
        work_dir = Path(td)
        duration = probe_duration(video_path)
        if duration > max_duration:
            raise RuntimeError(f"视频约 {duration:.1f} 秒，超过当前 {max_duration:.0f} 秒上限。先剪短一点再给我看。")
        audio_path = extract_audio(video_path, work_dir)
        frames = extract_frames(video_path, work_dir, duration, max_frames=max_frames)
        if not frames:
            raise RuntimeError("没有成功抽出任何视频帧。请确认视频格式可被 FFmpeg 读取。")

        transcript = transcribe_audio(client, audio_path, transcribe_model)
        analysis = analyze_frames_and_transcript(client, frames, transcript, duration, vision_model)

    report = {
        "video_id": video_id,
        "original_name": original_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3),
        "frame_count": len(frames),
        "transcript": transcript,
        "analysis": analysis,
        "models": {"vision": vision_model, "transcription": transcribe_model},
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
