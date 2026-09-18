# 近期对话与邮件快照

`src/app/conversation.py` 管理项目自己的近期上下文，CLI 和 Telegram 分别保存会话。不同执行模型可使用同一入口内允许共享的历史；本项目不合并三个 Hermes profile 的原生 session，也不使用 `--resume` 同步它们。

## 状态存放

| 状态 | 位置 | 用途 |
| --- | --- | --- |
| CLI 近期会话 | Local profile 的 `conversations/cli.json` | 连续命令之间恢复对话 |
| Telegram 近期会话 | `conversations/telegram-<chat_id>.json` | 同一私聊重启恢复 |
| 长期偏好 | `memories/USER.md` | Local 业务调用加载 |
| Hermes 原生记录 | 每个 profile 的 `state.db` | 保留独立调用记录 |

Local profile 为 `~/.hermes/profiles/hw3-local`。CLI 内容不会自动进入 Telegram。定时日报也不写入聊天会话。

`Conversation` 保存四个字段：`turns` 是用户/助手消息对；`private` 是持续生效的本地限制；`email` 是最近成功摘要邮件的原文快照；`complexity` 供追问继承上次复杂度。

## 一条消息的生命周期

入口通过 `conversation_session()` 加载会话，`handle_message()` 在识别前应用已有私有标记，并为已知 Local-only 请求锁定私有。分类器只看当前消息，执行模型才接收本轮允许的历史及邮件快照。业务成功后记录本轮，入口原子保存，然后显示或发送回答。

分类结果要求 Local，或实际开始 Local 业务回退时，也立即锁定私有状态。失败或 Ctrl+C 中断不会把会话重新变成公开；session 在异常路径只保存新锁定的私有标记，不追加失败轮次。正常公开远端成功仍保持公开。

邮件追问使用此前保存的同一封邮件，不重新读取“最新邮件”。明确的新摘要请求才读取 Gmail 并替换快照；空收件箱清除旧快照。这样新邮件到达不会悄悄改变追问对象。

没有历史却收到 `follow_up` 时返回缺少上下文的说明。分类器仍可能误分自然语言，历史存在不代表它一定正确判断任务。

## 隐私与重置

公开执行可以在 GPT 与 NIM 之间共享公开历史。处理邮件、私人内容或实际业务使用 Local 后，后续分类和执行保持 Local。Local 可能加载 USER.md，所以远程失败后回退 Local 的回答也不能在下轮直接发送到云端。裁掉旧消息不会解除私有标记。

使用 Telegram `/new` 或 `chat --new` 重置近期会话与邮件快照；长期偏好、Hermes 原生记录和已发消息不会删除。新会话粘贴私人文字仍需 `/private` 或 `--private`；程序管理已知来源与状态，不保证自动识别任意私人文本。

## 保留范围与失败语义

- 最近最多 6 对消息，总计不超过 12,000 字符；单条存储最多 6,000 字符。
- 邮件正文快照最多 16,000 字符，并保留截短提示；发件人与主题各最多 1,000 字符。
- 超限先移除最旧完整消息对；不做模型压缩，已经裁掉的信息可能无法回答。
- 保存采用同目录临时文件与 `os.replace()`，WSL 文件权限为 600。
- 文件损坏时返回错误，不能悄悄当成新的公开会话；用户可显式重置。

Telegram 使用单实例锁串行处理，CLI 也应串行运行。保存先于发送；发送失败时，生成结果可能已经进入会话。长期记忆提交、会话保存和消息发送分别完成，后续失败不撤销前一步。

如果会话保存本身失败，私有标记可能未落盘。CLI 明确提醒修复文件前继续使用 `--private`；Telegram 发出错误提示后停止接收，避免下一条消息用旧公开状态分类。

## 使用示例

```bash
hybrid-assistant chat --new "分别介绍 Python 列表和元组。"
hybrid-assistant chat "第二种和第一种有什么区别？"
hybrid-assistant chat "总结最新一封邮件。"
hybrid-assistant chat "这封邮件要求我做什么？"
hybrid-assistant chat --new "解释二分查找。"
```

Telegram 使用同样的自然语言和单独的 `/new` 命令。明确记忆变更见[长期记忆](memory.md)。历史模型检查位于 `Task.md`，日常检查使用 `python -m pytest -q`。