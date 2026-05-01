import json
import time
import uuid
import requests
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

from tools import TOOLS_SCHEMA, OPENROUTER_SERVER_TOOLS, TOOL_MAP, get_hidden_context
from system_prompt import SYSTEM_PROMPT
from logger import log_llm_call, log_tool_call, log_error

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _split_stream_chunks(text: str, max_chunk_size: int = 8) -> List[str]:
    """将文本拆分为适合流式推送的块。
    优先按标点断句，如果句子太长再按 max_chunk_size 字符切分。
    """
    if not text:
        return []
    import re
    # 按中文标点、英文标点、空格切分，保留分隔符
    pattern = r'([^。！？.?!;；\n]+[。！？.?!;；\n]+|[^\s]+\s+|[^\s]{' + str(max_chunk_size) + r',}?)'
    tokens = re.findall(pattern, text)
    if not tokens:
        # fallback: 纯字符切片
        return [text[i:i+max_chunk_size] for i in range(0, len(text), max_chunk_size)]
    # 合并过短的片段
    result = []
    buffer = ""
    for t in tokens:
        buffer += t
        if len(buffer) >= max_chunk_size:
            result.append(buffer)
            buffer = ""
    if buffer:
        result.append(buffer)
    return result


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    images: Optional[List[Dict]] = None
    reasoning: Optional[str] = None
    reasoning_details: Optional[List[Dict]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"role": self.role}
        if self.content:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        if self.images:
            d["images"] = self.images
        # 保留 reasoning 到多轮对话（OpenRouter 要求 assistant message 传回）
        if self.role == "assistant" and self.reasoning:
            d["reasoning"] = self.reasoning
        if self.role == "assistant" and self.reasoning_details:
            d["reasoning_details"] = self.reasoning_details
        return d


class Agent:
    def __init__(self, api_key: str, model: str = "openai/gpt-4o", max_iterations: int = 15):
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations
        self.messages: List[Message] = []
        self.session_id = str(uuid.uuid4())
        self._init_system()

    def _init_system(self):
        self.messages.append(Message(role="system", content=SYSTEM_PROMPT))

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "ImageVideoAgent"
        }

    def _call_llm(self, tools: bool = True) -> Dict[str, Any]:
        """调用 OpenRouter Chat Completions API"""
        # 基础消息（对话历史）
        base_messages = [m.to_dict() for m in self.messages]
        
        # 注入隐式长期上下文：在 system prompt 之后插入，但只存在于 API 调用中
        # 不加入 self.messages，用户前端完全看不到
        ctx = get_hidden_context(self.session_id)
        if ctx and ctx.get("content"):
            hidden_msg = {
                "role": "system",
                "content": (
                    f"===== 隐式参考上下文（仅 Agent 可见）=====\n"
                    f"来源: {ctx['label']}\n"
                    f"类型: {ctx.get('type', 'text')}\n"
                    f"-----\n{ctx['content']}\n"
                    f"===== 隐式参考上下文结束 ====="
                )
            }
            # 插入到 system prompt 之后（第 1 个位置）
            if base_messages and base_messages[0].get("role") == "system":
                base_messages.insert(1, hidden_msg)
            else:
                base_messages.insert(0, hidden_msg)
        
        payload = {
            "model": self.model,
            "messages": base_messages,
            "stream": False
        }
        if tools:
            # 合并本地 function tools 和 OpenRouter server tools
            combined_tools = TOOLS_SCHEMA + OPENROUTER_SERVER_TOOLS
            payload["tools"] = combined_tools
            payload["tool_choice"] = "auto"

        start = time.time()
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self._get_headers(),
                json=payload,
                timeout=300
            )
            resp.raise_for_status()
            data = resp.json()
            duration = (time.time() - start) * 1000
            log_llm_call(self.session_id, self.model, base_messages, duration, response=data)
            return data
        except requests.exceptions.RequestException as e:
            duration = (time.time() - start) * 1000
            error_msg = f"OpenRouter API 请求失败: {str(e)}"
            log_llm_call(self.session_id, self.model, base_messages, duration, error=error_msg)
            return {
                "error": True,
                "message": error_msg
            }

    def _execute_tool(self, tool_call: Dict) -> Dict[str, Any]:
        """执行单个工具调用"""
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name", "")
        arguments_str = function_info.get("arguments", "{}")
        tool_call_id = tool_call.get("id", "")

        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"success": False, "error": "工具参数 JSON 解析失败"})
            }

        # 为需要 session 上下文的工具注入 session_id
        if tool_name in ("create_plan", "update_plan", "set_context", "clear_context", "get_context_summary"):
            arguments["session_id"] = self.session_id

        tool_func = TOOL_MAP.get(tool_name)
        if not tool_func:
            err = f"未知工具: {tool_name}"
            log_tool_call(self.session_id, tool_name, arguments, {"success": False, "error": err}, 0, error=err)
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"success": False, "error": err})
            }

        start = time.time()
        try:
            result = tool_func(**arguments)
            duration = (time.time() - start) * 1000
            log_tool_call(self.session_id, tool_name, arguments, result, duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            result = {"success": False, "error": f"工具执行异常: {str(e)}"}
            log_tool_call(self.session_id, tool_name, arguments, result, duration, error=str(e))

        return {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "name": tool_name,
            "content": json.dumps(result, ensure_ascii=False, default=str)
        }

    def run(
        self,
        user_input: str,
        progress_callback: Optional[Callable[[str, Dict], None]] = None
    ) -> Dict[str, Any]:
        """
        执行 Agent 主循环。
        progress_callback(stage, data) 用于向前端报告进度:
            stage: 'thinking' | 'tool_call' | 'tool_result' | 'final'
            data: 相关数据字典
        """
        # 添加用户消息
        self.messages.append(Message(role="user", content=user_input))

        iteration = 0
        final_response = None

        while iteration < self.max_iterations:
            iteration += 1

            if progress_callback:
                progress_callback("thinking", {"iteration": iteration, "message": "Agent 正在思考..."})

            # 调用 LLM
            llm_response = self._call_llm(tools=True)

            if llm_response.get("error"):
                error_msg = llm_response.get("message", "未知错误")
                log_error(self.session_id, "llm_response", error_msg, {"iteration": iteration})
                self.messages.append(Message(role="assistant", content=f"发生错误: {error_msg}"))
                if progress_callback:
                    progress_callback("final", {"error": True, "message": error_msg})
                return {"success": False, "error": error_msg, "messages": self._extract_visible_messages()}

            if not llm_response.get("choices"):
                error_msg = "LLM 返回空 choices"
                log_error(self.session_id, "llm_response", error_msg, {"iteration": iteration, "raw": llm_response})
                if progress_callback:
                    progress_callback("final", {"error": True, "message": error_msg})
                return {"success": False, "error": error_msg, "messages": self._extract_visible_messages()}

            # 检测 OpenRouter server tool 使用情况并通知前端
            usage = llm_response.get("usage", {})
            server_tool_use = usage.get("server_tool_use", {})
            if server_tool_use and progress_callback:
                progress_callback("server_tool_usage", {
                    "server_tool_use": server_tool_use
                })

            choice = llm_response["choices"][0]
            message_data = choice.get("message", {})
            assistant_content = message_data.get("content", "") or ""
            tool_calls = message_data.get("tool_calls", [])
            images = message_data.get("images", [])
            reasoning = message_data.get("reasoning") or None
            reasoning_details = message_data.get("reasoning_details") or None

            # 将 assistant 回复加入历史（保留 reasoning 供多轮传递）
            self.messages.append(Message(
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls,
                images=images,
                reasoning=reasoning,
                reasoning_details=reasoning_details
            ))

            # 如果没有工具调用，就是最终回复 —— 流式输出到前端
            if not tool_calls:
                # 先推送 reasoning（如果有）
                if reasoning and progress_callback:
                    progress_callback("reasoning", {
                        "reasoning": reasoning,
                        "reasoning_details": reasoning_details
                    })

                # 流式推送 content（打字机效果）
                if progress_callback and assistant_content:
                    # 按段落/句子拆分推送，平衡流畅度和实时性
                    chunks = _split_stream_chunks(assistant_content)
                    for chunk in chunks:
                        progress_callback("stream_content", {"chunk": chunk})

                final_response = {
                    "success": True,
                    "content": assistant_content,
                    "images": images,
                    "reasoning": reasoning,
                    "iterations": iteration
                }
                if progress_callback:
                    progress_callback("final", final_response)
                return final_response

            # 有工具调用，逐个执行
            if progress_callback:
                progress_callback("tool_call", {
                    "iteration": iteration,
                    "count": len(tool_calls),
                    "tools": [{"name": tc.get("function", {}).get("name"), "id": tc.get("id")} for tc in tool_calls]
                })

            for tc in tool_calls:
                tool_name = tc.get("function", {}).get("name", "")
                tool_args = tc.get("function", {}).get("arguments", "")
                if progress_callback:
                    progress_callback("tool_executing", {
                        "name": tool_name,
                        "arguments": tool_args,
                        "id": tc.get("id")
                    })

                tool_result = self._execute_tool(tc)

                # 将工具结果加入历史
                self.messages.append(Message(
                    role="tool",
                    content=tool_result["content"],
                    tool_call_id=tool_result["tool_call_id"],
                    name=tool_result["name"]
                ))

                # 解析结果用于前端展示
                try:
                    parsed_result = json.loads(tool_result["content"])
                except:
                    parsed_result = {"raw": tool_result["content"]}

                if progress_callback:
                    progress_callback("tool_result", {
                        "name": tool_name,
                        "result": parsed_result,
                        "id": tc.get("id")
                    })

                # 如果是 plan 工具，额外推送 plan 事件供前端展示
                if tool_name == "create_plan" and parsed_result.get("success"):
                    if progress_callback:
                        progress_callback("plan_created", {
                            "plan": parsed_result.get("plan", [])
                        })
                elif tool_name == "update_plan" and parsed_result.get("success"):
                    if progress_callback:
                        progress_callback("plan_updated", {
                            "plan": parsed_result.get("plan", [])
                        })

                # 如果是上下文工具，推送上下文事件供前端展示
                if tool_name == "set_context" and parsed_result.get("success"):
                    if progress_callback:
                        progress_callback("context_set", {
                            "active": True,
                            "source": parsed_result.get("source", ""),
                            "label": parsed_result.get("label", ""),
                            "type": parsed_result.get("type", "text"),
                            "content_length": parsed_result.get("content_length", 0)
                        })
                elif tool_name == "clear_context" and parsed_result.get("success"):
                    if progress_callback:
                        progress_callback("context_cleared", {
                            "active": False,
                            "message": parsed_result.get("message", "")
                        })

        # 达到最大迭代次数
        error_msg = f"达到最大迭代次数限制 ({self.max_iterations})，任务未完成。"
        log_error(self.session_id, "agent_loop", error_msg, {"max_iterations": self.max_iterations})
        return {
            "success": False,
            "error": error_msg,
            "messages": self._extract_visible_messages()
        }

    def _extract_visible_messages(self) -> List[Dict]:
        """提取给用户看的消息历史（排除 system 和 tool 的原始 JSON）"""
        visible = []
        for m in self.messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                # tool 结果在 assistant 的后续回复中会被总结，这里只简要显示
                try:
                    parsed = json.loads(m.content)
                    status = "成功" if parsed.get("success") else "失败"
                    visible.append({
                        "role": "tool",
                        "tool_name": m.name,
                        "status": status,
                        "summary": self._summarize_tool_result(m.name, parsed)
                    })
                except:
                    visible.append({"role": "tool", "content": m.content[:200]})
            else:
                entry = {"role": m.role, "content": m.content}
                if m.images:
                    entry["images"] = m.images
                if m.reasoning:
                    entry["reasoning"] = m.reasoning
                visible.append(entry)
        return visible

    def _summarize_tool_result(self, tool_name: str, result: Dict) -> str:
        """为前端生成工具结果的简短摘要"""
        if not result.get("success"):
            return result.get("error", "失败")[:100]
        if tool_name == "generate_image":
            files = result.get("saved_files", [])
            params = result.get("params_used", {})
            ar = params.get("aspect_ratio") or "默认"
            sz = params.get("image_size") or "默认"
            base = f"生成 {result.get('image_count', 0)} 张图片 (比例:{ar}, 分辨率:{sz})"
            return base + (f"，已保存: {', '.join(files)}" if files else "")
        if tool_name == "generate_video":
            return f"视频已生成" + (f"，已保存: {result.get('saved_file', '')}" if result.get("saved_file") else "")
        if tool_name == "write_file":
            return f"已保存: {result.get('path', '')}"
        if tool_name == "read_file":
            if result.get("type") == "image":
                return f"读取图片: {result.get('path', '')} ({result.get('size', 0)} bytes)"
            lines = result.get("total_lines", 0)
            return f"读取 {lines} 行"
        if tool_name == "edit_file":
            return f"已编辑: {result.get('path', '')}"
        if tool_name == "list_files":
            count = len(result.get("entries", []))
            return f"列出 {count} 个文件/目录"
        if tool_name == "execute_command":
            return f"命令返回码: {result.get('returncode', '?')}"
        if tool_name == "create_plan":
            count = len(result.get("plan", []))
            return f"创建计划: {count} 项任务"
        if tool_name == "update_plan":
            return f"更新计划: {result.get('message', '')}"
        if tool_name == "set_context":
            return f"设定上下文: {result.get('label', result.get('source', ''))} ({result.get('content_length', 0)} 字符)"
        if tool_name == "clear_context":
            return result.get("message", "清除上下文")
        if tool_name == "get_context_summary":
            if result.get("active"):
                return f"当前上下文: {result.get('label', '')} ({result.get('content_length', 0)} 字符)"
            return "无活跃上下文"
        return json.dumps(result, ensure_ascii=False)[:100]

    def reset(self):
        """重置对话历史（保留 system prompt）并清除隐式上下文"""
        from tools import clear_context
        clear_context(self.session_id)
        self.messages = []
        self._init_system()

    def get_messages(self) -> List[Dict]:
        return self._extract_visible_messages()
