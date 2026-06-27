"""Remote Bridge — connect external IM channels (Feishu / QQ / WeChat) to the
local agent so the user can chat with their experts from messaging apps.

This module owns channel configuration + binding management. The actual
message relay (webhook receiver / long-poll adapter) is pluggable per channel
and started by `services.bridge_manager` when a channel is enabled.

Secrets (app_secret, tokens) are stored Fernet-encrypted; the API never echoes
them back in plaintext — it returns a masked "***" sentinel so the UI can show
"configured" without leaking the value.
"""
from __future__ import annotations
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.session import get_db, SessionLocal
from ..db.models import ChannelConfig, ChannelBinding, User
from ..deps import current_user
from ..core.crypto import encrypt_str, decrypt_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bridge", tags=["bridge"])

# Channel field catalogs — mirrors CodePilot's per-channel credential sets.
# `secret: True` fields are stored encrypted and masked on read.
CHANNELS: dict[str, dict] = {
    "feishu": {
        "name": "飞书",
        "desc": "通过飞书长连接（WebSocket）接入，无需公网地址。在飞书开放平台创建企业自建应用，"
                "开启『机器人』能力，并在『事件与回调』中将订阅方式设为『长连接』、添加事件"
                "『接收消息 im.message.receive_v1』，然后把下方 App ID / App Secret 填进来即可。",
        "mode": "ws",   # long-connection — no callback URL required
        "console_url": "https://open.feishu.cn/page/launcher?from=backend_oneclick",
        "console_label": "前往飞书开放平台获取 App ID / App Secret",
        "fields": [
            {"key": "app_id", "label": "App ID", "secret": False, "placeholder": "cli_xxx"},
            {"key": "app_secret", "label": "App Secret", "secret": True, "placeholder": "应用密钥"},
        ],
        "callback_path": None,
    },
    "qq": {
        "name": "QQ",
        "desc": "通过 QQ 开放平台机器人接入。在 QQ 机器人管理端获取 AppID 与 AppSecret/Token。",
        "fields": [
            {"key": "app_id", "label": "AppID", "secret": False, "placeholder": "QQ 机器人 AppID"},
            {"key": "token", "label": "Token", "secret": True, "placeholder": "机器人 Token"},
            {"key": "app_secret", "label": "AppSecret", "secret": True, "placeholder": "机器人 AppSecret"},
        ],
        "callback_path": "/api/bridge/qq/webhook",
    },
    "weixin": {
        "name": "微信",
        "desc": "通过微信公众号 / 企业微信接入。填写公众号的 AppID、AppSecret 和消息校验 Token。",
        "fields": [
            {"key": "app_id", "label": "AppID", "secret": False, "placeholder": "公众号 AppID"},
            {"key": "app_secret", "label": "AppSecret", "secret": True, "placeholder": "公众号 AppSecret"},
            {"key": "token", "label": "消息 Token", "secret": True, "placeholder": "服务器配置 Token"},
            {"key": "aes_key", "label": "EncodingAESKey", "secret": True, "placeholder": "消息加解密密钥（可选）"},
        ],
        "callback_path": "/api/bridge/weixin/webhook",
    },
    "wecom": {
        "name": "企业微信",
        "desc": "通过企业微信自建应用接入，可在企业微信 App 里直接和你的专家对话。"
                "在『企业微信管理后台 → 应用管理 → 自建应用』创建应用，记录企业 CorpID、"
                "应用 AgentId 和 Secret；在该应用『接收消息』里启用 API 接收，把下方回调 URL、"
                "Token、EncodingAESKey 填进后台并随机生成。回调地址需公网可达"
                "（桌面环境可用内网穿透，如 cpolar / frp 暴露本机 47900 端口）。",
        "console_url": "https://work.weixin.qq.com/wework_admin/frame#apps",
        "console_label": "前往企业微信管理后台创建自建应用",
        "fields": [
            {"key": "corp_id", "label": "企业 CorpID", "secret": False, "placeholder": "ww 开头的企业 ID"},
            {"key": "agent_id", "label": "应用 AgentId", "secret": False, "placeholder": "自建应用 AgentId（数字）"},
            {"key": "corp_secret", "label": "应用 Secret", "secret": True, "placeholder": "自建应用 Secret"},
            {"key": "token", "label": "回调 Token", "secret": True, "placeholder": "接收消息里设置的 Token"},
            {"key": "aes_key", "label": "EncodingAESKey", "secret": True, "placeholder": "43 位消息加解密密钥"},
        ],
        "callback_path": "/api/bridge/wecom/webhook",
    },
}

MASK = "***"


def _channel_meta(ch: str) -> dict:
    if ch not in CHANNELS:
        raise HTTPException(404, "未知渠道")
    return CHANNELS[ch]


def _decrypt_secrets(cfg: ChannelConfig) -> dict:
    if not cfg.config_enc:
        return {}
    try:
        return json.loads(decrypt_str(cfg.config_enc) or "{}")
    except Exception:
        return {}


def _serialize(ch: str, cfg: ChannelConfig | None) -> dict:
    meta = CHANNELS[ch]
    public = (cfg.config_json if cfg else {}) or {}
    secrets = _decrypt_secrets(cfg) if cfg else {}
    values: dict[str, str] = {}
    for f in meta["fields"]:
        if f["secret"]:
            values[f["key"]] = MASK if secrets.get(f["key"]) else ""
        else:
            values[f["key"]] = public.get(f["key"], "")
    return {
        "channel": ch,
        "name": meta["name"],
        "desc": meta["desc"],
        "mode": meta.get("mode", "webhook"),
        "console_url": meta.get("console_url"),
        "console_label": meta.get("console_label"),
        "fields": meta["fields"],
        "callback_path": meta.get("callback_path"),
        "enabled": cfg.enabled if cfg else False,
        "agent_id": cfg.agent_id if cfg else None,
        "status": cfg.status if cfg else "disconnected",
        "status_detail": cfg.status_detail if cfg else None,
        "values": values,
    }


@router.get("/channels")
async def list_channels(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """All three channels with their current config (secrets masked)."""
    rows = (await db.execute(select(ChannelConfig))).scalars().all()
    by_ch = {r.channel: r for r in rows}
    return [_serialize(ch, by_ch.get(ch)) for ch in CHANNELS.keys()]


@router.get("/channels/{ch}")
async def get_channel(ch: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    _channel_meta(ch)
    cfg = (await db.execute(select(ChannelConfig).where(ChannelConfig.channel == ch))).scalar_one_or_none()
    return _serialize(ch, cfg)


@router.put("/channels/{ch}")
async def save_channel(ch: str, payload: dict, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Save channel config. Secret fields equal to the mask sentinel keep their
    existing value; empty string clears them; any other value replaces them."""
    meta = _channel_meta(ch)
    cfg = (await db.execute(select(ChannelConfig).where(ChannelConfig.channel == ch))).scalar_one_or_none()
    if cfg is None:
        cfg = ChannelConfig(channel=ch, config_json={}, status="disconnected")
        db.add(cfg)

    incoming = payload.get("values") or {}
    public = dict(cfg.config_json or {})
    secrets = _decrypt_secrets(cfg)
    for f in meta["fields"]:
        k = f["key"]
        if k not in incoming:
            continue
        v = incoming[k]
        if f["secret"]:
            if v == MASK:
                continue                 # unchanged
            if v == "":
                secrets.pop(k, None)     # cleared
            else:
                secrets[k] = v           # replaced
        else:
            public[k] = v
    cfg.config_json = public
    cfg.config_enc = encrypt_str(json.dumps(secrets)) if secrets else None
    if "enabled" in payload:
        cfg.enabled = bool(payload["enabled"])
    if "agent_id" in payload:
        cfg.agent_id = payload["agent_id"]
    # Reset status before the manager re-syncs; it will flip to connected/error.
    if not cfg.enabled:
        cfg.status = "disconnected"
        cfg.status_detail = None
    else:
        cfg.status = "connecting"
        cfg.status_detail = None
    await db.commit()
    await db.refresh(cfg)

    # Hot-reload the live relay so the change takes effect immediately. For
    # Feishu this (re)opens or closes the WebSocket connection and writes the
    # real status back to the row.
    try:
        from ..services.bridge_manager import get_bridge_manager
        await get_bridge_manager().reload(ch)
        await db.refresh(cfg)
    except Exception:
        pass
    return _serialize(ch, cfg)


@router.post("/channels/{ch}/test")
async def test_channel(ch: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Validate that the required (non-optional) credentials are present.

    A full live-handshake requires the channel's webhook to be publicly
    reachable; here we do a config completeness check and surface the callback
    URL the user must register in the channel's developer console.
    """
    meta = _channel_meta(ch)
    cfg = (await db.execute(select(ChannelConfig).where(ChannelConfig.channel == ch))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(400, "尚未配置")
    secrets = _decrypt_secrets(cfg)
    public = cfg.config_json or {}
    missing = []
    for f in meta["fields"]:
        if "（可选）" in f.get("placeholder", "") or "可选" in f.get("placeholder", ""):
            continue
        k = f["key"]
        present = (secrets.get(k) if f["secret"] else public.get(k))
        if not present:
            missing.append(f["label"])
    if missing:
        return {"ok": False, "missing": missing, "message": f"缺少必填项: {', '.join(missing)}"}
    if meta.get("mode") == "ws":
        if cfg.enabled and cfg.status == "connected":
            return {"ok": True, "callback_path": None,
                    "message": "配置完整，且长连接已建立。直接在飞书里给机器人发消息即可对话。"}
        if cfg.enabled and cfg.status == "error":
            return {"ok": False,
                    "message": f"连接失败：{cfg.status_detail or '请检查 App ID / App Secret'}"}
        return {"ok": True, "callback_path": None,
                "message": "配置完整。开启上方开关并保存后，直接在飞书里给机器人发消息即可对话，无需配置回调地址。"}
    return {
        "ok": True,
        "message": "配置完整。请在渠道开发者后台将事件回调地址指向下方 URL。",
        "callback_path": meta.get("callback_path"),
    }


@router.get("/bindings")
async def list_bindings(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ChannelBinding).order_by(ChannelBinding.id.desc()))).scalars().all()
    return [
        {
            "id": b.id, "channel": b.channel,
            "external_chat_id": b.external_chat_id,
            "external_user_name": b.external_user_name,
            "conversation_id": b.conversation_id,
            "agent_id": b.agent_id,
        } for b in rows
    ]


@router.delete("/bindings/{bid}")
async def delete_binding(bid: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = (await db.execute(select(ChannelBinding).where(ChannelBinding.id == bid))).scalar_one_or_none()
    if b:
        await db.delete(b)
        await db.commit()
    return {"ok": True}


# ====================== 企业微信（WeCom）回调 ======================
# 企业微信自建应用通过『接收消息』把用户消息以加密 POST 推到这个回调；
# GET 用于后台保存配置时的 URL 有效性验证（回显解密后的 echostr）。
#
# 回调要求 5 秒内返回，而跑一次专家可能很久 —— 所以我们：
#   * 校验签名 + 解密拿到用户消息；
#   * 立刻返回空 200（满足企业微信时效要求，避免重试 / 报错）；
#   * 在后台异步跑 AgentRunner，再用主动发送接口把回答推回用户。

def _wecom_crypto_and_client(cfg: ChannelConfig):
    """从渠道配置构造 (WeComCrypto, WeComClient)。缺配置返回 (None, None)。"""
    from ..services.wecom_crypto import WeComCrypto, WeComClient
    public = cfg.config_json or {}
    secrets = _decrypt_secrets(cfg)
    corp_id = public.get("corp_id", "")
    agent_id = public.get("agent_id", "")
    token = secrets.get("token", "")
    aes_key = secrets.get("aes_key", "")
    corp_secret = secrets.get("corp_secret", "")
    if not (corp_id and token and aes_key):
        return None, None
    try:
        crypto = WeComCrypto(token=token, encoding_aes_key=aes_key, corp_id=corp_id)
    except Exception as e:
        logger.warning("WeCom 加解密初始化失败: %s", e)
        return None, None
    client = WeComClient(corp_id=corp_id, corp_secret=corp_secret, agent_id=agent_id) \
        if corp_secret else None
    return crypto, client


async def _wecom_load_cfg() -> ChannelConfig | None:
    async with SessionLocal() as db:
        return (await db.execute(
            select(ChannelConfig).where(ChannelConfig.channel == "wecom")
        )).scalar_one_or_none()


@router.get("/wecom/webhook")
async def wecom_verify(msg_signature: str = "", timestamp: str = "",
                       nonce: str = "", echostr: str = ""):
    """企业微信回调 URL 验证：解密 echostr 并原样返回明文。"""
    cfg = await _wecom_load_cfg()
    if cfg is None:
        raise HTTPException(400, "尚未配置企业微信")
    crypto, _ = _wecom_crypto_and_client(cfg)
    if crypto is None:
        raise HTTPException(400, "企业微信配置不完整（需 CorpID / Token / EncodingAESKey）")
    if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
        raise HTTPException(401, "签名校验失败")
    try:
        plain = crypto.decrypt(echostr)
    except Exception as e:
        raise HTTPException(400, f"echostr 解密失败: {e}")
    return PlainTextResponse(plain)


@router.post("/wecom/webhook")
async def wecom_receive(request: Request, msg_signature: str = "",
                        timestamp: str = "", nonce: str = ""):
    """接收企业微信用户消息：校验+解密后异步跑专家，立刻 200 返回。"""
    from ..services.wecom_crypto import parse_message_xml

    cfg = await _wecom_load_cfg()
    if cfg is None or not cfg.enabled:
        # 未启用：直接 200，避免企业微信反复重试。
        return PlainTextResponse("")
    crypto, client = _wecom_crypto_and_client(cfg)
    if crypto is None:
        return PlainTextResponse("")

    raw = (await request.body()).decode("utf-8", errors="ignore")
    try:
        # body 是 <xml><Encrypt>...</Encrypt>...</xml>
        import xml.etree.ElementTree as ET
        encrypt = (ET.fromstring(raw).findtext("Encrypt") or "").strip()
    except Exception:
        encrypt = ""
    if not encrypt:
        return PlainTextResponse("")
    if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypt):
        logger.warning("WeCom 回调签名校验失败")
        return PlainTextResponse("")
    try:
        plain = crypto.decrypt(encrypt)
    except Exception as e:
        logger.warning("WeCom 消息解密失败: %s", e)
        return PlainTextResponse("")

    msg = parse_message_xml(plain)
    msg_type = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "")
    text = (msg.get("Content", "") or "").strip()

    # 只处理文本；其它类型给个提示（若能发送）。
    if msg_type != "text" or not text:
        if client and from_user and msg_type != "event":
            asyncio.create_task(client.send_text(from_user, "目前仅支持文本消息哦~"))
        return PlainTextResponse("")
    if client is None:
        logger.warning("WeCom 收到消息但未配置应用 Secret，无法回复")
        return PlainTextResponse("")

    # 异步跑专家 + 主动回复，HTTP 立即返回。
    asyncio.create_task(_wecom_handle(cfg.agent_id, client, from_user, text))
    return PlainTextResponse("")


async def _wecom_handle(agent_id: int | None, client, from_user: str, text: str) -> None:
    """后台任务：跑一轮专家并把回答主动发回企业微信用户。"""
    from ..services.bridge_manager import _run_agent_turn
    try:
        reply = await _run_agent_turn(
            "wecom", from_user, text, from_user, agent_id)
    except Exception as e:  # pragma: no cover
        logger.exception("WeCom 处理失败: %s", e)
        reply = f"⚠️ 处理失败：{type(e).__name__}"
    try:
        await client.send_text(from_user, reply or "（无输出）")
    except Exception as e:  # pragma: no cover
        logger.exception("WeCom 回复发送失败: %s", e)
