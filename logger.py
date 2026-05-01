import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from threading import Lock

LOG_DIR = Path(__file__).parent / "workspace" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_lock = Lock()


def _get_log_path(session_id: str) -> Path:
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "_-").rstrip(".") or "default"
    return LOG_DIR / f"{safe_id}.jsonl"


def _write_entry(session_id: str, entry: Dict[str, Any]):
    if not session_id:
        return
    path = _get_log_path(session_id)
    entry["_ts"] = time.time()
    entry["_dt"] = datetime.now().isoformat()
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def log_llm_call(session_id: str, model: str, messages: List[Dict], duration_ms: float,
                 response: Optional[Dict] = None, error: Optional[str] = None):
    entry = {
        "type": "llm_call",
        "model": model,
        "message_count": len(messages),
        "duration_ms": round(duration_ms, 2),
    }
    if error:
        entry["error"] = error
    if response:
        choice = response.get("choices", [{}])[0] if response.get("choices") else {}
        msg = choice.get("message", {}) if choice else {}
        entry["response_summary"] = {
            "finish_reason": choice.get("finish_reason"),
            "content_preview": (msg.get("content", "") or "")[:200],
            "tool_calls_count": len(msg.get("tool_calls", [])),
        }
        usage = response.get("usage", {})
        if usage:
            entry["usage"] = usage
    _write_entry(session_id, entry)


def log_tool_call(session_id: str, tool_name: str, arguments: Dict[str, Any],
                  result: Dict[str, Any], duration_ms: float, error: Optional[str] = None):
    entry = {
        "type": "tool_call",
        "tool_name": tool_name,
        "arguments": arguments,
        "duration_ms": round(duration_ms, 2),
    }
    if error:
        entry["error"] = error
        entry["result_preview"] = {"success": False, "error": error}
    else:
        preview = {"success": result.get("success", False)}
        if "error" in result:
            preview["error"] = result["error"]
        if "path" in result:
            preview["path"] = result["path"]
        if "saved_file" in result:
            preview["saved_file"] = result["saved_file"]
        if "saved_files" in result:
            preview["saved_files"] = result["saved_files"]
        entry["result_preview"] = preview
    _write_entry(session_id, entry)


def log_error(session_id: str, stage: str, error: str, details: Optional[Dict] = None):
    entry = {
        "type": "error",
        "stage": stage,
        "error": error,
    }
    if details:
        entry["details"] = details
    _write_entry(session_id, entry)


def log_event(session_id: str, event_type: str, data: Dict[str, Any]):
    entry = {
        "type": event_type,
        **data
    }
    _write_entry(session_id, entry)


def get_session_logs(session_id: str) -> List[Dict[str, Any]]:
    path = _get_log_path(session_id)
    if not path.exists():
        return []
    logs = []
    with _lock:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return logs


def list_log_sessions() -> List[Dict[str, Any]]:
    sessions = []
    for f in sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = f.stat()
            sessions.append({
                "session_id": f.stem,
                "file": str(f.name),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        except Exception:
            continue
    return sessions


def clear_session_logs(session_id: str) -> bool:
    path = _get_log_path(session_id)
    if path.exists():
        path.unlink()
        return True
    return False
