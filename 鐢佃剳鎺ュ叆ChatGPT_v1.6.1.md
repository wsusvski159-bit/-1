# 阿屿看视频 v1.6.1：MCP 端点热修

只需要覆盖 GitHub `-1` 仓库里的：

- `app.py`

其他文件、Gemini 配置、API Key、`MCP_PATH_TOKEN` 都不要改。

Render 重新部署后，MCP 地址改为：

`https://你的Render域名/bridge-你的MCP_PATH_TOKEN/mcp`

当前服务形式例如：

`https://gong-kan-1-2.onrender.com/bridge-你的MCP_PATH_TOKEN/mcp`

ChatGPT 创建 App：

- MCP Server URL：上面的完整地址（必须包含最后的 `/mcp`）
- Authentication：None / 无身份验证
- OAuth：关闭
- 然后 Scan Tools / 创建

正常会扫描到：

- `list_recent_videos`
- `get_latest_video_report`
- `get_video_report`

注意：不要把 `MCP_PATH_TOKEN` 发给别人或截图公开。
