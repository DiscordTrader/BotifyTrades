"""
Base agent class with Claude API tool-use loop.
All specialized agents inherit from this.
"""
import json
import traceback
from typing import List, Dict, Any, Optional
from ..agent_types import AgentIdentity, AgentMessage, AgentState
from ..bus import MessageBus
from ..config import AgentConfig


class BaseAgent:
    _auth_manager = None

    def __init__(self, identity: AgentIdentity, bus: MessageBus, tools: list = None):
        self.identity = identity
        self.bus = bus
        self._tools = tools or []
        self._client = None
        self._state = AgentState(name=identity.name)
        self._budget_usd = AgentConfig.DEFAULT_BUDGET_USD

    @classmethod
    def set_auth_manager(cls, auth_manager):
        cls._auth_manager = auth_manager

    def _get_client(self):
        if self._client is None:
            if self._auth_manager:
                self._client = self._auth_manager.get_client()
            else:
                import anthropic
                self._client = anthropic.Anthropic(api_key=AgentConfig.get_api_key())
        return self._client

    def _get_system_prompt(self) -> str:
        raise NotImplementedError("Subclasses must implement _get_system_prompt")

    def _get_tool_definitions(self) -> list:
        defs = []
        for tool_provider in self._tools:
            if hasattr(tool_provider, 'get_tool_definitions'):
                defs.extend(tool_provider.get_tool_definitions())
        return defs

    def _execute_tool(self, name: str, args: dict) -> dict:
        for tool_provider in self._tools:
            if hasattr(tool_provider, 'execute_tool'):
                defs = tool_provider.get_tool_definitions()
                tool_names = [d["name"] for d in defs]
                if name in tool_names:
                    return tool_provider.execute_tool(name, args)
        return {"success": False, "error": f"Tool not found: {name}"}

    def _update_state(self, status: str, progress: int = 0, task_id: str = None):
        self._state.status = status
        self._state.progress_pct = progress
        if task_id:
            self._state.current_task_id = task_id
        self.bus.publish_state(self._state)

    def _emit(self, task_id: str, to_agent: str, msg_type: str, content: str, metadata: dict = None):
        msg = AgentMessage(
            from_agent=self.identity.name,
            to_agent=to_agent,
            message_type=msg_type,
            task_id=task_id,
            content=content,
            metadata=metadata or {},
        )
        self.bus.publish(msg)
        return msg

    def run(self, task_id: str, input_message: AgentMessage) -> AgentMessage:
        from datetime import datetime, timezone
        self._state.started_at = datetime.now(timezone.utc).isoformat()
        self._update_state("thinking", 10, task_id)

        try:
            result = self._execute_agent_loop(task_id, input_message)
            self._update_state("done", 100, task_id)
            return result
        except Exception as e:
            error_msg = f"Agent {self.identity.name} failed: {str(e)}"
            self._update_state("error", 0, task_id)
            return self._emit(task_id, "orchestrator", "error", error_msg, {
                "traceback": traceback.format_exc()
            })

    def _execute_agent_loop(self, task_id: str, input_message: AgentMessage) -> AgentMessage:
        client = self._get_client()
        system_prompt = self._get_system_prompt()
        tool_defs = self._get_tool_definitions()

        messages = [
            {"role": "user", "content": self._build_input(input_message)}
        ]

        api_kwargs = {
            "model": self.identity.model,
            "max_tokens": 4096,
            "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }
        if tool_defs:
            api_kwargs["tools"] = tool_defs

        total_input_tokens = 0
        total_output_tokens = 0
        iteration = 0
        max_iterations = 20

        while iteration < max_iterations:
            iteration += 1
            progress = min(10 + (iteration * 4), 90)
            self._update_state("working", progress, task_id)

            response = client.messages.create(**api_kwargs)

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            self._state.token_usage = {"input": total_input_tokens, "output": total_output_tokens}

            running_cost = AgentConfig.estimate_cost(
                self.identity.model, total_input_tokens, total_output_tokens
            )
            if running_cost > self._budget_usd:
                return self._emit(task_id, "orchestrator", "error",
                    f"Agent {self.identity.name} exceeded budget ceiling "
                    f"(${running_cost:.4f} > ${self._budget_usd:.2f}). Aborting.",
                    {"cost_usd": round(running_cost, 4), "budget_usd": self._budget_usd}
                )

            if response.stop_reason == "end_turn":
                final_text = self._extract_text(response.content)
                cost = AgentConfig.estimate_cost(
                    self.identity.model, total_input_tokens, total_output_tokens
                )
                return self._emit(task_id, "orchestrator", "handoff", final_text, {
                    "token_usage": {"input": total_input_tokens, "output": total_output_tokens},
                    "cost_usd": round(cost, 4),
                })

            if response.stop_reason == "max_tokens":
                final_text = self._extract_text(response.content)
                return self._emit(task_id, "orchestrator", "error",
                    f"Agent {self.identity.name} hit max_tokens limit. Partial output: {final_text[:200]}...",
                    {"truncated": True}
                )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        self._emit(task_id, "broadcast", "status",
                            f"Using tool: {block.name}", {"tool": block.name, "args": block.input}
                        )
                        result = self._execute_tool(block.name, block.input)
                        result_str = json.dumps(result, default=str)
                        if len(result_str) > 10000:
                            result_str = result_str[:10000] + "... [truncated]"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                api_kwargs["messages"] = messages
                continue

            break

        return self._emit(task_id, "orchestrator", "error",
            f"Agent {self.identity.name} exceeded max iterations ({max_iterations})")

    def _build_input(self, input_message: AgentMessage) -> str:
        parts = [f"Task ID: {input_message.task_id}"]
        if input_message.content:
            parts.append(f"\n{input_message.content}")
        if input_message.metadata:
            parts.append(f"\nContext: {json.dumps(input_message.metadata, indent=2, default=str)}")
        return "\n".join(parts)

    def _extract_text(self, content) -> str:
        texts = []
        for block in content:
            if hasattr(block, 'text'):
                texts.append(block.text)
        return "\n".join(texts)

    def set_budget(self, budget_usd: float):
        self._budget_usd = budget_usd

    def reset(self):
        self._state = AgentState(name=self.identity.name)
        self._budget_usd = AgentConfig.DEFAULT_BUDGET_USD
        self._client = None
        self.bus.publish_state(self._state)
