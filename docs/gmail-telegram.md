# Gmail、Telegram 推送与每日简报

Gmail 使用应用专用密码，通过 TLS/IMAP 只读访问 INBOX。摘要由 Local Gemma 生成，可预览或交给 Hermes 发送到已绑定 Telegram 私聊。接收 Telegram 消息另见[入站说明](telegram-inbound.md)。

## 调用链

```text
cli.gmail → adapters.gmail.read_gmail_emails()
  → list[Email]，从新到旧
  → features.email.summarize_email()，或 briefing.build_email_briefing()
  → Local 路由 → Hermes → Gemma
  → 来源头 + 摘要
  → 可选 adapters.messaging.send_message() → Hermes → Telegram
```

默认只预览，`--send` 才发送。接收人来自本地配置，邮件和模型不能指定其他人。发送只接受文本，拒绝 Hermes 的 `MEDIA:` 附件标记；发送超时后不会自动重试。

## Gmail 配置

本机已完成新 Gmail 账号配置，无需重新授权。新机器在 Google 两步验证开启后，从[应用专用密码页面](https://myaccount.google.com/apppasswords)创建应用密码。这里不是 Google 登录密码，也不是 Gmail OAuth。

配置路径为 `~/.hermes/profiles/hw3-local/gmail.json`，格式参考[仓库模板](../config/gmail.example.json)。新文件可用编辑器创建；已有文件直接编辑，不能用空模板覆盖：

```bash
code ~/.hermes/profiles/hw3-local/gmail.json
chmod 600 ~/.hermes/profiles/hw3-local/gmail.json
```

填写 `address` 和 `app_password`，不放到聊天或 Git。应用密码本身不是只读权限令牌；当前实现通过只读 INBOX 和 `BODY.PEEK[]` 保留已读标记。

## Telegram 配置

本机 Token 与数字私聊绑定已完成。新机器在官方 [@BotFather](https://t.me/BotFather) 创建 bot，将 Token 写入 Local profile 的 `.env`，再向 bot 私聊发送 `/start` 和一条连接消息。

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_HOME_CHANNEL=
```

保留文件其他设置，不用模板覆盖整个文件。在该私聊的 `getUpdates` 结果中核对 `message.from.id` 与 `message.chat.id`，将已确认的数字 ID 填到对应字段；这里配置的是单个绑定用户的私聊，二者应相同。`@username` 不替代数字 ID。不要打印或分享带 Token 的 API URL。

```bash
code ~/.hermes/profiles/hw3-local/.env
chmod 600 ~/.hermes/profiles/hw3-local/.env
```

Hermes 最小安装可能缺 Telegram 发送依赖；本机已补装。使用本机已验证 Hermes v0.21.0 的新环境可执行：

```bash
~/.hermes/bin/uv pip install --python ~/.hermes/hermes-agent/venv/bin/python "python-telegram-bot==22.8"
```

这是 Hermes 自己的依赖，不加进项目 `.venv`。其他 Hermes 版本应按其依赖声明安装。

## 选择与运行

在 **WSL**：

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
hybrid-assistant gmail
hybrid-assistant gmail --limit 3
hybrid-assistant gmail --subject "课程通知" --limit 3
```

最新指 INBOX 中最高 UID，而不是发件人填写的 Date。主题过滤先于数量选择；不足数量时取实际匹配数。一次 IMAP 连接读取全部所选邮件。支持普通 MIME 纯文本和 HTML，不分析附件；读取完整 MIME 可能仍传输附件数据。

需要真实推送时：

```bash
hybrid-assistant gmail --limit 3 --send
```

单封模型失败时退出、不发送；批量/日报逐封处理，模型失败保留原始来源头与“摘要暂不可用”，继续后续邮件。网络、登录或 MIME 解码失败中止整次读取。普通单封/批量无邮件时不发送，日报无新邮件则报告空窗口。

## 每天 08:00 日报

日报读取实际执行时刻之前整整 24 小时的 INBOX 邮件，不区分已读/未读，不限数量；归档、Spam 和 Trash 不在范围。使用 Gmail `INTERNALDATE`，先粗筛日期，再精确比较 `start <= received < end`；发件人的 Date 不参与。

时间范围在 UTC 减去 24 小时，再以 America/Los_Angeles 展示。夏令时切换会让相邻日报窗口重叠或留间隔；这是滚动 24 小时报告，不是邮件恰好一次通知账本。

```bash
hybrid-assistant gmail --daily
hybrid-assistant gmail --daily --send
```

安装或更新（**Windows PowerShell**；它会注册/更新真实任务）：

```powershell
cd D:\ai_agent_projects\hw3
.\scripts\install_daily_briefing.ps1
```

安装器面向本机 Ubuntu/fyp，检查 Windows 时区为 `Pacific Standard Time`，不修改系统时区。无固定 UTC offset 的 Windows 触发器按本地 08:00 和夏令时运行。Hermes 自身 cron 在该安装版本的夏令时边界存在偏移，因此 Windows 负责计时，Hermes job 平时 paused，由 runner 临时 resume、run、finally pause。不要长期开启第二套 Hermes 定时器。

```text
Windows "HW3 Daily Email Briefing"
  → scripts/run_daily_briefing.ps1
  → Hermes hw3-local 的 hw3-daily-email job
  → ~/.hermes/profiles/hw3-local/scripts/hw3-daily-email.sh
  → 启动 hw3-ollama
  → hybrid-assistant gmail --daily --send --quiet
```

旧的已安装 shell launcher 仍指向 `examples/gmail_summary.py`。该文件暂留为兼容转发，不包含独立业务；新安装器使用上述包命令。重整代码无需重装现有计划。

安装位置：

| 文件 | 内容 |
| --- | --- |
| Local profile 的 `cron/jobs.json` | Hermes job 定义与状态 |
| `scripts/hw3-daily-email.sh` | profile 下的任务 launcher，权限 700 |
| `.env` | 原有 Telegram 配置与 `HERMES_TIMEZONE=America/Los_Angeles` |
| `gmail.json` | 已有邮箱配置 |

`--quiet` 只向 stdout 输出状态和数量，摘要发 Telegram；模型 session 仍存 Local profile。单封摘要失败可生成降级报告，读取或发送失败则让任务失败。Hermes 可以尝试通知绑定私聊；网络不可用时通知也可能失败。项目不自动重发日报。长报告由 Hermes 按其发送行为拆分。

## 检查、暂停与恢复

**2026-09-17 阶段审查的只读检查**发现：Windows 任务仍安装，08:00 trigger 启用，但任务本身为 `Disabled`、`Settings.Enabled=false`。本轮未改变状态，也未运行日报；这与 Hermes job 平时 paused 是不同的两层开关。

查看当前状态（**Windows PowerShell**）：

```powershell
Get-ScheduledTask -TaskName "HW3 Daily Email Briefing" | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName "HW3 Daily Email Briefing"
```

按需执行以下操作；立即运行会发送真实日报：

```powershell
# 暂停后续自动推送
Disable-ScheduledTask -TaskName "HW3 Daily Email Briefing"
# 恢复自动推送
Enable-ScheduledTask -TaskName "HW3 Daily Email Briefing"
# 立即生成并发送真实日报
Start-ScheduledTask -TaskName "HW3 Daily Email Briefing"
```

运行需要 Windows 用户保持登录（可锁屏）、电脑开启或允许唤醒且联网。无需常驻 VS Code 或 Telegram receiver。错过后可在可运行时补一次，统计实际开始前 24 小时，不补更早漏报。08:00 是开始生成时间；摘要生成完才发送。Windows 忽略同任务并发启动；Hermes 脚本最长 6 小时，Windows 最长 7 小时。

## 验证与参考

运行 `python -m pytest -q` 检查读取、筛选、路由、失败及发送接线；这些测试不发送真实消息。实际投递与用户确认记录保存在 `Task.md`。Local 摘要读取当前 [USER.md 偏好](memory.md)，生成质量仍需核对。

- [Google 应用专用密码](https://support.google.com/accounts/answer/185833?hl=zh-Hans)
- [Gmail 客户端连接](https://support.google.com/mail/answer/7126229?hl=zh-Hans)
- [Hermes 发送脚本输出](https://hermes-agent.nousresearch.com/docs/guides/pipe-script-output)
- [Hermes Telegram](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)
- [Hermes cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)
- [Windows 触发时间](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-itrigger-put_startboundary)
- [IMAP INTERNALDATE](https://www.rfc-editor.org/rfc/rfc9051.html)