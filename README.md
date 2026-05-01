# ImageVideoAgent — OpenRouter 多模态创作 Agent

一个具备**图片生成、视频生成、文件管理、代码执行**能力的完整 Agent 系统，基于 OpenRouter API 构建，提供美观的 Web UI。

## ✨ 功能特性

- 🎨 **图片生成** — 调用 OpenRouter 图像模型（Gemini、Flux 等）生成高质量图片
- 🎬 **视频生成** — 调用 OpenRouter 视频模型（Veo、Wan 等）生成 AI 视频
- 📝 **文件管理** — 在 Workspace 中创建、读取、编辑、列出文件
- ⚡ **代码执行** — 运行 Python 脚本、安装依赖、处理文件
- 🤖 **ReAct Agent** — 支持多轮工具调用，自主规划并完成任务
- 💬 **流式交互** — SSE 实时推送 Agent 的思考、工具调用和结果
- 🖥️ **Web UI** — 现代化的聊天界面 + 文件浏览器

## 🚀 快速开始

### 1. 配置环境变量

```bash
# Windows PowerShell
$env:OPENROUTER_API_KEY = "sk-or-v1-xxxxxxxx"

# 或创建 .env 文件
echo "OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx" > .env
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

```bash
python main.py
```

服务将运行在 http://localhost:8000

### 4. 打开浏览器访问

http://localhost:8000

## 📁 项目结构

```
.
├── main.py              # FastAPI 后端入口
├── agent_core.py        # Agent 核心逻辑（ReAct 循环）
├── tools.py             # 工具实现（图片/视频/文件/命令）
├── system_prompt.py     # Agent System Prompt
├── requirements.txt     # Python 依赖
├── static/
│   ├── index.html       # Web UI 页面
│   └── app.js           # 前端逻辑
└── workspace/           # Agent 工作目录（自动创建）
```

## 🔧 可用工具

| 工具 | 说明 |
|------|------|
| `generate_image` | 生成图片，支持配置模型、宽高比、分辨率 |
| `generate_video` | 生成视频，支持配置分辨率、时长、宽高比 |
| `write_file` | 写入/覆盖文件 |
| `read_file` | 读取文件内容 |
| `edit_file` | 精确编辑文件（字符串替换） |
| `list_files` | 列出目录内容 |
| `execute_command` | 执行系统命令 |

## 🧠 Agent 工作流

```
用户输入 -> Agent 分析 -> LLM 推理 -> 调用工具 -> 观察结果 -> ... -> 最终回复
```

Agent 会自主决定调用哪些工具、调用顺序，最多执行 15 轮迭代。

## 📝 使用示例

**生成图片：**
> "生成一张赛博朋克风格的城市夜景图，16:9 比例，保存为 cyberpunk.png"

**生成视频：**
> "用模型 google/veo-3.1 生成一段 5 秒的海浪拍打沙滩的视频，1080p"

**综合创作：**
> "帮我写一个 Python 脚本生成随机迷宫，然后运行它，把生成的迷宫保存为图片 maze.png"

**文件管理：**
> "在 src/ 目录下创建一个 React 组件 Button.tsx，包含基本的按钮样式和点击事件"

## ⚙️ 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENROUTER_API_KEY` | OpenRouter API Key | 必填 |
| `AGENT_MODEL` | 默认使用的 LLM 模型 | `openai/gpt-4o` |

## 🔒 安全说明

- Agent 运行在本地 Workspace 目录中，不会访问系统关键路径
- 视频生成需要较长的轮询等待时间（30秒~数分钟）
- 请妥善保管 OPENROUTER_API_KEY，不要提交到代码仓库

## 📄 许可证

MIT
