"""本地 MCP 入口。

用途：先给 Codex / 本地 MCP 客户端读取已经分析好的视频报告。
如果要接 ChatGPT 网页连接器，需要把服务部署到公网 HTTPS，并补好认证；v1 暂不默认裸奔公网。
"""
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from video_analyzer import get_report, list_reports

load_dotenv()
mcp = FastMCP("阿屿看视频")


@mcp.tool()
def list_recent_videos(limit: int = 8) -> list[dict]:
    """列出最近已经上传并分析完成的视频。"""
    return list_reports(max(1, min(limit, 20)))


@mcp.tool()
def get_video_analysis(video_id: str) -> dict:
    """读取一个视频的完整分析报告，包括转写、画面分析和模型信息。"""
    report = get_report(video_id)
    if not report:
        return {"ok": False, "error": "没有找到这个 video_id"}
    return {"ok": True, "report": report}


if __name__ == "__main__":
    mcp.run()
