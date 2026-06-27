# 企业微信（WeCom）远程桥接 — 技术交接

> 相关产品思考见 [docs/insights/why-wecom-bridge.md](../insights/why-wecom-bridge.md)

## 目标
让用户在**企业微信 App**里直接 @ 自建应用、和本地智能体（专家）多轮对话，
作为继飞书之后的第二个远程桥接渠道。

## 为什么和飞书实现方式不同
飞书提供**长连接(WebSocket)**，桌面无公网也能收发，所以 `bridge_manager` 用
lark-oapi 起常驻 ws 客户端。企业微信自建应用**没有官方长连接**，只能走
**加密回调(webhook)**：

- 用户消息由企业微信服务端以加密 POST 推到我们配置的回调 URL；
- 回复用「主动发送应用消息」接口（`access_token` + `/cgi-bin/message/send`）。

因此企业微信**需要公网可达的回调地址**（桌面环境可用 cpolar / frp 把本机
`47900` 端口穿透到公网）。

## 代码落点
| 文件 | 作用 |
|------|------|
| `backend/app/services/wecom_crypto.py` | 新增。`WeComCrypto`（WXBizMsgCrypt：AES-256-CBC 加解密 + sha1 签名校验 + XML 解析）与 `WeComClient`（access_token 缓存 + 发文本消息）。仅依赖 stdlib + pycryptodome，不引官方 SDK，便于打包 |
| `backend/app/api/bridge.py` | `CHANNELS["wecom"]` 渠道字段目录；新增 `GET/POST /api/bridge/wecom/webhook` 两个回调端点；`_wecom_crypto_and_client()` / `_wecom_handle()` 辅助 |
| `backend/app/services/bridge_manager.py` | `_sync_channel` 增加 `wecom` 分支：webhook 无常驻客户端，仅按配置完整性把状态写成 connected/error |
| `backend/pyproject.toml` | 显式声明 `pycryptodome>=3.20` |
| `backend/sidecar.spec` | `collect_all` 列表加入 `Crypto`，确保 PyInstaller 打包带上加解密库 |
| `frontend/src/views/settings/Bridge.vue` | 数据驱动渲染，自动出现「企业微信」Tab；webhook 回调框补充「需公网可达 + 穿透」提示与开发者后台链接 |

## 请求流（POST 回调）
1. 企业微信推送加密 XML（`<xml><Encrypt>...</Encrypt></xml>`）+ 查询参数
   `msg_signature/timestamp/nonce`。
2. `wecom_receive()`：取 `<Encrypt>` → `verify_signature` 校验 → `decrypt` 得明文
   XML → `parse_message_xml` 取 `FromUserName / MsgType / Content`。
3. **立刻返回空 200**（企业微信要求 5s 内响应，否则重试/报错）。
4. `asyncio.create_task(_wecom_handle(...))` 后台跑 `_run_agent_turn("wecom", ...)`
   （复用与飞书相同的会话绑定 + AgentRunner 逻辑），完成后用
   `WeComClient.send_text(from_user, reply)` 主动推回。

## URL 验证流（GET 回调）
后台保存接收消息配置时企业微信会发 GET：解密 `echostr` 后**原样返回明文**即通过。
`wecom_verify()` 负责。

## 复用点
- 会话上下文、专家选择、Conversation/Message 落库**完全复用** `_run_agent_turn`，
  `channel="wecom"`，`ChannelBinding(channel, external_chat_id)` 以企业微信
  `FromUserName`（用户 UserID）为 key。`channel` 字段 String(16) 容得下 "wecom"。
- 密钥（corp_secret/token/aes_key）走既有 `config_enc` Fernet 加密，read 时掩码 `***`。

## 配置项（管理后台 → 应用 → 自建应用）
| 字段 | 类型 | 说明 |
|------|------|------|
| corp_id | 公开 | 企业 CorpID（ww 开头） |
| agent_id | 公开 | 自建应用 AgentId（数字） |
| corp_secret | 密文 | 应用 Secret（用于换 access_token 发消息） |
| token | 密文 | 接收消息里设置的 Token |
| aes_key | 密文 | 43 位 EncodingAESKey |

## 已验证 / 未验证
- ✅ 加解密 + 签名 + XML 解析 round-trip 单测通过（见提交时的临时脚本）。
- ✅ 后端 import / 路由注册通过。
- ⚠️ 未做企业微信真实回调端到端联调（需公网穿透 + 真实自建应用）。上线前请用
  cpolar 暴露 47900，在后台填回调 URL 完成验证，再发消息验证收发。

## 注意事项
- `WeComClient.send_text` 文本上限 ~2048 字节，超长自动截断，避免整条发送失败。
- access_token 缓存 7200s，遇 40014/42001 自动清缓存重取。
- 非文本消息（图片/事件等）暂回提示文案；后续可扩展。
