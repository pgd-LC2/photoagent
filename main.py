import os
import json
import asyncio
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent_core import Agent
from tools import WORKSPACE_DIR

# 从环境变量读取配置
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "moonshotai/kimi-k2.6")

app = FastAPI(title="ImageVideoAgent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 会话管理
agents: Dict[str, Agent] = {}

# ==================== Pydantic Models ====================

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    model: Optional[str] = None

class ResetRequest(BaseModel):
    session_id: str

# ==================== Helper ====================

def get_or_create_agent(session_id: Optional[str], model: Optional[str] = None) -> tuple[str, Agent]:
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="服务器未配置 OPENROUTER_API_KEY 环境变量")
    
    if session_id and session_id in agents:
        return session_id, agents[session_id]
    
    sid = session_id or f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{id(object())}"
    m = model or DEFAULT_MODEL
    agent = Agent(api_key=OPENROUTER_API_KEY, model=m)
    agents[sid] = agent
    return sid, agent

# ==================== API Routes ====================

@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    """流式聊天接口，使用 SSE 返回 Agent 的思考和工具调用进度"""
    try:
        sid, agent = get_or_create_agent(req.session_id, req.model)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()

        def progress_callback(stage: str, data: dict):
            asyncio.run_coroutine_threadsafe(
                queue.put({"stage": stage, "data": data}),
                loop
            )

        # 在后台线程运行 Agent（因为工具调用中有同步阻塞操作如 time.sleep）
        def run_agent():
            try:
                result = agent.run(req.message, progress_callback=progress_callback)
                asyncio.run_coroutine_threadsafe(
                    queue.put({"stage": "done", "data": result}),
                    loop
                )
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"stage": "error", "data": {"error": str(e)}}),
                    loop
                )

        import threading
        t = threading.Thread(target=run_agent)
        t.start()

        while True:
            event = await queue.get()
            event["session_id"] = sid
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["stage"] in ("done", "error", "final"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/chat/sync")
async def chat_sync(req: ChatRequest):
    """非流式聊天接口，直接返回最终结果"""
    try:
        sid, agent = get_or_create_agent(req.session_id, req.model)
    except HTTPException as e:
        raise e

    try:
        result = agent.run(req.message)
        result["session_id"] = sid
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """获取指定会话的消息历史"""
    agent = agents.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": agent.get_messages()}


@app.delete("/api/sessions/{session_id}")
async def reset_session(session_id: str):
    """重置指定会话"""
    agent = agents.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="会话不存在")
    agent.reset()
    return {"session_id": session_id, "status": "reset"}


@app.get("/api/sessions/{session_id}/plan")
async def get_session_plan(session_id: str):
    """获取指定会话的当前计划"""
    from tools import get_plan
    plan = get_plan(session_id)
    if plan is None:
        return {"session_id": session_id, "plan": [], "has_plan": False}
    return {"session_id": session_id, "plan": plan, "has_plan": True}


@app.get("/api/sessions/{session_id}/context")
async def get_session_context(session_id: str):
    """获取指定会话的隐式长期上下文摘要"""
    from tools import get_context_summary
    result = get_context_summary(session_id)
    return result


# ==================== File API ====================

@app.get("/api/files")
async def api_list_files(path: str = ""):
    """列出 Workspace 中的文件"""
    from tools import list_files
    result = list_files(path)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/files/content")
async def api_read_file(path: str, offset: int = 1, limit: int = 2000):
    """读取文件内容"""
    from tools import read_file
    result = read_file(path, offset=offset, limit=limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/files/download/{path:path}")
async def api_download_file(path: str):
    """下载文件"""
    target = WORKSPACE_DIR / path
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=target.name)


# ==================== Logs API ====================

@app.get("/api/logs")
async def api_list_log_sessions():
    """列出所有有日志记录的会话"""
    from logger import list_log_sessions
    return {"sessions": list_log_sessions()}


@app.get("/api/logs/{session_id}")
async def api_get_session_logs(session_id: str):
    """获取指定会话的详细日志"""
    from logger import get_session_logs
    logs = get_session_logs(session_id)
    return {"session_id": session_id, "count": len(logs), "logs": logs}


@app.delete("/api/logs/{session_id}")
async def api_clear_session_logs(session_id: str):
    """清除指定会话的日志"""
    from logger import clear_session_logs
    cleared = clear_session_logs(session_id)
    return {"session_id": session_id, "cleared": cleared}


# ==================== Static Files ====================

app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
