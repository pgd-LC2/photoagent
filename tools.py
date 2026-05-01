import os
import json
import time
import base64
import requests
from typing import Dict, List, Any, Optional
from pathlib import Path

# Workspace 根目录
WORKSPACE_DIR = Path(__file__).parent / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ==================== 工具 Schema 定义 ====================

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "使用固定的 openai/gpt-5.4-image-2 模型根据文本提示生成图片。支持配置宽高比、分辨率，以及传入参考图片进行图生图创作。生成成功后返回图片的 base64 data URL 或保存路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "描述要生成的图片内容的详细文本提示词。越详细效果越好。"
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "description": "图片宽高比，可选值: '1:1'(默认), '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'。"
                    },
                    "image_size": {
                        "type": "string",
                        "description": "图片质量/分辨率等级。1K = Standard resolution (默认，标准清晰度); 2K = Higher resolution (更高清晰度); 4K = Highest resolution (最高清晰度)。"
                    },
                    "reference_image": {
                        "type": "string",
                        "description": "（可选）Workspace 中的图片文件路径，作为参考图输入。模型会以该图片为参考进行风格迁移或图像编辑。支持 .png, .jpg, .jpeg, .webp, .gif 格式。"
                    },
                    "save_to_workspace": {
                        "type": "boolean",
                        "description": "是否将生成的图片保存到 workspace 目录。默认为 true。"
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存到 workspace 时的文件名（不含扩展名）。如果不指定，将使用基于时间戳的默认名称。"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": "使用指定的视频生成模型根据文本提示生成视频。这是一个异步过程：提交任务后需要轮询直到完成。支持配置分辨率、宽高比、时长，以及传入参考图片作为首尾帧或风格参考。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "描述要生成的视频内容的详细文本提示词。应包含场景、动作、光线、镜头角度等细节。"
                    },
                    "model": {
                        "type": "string",
                        "enum": ["bytedance/seedance-2.0", "alibaba/wan-2.7", "bytedance/seedance-2.0-fast"],
                        "description": "使用的视频模型。可选: 'bytedance/seedance-2.0' (默认，高质量), 'alibaba/wan-2.7' (支持图生视频), 'bytedance/seedance-2.0-fast' (快速生成)。"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "视频时长（秒）。如果不指定，使用模型默认值。"
                    },
                    "resolution": {
                        "type": "string",
                        "description": "视频分辨率，可选值: '480p', '720p', '1080p', '1K', '2K', '4K'。"
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "description": "视频宽高比，可选值: '16:9'(默认), '9:16', '1:1', '4:3', '3:4', '21:9', '9:21'。"
                    },
                    "size": {
                        "type": "string",
                        "description": "精确的像素尺寸，格式为 'WIDTHxHEIGHT'，例如 '1920x1080'。与 resolution + aspect_ratio 互斥。"
                    },
                    "reference_image": {
                        "type": "string",
                        "description": "（可选）Workspace 中的图片文件路径，作为视频生成的图片输入。支持 .png, .jpg, .jpeg, .webp, .gif 格式。"
                    },
                    "image_mode": {
                        "type": "string",
                        "enum": ["frame_images", "input_references"],
                        "description": "图片输入模式。'frame_images' = 将该图片作为视频的首帧/尾帧（图生视频）; 'input_references' = 将该图片作为风格/内容参考（参考图生成）。仅在提供了 reference_image 时有效。"
                    },
                    "frame_type": {
                        "type": "string",
                        "enum": ["first_frame", "last_frame"],
                        "description": "当 image_mode 为 'frame_images' 时，指定该图片作为首帧还是尾帧。默认 'first_frame'。"
                    },
                    "generate_audio": {
                        "type": "boolean",
                        "description": "是否同时生成音频。默认为 true（如果模型支持）。"
                    },
                    "save_to_workspace": {
                        "type": "boolean",
                        "description": "是否将生成的视频保存到 workspace 目录。默认为 true。"
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存到 workspace 时的文件名（不含扩展名）。如果不指定，将使用基于时间戳的默认名称。"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "在 workspace 中创建新文件或完全覆盖已有文件。用于保存代码、文档、数据等内容。如果文件路径包含不存在的目录，会自动创建。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于 workspace 根目录。例如 'scripts/hello.py' 或 'report.md'。"
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入文件的完整内容。"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认为 'utf-8'。"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取 workspace 中指定文件的内容。支持指定偏移行数和限制行数，适合读取大文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于 workspace 根目录。"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "开始读取的行号（从1开始）。默认为1。"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多读取的行数。默认为2000。"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认为 'utf-8'。"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "对 workspace 中的现有文件进行精确编辑。使用字符串替换的方式：找到 old_string 并将其替换为 new_string。old_string 必须在文件中唯一存在，否则会失败。用于修改代码、更新文档等精细操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于 workspace 根目录。"
                    },
                    "old_string": {
                        "type": "string",
                        "description": "文件中要替换的原始字符串。必须精确匹配，包括缩进和换行。"
                    },
                    "new_string": {
                        "type": "string",
                        "description": "用于替换的新字符串。"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认为 'utf-8'。"
                    }
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出 workspace 中指定目录下的文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，相对于 workspace 根目录。默认为空字符串（根目录）。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "在 workspace 目录下执行一条系统命令（如运行 Python 脚本、安装依赖等）。请谨慎使用，只执行安全的命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令字符串。"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "命令超时时间（秒），默认为60秒。"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "在开始复杂多步骤任务前，创建一个结构化的任务计划（TODO 列表）。这能帮助你和用户清晰地跟踪任务进度。每个计划项包含编号、描述、状态和备注。计划创建后会显示在前端 UI 中。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "任务列表，每项是一个字符串描述。例如：[\"分析需求\", \"生成图片\", \"保存文件\"]"
                    }
                },
                "required": ["tasks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "更新任务计划中某个任务的状态。应在完成、开始或遇到困难时调用，以便用户实时了解进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_index": {
                        "type": "integer",
                        "description": "要更新的任务编号（从1开始）"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "failed"],
                        "description": "新状态: pending(待办), in_progress(进行中), completed(已完成), failed(失败)"
                    },
                    "note": {
                        "type": "string",
                        "description": "可选的备注信息，说明当前进展或遇到的问题"
                    }
                },
                "required": ["task_index", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_context",
            "description": "将 workspace 中的某个文件内容设为 Agent 的隐式长期上下文（Hidden Context）。该内容会作为额外的系统指令，在每次 LLM 调用时自动注入到对话中，但**用户前端不会看到**。适合保留设计规范、提示词模板、风格指南等需要贯穿始终的参考资料。只有你能看到这个内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "workspace 中的文件路径。支持文本文件（.md, .txt, .json 等）和图片文件（.png, .jpg 等）。图片文件会转为描述性占位符。"
                    },
                    "label": {
                        "type": "string",
                        "description": "上下文的标签/标题，用于标识这段内容的用途。例如 '设计规范'、'提示词模板'、'代码规范'"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_context",
            "description": "清空当前 Agent 的隐式长期上下文。清除后，该内容将不再注入到 LLM 调用中。适合当任务完成、不再需要参考该文件，或需要更换新的上下文文件时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_context_summary",
            "description": "获取当前隐式长期上下文的摘要信息（文件名、标签、内容长度）。用于向用户汇报当前记住了什么，或者确认上下文是否已正确设置。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# ==================== 工具实现 ====================

def _get_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "ImageVideoAgent"
    }

def generate_image(
    prompt: str,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    reference_image: Optional[str] = None,
    save_to_workspace: bool = True,
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """使用 openai/gpt-5.4-image-2 生成图片，支持参考图片输入"""
    if not OPENROUTER_API_KEY:
        return {"success": False, "error": "未设置 OPENROUTER_API_KEY 环境变量"}

    FIXED_IMAGE_MODEL = "openai/gpt-5.4-image-2"

    # 构建 messages，支持参考图片输入
    messages = [{"role": "user", "content": []}]

    # 如果有参考图片，读取并转为 base64 data URL
    if reference_image:
        ref_path = WORKSPACE_DIR / reference_image
        image_exts = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        ext = ref_path.suffix.lower()
        if ref_path.exists() and ref_path.is_file() and ext in image_exts:
            with open(ref_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = image_exts[ext]
            data_url = f"data:{mime};base64,{b64}"
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": data_url}
            })
        else:
            return {
                "success": False,
                "error": f"参考图片不存在或格式不支持: {reference_image}。支持 .png, .jpg, .jpeg, .webp, .gif"
            }

    # 添加文本 prompt
    messages[0]["content"].append({"type": "text", "text": prompt})

    payload = {
        "model": FIXED_IMAGE_MODEL,
        "messages": messages,
        "modalities": ["image", "text"]
    }

    image_config = {}
    if aspect_ratio:
        image_config["aspect_ratio"] = aspect_ratio
    if image_size:
        image_config["image_size"] = image_size
    if image_config:
        payload["image_config"] = image_config

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=_get_headers(),
            json=payload,
            timeout=300
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("choices"):
            return {"success": False, "error": "API 返回异常", "raw": data}

        message = data["choices"][0].get("message", {})
        images = message.get("images", [])
        text = message.get("content", "")

        result = {
            "success": True,
            "text": text,
            "image_count": len(images),
            "saved_files": [],
            "params_used": {
                "model": FIXED_IMAGE_MODEL,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "image_config": image_config if image_config else None
            }
        }

        if images and save_to_workspace:
            for idx, img in enumerate(images):
                url = img.get("image_url", {}).get("url", "")
                if url.startswith("data:image"):
                    # 从 data URL 提取 base64
                    header, b64 = url.split(",", 1)
                    ext = header.split("/")[1].split(";")[0] if "/" in header else "png"
                    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                        ext = "png"
                    name = filename or f"generated_image_{int(time.time())}"
                    if len(images) > 1:
                        name = f"{name}_{idx+1}"
                    save_path = WORKSPACE_DIR / f"{name}.{ext}"
                    with open(save_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    result["saved_files"].append(str(save_path.relative_to(WORKSPACE_DIR.parent)))
                elif url.startswith("http"):
                    # 下载远程图片
                    img_resp = requests.get(url, timeout=60)
                    img_resp.raise_for_status()
                    ext = url.split("?")[0].split(".")[-1]
                    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                        ext = "png"
                    name = filename or f"generated_image_{int(time.time())}"
                    if len(images) > 1:
                        name = f"{name}_{idx+1}"
                    save_path = WORKSPACE_DIR / f"{name}.{ext}"
                    with open(save_path, "wb") as f:
                        f.write(img_resp.content)
                    result["saved_files"].append(str(save_path.relative_to(WORKSPACE_DIR.parent)))

        if images and not save_to_workspace:
            result["images"] = [img.get("image_url", {}).get("url", "") for img in images]

        return result

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"网络请求失败: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"生成图片时出错: {str(e)}"}


def _encode_image_to_data_url(image_path: Path) -> Optional[str]:
    """将 workspace 中的图片文件编码为 base64 data URL"""
    image_exts = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    ext = image_path.suffix.lower()
    if not image_path.exists() or not image_path.is_file() or ext not in image_exts:
        return None
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{image_exts[ext]};base64,{b64}"


def generate_video(
    prompt: str,
    model: str = "bytedance/seedance-2.0",
    duration: Optional[int] = None,
    resolution: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    size: Optional[str] = None,
    reference_image: Optional[str] = None,
    image_mode: Optional[str] = None,
    frame_type: Optional[str] = None,
    generate_audio: Optional[bool] = None,
    save_to_workspace: bool = True,
    filename: Optional[str] = None
) -> Dict[str, Any]:
    """生成视频（异步任务），支持参考图片"""
    if not OPENROUTER_API_KEY:
        return {"success": False, "error": "未设置 OPENROUTER_API_KEY 环境变量"}

    payload = {
        "model": model,
        "prompt": prompt
    }
    if duration is not None:
        payload["duration"] = duration
    if resolution:
        payload["resolution"] = resolution
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if size:
        payload["size"] = size
    if generate_audio is not None:
        payload["generate_audio"] = generate_audio

    # 处理参考图片输入
    if reference_image:
        data_url = _encode_image_to_data_url(WORKSPACE_DIR / reference_image)
        if not data_url:
            return {
                "success": False,
                "error": f"参考图片不存在或格式不支持: {reference_image}。支持 .png, .jpg, .jpeg, .webp, .gif"
            }

        img_entry = {
            "type": "image_url",
            "image_url": {"url": data_url}
        }

        mode = image_mode or "input_references"
        if mode == "frame_images":
            img_entry["frame_type"] = frame_type or "first_frame"
            payload["frame_images"] = [img_entry]
        else:
            payload["input_references"] = [img_entry]

    try:
        # Step 1: Submit
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/videos",
            headers=_get_headers(),
            json=payload,
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()

        job_id = result.get("id")
        polling_url = result.get("polling_url")
        if not job_id or not polling_url:
            return {"success": False, "error": "提交视频任务失败，未返回 job_id", "raw": result}

        # Step 2: Poll
        max_polls = 120  # 最多轮询 120 次
        poll_interval = 10  # 每 10 秒轮询一次
        for i in range(max_polls):
            time.sleep(poll_interval)
            poll_resp = requests.get(polling_url, headers=_get_headers(), timeout=30)
            poll_resp.raise_for_status()
            status_data = poll_resp.json()

            status = status_data.get("status")
            if status == "completed":
                urls = status_data.get("unsigned_urls", [])
                if not urls:
                    return {"success": False, "error": "视频生成完成但未返回下载链接", "raw": status_data}

                # Step 3: Download
                video_url = urls[0]
                video_resp = requests.get(video_url, timeout=120)
                video_resp.raise_for_status()

                saved_path = None
                if save_to_workspace:
                    name = filename or f"generated_video_{int(time.time())}"
                    save_path = WORKSPACE_DIR / f"{name}.mp4"
                    with open(save_path, "wb") as f:
                        f.write(video_resp.content)
                    saved_path = str(save_path.relative_to(WORKSPACE_DIR.parent))

                return {
                    "success": True,
                    "job_id": job_id,
                    "status": "completed",
                    "video_url": video_url,
                    "saved_file": saved_path,
                    "usage": status_data.get("usage", {})
                }

            elif status == "failed":
                return {
                    "success": False,
                    "error": status_data.get("error", "视频生成失败，未知错误"),
                    "job_id": job_id,
                    "raw": status_data
                }
            # 否则继续轮询: pending / in_progress

        return {
            "success": False,
            "error": "视频生成超时，请稍后通过 job_id 查询状态",
            "job_id": job_id,
            "polling_url": polling_url
        }

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"网络请求失败: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"生成视频时出错: {str(e)}"}


def write_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """写入文件"""
    try:
        target = WORKSPACE_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding=encoding) as f:
            f.write(content)
        return {"success": True, "path": path, "message": f"文件已保存: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(path: str, offset: int = 1, limit: int = 2000, encoding: str = "utf-8") -> Dict[str, Any]:
    """读取文件。如果是图片格式（.png/.jpg/.jpeg/.webp/.gif/.bmp/.svg），则返回 base64 data URL 供前端直接渲染。"""
    try:
        target = WORKSPACE_DIR / path
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"路径不是文件: {path}"}

        # 判断是否为图片文件
        image_exts = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }
        ext = target.suffix.lower()
        if ext in image_exts:
            with open(target, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = image_exts[ext]
            return {
                "success": True,
                "path": path,
                "type": "image",
                "mime_type": mime,
                "data_url": f"data:{mime};base64,{b64}",
                "size": target.stat().st_size
            }

        # 文本文件
        with open(target, "r", encoding=encoding) as f:
            lines = f.readlines()

        total_lines = len(lines)
        start = max(0, offset - 1)
        end = min(total_lines, start + limit)
        selected = lines[start:end]

        return {
            "success": True,
            "path": path,
            "type": "text",
            "content": "".join(selected),
            "total_lines": total_lines,
            "displayed_from": start + 1,
            "displayed_to": end
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def edit_file(path: str, old_string: str, new_string: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """编辑文件（精确替换）"""
    try:
        target = WORKSPACE_DIR / path
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        with open(target, "r", encoding=encoding) as f:
            content = f.read()

        if old_string not in content:
            return {"success": False, "error": f"未找到要替换的字符串，请确保 old_string 精确匹配文件内容。"}

        if content.count(old_string) > 1:
            return {"success": False, "error": f"找到多个匹配的字符串，请提供更精确的上下文以确保唯一匹配。"}

        new_content = content.replace(old_string, new_string, 1)
        with open(target, "w", encoding=encoding) as f:
            f.write(new_content)

        return {"success": True, "path": path, "message": f"文件已编辑: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(path: str = "") -> Dict[str, Any]:
    """列出文件"""
    try:
        target = WORKSPACE_DIR / path
        if not target.exists():
            return {"success": False, "error": f"目录不存在: {path}"}
        if not target.is_dir():
            return {"success": False, "error": f"路径不是目录: {path}"}

        entries = []
        for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None
            })
        return {"success": True, "path": path, "entries": entries}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_command(command: str, timeout: int = 60) -> Dict[str, Any]:
    """执行命令"""
    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"命令执行超时（>{timeout}秒）"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== 计划状态存储 ====================
# key: session_id, value: List[Dict] 计划列表
_plans_store: Dict[str, List[Dict[str, Any]]] = {}

# ==================== 隐式长期上下文存储 ====================
# key: session_id, value: Dict { source: 文件名, content: 内容, updated_at: 时间戳 }
_hidden_context_store: Dict[str, Dict[str, Any]] = {}


def create_plan(session_id: str, tasks: List[str]) -> Dict[str, Any]:
    """创建一个任务计划列表。用于在开始复杂任务前规划步骤，让用户和 Agent 都清楚当前进度。"""
    if not session_id:
        return {"success": False, "error": "缺少 session_id"}
    if not tasks or not isinstance(tasks, list):
        return {"success": False, "error": "tasks 必须是非空列表"}

    plan = []
    for i, task in enumerate(tasks, start=1):
        plan.append({
            "index": i,
            "task": str(task),
            "status": "pending",
            "note": ""
        })
    _plans_store[session_id] = plan
    return {
        "success": True,
        "plan": plan,
        "message": f"已创建包含 {len(tasks)} 项任务的计划"
    }


def update_plan(session_id: str, task_index: int, status: str, note: str = "") -> Dict[str, Any]:
    """更新计划中某个任务的状态。用于在执行过程中标记任务进展。"""
    if not session_id:
        return {"success": False, "error": "缺少 session_id"}
    plan = _plans_store.get(session_id, [])
    if not plan:
        return {"success": False, "error": "当前会话没有活跃的计划，请先调用 create_plan 创建计划"}

    valid_statuses = ["pending", "in_progress", "completed", "failed"]
    if status not in valid_statuses:
        return {"success": False, "error": f"无效状态 '{status}'，可选值: {', '.join(valid_statuses)}"}

    found = False
    for item in plan:
        if item["index"] == task_index:
            item["status"] = status
            if note:
                item["note"] = note
            found = True
            break

    if not found:
        return {"success": False, "error": f"未找到编号为 {task_index} 的任务"}

    return {"success": True, "plan": plan, "message": f"任务 #{task_index} 已更新为 {status}"}


def get_plan(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """获取指定会话的当前计划"""
    return _plans_store.get(session_id)


# ==================== 隐式长期上下文工具 ====================

def set_context(session_id: str, path: str, label: Optional[str] = None) -> Dict[str, Any]:
    """将 workspace 中的文件设为隐式长期上下文。"""
    if not session_id:
        return {"success": False, "error": "缺少 session_id"}

    target = WORKSPACE_DIR / path
    if not target.exists():
        return {"success": False, "error": f"文件不存在: {path}"}
    if not target.is_file():
        return {"success": False, "error": f"路径不是文件: {path}"}

    try:
        # 判断是否为图片
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
        ext = target.suffix.lower()

        if ext in image_exts:
            # 图片文件：存储路径和文件信息，而不是 base64（避免太大）
            content = f"[图片文件: {path}]\n文件大小: {target.stat().st_size} bytes\n格式: {ext}\n"
            content += f"说明: 这是一个图片文件，已被设为隐式上下文参考。"
            _hidden_context_store[session_id] = {
                "source": path,
                "label": label or path,
                "content": content,
                "type": "image",
                "updated_at": time.time()
            }
        else:
            # 文本文件：读取完整内容
            with open(target, "r", encoding="utf-8") as f:
                file_content = f.read()
            _hidden_context_store[session_id] = {
                "source": path,
                "label": label or path,
                "content": file_content,
                "type": "text",
                "updated_at": time.time()
            }

        return {
            "success": True,
            "source": path,
            "label": label or path,
            "type": "image" if ext in image_exts else "text",
            "content_length": len(_hidden_context_store[session_id]["content"]),
            "message": f"已将 '{label or path}' 设为隐式长期上下文。该内容将在每次思考时自动注入，但用户前端不可见。"
        }
    except Exception as e:
        return {"success": False, "error": f"读取文件失败: {str(e)}"}


def clear_context(session_id: str) -> Dict[str, Any]:
    """清空当前会话的隐式长期上下文。"""
    if not session_id:
        return {"success": False, "error": "缺少 session_id"}

    if session_id in _hidden_context_store:
        removed = _hidden_context_store.pop(session_id)
        return {
            "success": True,
            "message": f"已清除隐式上下文: {removed.get('label', removed.get('source', '未知'))}",
            "was_active": True
        }
    return {
        "success": True,
        "message": "当前没有活跃的隐式上下文",
        "was_active": False
    }


def get_context_summary(session_id: str) -> Dict[str, Any]:
    """获取当前隐式上下文的摘要。"""
    if not session_id:
        return {"success": False, "error": "缺少 session_id"}

    ctx = _hidden_context_store.get(session_id)
    if not ctx:
        return {"success": True, "active": False, "message": "当前没有隐式长期上下文"}

    return {
        "success": True,
        "active": True,
        "source": ctx["source"],
        "label": ctx["label"],
        "type": ctx["type"],
        "content_length": len(ctx["content"]),
        "updated_at": ctx["updated_at"]
    }


def get_hidden_context(session_id: str) -> Optional[Dict[str, Any]]:
    """内部方法：获取指定会话的完整隐式上下文数据"""
    return _hidden_context_store.get(session_id)


# ==================== OpenRouter Server Tools ====================
# 这些工具由 OpenRouter 服务端自动执行，不需要本地实现。
# 在 API 请求中与本地 function tools 合并传递。

OPENROUTER_SERVER_TOOLS = [
    {
        "type": "openrouter:web_fetch",
        "parameters": {}
    },
    {
        "type": "openrouter:web_search",
        "parameters": {}
    },
    {
        "type": "openrouter:datetime",
        "parameters": {}
    }
]

# 工具名称到函数的映射
TOOL_MAP = {
    "generate_image": generate_image,
    "generate_video": generate_video,
    "write_file": write_file,
    "read_file": read_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "execute_command": execute_command,
    "create_plan": create_plan,
    "update_plan": update_plan,
    "set_context": set_context,
    "clear_context": clear_context,
    "get_context_summary": get_context_summary,
}
