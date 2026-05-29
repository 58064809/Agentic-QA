"""飞书 SDK 客户端封装，自动管理 tenant_access_token。

使用 lark-oapi SDK 替代原手写 HTTP 调用（_get_tenant_token / _api_get）。
"""

from __future__ import annotations

import os

from lark_oapi import Client, LogLevelEnum

_client_instance: Client | None = None


def get_feishu_client() -> Client:
    """获取飞书 SDK Client（单例），从环境变量读取应用凭证。

    Returns:
        lark_oapi.Client 实例

    Raises:
        ValueError: 未配置 FEISHU_APP_ID / FEISHU_APP_SECRET
    """
    global _client_instance

    if _client_instance is not None:
        return _client_instance

    app_id = os.environ.get("FEISHU_APP_ID") or os.environ.get("LARK_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET") or os.environ.get("LARK_APP_SECRET")

    if not app_id or not app_secret:
        raise ValueError(
            "未配置飞书应用凭证。请设置环境变量：\n"
            "  FEISHU_APP_ID    或 LARK_APP_ID\n"
            "  FEISHU_APP_SECRET 或 LARK_APP_SECRET\n\n"
            "获取方式：前往 https://open.feishu.cn/app 创建企业自建应用，"
            "开启「获取文档内容」权限后获取。"
        )

    _client_instance = (
        Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(LogLevelEnum.ERROR)
        .build()
    )
    return _client_instance


def has_api_credentials() -> bool:
    """检查是否配置了飞书 Open API 凭证。"""
    return bool(
        os.environ.get("FEISHU_APP_ID") or os.environ.get("LARK_APP_ID")
    ) and bool(
        os.environ.get("FEISHU_APP_SECRET") or os.environ.get("LARK_APP_SECRET")
    )
