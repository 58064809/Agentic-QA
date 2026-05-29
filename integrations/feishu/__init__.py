"""飞书集成 — 使用 lark-oapi SDK 封装飞书 Open API。"""

from integrations.feishu.client import get_feishu_client, has_api_credentials
from integrations.feishu.doc_fetcher import (
    fetch_docx_content,
    fetch_docx_raw_content,
    fetch_wiki_node,
    fetch_doc_content,
)
