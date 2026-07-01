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
import uuid
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


class _LenientLock(asyncio.Lock):
    """An asyncio.Lock whose ``release()`` is a no-op when not held.

    lark-oapi's ws.Client._connect()/_disconnect() call ``self._lock.release()``
    in a ``finally`` even when the lock isn't actually held (its early ``return``
    at connect happens *before* the try/finally that acquired it, and the ws
    client runs in its own thread/loop where the lock state can desync). The
    stock Lock raises ``RuntimeError: Lock is not acquired`` there, which killed
    the ws thread and surfaced as a scary startup traceback. Tolerating an
    unbalanced release fixes the crash at its source for both methods.
    """

    def release(self) -> None:
        if self.locked():
            super().release()


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
        # Swap in a lock that tolerates unbalanced release() so lark's
        # _connect/_disconnect finally blocks can't crash the ws thread with
        # "RuntimeError: Lock is not acquired". Safe to replace here: the lock is
        # created in the client's __init__ and only binds to a loop on first use
        # (which happens later, inside self._ws.start() on the ws thread).
        try:
            self._ws._lock = _LenientLock()
        except Exception:  # pragma: no cover — never block startup on this
            pass

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


# ====================== 企业微信智能机器人长连接（WebSocket）======================
# 企业微信『智能机器人』支持长连接 API 模式：通过 wss 建立一条 WebSocket，用
# BotID + Secret 订阅，之后服务端把用户消息以 JSON 命令推下来，开发者再用同一条
# 连接主动回复（支持流式）。无需公网回调地址、无需消息加解密。协议参考：
#   https://developer.work.weixin.qq.com/document/path/101463
#
# 设计上对齐飞书长连接：ws 客户端跑在自己的守护线程 + 事件循环里，重活
# （跑专家、读写本地库）通过 run_coroutine_threadsafe 交回主事件循环执行，
# 流式增量再跨回 ws 线程的循环用同一条连接发出去。

WECOM_WS_URL = "wss://openws.work.weixin.qq.com"
_WECOM_PING_INTERVAL = 30.0   # seconds — 文档建议每 30 秒发一次 ping 保活


def _make_wss_ssl_context():
    """Build an SSL context that trusts the certifi CA bundle.

    In a packaged desktop build the bundled Python often can't reach the OS
    trust store, so the default verification fails with
    ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``.
    Pointing at certifi's bundled cacert.pem (shipped via httpx) fixes it
    without disabling verification.
    """
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover - certifi should always be present
        return ssl.create_default_context()


class _WeComBotClient:
    """One WeCom AI-bot long-connection bound to a single ChannelConfig row.

    Runs an asyncio websocket client in a dedicated daemon thread (its own loop).
    Inbound `aibot_msg_callback` messages are handed to the FastAPI main loop to
    run the AgentRunner safely (the async DB engine is bound to that loop); the
    streamed reply is pushed back over the same socket via `aibot_respond_msg`.
    """

    def __init__(self, bot_id: str, secret: str, agent_id: int | None,
                 main_loop: asyncio.AbstractEventLoop):
        self.bot_id = bot_id
        self.secret = secret
        self.agent_id = agent_id
        self._main_loop = main_loop
        self._thread: threading.Thread | None = None
        self._ws: Any = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._subscribed = False

    # ---- thread / connection lifecycle ----------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"wecom-ws-{self.bot_id}",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop, ws = self._ws_loop, self._ws
        if loop and ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass
        self._thread = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._ws_loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connect_loop())
        except Exception as e:  # pragma: no cover
            logger.warning("wecom ws loop stopped: %s", e)
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._ws_loop = None

    async def _connect_loop(self) -> None:
        try:
            import websockets
        except Exception:  # pragma: no cover
            await self._set_status("error", "缺少 websockets 依赖，请安装后重试")
            return
        backoff = 1
        ssl_ctx = _make_wss_ssl_context()
        while not self._stop.is_set():
            self._subscribed = False
            try:
                async with websockets.connect(
                    WECOM_WS_URL, ssl=ssl_ctx, ping_interval=None, max_size=None
                ) as ws:
                    self._ws = ws
                    await self._subscribe(ws)
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            await self._on_raw(ws, raw)
                    finally:
                        hb.cancel()
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning("wecom ws disconnected: %s; reconnect in %ss", e, backoff)
                await self._set_status("connecting", f"连接断开，重连中…（{e}）")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            finally:
                self._ws = None
            # Clean exit of the read loop (e.g. server closed) → reconnect.
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        await self._set_status("disconnected", None)

    async def _subscribe(self, ws) -> None:
        await ws.send(json.dumps({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": uuid.uuid4().hex},
            "body": {"bot_id": self.bot_id, "secret": self.secret},
        }, ensure_ascii=False))

    async def _heartbeat(self, ws) -> None:
        try:
            while True:
                await asyncio.sleep(_WECOM_PING_INTERVAL)
                await ws.send(json.dumps({
                    "cmd": "ping", "headers": {"req_id": uuid.uuid4().hex},
                }, ensure_ascii=False))
        except asyncio.CancelledError:  # normal teardown
            pass
        except Exception as e:  # pragma: no cover
            logger.debug("wecom heartbeat ended: %s", e)

    # ---- inbound dispatch -----------------------------------------------
    async def _on_raw(self, ws, raw) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        cmd = msg.get("cmd")
        if cmd == "aibot_msg_callback":
            await self._on_message(msg)
        elif cmd == "aibot_event_callback":
            await self._on_event(ws, msg)
        elif cmd is None:
            # Response to subscribe / ping / respond — only errcode matters.
            errcode = msg.get("errcode")
            if errcode in (None, 0):
                if not self._subscribed:
                    self._subscribed = True
                    await self._set_status("connected", None)
                    logger.info("wecom bridge connected (bot_id=%s)", self.bot_id)
            else:
                detail = msg.get("errmsg") or f"errcode={errcode}"
                logger.warning("wecom ws command error: %s", detail)
                if not self._subscribed:
                    await self._set_status("error", f"订阅失败：{detail}")

    async def _on_message(self, msg: dict) -> None:
        body = msg.get("body") or {}
        req_id = (msg.get("headers") or {}).get("req_id") or uuid.uuid4().hex
        if body.get("msgtype") != "text":
            await self._respond_stream(req_id, uuid.uuid4().hex,
                                       "目前仅支持文本消息哦~", finish=True)
            return
        text = ((body.get("text") or {}).get("content") or "").strip()
        if not text:
            return
        chattype = body.get("chattype") or "single"
        chatid = body.get("chatid") or ""
        userid = (body.get("from") or {}).get("userid") or ""
        # Route per conversation: group → chatid, single → sender userid.
        conv_key = chatid if (chattype == "group" and chatid) else userid
        if not conv_key:
            return
        stream_id = uuid.uuid4().hex

        async def on_delta(partial: str) -> None:
            # Runs on the main loop; push the stream frame over the ws loop.
            await self._respond_stream(req_id, stream_id, partial, finish=False)

        # Run the agent turn on the main loop (async DB lives there), await here.
        reply = await self._run_on_main(
            _run_agent_turn("wecom", conv_key, text, userid, self.agent_id,
                            on_delta=on_delta)
        )
        await self._respond_stream(req_id, stream_id, reply or "（无输出）", finish=True)

    async def _on_event(self, ws, msg: dict) -> None:
        body = msg.get("body") or {}
        eventtype = (body.get("event") or {}).get("eventtype") or ""
        req_id = (msg.get("headers") or {}).get("req_id") or uuid.uuid4().hex
        if eventtype == "enter_chat":
            # Lightweight welcome (must reply within 5s; keep it static/fast).
            try:
                await ws.send(json.dumps({
                    "cmd": "aibot_respond_welcome_msg",
                    "headers": {"req_id": req_id},
                    "body": {"msgtype": "text",
                             "text": {"content": "你好，我是你的智能体专家，有什么可以帮你的？"}},
                }, ensure_ascii=False))
            except Exception:  # pragma: no cover
                pass
        elif eventtype == "disconnected_event":
            # The server kicked us because a newer connection subscribed. Stop
            # reconnecting to avoid fighting over the single allowed connection.
            logger.warning("wecom ws kicked by a newer connection; stopping reconnect")
            self._stop.set()
            await self._set_status("error", "该机器人已在别处建立长连接（同一时间仅允许一个连接）")
            try:
                await ws.close()
            except Exception:
                pass

    # ---- outbound: stream a reply frame over the socket -----------------
    async def _respond_stream(self, req_id: str, stream_id: str, content: str,
                              *, finish: bool) -> None:
        """Send/refresh a streaming reply. Cross-loop safe.

        May be called from the main loop (via on_delta) or the ws loop; in both
        cases the actual send is scheduled onto the ws loop that owns the socket.
        """
        loop = self._ws_loop
        ws = self._ws
        if loop is None or ws is None:
            return
        payload = json.dumps({
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": req_id},
            "body": {
                "msgtype": "stream",
                "stream": {"id": stream_id, "finish": finish, "content": content or " "},
            },
        }, ensure_ascii=False)

        async def _send() -> None:
            try:
                await ws.send(payload)
            except Exception as e:  # pragma: no cover
                logger.debug("wecom respond send failed: %s", e)

        running = asyncio.get_running_loop()
        if running is loop:
            await _send()
        else:
            fut = asyncio.run_coroutine_threadsafe(_send(), loop)
            await asyncio.wrap_future(fut)

    # ---- helpers --------------------------------------------------------
    async def _run_on_main(self, coro):
        """Await a coroutine on the FastAPI main loop from the ws loop."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._main_loop)
        return await asyncio.wrap_future(fut)

    async def _set_status(self, status: str, detail: str | None) -> None:
        await self._run_on_main(
            get_bridge_manager()._set_status("wecom", status, detail))


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
        self._clients: dict[str, Any] = {}
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

        # 企业微信走『智能机器人长连接』（WebSocket）：用 BotID + Secret 建一条常驻
        # 连接接收/回复消息，无需公网回调地址、无需加解密。收发在 _WeComBotClient 里。
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
            bot_id = public.get("bot_id", "")
            secret = secrets.get("secret", "")
            missing = []
            if not bot_id:
                missing.append("BotID")
            if not secret:
                missing.append("Secret")
            if missing:
                await self._set_status(channel, "error", f"缺少: {', '.join(missing)}")
                return
            try:
                client = _WeComBotClient(bot_id, secret, cfg.agent_id, self._loop)  # type: ignore[arg-type]
                # Mark connecting *before* starting so the async subscribe-ack
                # that flips the row to "connected" can't be overwritten by a
                # late "connecting" write.
                await self._set_status(channel, "connecting", "正在建立企业微信长连接…")
                client.start()
                self._clients[channel] = client
                logger.info("wecom bridge starting (bot_id=%s)", bot_id)
            except Exception as e:
                logger.exception("wecom bridge start failed: %s", e)
                await self._set_status(channel, "error", str(e))
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



