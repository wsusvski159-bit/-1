import os, shutil
from dotenv import load_dotenv
load_dotenv()
print("FFmpeg:", shutil.which("ffmpeg") or "未找到")
print("ffprobe:", shutil.which("ffprobe") or "未找到")
print("OPENAI_API_KEY:", "已配置" if os.getenv("OPENAI_API_KEY") else "未配置")
print("如果上面三项都正常，就可以运行 app.py 了。")
