"""LINE Messaging API 輕量封裝（不需額外 SDK，直接呼叫 REST）。

- verify_signature：驗證 webhook 的 X-Line-Signature（HMAC-SHA256 + channel secret）
- reply：以 replyToken 立即回覆（效期短，用於「查詢中…」）
- push：主動推播（用於背景分析完成後送出完整結果）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import requests

from ..config import settings

logger = logging.getLogger(__name__)

_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def is_configured() -> bool:
    return bool(
        settings.line_channel_access_token and settings.line_channel_secret
    )


def verify_signature(body: bytes, signature: str | None) -> bool:
    """驗證 LINE webhook 簽章，防止偽造請求。"""
    secret = settings.line_channel_secret
    if not secret or not signature:
        return False
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.line_channel_access_token}",
    }


def reply(reply_token: str, text: str) -> None:
    """以 replyToken 回覆文字訊息。"""
    if not settings.line_channel_access_token:
        logger.warning("[line] 未設定 access token，略過 reply")
        return
    try:
        resp = requests.post(
            _REPLY_URL,
            headers=_headers(),
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning("[line] reply failed %s: %s", resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[line] reply error: %s", exc)


def push(to: str, text: str) -> None:
    """主動推播文字訊息給指定 userId。"""
    if not settings.line_channel_access_token:
        logger.warning("[line] 未設定 access token，略過 push")
        return
    try:
        resp = requests.post(
            _PUSH_URL,
            headers=_headers(),
            json={"to": to, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.warning("[line] push failed %s: %s", resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[line] push error: %s", exc)


def push_image(to: str, original_url: str, preview_url: str | None = None) -> None:
    """主動推播圖片訊息給指定 userId。

    LINE image message 要求 ``originalContentUrl`` / ``previewImageUrl`` 皆為
    公開可達的 HTTPS 網址（JPEG/PNG）。
    """
    if not settings.line_channel_access_token:
        logger.warning("[line] 未設定 access token，略過 push_image")
        return
    if not original_url or not original_url.lower().startswith("https://"):
        logger.warning("[line] 圖片網址非 HTTPS，略過 push_image：%s", original_url)
        return
    preview = preview_url or original_url
    try:
        resp = requests.post(
            _PUSH_URL,
            headers=_headers(),
            json={
                "to": to,
                "messages": [
                    {
                        "type": "image",
                        "originalContentUrl": original_url,
                        "previewImageUrl": preview,
                    }
                ],
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.warning(
                "[line] push_image failed %s: %s", resp.status_code, resp.text
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[line] push_image error: %s", exc)

