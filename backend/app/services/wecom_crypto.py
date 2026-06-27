"""企业微信（WeCom）回调消息加解密 + 主动消息发送。

企业微信自建应用通过"接收消息"回调把用户消息推送到我们配置的 URL。回调走
AES-256-CBC 加密（即 WXBizMsgCrypt 方案），与微信公众平台一致：

  * URL 验证(GET)：对 echostr 解密后原样返回。
  * 消息接收(POST)：body 是带 <Encrypt> 的 XML，解密后得到明文 XML。
  * 签名校验：sha1(sorted([token, timestamp, nonce, encrypt]))。

回复无法在 HTTP 响应里直接带（企业微信被动回复限制多），所以我们用"主动发送
应用消息"接口（access_token + /message/send）把专家的回答推回给用户。

仅依赖 stdlib + pycryptodome（项目已装），不引入企业微信官方 SDK，便于打包。
"""
from __future__ import annotations

import base64
import hashlib
import logging
import socket
import struct
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from Crypto.Cipher import AES

logger = logging.getLogger(__name__)


class WeComCryptoError(Exception):
    """加解密 / 签名校验失败。"""


def _sha1_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """企业微信签名：对 [token, timestamp, nonce, encrypt] 字典序排序后 sha1。"""
    items = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()


class WeComCrypto:
    """封装一个企业微信应用的回调加解密。

    参数:
      token: 自建应用『接收消息』里设置的 Token。
      encoding_aes_key: 43 位的 EncodingAESKey（base64，缺一个 '=' 补齐）。
      corp_id: 企业 CorpID（解密后用于校验 receiveid）。
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        try:
            self.aes_key = base64.b64decode(encoding_aes_key + "=")
        except Exception as e:  # pragma: no cover
            raise WeComCryptoError(f"EncodingAESKey 非法: {e}")
        if len(self.aes_key) != 32:
            raise WeComCryptoError("EncodingAESKey 解码后必须为 32 字节")

    # ---- 校验签名 ----
    def verify_signature(self, signature: str, timestamp: str, nonce: str,
                         encrypt: str) -> bool:
        return _sha1_signature(self.token, timestamp, nonce, encrypt) == signature

    # ---- 解密 ----
    def decrypt(self, encrypt_b64: str) -> str:
        """解密 <Encrypt> 内容，返回明文（XML 或 echostr）。"""
        try:
            ciphertext = base64.b64decode(encrypt_b64)
            cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
            plain = cipher.decrypt(ciphertext)
        except Exception as e:
            raise WeComCryptoError(f"AES 解密失败: {e}")
        # 去 PKCS7 填充
        pad = plain[-1]
        if pad < 1 or pad > 32:
            raise WeComCryptoError("填充长度非法")
        content = plain[:-pad]
        # content = random(16) + msg_len(4, 网络字节序) + msg + receiveid
        if len(content) < 20:
            raise WeComCryptoError("解密内容过短")
        msg_len = struct.unpack(">I", content[16:20])[0]
        msg = content[20:20 + msg_len]
        receive_id = content[20 + msg_len:]
        if self.corp_id and receive_id.decode(errors="ignore") != self.corp_id:
            raise WeComCryptoError("receiveid 与 CorpID 不匹配")
        return msg.decode("utf-8")

    # ---- 加密（如需被动回复时用，目前主要走主动发送）----
    def encrypt(self, plain_xml: str, timestamp: str | None = None,
                nonce: str | None = None) -> dict[str, str]:
        timestamp = timestamp or str(int(time.time()))
        nonce = nonce or str(int(time.time() * 1000) % 1000000000)
        msg = plain_xml.encode("utf-8")
        rand = base64.b64encode(socket.gethostname().encode()).ljust(16, b"0")[:16]
        payload = rand + struct.pack(">I", len(msg)) + msg + self.corp_id.encode()
        pad_len = 32 - (len(payload) % 32)
        payload += bytes([pad_len]) * pad_len
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypt_b64 = base64.b64encode(cipher.encrypt(payload)).decode()
        signature = _sha1_signature(self.token, timestamp, nonce, encrypt_b64)
        return {"encrypt": encrypt_b64, "signature": signature,
                "timestamp": timestamp, "nonce": nonce}


def parse_message_xml(plain_xml: str) -> dict[str, Any]:
    """把解密后的明文 XML 解析成 dict，键为标签名。"""
    out: dict[str, Any] = {}
    try:
        root = ET.fromstring(plain_xml)
        for child in root:
            out[child.tag] = (child.text or "").strip()
    except Exception as e:  # pragma: no cover
        logger.warning("WeCom 消息 XML 解析失败: %s", e)
    return out


# ---------------- 主动发送（access_token 缓存 + /message/send） -------------
class WeComClient:
    """企业微信应用消息发送客户端（带 access_token 缓存）。"""

    def __init__(self, corp_id: str, corp_secret: str, agent_id: str):
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.app_agent_id = agent_id   # 企业微信应用的 AgentId（数字）
        self._token: str | None = None
        self._token_exp: float = 0.0

    async def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(url, params={"corpid": self.corp_id,
                                           "corpsecret": self.corp_secret})
            data = r.json()
        if data.get("errcode", 0) != 0:
            raise WeComCryptoError(f"获取 access_token 失败: {data}")
        self._token = data["access_token"]
        self._token_exp = now + int(data.get("expires_in", 7200))
        return self._token

    async def send_text(self, to_user: str, content: str) -> dict[str, Any]:
        """给指定用户发文本消息。content 超长会被企业微信截断（上限约 2048 字节）。"""
        token = await self._get_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
        # 文本消息上限 2048 字节，超出截断以免整条发送失败。
        safe = content
        while len(safe.encode("utf-8")) > 2000:
            safe = safe[:-50]
        body = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(self.app_agent_id) if str(self.app_agent_id).isdigit() else self.app_agent_id,
            "text": {"content": safe},
            "safe": 0,
        }
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(url, params={"access_token": token}, json=body)
            data = r.json()
        if data.get("errcode", 0) != 0:
            # 40014/42001：token 失效，清缓存下次重取。
            if data.get("errcode") in (40014, 42001):
                self._token = None
            logger.warning("WeCom 发送失败: %s", data)
        return data
