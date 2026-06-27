"""Remote-bridge relay manager.

Connects external IM channels to the local agent. The first (and simplest)
adapter is **Feishu long-connection (WebSocket)** mode: it needs only the
app's `app_id` + `app_secret` — NO public callback URL, no verification token,
no encrypt key. This makes it usable from a desktop / LAN install where the
backend has no public address.

Lifecycle:
  * `manager.start()` is called once on app startup. It loads every enabled
    Feishu `ChannelConfig` and opens a WebSocket client for each.
  * `manager.reload("feishu")` is called by the API after a config is saved so
    changes take effect without restarting the process.
  * `manager.stop()` tears every client down on shutdown.

The lark-oapi WebSocket client (`lark.ws.Client`) is *blocking* and owns its
own event loop, so each channel runs in a dedicated daemon thread. Inbound
messages are marshalled back onto the FastAPI event loop via
`asyncio.run_coroutine_threadsafe`, where we run the AgentRunner and post the
reply back through the lark HTTP client.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from sqlalchemy import select

from ..db.session import SessionLocal
from ..db.models import ChannelConfig, ChannelBinding, Conversation, Message, User
from ..core.crypto import decrypt_str
from ..runtime.agent_runner import AgentRunner

logger = logging.getLogger(__name__)

# --- streaming-via-card tuning -------------------------------------------
# Feishu has no SSE; we emulate streaming by sending one *updatable* card and
# PATCH-ing its content as tokens arrive. Feishu rate-limits message edits, so
# we throttle updates: push at most once per _STREAM_MIN_INTERVAL seconds, or
# whenever at least _STREAM_MIN_CHARS new characters have accumulated.
_STREAM_MIN_INTERVAL = 0.7   # seconds between card patches
_STREAM_MIN_CHARS = 24       # or when this many new chars buffered


def _build_card(text: str, *, streaming: bool) -> str:
    """Build an interactive-card JSON string for a (partial) reply.

    ``update_multi=True`` makes the card patchable so we can keep editing the
    same message as more text streams in. While streaming we append a subtle
    typing indicator so the user knows more is coming.
    """
    body = text if text else " "
    if streaming:
        body = body + " ●●●"
    card = {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "elements": [
            {"tag": "markdown", "content": body},
        ],
    }
    return json.dumps(card, ensure_ascii=False)


# Optional dependency — only required when a Feishu channel is actually used.
try:  # pragma: no cover - import guard
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        P2ImMessageReceiveV1,
        CreateMessageRequest,
        CreateMessageRequestBody,
        PatchMessageRequest,
        PatchMessageRequestBody,
    )
    _LARK_OK = True
except Exception:  # pragma: no cover
    lark = None  # type: ignore
    _LARK_OK = False


def _patch_lark_disconnect_bug() -> None:
    """Work around a lark-oapi (v1.6.x) bug in ws.Client._disconnect().

    Its ``finally`` block unconditionally calls ``self._lock.release()`` even
    when ``await self._lock.acquire()`` was interrupted by CancelledError (on
    reconnect / dev --reload), raising a noisy ``RuntimeError: Lock is not
    acquired``. This wrapper only releases a lock we actually hold. It is
    harmless if the SDK later fixes this itself.
    """
    if not _LARK_OK:
        return
    try:
        from lark_oapi.ws.client import Client as _WsClient
    except Exception:  # pragma: no cover
        return
    if getattr(_WsClient, "_h3c_disconnect_patched", False):
        return

    async def _safe_disconnect(self):  # type: ignore[no-untyped-def]
        try:
            await self._lock.acquire()
            if self._conn is None:
                return
            await self._conn.close()
        except Exception:
            pass
        finally:
            self._conn = None
            self._conn_url = ""
            self._conn_id = ""
            self._service_id = ""
            if self._lock.locked():
                self._lock.release()

    _WsClient._disconnect = _safe_disconnect
    _WsClient._h3c_disconnect_patched = True


_patch_lark_disconnect_bug()


class _FeishuClient:
    """One Feishu WebSocket connection bound to a single ChannelConfig row.

    Runs the blocking lark ws client in a daemon thread. The main asyncio loop
    is captured so inbound events can hand work back to it safely.
    """

    def __init__(self, app_id: str, app_secret: str, agent_id: int | None,
                 main_loop: asyncio.AbstractEventLoop):
        self.app_id = app_id
        self.app_secret = app_secret
        self.agent_id = agent_id
        self._main_loop = main_loop
        self._thread: threading.Thread | None = None
        self._ws: Any = None
        # HTTP client for sending replies (REST).
        self._api = (
            lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
            if _LARK_OK else None
        )

    # ---- inbound: a user messaged the bot -------------------------------
    def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        try:
            ev = data.event
            msg = ev.message
            chat_id = msg.chat_id
            msg_type = msg.message_type
            text = ""
            if msg_type == "text":
                try:
                    text = (json.loads(msg.content or "{}") or {}).get("text", "")
                except Exception:
                    text = msg.content or ""
            else:
                # Non-text messages aren't handled yet; ack with a hint.
                self._reply(chat_id, "目前仅支持文本消息哦~")
                return
            text = (text or "").strip()
            if not text:
                return
            sender_name = None
            try:
                sender_name = ev.sender.sender_id.open_id  # best-effort id
            except Exception:
                pass
            # Hand the heavy lifting to the main asyncio loop.
            fut = asyncio.run_coroutine_threadsafe(
                self._handle(chat_id, text, sender_name), self._main_loop
            )
            # Don't block the ws thread on the result; log failures async.
            def _done(f):
                try:
                    f.result()
                except Exception as e:  # pragma: no cover
                    logger.exception("feishu handle failed: %s", e)
            fut.add_done_callback(_done)
        except Exception as e:  # pragma: no cover
            logger.exception("feishu on_message error: %s", e)

    # ---- run the agent on the main loop, then reply ---------------------
    async def _handle(self, chat_id: str, text: str, sender_name: str | None) -> None:
        # Send an initial (empty) updatable card immediately so the user sees
        # the bot "thinking", then stream tokens into it by patching the card.
        msg_id = self._send_card(chat_id, "正在思考…", streaming=True)
        if not msg_id:
            # Card send failed — fall back to the old collect-then-send path.
            reply = await _run_agent_turn(
                "feishu", chat_id, text, sender_name, self.agent_id)
            if reply:
                self._reply(chat_id, reply)
            return

        async def on_delta(partial: str) -> None:
            self._patch_card(msg_id, partial, streaming=True)

        reply = await _run_agent_turn(
            "feishu", chat_id, text, sender_name, self.agent_id,
            on_delta=on_delta)
        # Final definitive content (drops the typing indicator).
        self._patch_card(msg_id, reply or "（无输出）", streaming=False)

    # ---- outbound: send an interactive card, return its message_id ------
    def _send_card(self, chat_id: str, text: str, *, streaming: bool) -> str | None:
        if not self._api:
            return None
        try:
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(_build_card(text, streaming=streaming))
                .build()
            )
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.create(req)
            if not resp.success():
                logger.warning("feishu card send failed: code=%s msg=%s",
                               resp.code, resp.msg)
                return None
            return getattr(resp.data, "message_id", None)
        except Exception as e:  # pragma: no cover
            logger.exception("feishu card send error: %s", e)
            return None

    # ---- outbound: patch an existing card's content ---------------------
    def _patch_card(self, message_id: str, text: str, *, streaming: bool) -> None:
        if not self._api or not message_id:
            return
        try:
            body = (
                PatchMessageRequestBody.builder()
                .content(_build_card(text, streaming=streaming))
                .build()
            )
            req = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.patch(req)
            if not resp.success():
                logger.warning("feishu card patch failed: code=%s msg=%s",
                               resp.code, resp.msg)
        except Exception as e:  # pragma: no cover
            logger.exception("feishu card patch error: %s", e)

    # ---- outbound: send a plain-text reply (fallback path) --------------
    def _reply(self, chat_id: str, text: str) -> None:
        if not self._api:
            return
        try:
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.create(req)
            if not resp.success():
                logger.warning("feishu reply failed: code=%s msg=%s",
                               resp.code, resp.msg)
        except Exception as e:  # pragma: no cover
            logger.exception("feishu reply error: %s", e)

    # ---- thread lifecycle ----------------------------------------------
    def start(self) -> None:
        if not _LARK_OK:
            raise RuntimeError("lark-oapi 未安装，无法启用飞书长连接")

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        self._ws = lark.ws.Client(
            self.app_id, self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )

        def _run() -> None:
            try:
                self._ws.start()  # blocking; owns its own loop
            except Exception as e:  # pragma: no cover
                logger.warning("feishu ws stopped: %s", e)

        self._thread = threading.Thread(target=_run, name=f"feishu-ws-{self.app_id}",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        # lark ws client has no public stop(); rely on daemon-thread teardown at
        # process exit. We drop our reference so a reload can replace it.
        self._ws = None
        self._thread = None


# ---------- shared agent-turn runner (used by every channel) ----------
async def _resolve_agent_id(db, explicit_agent_id: int | None) -> int | None:
    """Pick the expert that answers a bridged message.

    Priority: channel-configured agent → system default agent → first enabled.
    """
    from ..db.models import Agent
    if explicit_agent_id:
        a = (await db.execute(select(Agent).where(Agent.id == explicit_agent_id,
                                                  Agent.enabled.is_(True)))).scalar_one_or_none()
        if a:
            return a.id
    a = (await db.execute(select(Agent).where(Agent.is_default.is_(True),
                                              Agent.enabled.is_(True)))).scalar_one_or_none()
    if a:
        return a.id
    a = (await db.execute(select(Agent).where(Agent.enabled.is_(True)).order_by(Agent.id))).scalars().first()
    return a.id if a else None


async def _run_agent_turn(channel: str, external_chat_id: str, text: str,
                          sender_name: str | None, agent_id: int | None,
                          on_delta=None) -> str:
    """Run one agent turn for an inbound IM message and return the reply text.

    A per-(channel, chat) ChannelBinding keeps a persistent local Conversation
    so multi-turn context carries across messages, mirroring the in-app chat.

    If ``on_delta`` is provided it is awaited with the *cumulative* reply text
    as tokens stream in (throttled by the caller's update policy), enabling a
    streaming UX on channels that support editable messages (e.g. Feishu cards).
    """
    import time
    # Import here to avoid a circular import at module load.
    from ..api.chat import _load_agent_context

    async with SessionLocal() as db:
        # Resolve the owning local user (desktop single-user → id=1).
        owner = (await db.execute(select(User).where(User.id == 1))).scalar_one_or_none()
        if owner is None:
            owner = (await db.execute(select(User).order_by(User.id))).scalars().first()
        if owner is None:
            return "系统尚未初始化用户，无法回复。"

        eff_agent_id = await _resolve_agent_id(db, agent_id)
        if eff_agent_id is None:
            return "尚未配置可用的专家（智能体）。"

        # Find or create the binding + conversation for this external chat.
        binding = (await db.execute(
            select(ChannelBinding).where(
                ChannelBinding.channel == channel,
                ChannelBinding.external_chat_id == external_chat_id,
            )
        )).scalar_one_or_none()

        conv = None
        if binding and binding.conversation_id:
            conv = (await db.execute(
                select(Conversation).where(Conversation.id == binding.conversation_id)
            )).scalar_one_or_none()

        if conv is None:
            conv = Conversation(user_id=owner.id, agent_id=eff_agent_id,
                                title=f"[{channel}] {sender_name or external_chat_id}")
            db.add(conv)
            await db.flush()
            if binding is None:
                binding = ChannelBinding(
                    channel=channel, external_chat_id=external_chat_id,
                    external_user_name=sender_name, conversation_id=conv.id,
                    agent_id=eff_agent_id,
                )
                db.add(binding)
            else:
                binding.conversation_id = conv.id
                binding.agent_id = eff_agent_id
            await db.commit()

        # Persist the inbound user message.
        db.add(Message(conversation_id=conv.id, role="user",
                       content_json={"text": text}))
        await db.commit()

        ctx = await _load_agent_context(db, eff_agent_id, conversation_id=conv.id)

        # Consume the runner stream into a single reply string, pushing
        # throttled deltas to on_delta so the channel can render progress.
        runner = AgentRunner(ctx, user_id=owner.id)
        parts: list[str] = []
        tokens_in = tokens_out = 0
        err: str | None = None
        last_push = 0.0
        last_len = 0

        async def _maybe_push(force: bool = False) -> None:
            nonlocal last_push, last_len
            if on_delta is None:
                return
            cur = "".join(parts)
            now = time.monotonic()
            enough_chars = (len(cur) - last_len) >= _STREAM_MIN_CHARS
            enough_time = (now - last_push) >= _STREAM_MIN_INTERVAL
            if not force and not (enough_chars and enough_time):
                return
            if cur == "" and not force:
                return
            last_push = now
            last_len = len(cur)
            try:
                await on_delta(cur)
            except Exception:  # pragma: no cover - never let UI errors abort
                logger.exception("on_delta push failed")

        try:
            async for ev in runner.stream(text, []):
                if ev.type == "text":
                    parts.append((ev.data or {}).get("text", ""))
                    await _maybe_push()
                elif ev.type == "done":
                    tokens_in = (ev.data or {}).get("tokens_in", 0) or 0
                    tokens_out = (ev.data or {}).get("tokens_out", 0) or 0
                elif ev.type == "error":
                    err = (ev.data or {}).get("message") or "执行错误"
        except Exception as e:  # pragma: no cover
            err = f"{type(e).__name__}: {e}"

        reply = ("".join(parts)).strip()
        if not reply and err:
            reply = f"⚠️ 处理失败：{err}"
        if not reply:
            reply = "（无输出）"

        # Persist the assistant reply.
        db.add(Message(conversation_id=conv.id, role="assistant",
                       content_json={"text": reply},
                       tokens_in=tokens_in, tokens_out=tokens_out))
        await db.commit()
        return reply


# ---------- manager singleton ----------
class BridgeManager:
    """Owns one live client per enabled channel and supports hot reload."""

    def __init__(self) -> None:
        self._clients: dict[str, _FeishuClient] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Open clients for every enabled channel. Safe to call once on boot."""
        self._loop = asyncio.get_running_loop()
        await self._reload_all()

    async def _reload_all(self) -> None:
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(ChannelConfig).where(ChannelConfig.enabled.is_(True))
            )).scalars().all()
            cfgs = [(r.channel, r) for r in rows]
        for ch, cfg in cfgs:
            await self._sync_channel(ch, cfg)

    async def reload(self, channel: str) -> None:
        """Re-read one channel's config and (re)connect or disconnect it."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        async with SessionLocal() as db:
            cfg = (await db.execute(
                select(ChannelConfig).where(ChannelConfig.channel == channel)
            )).scalar_one_or_none()
        await self._sync_channel(channel, cfg)

    async def _sync_channel(self, channel: str, cfg: ChannelConfig | None) -> None:
        # Tear down any existing client first.
        old = self._clients.pop(channel, None)
        if old:
            old.stop()

        # 企业微信走加密回调（webhook），无需常驻长连接客户端：只要应用启用且
        # 配置完整，就把状态标成 connected（回调就绪）。真正的收发在
        # api/bridge.py 的 /wecom/webhook 里处理。
        if channel == "wecom":
            if not cfg or not cfg.enabled:
                await self._set_status(channel, "disconnected", None)
                return
            public = cfg.config_json or {}
            secrets = {}
            if cfg.config_enc:
                try:
                    secrets = json.loads(decrypt_str(cfg.config_enc) or "{}")
                except Exception:
                    secrets = {}
            missing = []
            if not public.get("corp_id"):
                missing.append("CorpID")
            if not public.get("agent_id"):
                missing.append("AgentId")
            if not secrets.get("corp_secret"):
                missing.append("Secret")
            if not secrets.get("token"):
                missing.append("Token")
            if not secrets.get("aes_key"):
                missing.append("EncodingAESKey")
            if missing:
                await self._set_status(channel, "error", f"缺少: {', '.join(missing)}")
            else:
                await self._set_status(
                    channel, "connected",
                    "回调已就绪。请确认企业微信后台的接收消息 URL 指向本机回调地址且公网可达。")
            return

        if channel != "feishu":
            # Only Feishu long-connection is implemented for now.
            await self._set_status(channel, "disconnected",
                                   "该渠道暂未支持自动中继" if cfg and cfg.enabled else None)
            return
        if not cfg or not cfg.enabled:
            await self._set_status(channel, "disconnected", None)
            return
        if not _LARK_OK:
            await self._set_status(channel, "error", "缺少 lark-oapi 依赖，请安装后重试")
            return

        app_id = (cfg.config_json or {}).get("app_id", "")
        secrets = {}
        if cfg.config_enc:
            try:
                secrets = json.loads(decrypt_str(cfg.config_enc) or "{}")
            except Exception:
                secrets = {}
        app_secret = secrets.get("app_secret", "")
        if not app_id or not app_secret:
            await self._set_status(channel, "error", "缺少 App ID 或 App Secret")
            return

        try:
            client = _FeishuClient(app_id, app_secret, cfg.agent_id, self._loop)  # type: ignore[arg-type]
            client.start()
            self._clients[channel] = client
            await self._set_status(channel, "connected", None)
            logger.info("feishu bridge connected (app_id=%s)", app_id)
        except Exception as e:
            logger.exception("feishu bridge start failed: %s", e)
            await self._set_status(channel, "error", str(e))

    async def _set_status(self, channel: str, status: str, detail: str | None) -> None:
        async with SessionLocal() as db:
            cfg = (await db.execute(
                select(ChannelConfig).where(ChannelConfig.channel == channel)
            )).scalar_one_or_none()
            if cfg is None:
                return
            cfg.status = status
            cfg.status_detail = detail
            await db.commit()

    async def stop(self) -> None:
        for c in list(self._clients.values()):
            try:
                c.stop()
            except Exception:
                pass
        self._clients.clear()

    # ---- outbound push (used by task notifications, etc.) ----------------
    def feishu_available(self) -> bool:
        """True when a live Feishu client is connected and able to send."""
        c = self._clients.get("feishu")
        return bool(c and c._api)

    async def push_feishu_text(self, text: str) -> dict:
        """Push a plain-text message to every Feishu chat the bot is bound to.

        Returns a status dict: {ok, sent, total, error?}. Used by task
        notifications so a scheduled run can report into Feishu — reusing the
        already-configured remote-bridge connection (no extra credentials).
        """
        client = self._clients.get("feishu")
        if not client or not client._api:
            return {"ok": False, "error": "飞书未连接（请在远程桥接中启用飞书）"}
        async with SessionLocal() as db:
            chat_ids = [
                r[0] for r in (await db.execute(
                    select(ChannelBinding.external_chat_id).where(
                        ChannelBinding.channel == "feishu")
                )).all()
                if r[0]
            ]
        # De-dup while preserving order.
        seen: set[str] = set()
        chat_ids = [c for c in chat_ids if not (c in seen or seen.add(c))]
        if not chat_ids:
            return {"ok": False, "error": "尚无飞书会话绑定，请先在飞书里给机器人发一条消息"}
        sent = 0
        last_err: str | None = None
        loop = asyncio.get_running_loop()
        for cid in chat_ids:
            try:
                # _reply is blocking (lark REST); run it off the event loop.
                await loop.run_in_executor(None, client._reply, cid, text)
                sent += 1
            except Exception as e:  # pragma: no cover
                last_err = f"{type(e).__name__}: {e}"
                logger.warning("feishu push to %s failed: %s", cid, e)
        return {"ok": sent > 0, "sent": sent, "total": len(chat_ids),
                **({"error": last_err} if sent == 0 and last_err else {})}


_manager = BridgeManager()


def get_bridge_manager() -> BridgeManager:
    return _manager



