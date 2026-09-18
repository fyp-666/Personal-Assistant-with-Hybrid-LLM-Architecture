# 从自然语言请求到实际结果

`examples/assistant.py` 接受一条消息，调用 `src/hybrid_assistant/assistant.py` 的 `handle_message()`。[Telegram 接收器](telegram-inbound.md) 共用它。目前支持普通问题、多轮追问、Gmail 最新一封邮件摘要，以及明确的长期偏好新增、修改和删除。

## 在 WSL 运行

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/assistant.py --new "用两句话解释 Python 列表和元组的区别。"
python examples/assistant.py "第二种适合什么情况？"
python examples/assistant.py "总结最新收到的一封邮件。"
python examples/assistant.py "这封邮件要求我做什么？"
python examples/assistant.py "请记住：解释 Python 概念时，优先给一个简短示例。"
```

入口打印识别模型、任务类型、实际执行模型、是否回退以及最终回答。连续运行会恢复同一个 CLI 会话；`--new` 清空近期上下文后处理本条消息，长期偏好保留。`examples/identify_task.py` 仍是只识别、不执行的预览入口。

新会话的当前请求默认可发给 GPT；输入本身包含私人内容时加 `--private`。`--offline` 让识别和回答都走 Gemma，也阻止 Gmail 读取。进入私有会话之后继续留在本地，直到 `--new`。

## 变量与调用链

CLI 准备 `message`、`context` 和从磁盘加载的 `conversation`，并创建两份模型函数映射：

- `classifiers = create_providers(load_local_context=False)`：识别只接收当前消息，不自动附加 USER.md。
- `providers = create_providers()`：实际执行使用现有默认行为，Local 可读取保存的偏好，OpenAI/NIM 不读私人记忆。

它们只是可调用函数的集合，并不会一次启动多个模型。CLI 还传入两个业务回调：`read_latest_email` 只在新的邮件摘要分支连接 Gmail；`update_memory=update_user_memory` 只在明确的记忆更新分支调用。后者固定使用 Local，不经过通用回答模型再生成一份“记住了”。

```text
load_conversation(path) → conversation
handle_message(message, providers, classifiers=..., context=..., conversation=...)
  → 已知私有会话先收紧 context
  → identify_task(仅当前 message) → intent
      ├─ chat / follow_up
      │    → 当前消息 + 近期历史 + 追问所需的邮件快照
      │    → plan_route(intent.context) → execute_plan() → ExecutionResult
      ├─ memory_update
      │    → update_memory(message) → 本地提取、校验并保存 USER.md
      │    → MemoryUpdate(before, after) → render_memory_update()
      └─ latest_email_summary
           → read_latest_email() → Email
           → summarize_email(email, providers) → Local ExecutionResult
           → render_email_summary(email, result.text)
  → conversation.record() → AssistantReply(text, intent, execution)
save_conversation(path, conversation) → 显示回答
```

`intent` 带有任务类型、执行上下文和实际识别模型。公开普通请求用 GPT，公开复杂请求用 NIM，私有依赖与离线请求用 Gemma。复杂讨论的 `follow_up` 继承上一轮复杂度，独立问题按本轮识别结果决定。识别回退和执行回退继续沿用既有 Local 路径。

邮件摘要仍由现有 `summarize_email()` 固定邮件来源和敏感级别，正文只交给 Local。摘要和来源头组成最终回答；原文另存为同一封邮件的快照，后续追问无需重读邮箱。详见[会话模块逐段说明](conversation.md)。

`AssistantReply.execution` 表示实际业务推理。空邮箱、离线邮件或未接入任务没有业务推理，该字段为 `None`，返回程序说明。Gmail 配置仍由共享 `load_gmail_credentials()` 读取，不复制到新配置或加入 prompt。

## 当前范围

`latest_email_summary` 仅指无筛选条件的最新 INBOX 邮件。新的摘要请求若指定主题、日期、发件人、收件箱序号或粘贴正文，属于 `email_summary`，聊天入口暂时返回说明。原 Gmail 命令的 `--subject`、`--limit`、`--daily` 仍可用。

记忆分支复用 `memory.py`，传入当前用户请求，函数自行读取已有档案；不把邮件快照或近期历史当成保存来源。成功时显示实际增删内容，无变化时明确说明。`AssistantReply.execution` 标记为固定执行的 Local；`finish()` 将这条反馈加入私有会话。详见[记忆调用链](memory.md)。

意图不明时返回澄清；简报、日历暂未接入聊天分支。普通聊天没有邮件查询、日历或实时搜索工具；最新邮件分支才调用 reader。`handle_message()` 不负责 Telegram 收发，也不直接读写会话文件；这些由外层入口负责。

## 验证

当前完整测试数量和真实上下文验证见 [conversation.md](conversation.md)。此前处理函数检查点通过 383 项测试及 Ruff，8 个真实场景覆盖 GPT/NIM 回答、真实 Gmail 到 Gemma 摘要、私有聊天及未接入请求的说明。邮件事实准确性和任意自然语言分类不由这些样例保证。
