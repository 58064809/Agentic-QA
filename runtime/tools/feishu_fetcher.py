"""从飞书文档链接获取内容，支持两种方式：

1. 公开分享文档 → 网页抓取（无需配置）
2. 私密文档 → 飞书 Open API（需配置 FEISHU_APP_ID / FEISHU_APP_SECRET）

使用 lark-oapi SDK 调用飞书 Open API，替代手写 HTTP。
"""

from __future__ import annotations

import json
import re

import requests
from bs4 import BeautifulSoup

from integrations.feishu import (
    fetch_docx_content,
    fetch_wiki_node,
)
from integrations.feishu import (
    has_api_credentials as _integration_has_api_credentials,
)

# ── URL 模式 ──────────────────────────────────────────────────────────
FEISHU_DOCX_PATTERN = re.compile(r"https?://[-a-zA-Z0-9@:%._+~#=]+\.feishu\.cn/docx/([a-zA-Z0-9]+)")
FEISHU_WIKI_PATTERN = re.compile(r"https?://[-a-zA-Z0-9@:%._+~#=]+\.feishu\.cn/wiki/([a-zA-Z0-9]+)")

# ── 登录页面检测 ─────────────────────────────────────────────────────
LOGIN_INDICATORS = [
    "/accounts/page/login",
    "login_redirect_times",
    "请登录",
    "account/login",
    "passport",
]


def _extract_doc_id(url: str) -> str | None:
    """从飞书链接中提取文档 ID / wiki_token。"""
    for pattern in (FEISHU_DOCX_PATTERN, FEISHU_WIKI_PATTERN):
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _extract_url_type(url: str) -> str | None:
    """判断链接类型: 'docx' | 'wiki' | None"""
    if FEISHU_DOCX_PATTERN.search(url):
        return "docx"
    if FEISHU_WIKI_PATTERN.search(url):
        return "wiki"
    return None


def is_feishu_url(url: str) -> bool:
    return _extract_doc_id(url) is not None


# ── 飞书 Open API 方式（私密文档，使用 lark-oapi SDK） ────────────────


def _fetch_via_api(url: str) -> tuple[str, str]:
    """通过飞书 Open API（lark-oapi SDK）获取文档内容。

    Returns:
        (title, markdown_content)
    """
    doc_id = _extract_doc_id(url)
    url_type = _extract_url_type(url)
    if not doc_id or not url_type:
        raise ValueError(f"无法识别飞书文档链接: {url}")

    if url_type == "wiki":
        # Wiki 链接：先解析节点信息
        node_info = fetch_wiki_node(doc_id)
        obj_token = node_info["obj_token"]
        obj_type = node_info["obj_type"]
        title = node_info["title"]

        if obj_type == "docx":
            _, content = fetch_docx_content(obj_token)
        else:
            raise ValueError(f"仅支持飞书 docx 文档，当前类型: {obj_type}")
        return title or "未命名文档", content

    elif url_type == "docx":
        # 新版文档直链
        title, content = fetch_docx_content(doc_id)
        return title, content

    raise ValueError(f"不支持的链接类型: {url_type}")


# ── 网页抓取方式（公开文档） ──────────────────────────────────────────


def _is_login_page(html: str, url: str) -> bool:
    for indicator in LOGIN_INDICATORS:
        if indicator in html or indicator in url:
            return True
    return False


def _extract_page_title(soup: BeautifulSoup, fallback: str = "未命名文档") -> str:
    for sel in (
        "meta[property='og:title']",
        "meta[name='title']",
        "meta[name='citation_title']",
        "title",
    ):
        tag = soup.select_one(sel)
        if tag:
            text = tag.get("content") or tag.get_text(strip=True)
            if text:
                return text.strip()
    return fallback


def _extract_content_from_html(soup: BeautifulSoup, html: str) -> str:
    from markdownify import markdownify as md

    for selector in (
        "div.doc-content",
        "div[class*='doc-content']",
        "div[data-page-doc-body]",
        "div.ne-view",
        "div#page-content",
        "article",
        "main",
        "div.content",
        "div[class*='content']",
        "div[class*='article']",
    ):
        div = soup.select_one(selector)
        if div:
            html_str = str(div)
            markdown = md(html_str, heading_style="ATX", strip=["script", "style"])
            return _clean_markdown(markdown)
    return ""


def _clean_markdown(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line.strip() == "":
            if not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False
    return "\n".join(cleaned).strip()


def _extract_page_body_text(soup: BeautifulSoup) -> str:
    texts: list[str] = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 10:
            texts.append(text)
    if texts:
        return "\n\n".join(texts)
    return soup.get_text(separator="\n", strip=True)[:50000]


def _extract_content_from_json(soup: BeautifulSoup, html: str) -> str:
    for script in soup.find_all("script"):
        text = script.string or ""

        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});\s*$", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                for key in ("docContent", "document", "content", "pageContent"):
                    val = data.get(key) or {}
                    if isinstance(val, dict):
                        text_val = _deep_search_text(val)
                        if text_val:
                            return text_val
            except (json.JSONDecodeError, KeyError):
                pass

        for prefix in ("__SSR_DATA__", "__FEISHU_DATA__", "__pageData__"):
            if prefix in text:
                m2 = re.search(
                    rf"window\.{re.escape(prefix)}\s*=\s*({{\s*.*?\}});", text, re.DOTALL
                )
                if m2:
                    try:
                        data = json.loads(m2.group(1))
                        for key in ("content", "data", "document", "blocks"):
                            val = data.get(key) or data.get("props", {}).get(key) or ""
                            if isinstance(val, str) and len(val) > 100:
                                return val
                    except (json.JSONDecodeError, KeyError):
                        pass
    return ""


def _deep_search_text(obj, max_depth: int = 5, _depth: int = 0) -> str | None:
    if _depth > max_depth:
        return None
    if isinstance(obj, dict):
        for _key, value in obj.items():
            if isinstance(value, str) and len(value) > 200:
                return value
            if isinstance(value, dict | list):
                result = _deep_search_text(value, max_depth, _depth + 1)
                if result:
                    return result
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict | list):
                result = _deep_search_text(item, max_depth, _depth + 1)
                if result:
                    return result
    return None


def _fetch_via_web(url: str, *, timeout: int = 30) -> tuple[str, str]:
    """通过网页抓取获取公开飞书文档。"""
    doc_id = _extract_doc_id(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise ValueError(f"飞书文档访问失败: {e}") from e

    resp.encoding = "utf-8"
    html = resp.text
    final_url = resp.url

    if _is_login_page(html, final_url):
        raise ValueError("LOGIN_REQUIRED")

    soup = BeautifulSoup(html, "html.parser")
    title = _extract_page_title(soup, f"飞书文档-{doc_id}")

    content = _extract_content_from_html(soup, html)
    if not content:
        content = _extract_content_from_json(soup, html)
    if not content:
        content = _extract_page_body_text(soup)

    return title, content


# ── 统一入口 ──────────────────────────────────────────────────────────


def has_api_credentials() -> bool:
    """检查是否配置了飞书 Open API 凭证。"""
    return _integration_has_api_credentials()


def fetch_feishu_doc(url: str, *, timeout: int = 30) -> tuple[str, str]:
    """从飞书文档链接提取文档内容。

    自动选择获取方式：
    - 如果配置了 FEISHU_APP_ID / FEISHU_APP_SECRET，优先使用 Open API（支持私密文档）
    - 否则使用网页抓取（仅支持公开分享文档）

    Args:
        url: 飞书文档分享链接
        timeout: 请求超时秒数

    Returns:
        (title, markdown_content)

    Raises:
        ValueError: 无法识别链接、获取失败
    """
    doc_id = _extract_doc_id(url)
    if doc_id is None:
        raise ValueError(f"无法识别飞书文档链接: {url}")

    # 优先使用 Open API（如果配置了凭证）
    if has_api_credentials():
        try:
            return _fetch_via_api(url)
        except ValueError as e:
            # 如果 API 失败且有明确原因，向上抛出
            error_msg = str(e)
            if "未配置" not in error_msg and "凭证" not in error_msg:
                raise
            # 凭证相关错误不抛，继续尝试网页抓取

    # 网页抓取
    try:
        return _fetch_via_web(url, timeout=timeout)
    except ValueError as e:
        error_msg = str(e)
        if error_msg == "LOGIN_REQUIRED":
            if has_api_credentials():
                raise ValueError(
                    "飞书 API 也无法访问该文档，请检查：\n"
                    "  1. 应用中是否开启了「文档」相关权限\n"
                    "  2. 是否已将应用添加到该知识库的「管理员」中\n"
                    "  3. 应用是否已发布并生效"
                ) from e
            else:
                raise ValueError(
                    "该飞书文档需要登录才能查看。有两种方式解决：\n\n"
                    "方式 A：配置飞书应用凭证（推荐，支持私密文档）\n"
                    "  1. 前往 https://open.feishu.cn/app 创建企业自建应用\n"
                    "  2. 开启权限：文档 > 获取文档内容、知识库 > 获取知识库内容\n"
                    "  3. 发布应用后，设置环境变量：\n"
                    "     FEISHU_APP_ID=cli_xxx\n"
                    "     FEISHU_APP_SECRET=xxx\n\n"
                    "方式 B：将文档设为公开分享\n"
                    "  文档右上角「分享」→「 anyone with link 」\n\n"
                    "方式 C：下载为 PDF，使用 agentic-qa 自然语言入口传入路径"
                ) from e
        raise
