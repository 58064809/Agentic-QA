from __future__ import annotations

from runtime.llm.config import OpenAICompatibleConfig


class OpenAICompatibleAdapter:
    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    def generate_text(self, prompt: str) -> str:
        if not self.config.api_key:
            raise ValueError("缺少 FREEMODEL_API_KEY，无法调用 LLM。")

        from openai import OpenAI

        client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        response = client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 Agentic-QA 的 QA 草稿生成助手，"
                        "只输出可人工审核的 Markdown 草稿。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM 返回内容为空。")
        return content
