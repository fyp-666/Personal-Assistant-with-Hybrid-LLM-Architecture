# 任务识别与执行路由

`src/app/intent.py` 判断任务、复杂度及私人上下文需求；`src/core/routing.py` 根据可信元数据选择实际执行模型。识别已整合进聊天循环，不再维护独立的路由预览脚本。

## 数据顺序

```text
入口提供当前消息与 RequestContext
  → 已有私有会话先收紧限制
  → plan_route(分类用 context，复杂度设为 NORMAL)
  → GPT 或 Local 识别当前消息
  → 验证三个 JSON 字段
  → 保留调用方限制，并根据任务进一步收紧
  → handler 分派业务
  → plan_route(执行用 context) → 执行
```

分类模型使用 `create_providers(load_local_context=False)`，只看到 `{"message": "..."}` 和固定说明。它不读取 USER.md、邮件、日历或历史。普通允许公开的当前文字交给 GPT；已知私有、未知来源/隐私、离线或禁止云端的输入连分类也走 Local。NIM 只承担复杂公开业务执行，不承担分类。

模型返回例如：

```json
{"task": "latest_email_summary", "complexity": "normal", "needs_private_context": true}
```

| 字段 | 可用值 / 含义 |
| --- | --- |
| `task` | `chat`、`follow_up`、`latest_email_summary`、`email_summary`、`email_briefing`、`calendar`、`memory_update`、`unknown` |
| `complexity` | `normal` 或 `complex` |
| `needs_private_context` | 是否依赖邮件、日历、私人偏好等数据，只能收紧路由 |

识别出任务类型不代表已实现该功能。聊天入口只处理[已接入的分支](assistant.md)，其余返回能力说明。

## 硬性边界与失败

模型不能返回 provider，也不能用 `chat` 或 `false` 清除调用方的来源、敏感级别、离线和云端限制。业务取得邮件/日历后，领域函数仍自行固定 Local 路由。

GPT 调用发生 `ProviderError` 时可按既有计划回退 Gemma，并保持本次执行 Local。Local 私有调用失败不会转到远程。非法 JSON、未知字段和值会终止，不执行任务，不额外重试。

这不是通用私人文本检测器。新会话含私人内容时用 `chat --private` 或 Telegram `/private`。分类通常会增加一次模型调用，这是自动分派的时间和用量成本。

## 检查

通过 `hybrid-assistant chat "当前问题"` 查看实际识别与执行结果。离线测试覆盖分类载荷、字段验证、调用方限制、回退及业务路由；运行 `python -m pytest -q`。以往真实识别样例保存在 `Task.md`，不等于任意输入都分类正确。