# 阿屿看视频 v1.6：ChatGPT MCP 接入

上传到原 GitHub `-1` 仓库并覆盖：
- `app.py`
- `video_analyzer.py`
- `requirements.txt`
- 新增 `mcp_bridge.py`

Render 环境变量新增：
- `MCP_PATH_TOKEN`：自己生成一串至少 24 位的随机字母数字，保存好。

部署后 MCP 地址：

`https://你的Render域名/mcp-你的MCP_PATH_TOKEN`

当前服务对应的形式例如：

`https://gong-kan-1-2.onrender.com/mcp-你的MCP_PATH_TOKEN`

这个 MCP 只提供三个只读工具：
- `list_recent_videos`
- `get_latest_video_report`
- `get_video_report`

ChatGPT 网页版：Settings → Apps → Advanced settings → Developer mode；然后 Settings → Apps → Create，填上 MCP 地址，Scan tools，再 Create。
