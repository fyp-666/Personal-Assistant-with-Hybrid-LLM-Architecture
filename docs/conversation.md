# 多轮上下文：由项目保存，按路由交给模型

近期上下文由 `src/hybrid_assistant/conversation.py` 管理。CLI 和 Telegram 共用这份实现，但分别保存会话；OpenAI、NIM、Gemma 都通过原有 Hermes 调用函数执行。每次把本轮允许使用的上下文组装进 prompt，不依赖三个 profile 的原生 session 相互同步，也没有改 Hermes 源码。

## 三种状态分别做什么

| 状态 | 存放位置 | 用途 |
| --- | --- | --- |
| 近期对话与当前邮件 | `~/.hermes/profiles/hw3-local/conversations/` | 本项目下一轮主动读取，用于指代、追问和连续讨论 |
| 长期偏好 | `~/.hermes/profiles/hw3-local/memories/USER.md` | Hermes 在 Local 业务调用时加载；现有 `remember.py` 更新 |
| Hermes 原生 session | 各 profile 的 `state.db` | 保留各次调用记录；本项目没有用 `--resume` 将它们拼成共享历史 |

CLI 使用 `cli.json`，Telegram 使用 `telegram-<chat_id>.json`。在 CLI 聊过的内容不会自动进入 Telegram，反之亦然。会话在不同模型间共享，是指同一个入口的这份历史可交给不同执行模型。

## 对照代码看一次消息的传递

```text
examples/assistant.py 或 examples/telegram_bot.py
  → load_conversation(path) → conversation
  → handle_message(message, ..., conversation=conversation)
      → 若 conversation.private 为真：先把 context 收紧到 Local
      → identify_task(message, classifiers, context=...)
          只给当前 message，不给历史、邮件或 USER.md
      → intent.task / intent.context
      → chat 或 follow_up
          → message + history +（追问时的 current_email）
          → plan_route(intent.context) → execute_plan() → Hermes → 模型
      → latest_email_summary
          → Gmail reader → Email → summarize_email() → Hermes → Gemma
      → conversation.record(message, 最终回答, private=..., complexity=..., email=...)
      → AssistantReply
  → save_conversation(path, conversation)
  → CLI 显示，或 Telegram 发送 reply.text
```

`Conversation` 中只有四个字段：

- `turns`：按时间排列的 `{"user": ..., "assistant": ...}` 对话对。换执行模型时，新模型读取这些相同内容。
- `private`：会话是否必须留在本地。旧消息被裁掉也不会自动解除这个标记。
- `email`：最近成功摘要的那封邮件快照，包含发件人、主题和正文。它保存原文，因此追问不只依靠上一条摘要。
- `complexity`：上一轮复杂度。识别为 `follow_up` 且上轮复杂时继续使用复杂路由；独立新问题由本轮识别结果决定。

`record()` 直接更新传入的会话对象，所以外层保存的是已经追加本轮结果的同一个对象。模型或 Gmail 失败时不会追加一轮成功回答。

## 为什么增加 follow_up

分类器仍只看当前消息，例如“第二种呢”“这封邮件的截止时间是什么”，将其标为 `follow_up`。具体的“第二种”是什么，由执行模型结合 `history` 理解。分类器不需要先看到历史才能识别这是一条追问，但自然语言分类仍可能出错。

公开场景可以是：GPT 解释两个概念 → 用户要求复杂比较 → NIM 接收前一轮历史并比较 → 简短追问继承复杂任务上下文。没有历史时收到追问，程序请用户先说明问题，不编造前文。

邮件场景是：读取一次最新邮件 → Gemma 摘要 → 保存这封 `Email` → 追问时使用 `current_email`。追问不会再次读取“最新邮件”，避免有新信到达后答错对象。明确要求再次总结最新邮件才重新读取并替换快照；读到空收件箱则清除旧快照。

## 本轮采用的隐私边界

公开会话的执行模型可以读取公开历史；GPT 分类器始终只读当前消息。一旦处理邮件、私人内容，或实际业务调用回退到 Local，整个会话后续都留在 Local，直到显式开始新会话。原因是 Local 回答可能引用 USER.md，不能在下一轮直接交给云端。

因此，在邮件对话之后单独问一个公开知识问题，也仍由 Gemma 处理。当前实现没有让模型判断私人历史是否可以解除限制。用 Telegram `/new` 或 CLI `--new` 开始公开话题即可恢复正常自动路由。重置不删除 USER.md，不删除 Hermes 已有 session，也不撤回 Telegram 已发送的消息。

新会话的普通输入默认允许送给 GPT；若输入本身包含私人文字，仍需 `/private` 或 `--private`。这套设计管理已知的数据来源和会话依赖，不是自动识别所有私人文字的检测器。

## 保留范围和失败处理

最多保留最近 6 对消息，总计不超过 12,000 字符；单条用户消息或回答存储时最多 6,000 字符。超限先删除最旧的完整对话对。邮件正文快照最多 16,000 字符，超长时附加截短提示，发件人和主题各最多 1,000 字符。这是简单的字符预算，尚未实现模型压缩；截掉的信息不能保证仍能回答。

文件通过同目录临时文件加 `os.replace()` 保存，在 WSL home 中权限为 600。文件损坏时返回错误，不把一个可能包含私人资料的会话悄悄当成新的公开会话。可以用 `/new` 或 `--new` 显式重置。

Telegram 仍使用原有单实例锁，串行处理消息；CLI 请串行运行。保存发生在发送回复之前，若发送失败，生成结果可能已进入会话，但未送达用户。接收器仍停止且不自动重放，保持已有失败语义。

## 自己测试

在已激活项目环境的 WSL 终端运行：

```bash
systemctl --user start hw3-ollama
python examples/assistant.py --new "用两句话分别介绍 Python 列表和元组。"
python examples/assistant.py "第二种和第一种有什么区别？"
python examples/assistant.py "总结最新一封邮件。"
python examples/assistant.py "这封邮件要求我做什么？"
python examples/assistant.py --new "解释什么是二分查找。"
```

Telegram 启动命令仍是 `python examples/telegram_bot.py`，随后在私聊依次发送上述文字；清空时单独发 `/new`。重启接收器会恢复这个私聊的会话。

聊天入口现已复用 `memory.py` 处理明确的记忆请求；仅当识别为 `memory_update` 时更新 USER.md。普通聊天和邮件内容不会自动成为长期记忆。更新反馈会进入近期私有会话；删除长期偏好不清除以前的对话或模型记录，`/new` 可清空本项目近期上下文。详见[记忆说明](memory.md)。

## 本轮验证

上下文检查点通过了 442 项离线测试、Ruff 静态检查和格式检查；加入聊天记忆更新后当前共 452 项测试。新增测试覆盖跨模型历史、邮件快照、重启恢复、私有状态、Local 回退、历史裁剪、损坏文件、原子保存失败，以及 CLI/Telegram 的新会话接线。

真实模型验证的 7 个场景在约 45 秒内通过：GPT 初始回答、GPT 历史交给 NIM、继续 NIM 追问、合成邮件摘要、重新加载后从邮件原文回答编号、私有会话继续使用 Gemma，以及新会话恢复 GPT。共 14 次实际推理，每次记录为一次模型 API 调用、零工具调用。分类调用逐次检查只有当前消息；执行调用检查是否携带预期历史与邮件快照。邮件 reader 仅调用一次，返回合成数据，没有连接真实 Gmail 或发送 Telegram 消息。

初测中 Gemma 曾将邮件编号追问误分为 `email_summary`；明确分类提示后上述完整流程通过。验证证明这些样例的调用链可用，不保证所有自然语言都能正确分类。本轮 Telegram 的重启恢复与 `/new` 由接线测试验证；真实 Telegram 传输沿用此前两次已完成的联调，没有把本轮的模型直连验证称为新的 Telegram 多轮实测。

证据保存在忽略目录 `.hermes-runtime/context-smoke.json`，包含状态、允许的模型元数据及公开合成问题回答，不含真实邮件。检查过的 active config、凭据和 USER.md 内容均未改变。
