from __future__ import annotations

from typing import Any

from runtime.llm.config import OpenAICompatibleConfig

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    OpenAI = None  # type: ignore[assignment]

SYSTEM_PROMPT = "你是 Agentic-QA 的 QA 草稿生成助手，只输出可人工审核的 Markdown 草稿。"
LLM_TIMEOUT_SECONDS = 180.0


class OpenAICompatibleAdapter:
    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    def generate_text(self, prompt: str) -> str:
        if not self.config.api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY，无法调用 LLM。")
        if OpenAI is None:
            raise RuntimeError("openai SDK 未安装，无法调用 LLM。")

        client = self._create_client()
        # chat.completions 优先 (兼容 DeepSeek / 多数 provider)
        try:
            content = self._generate_with_chat_completions(client, prompt)
            if content:
                return content
        except Exception:
            pass

        # responses API fallback (仅支持该接口的 provider)
        try:
            content = self._generate_with_responses(client, prompt)
            if content:
                return content
        except Exception as exc:
            raise RuntimeError("chat.completions 与 responses 均调用失败: " f"{exc}") from exc

        raise ValueError("LLM 返回内容为空。")

    def _create_client(self) -> Any:
        return OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def _generate_with_responses(self, client: Any, prompt: str) -> str:
        # freemodel 的 OpenAI-compatible responses 接口已通过用户本地验证：
        # client.responses.create(model="gpt-5.5", input="纯文本")。
        # 因此这里优先使用纯文本 input，避免 role-list / temperature 等参数导致兼容失败。
        response = client.responses.create(
            model=self.config.model,
            input=f"{SYSTEM_PROMPT}\n\n{prompt}",
        )
        content = _extract_response_text(response)
        if not content:
            raise ValueError("responses.create 返回内容为空。")
        return content

    def _generate_with_chat_completions(self, client: Any, prompt: str) -> str:
        response = client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        return content or ""


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    chunks: list[str] = []
    for output_item in getattr(response, "output", []) or []:
        for content_item in getattr(output_item, "content", []) or []:
            text = getattr(content_item, "text", None)
            if text:
                chunks.append(str(text))
    return "".join(chunks)
