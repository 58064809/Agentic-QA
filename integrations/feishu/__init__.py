"""飞书集成 — 使用 lark-oapi SDK 封装飞书 Open API。"""

from integrations.feishu.client import (
    get_feishu_client as get_feishu_client,
)
from integrations.feishu.client import (
    has_api_credentials as has_api_credentials,
)
from integrations.feishu.doc_fetcher import (
    fetch_docx_content as fetch_docx_content,
)
from integrations.feishu.doc_fetcher import (
    fetch_docx_raw_content as fetch_docx_raw_content,
)
from integrations.feishu.doc_fetcher import (
    fetch_wiki_node as fetch_wiki_node,
)

__all__ = [
    "fetch_docx_content",
    "fetch_docx_raw_content",
    "fetch_wiki_node",
    "get_feishu_client",
    "has_api_credentials",
]
