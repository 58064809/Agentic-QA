"""使用 lark-oapi SDK 获取飞书文档内容。

提供类型安全的 SDK 封装，替代原 feishu_fetcher.py 中手写 HTTP 的
_get_tenant_token / _api_get / _get_wiki_node_info / _get_docx_content 等函数。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from lark_oapi.api.docx.v1.model import (
    GetDocumentRequest,
    RawContentDocumentRequest,
)
from lark_oapi.api.wiki.v2.model import GetNodeSpaceRequest
from lark_oapi.api.docs.v1.model import GetDocumentContentRequest

from integrations.feishu.client import get_feishu_client

# ── 新版文档（docx） ─────────────────────────────────────────────────────


def fetch_docx_meta(doc_id: str) -> Dict[str, Any]:
    """获取新版文档元信息（标题等）。

    Returns:
        dict: {title: str}
    """
    client = get_feishu_client()
    req = GetDocumentRequest.builder().document_id(doc_id).build()
    resp = client.docx.v1.document.get(req)
    if not resp.success():
        _raise_sdk_error("获取文档元信息失败", resp.code, resp.msg)
    doc = resp.data.document
    return {"title": doc.title or "未命名文档"}


def fetch_docx_raw_content(doc_id: str) -> str:
    """获取新版文档的 raw_content（Markdown 格式）。

    Returns:
        markdown 文本
    """
    client = get_feishu_client()
    req = RawContentDocumentRequest.builder().document_id(doc_id).build()
    resp = client.docx.v1.document.raw_content(req)
    if not resp.success():
        _raise_sdk_error("获取文档 raw_content 失败", resp.code, resp.msg)
    return resp.data.raw_content or ""


def fetch_docx_content(doc_id: str) -> Tuple[str, str]:
    """获取新版文档内容，返回 (title, markdown)。

    先获取 raw_content，如果为空再尝试 blocks 兜底（调用方负责兜底逻辑）。
    """
    meta = fetch_docx_meta(doc_id)
    title = meta["title"]
    content = fetch_docx_raw_content(doc_id)
    return title, content


# ── Wiki 节点 ────────────────────────────────────────────────────────────


def fetch_wiki_node(wiki_token: str) -> Dict[str, Any]:
    """查询 Wiki 节点信息。

    Returns:
        dict: {obj_token, obj_type, space_id, title}
    """
    client = get_feishu_client()
    req = GetNodeSpaceRequest.builder().token(wiki_token).build()
    resp = client.wiki.v2.space.get_node(req)
    if not resp.success():
        _raise_sdk_error("查询 Wiki 节点失败", resp.code, resp.msg)
    node = resp.data.node
    if not node:
        raise ValueError("未找到该 Wiki 节点，请检查链接是否正确。")
    return {
        "obj_token": node.obj_token,
        "obj_type": node.obj_type,
        "space_id": node.space_id or "",
        "title": node.title or "",
    }


# ── 旧版文档（doc） ──────────────────────────────────────────────────────


def fetch_doc_content(doc_token: str) -> Tuple[str, str]:
    """获取旧版文档内容（doc 格式）。返回 (title, content)。"""
    client = get_feishu_client()
    req = GetDocumentContentRequest.builder().doc_token(doc_token).build()
    resp = client.docs.v1.document_content.get(req)
    if not resp.success():
        _raise_sdk_error("获取旧版文档内容失败", resp.code, resp.msg)
    content = resp.data.content or ""
    title = resp.data.title or "未命名文档"
    return title, content


# ── 公共 ─────────────────────────────────────────────────────────────────


def _raise_sdk_error(context: str, code: int, msg: str) -> None:
    """格式化 SDK 错误信息为 ValueError，含中文提示。"""
    hints = {
        99991663: "应用未获得该文档的访问权限，请在飞书开发者后台添加「文档」权限并重新授权。",
        99991668: "文档不存在或已被删除。",
        99991664: "没有权限访问该知识库/空间。",
        403: "访问被拒绝，请检查应用权限范围。",
    }
    hint = hints.get(code, "")
    raise ValueError(
        f"{context} (code={code}): {msg}"
        + (f"\n💡 {hint}" if hint else "")
    )
