# Telegram 接收与回复

`hybrid-assistant telegram` 在 WSL 前台运行，使用已绑定 bot 的私聊，复用统一消息处理函数。支持聊天、追问、最新 Gmail 摘要和明确的长期偏好更新。

## 启动

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
hybrid-assistant telegram
```

终端保持运行，Ctrl+C 停止。没有安装接收器后台服务。不要同时启动 Hermes gateway 或另一个接收同一 bot 的程序。`--once` 等待、回复一条授权消息后退出，用于联调；无新消息时仍会等待。

| 输入 | 行为 |
| --- | --- |
| 普通知识问题 | GPT 识别，按正常 / 复杂路由回答 |
| `总结最新一封邮件` | 程序读取 Gmail，由 Gemma 摘要 |
| `这封邮件的截止时间是什么？` | Gemma 使用同一邮件快照回答 |
| `/private 你的问题` | 分类和回答均在 Local |
| `请记住：邮件摘要用中文` | Local 提取，校验并保存 USER.md，回复实际差异 |
| `/new` | 重置近期对话与邮件快照，保留长期偏好 |
| `/start`、`/help` | 显示使用说明 |

新会话的普通消息只把当前文字交给 GPT 分类。私人文字应加 `/private`；引用/回复旧消息强制 Local，但不附加被引用原文。执行可以利用该私聊仍保存的历史。转发、图片、语音和附件返回暂不支持说明。私有会话持续 Local，直到 `/new`。

## 代码分工

`src/adapters/telegram.py` 读取 Local profile 的绑定配置，检查 webhook，通过 Bot API 轮询，并在任何推理前验证发送用户、私聊类型和固定 chat ID。其他用户及群聊不触发模型，也不回复。已有 webhook 只报告冲突，不自动删除。

`src/cli/telegram.py` 负责接收器生命周期、单实例锁、cursor 和运行接线。消息经过统一处理函数，保存会话后调用 `adapters.messaging.send_message()`，由 Hermes 发回同一个绑定私聊。内容与模型不能另选接收人。

项目轮询使用标准库，Hermes 发送依赖留在 Hermes 自己的环境。无需为项目增加 Telegram SDK；首次配置见[连接指南](gmail-telegram.md)。

## 状态、失败与重启

Local profile 为 `~/.hermes/profiles/hw3-local`：

- `conversations/telegram-<chat_id>.json`：近期会话，重启恢复。
- `telegram-inbound/receiver.lock`：WSL 单实例文件锁。
- `telegram-inbound/offset`：下次读取的更新编号，不保存正文。

首次启动跳过积压更新，以后恢复 cursor。每条更新在业务执行前保存下一编号，避免重启自动重放可能已执行的请求；崩溃时可能有消息没有回答，这不是恰好一次交付协议。

模型和邮件的预期失败返回简短说明，已锁定的私有状态仍保存。会话文件读写失败时，接收器回复错误并停止，避免后续输入沿用旧的公开状态；轮询/发送失败同样退出，不自动重复发。长期偏好提交后再保存会话、发送回复，后两步失败不会回滚 USER.md。程序会在相关错误提示中说明业务可能已执行，不能声称已撤销。

日报通过独立 Windows 任务运行，不依赖 Telegram 前台接收器。任务实际启用状态见[调度说明](gmail-telegram.md#每天-0800-日报)。

## 验证

离线集成测试覆盖绑定身份、引用隔离、命令、cursor、重启、单实例锁、会话与记忆回调，运行 `python -m pytest -q`。真实 Telegram 联调时先启动接收器，再由用户从绑定私聊发送 `/help`、`/new` 和测试问题，逐条核对回复。涉及记忆更新的消息会修改正式 USER.md，应使用用户实际希望保存的偏好。

历史联调记录在 `Task.md`，Bot API 语义见 [Telegram getUpdates 文档](https://core.telegram.org/bots/api#getupdates)。