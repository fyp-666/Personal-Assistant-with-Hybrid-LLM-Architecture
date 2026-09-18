# Telegram 接收与回复

这一小步把现有 `handle_message()` 接到已绑定的 Telegram bot，支持问题回答、多轮追问、最新 Gmail 邮件摘要和长期偏好更新。没有重写模型、路由、邮件摘要或消息发送模块。

## 启动与停止

在 VS Code 的 WSL 终端执行：

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/telegram_bot.py
```

看到“Telegram 接收器已启动”后，在 bot 私聊发送文字。终端需要保持运行；`Ctrl+C` 停止。接收器本轮没有安装为开机服务。不要同时启动 Hermes gateway 或另一个接收同一 bot 的程序。

只测试一条消息时：

```bash
python examples/telegram_bot.py --once
```

它会等待、处理并回复一条授权消息，然后退出；之后要继续聊天需重新启动普通模式。

| Telegram 输入 | 行为 |
| --- | --- |
| `用两句话解释 Python 列表和元组的区别` | GPT 识别，再按路由生成回答 |
| `比较两种任务调度方案，分析取舍并给出迁移计划` | 识别为复杂公开任务时交给 NIM |
| `总结最新一封邮件` | GPT 识别请求，程序读取 Gmail，Gemma 摘要并回复 |
| `/private 我有3小时，阅读用了1小时，还剩多久？` | 识别和回答都用 Gemma |
| `这封邮件的截止时间是什么？` | 使用已保存的同一封邮件快照，由 Gemma 回答 |
| `请记住：邮件摘要用中文` | 本地模型提取偏好，校验保存后回复实际变更 |
| `修改我的邮件摘要偏好：改用英文` / `忘记邮件摘要偏好` | 更新或删除对应长期条目 |
| `/new` | 清空近期对话及邮件快照，保留长期偏好 |
| `/start` 或 `/help` | 显示使用说明 |

普通消息沿用用户已确认的规则：只把当前文字交给 GPT 识别，不附带邮件、日历、私人记忆或聊天历史。私人文字要加 `/private`。回复某条旧消息时，仅处理新输入的文字并强制 Local，不附加被引用内容；执行模型可使用该私聊已保存的近期历史，但引用的消息如果不在保留范围内，仍可能缺少信息。转发消息、图片、语音和附件暂时只返回不支持说明。会话一旦含私人内容或实际业务使用 Local，后续识别和回答都保持 Local，直到 `/new`。

## 对照代码

`src/hybrid_assistant/telegram.py` 负责与 Telegram 接收相关的部分：

- `load_telegram_config(profile)`：读取已有 Local profile 的 `.env`，要求同一个数字用户 ID 与私聊 ID；Token 不进入日志或模型 prompt。
- `check_polling_available()`：确认没有 webhook；发现已有 webhook 时停止，不修改它。
- `get_updates()`：通过官方 Bot API 长轮询取回新消息，正常等待最多 20 秒，HTTP 超时 35 秒。
- `reply_to_update()`：先检查发送者、私聊类型与固定聊天 ID，再处理命令或调用传入的业务函数。其他用户和群聊不会调用模型，也不会收到回复。

`examples/telegram_bot.py` 负责运行接线：

```text
Telegram getUpdates → update
  → reply_to_update(update, config, handle=handle, send=send, reset=reset)
      → 检查用户和私聊，提取当前 text 与 RequestContext
      → handle(text, context)
          → load_conversation()
          → handle_message(conversation=...) → 识别/路由/业务函数并更新会话
          → save_conversation() → AssistantReply.text
      → send(text)
          → send_message(text, target="telegram:已绑定私聊ID")
          → Hermes CLI → 同一个 Telegram 私聊
```

`handle` 负责加载会话、调用统一业务入口和保存结果；`send` 复用已有 Hermes 发送封装；`reset` 保存一份空会话，供授权用户的 `/new` 调用。接收人由本地账号绑定决定，用户消息和模型输出都无法另选接收人。普通聊天不读取 Gmail 配置，邮件分支才读取。模型/Gmail/会话文件的预期失败回复一条简短说明；发送失败或结果不明时停止，不自动重复发。

项目接收器使用 Python 标准库访问 Telegram Bot API，不新增运行依赖。模型仍由 Hermes profiles 执行，回复仍由 `hermes send` 处理，包括已有的长文本拆分和附件标记拒绝。本机 Hermes 公开了原生平台 handler 注册接口；本轮使用独立接收入口，保持现有任务路由与官方 gateway 默认消息处理彼此独立，没有修改 Hermes 源码。

## 进度记录

近期对话保存在 `~/.hermes/profiles/hw3-local/conversations/telegram-<chat_id>.json`，重启后恢复。保留范围、私有标记与邮件快照见[上下文说明](conversation.md)。长期记忆先由更新函数保存，随后保存近期会话，再发送回复。若后两步失败，已提交的长期记忆不会自动撤销；会话文件错误提示会明确这一点。发送失败时生成结果也可能已保存。Hermes 仍按原有配置记录各次模型调用。接收进度状态另存于 `~/.hermes/profiles/hw3-local/telegram-inbound/`：

- `receiver.lock`：WSL 文件锁，防止启动两个项目接收器。
- `offset`：下一条要读取的更新编号，不保存聊天正文。

首次启动跳过之前积压的消息；以后从保存的位置继续。程序在处理每条更新前原子保存下一编号，避免进程重启后重复推理或重复回复。代价是处理途中崩溃可能让该请求没有回答；用户可重新发送。这是简化的“不自动重放已开始请求”，不承诺每条消息恰好送达一次。

网络或发送错误会显示错误并退出，修复后重新启动即可。日常使用请保持 WSL 和这个终端可用。已有 08:00 每日简报仍由 Windows 定时任务触发，与这个前台接收器分别运行；本轮未改动其配置。

## 验证与参考

452 项项目测试和 Ruff 检查通过，包括 34 项接收模块测试及 7 项 CLI 接线测试，覆盖重启恢复、`/new` 会话清空和记忆回调接线。覆盖绑定身份、私有路由、引用隔离、未知命令、传输错误、首次跳过旧消息、保存进度、重启去重和单实例锁。

此前两次用户发起的真实单消息联调已完成：普通 Python 问题经过 GPT 识别与回答后回复 Telegram；“总结最新一封邮件”经过 GPT 识别、真实 Gmail 读取与 Gemma 摘要后回复 Telegram。两次 `--once` 进程均正常退出，Hermes 发送成功；配置、凭据和 USER.md 哈希未改变。现在继续使用需要运行上面的普通启动命令。

接收语义参考 [Telegram 官方 getUpdates 文档](https://core.telegram.org/bots/api#getupdates)；框架扩展接口参考 [Hermes 官方平台 handler 文档](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/#register-native-platform-handlers-any-platform)。

聊天记忆更新联调也已完成：用户亲自发送长期偏好请求，GPT 识别、Gemma 本地提取并写入正式 USER.md，随后通过 Hermes 回复同一个私聊。回复内容与实际保存差异核对一致。一次性接收器已正常退出；后续聊天继续使用上方普通启动命令。
