# 自然语言请求与业务处理

`hybrid-assistant chat` 与 [Telegram 接收器](telegram-inbound.md) 共用 `app.assistant.handle_message()`。当前支持聊天、多轮追问、最新一封 Gmail 摘要，以及明确的长期偏好新增、修改和删除。

## 在 WSL 使用

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
hybrid-assistant chat --new "用两句话解释 Python 列表和元组的区别。"
hybrid-assistant chat "第二种适合什么情况？"
hybrid-assistant chat "总结最新收到的一封邮件。"
hybrid-assistant chat "这封邮件要求我做什么？"
```

入口展示识别模型、任务类型、实际执行模型、是否回退与回答。连续调用恢复同一个 CLI 会话；`--new` 重置近期上下文后处理当前消息，保留 USER.md。新会话的输入默认允许发给 GPT；私人内容使用 `--private`。`--offline` 让识别与回答走 Local，也阻止 Gmail 读取。

## 调用顺序

```text
入口加载会话
  → handle_message(message, providers, classifiers, context, conversation)
  → 按已知私有会话先收紧 context
  → identify_task(仅当前 message)
      ├─ chat / follow_up
      │    → 当前消息 + 允许的历史 + 追问时的同一邮件快照
      │    → plan_route → execute_plan
      ├─ latest_email_summary
      │    → 延迟读取 Gmail → Local 摘要 → 来源头与摘要
      └─ memory_update
           → Local 提取 → 校验并保存 USER.md → 实际变更反馈
  → 记录成功轮次 → AssistantReply
conversation_session 保存会话 → 显示或发送回答
处理失败或中断 → 仅保存新锁定的私有状态，不追加成功轮次
```

已知仅限本地的请求在分类前锁定私有状态；分类后要求 Local，或实际开始 Local 业务回退时也锁定。处理失败仍保留这个限制，普通公开远端成功则不因此变私有。

运行接线使用两份惰性的模型映射：

- `create_providers(load_local_context=False)` 用于识别；不注入私人偏好或历史。
- `create_providers()` 用于实际业务；仅 Local 可以加载 USER.md。

`read_latest_email` 和 `update_memory` 是注入的回调，只在对应分支执行。普通聊天不读取 Gmail 凭据。`handle_message()` 不承担消息传输或会话文件保存。

普通公开任务走 GPT，复杂公开任务走 NIM；`follow_up` 可继承上轮复杂度。邮件、私人上下文和记忆操作使用 Local。邮件快照和私有会话细节见[会话说明](conversation.md)。

## 能力范围

`latest_email_summary` 仅指没有筛选条件的最新 INBOX 邮件。指定发件人、主题、日期、序号、批量或粘贴正文的请求不被偷换成“最新一封”；聊天入口暂时返回能力说明。主题筛选与批量摘要使用 `hybrid-assistant gmail --subject "主题" --limit 3`。

明确的长期记忆请求调用 `features.memory`，只给当前请求和已有 USER.md；不会把历史和邮件自动写入偏好。“把这次回答改短”属于追问，“以后回答都简短”才是长期偏好请求。具体含义仍可能被模型误判，应阅读实际变更反馈。

日历和完整日报尚未接入聊天分支。聊天没有浏览器、实时搜索或任意执行工具，不应把模型文字当作已完成外部操作的凭证。

## 验证

离线测试覆盖路由、业务分支、回调延迟加载、会话恢复、邮件快照、记忆接线和失败处理。运行 `python -m pytest -q`。历史真实联调记录位于 `Task.md`；本轮结果以阶段审查报告为准。