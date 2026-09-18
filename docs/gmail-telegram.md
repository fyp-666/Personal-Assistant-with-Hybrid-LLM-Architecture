# Gmail → 本地 Gemma → Telegram

日历暂缓。这一步把真实邮件接进已经实现的摘要函数，并复用 Hermes 官方消息发送命令。

## 调用链

```text
Gmail IMAP（TLS、只读 INBOX、--limit N、可按主题筛选）
  → read_gmail_emails() → list[Email]（从新到旧）
  → build_email_briefing()（批量模式）
      → 每封 summarize_email() → Local 路由 → Hermes → Gemma
      → render_email_summary() → 合并为一份邮件简报
  → send_message() → hermes send → Telegram 私聊
```

默认只在终端预览，加 `--send` 才发送。消息接收位置来自本地配置，邮件正文或模型不能选择接收人。
发送接口只接受文本，拒绝会被 Hermes 解释为附件的 `MEDIA:` 标记。项目入口不会在超时后自动重新运行发送命令。

## 当前已验证与待验证

- WSL 到 `imap.gmail.com:993` 和 `api.telegram.org:443` 的 TLS 连接正常。
- 邮件 MIME 解码、HTML 转文本、只读读取、模型路由、发送失败和工作流测试已通过。
- 新 Gmail 的真实登录、最新邮件读取和本地 Gemma 摘要已通过（2026-09-08）：总计约 14.4 秒，其中一次 hw3-local 调用约 10.8 秒。项目检查报告只记录状态和耗时，不保存邮件内容。
- 当前 452 项离线测试通过；单次真实摘要说明调用链可用，不等于全面验证摘要事实准确性。
- Telegram 机器人身份和 HW3-CONNECT 私聊已验证，允许用户及默认接收位置已绑定。真实 Gmail → 本地 Gemma → Telegram 发送成功，总计约 10 秒；Hermes 返回成功，用户已确认收到并自行测试通过。
- 最近 3 封真实邮件的批量预览已通过：共 3 次 hw3-local 调用，总计约 17.5 秒。本次批量检查只预览，未再次推送。
- 每日模式已实测：过去 24 小时读到 6 封邮件，6 次本地模型调用的预览共约 33 秒。随后通过真实 Windows 计划任务执行，约 45 秒完成 6 封邮件的日报发送，Windows 返回 0，Hermes 记录成功；任务下一次触发为 2026-09-10 美西时间 08:00。
- Telegram 推送使用 `hermes send`，不需要启动长期运行的 gateway。新增的 [Telegram 入站入口](telegram-inbound.md) 已能接收文字请求并复用统一处理函数。

## 1. 准备 Gmail

你已选择换另一个 Gmail 账号。本轮使用新账号的应用专用密码连接 IMAP。先开启 Google 两步验证，再在
[应用专用密码页面](https://myaccount.google.com/apppasswords) 创建一个名为 `HW3` 的密码。
这里需要的是应用专用密码，不是 Google 登录密码。

个人 Gmail 的 IMAP 已默认开启，不必再找启用开关。
应用密码本身不是只读权限令牌；当前读取器用只读 INBOX 和 `BODY.PEEK[]`，不修改已读标记。

在 VS Code 的 WSL 终端打开已准备的文件：

```bash
code ~/.hermes/profiles/hw3-local/gmail.json
```

填写新 Gmail 账号的 `address` 和该账号创建的 `app_password`。文件保存在 WSL home，权限为 600，不在仓库里。
密码不要发到聊天中。

## 2. 准备 Telegram

Hermes 的最小安装可能没有 Telegram 依赖。本机已补装完成；其他机器使用同版本 Hermes 时，可在 WSL 执行：

```bash
~/.hermes/bin/uv pip install --python ~/.hermes/hermes-agent/venv/bin/python "python-telegram-bot==22.8"
```

该版本与当前 Hermes 的官方依赖声明一致，安装在 Hermes 自己的环境中；项目 .venv 不需要添加这个库。

1. 在 Telegram 找到官方 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示创建机器人。
2. 保存 BotFather 给出的 Token 到下方 `.env` 中的 `TELEGRAM_BOT_TOKEN=` 后面。
3. 打开你刚创建的机器人私聊，点击 Start，再发送 `HW3-CONNECT`。

```bash
code ~/.hermes/profiles/hw3-local/.env
```

文件中已经补好以下空字段，保留其他已有设置：

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_HOME_CHANNEL=
```

先填写 Token 即可。后续连接检查从你发送的 `HW3-CONNECT` 更新中确认私聊 ID，
再把该 ID 写入 `TELEGRAM_ALLOWED_USERS` 和 `TELEGRAM_HOME_CHANNEL`。
如果自己已经知道 Telegram 数字用户 ID，可以填写这两项；私聊中二者使用同一 ID。
用户名（`@name`）不能代替数字 ID。不要把整个 `.env` 替换成仓库的空模板。

## 3. 选择邮件

默认直接读取收件箱最新的一封，无须准备测试邮件。这里的最新指 INBOX 中 UID 最大的一封，即较后加入收件箱的邮件，不按发件人填写的日期排序。

加 `--limit 3` 可读取最近 3 封。与 `--subject` 一起使用时，先筛选主题，再取匹配邮件中最新的 3 封；不足 3 封时读取实际数量。只登录一次 Gmail，按从新到旧的顺序读取和显示。

如果想用内容已知的邮件测试，可以在 Gmail 中给自己发一封纯文本邮件：

- 主题：`HW3-EMAIL-TEST`
- 正文：`请在 2026-09-10 16:00（UTC-07:00）前提交 1 份 PDF 和 2 张截图。提交前检查附件能否打开。`

运行时加 `--subject "HW3-EMAIL-TEST"`，会只搜索 INBOX 中主题包含该文字的邮件，并读取 UID 最大的一封。
它支持常见纯文本和 HTML 正文，但本轮不分析附件。读取完整 MIME 时仍可能传输附件数据。

## 4. 运行

以下命令在 WSL 项目终端执行：

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/gmail_summary.py
```

应看到原始发件人、主题和 Gemma 生成的中文摘要。
确认 Telegram 私聊配置后，执行下列命令会重新读取、生成摘要并发送一次：

```bash
python examples/gmail_summary.py --send
```

批量用法：

```bash
# 预览最近 3 封邮件的摘要
python examples/gmail_summary.py --limit 3

# 合并推送到 Telegram
python examples/gmail_summary.py --limit 3 --send

# 只选择主题包含指定文字的最近 3 封
python examples/gmail_summary.py --subject "课程通知" --limit 3 --send
```

不加 `--limit` 或 `--daily` 仍只处理一封。批量模式会逐封调用本地模型，保留各自的发件人和主题；某封模型调用失败时显示“邮件摘要暂不可用”，随后继续其他邮件。即使所有模型调用都失败，批量简报仍会保留各封邮件的失败提示。原单封模式保持模型失败即退出、不发送的行为。

这里复用 `briefing.py` 中的 `build_email_briefing()`；每日简报也调用它。原 `read_gmail_email()` 作为只读一封的兼容入口继续保留。

普通单封/批量模式在空收件箱或无匹配邮件时不发送；`--daily` 会发送“过去 24 小时暂无新邮件”。网络、邮件读取或 MIME 解码失败仍会中止整次读取；本轮隔离的是模型摘要失败。合并后的文本一次交给项目发送接口。
邮件内容只交给本地模型推理；发送的摘要会交给 Telegram，这是本步骤明确选择的消息出口。

## 5. 每天早上 08:00 自动推送

日报范围沿用 **INBOX 收件箱**：读取运行时往前 24 小时收到的全部邮件，不区分已读/未读，不设数量上限。不包括已归档、垃圾邮件和垃圾箱；不分析附件。

使用 Gmail 的 `INTERNALDATE` 收件时间，先按日期粗筛，再比较精确时间：`开始 <= 收件时间 < 结束`。发件人填写的 `Date` 不参与筛选。先在 UTC 上减去 24 小时，再按 `America/Los_Angeles` 展示范围；因此夏令时切换那一天，范围起点可能显示前一天 07:00 或 09:00，实际长度仍是 24 小时。

每封调用一次本地 Gemma，保留发件人、主题及摘要，按从新到旧的顺序合并推送。某封模型失败保留“邮件摘要暂不可用”，继续其他邮件；没有新邮件时发一条明确的空日报，不调用模型。读取、登录、解码或发送失败会让整个任务失败，Hermes 会尝试向同一个 Telegram 私聊发送失败通知；网络仍不可用时通知也可能失败。不会自动重发日报。

调用链：

```text
Windows 计划任务（美西每天 08:00）
  → run_daily_briefing.ps1 → 启动 Ubuntu / Hermes job
  → hw3-daily-email.sh → 启动 hw3-ollama
  → gmail_summary.py --daily --send --quiet
  → read_gmail_emails(过去 24 小时, limit=None)
  → build_email_briefing → 每封 Local Gemma 摘要
  → send_message → Hermes → Telegram
```

Hermes 的 `--no-agent` 表示定时器直接执行脚本；邮件摘要仍在脚本内部调用真实本地模型。`--quiet` 让本次任务输出只记录发送状态和邮件数量，邮件摘要发到 Telegram；Hermes 的模型会话仍按原配置保存在本地 profile 中。长日报可能由 Hermes 拆成多条 Telegram 消息。

手动预览或立即发送（**WSL，已激活项目环境**）：

```bash
systemctl --user start hw3-ollama
python examples/gmail_summary.py --daily
python examples/gmail_summary.py --daily --send
```

安装/更新计划任务（**Windows PowerShell**，这台电脑上已经安装）：

```powershell
cd D:\ai_agent_projects\hw3
.\scripts\install_daily_briefing.ps1
```

安装器面向当前 Ubuntu/fyp 环境，重复执行会更新同一个任务。它检查 Windows 时区为 `Pacific Standard Time`（含夏令时），不会修改系统时区。Windows 触发器未固定 UTC 偏移；请保留美西系统时区，以保证全年本地 08:00。任务配置在 Windows 计划任务中，Hermes 文件统一在 WSL home：

- `~/.hermes/profiles/hw3-local/cron/jobs.json`：任务定义和运行状态。
- `~/.hermes/profiles/hw3-local/scripts/hw3-daily-email.sh`：调用项目入口的小脚本，权限 700。
- `~/.hermes/profiles/hw3-local/.env`：已有 Telegram 配置，以及 `HERMES_TIMEZONE=America/Los_Angeles`；权限 600。
- `gmail.json` 和三种模型配置继续使用原来的 home 位置。

当前 Hermes 的 cron 时间库在夏令时切换日存在偏移，因此 **Windows 负责何时启动，Hermes 负责执行**。Hermes job 平时显示 `paused` 是预期状态：运行脚本先 `resume`，再 `run`，最后 `pause`，避免 Hermes 自己再次定时触发。不要通过 `hermes cron resume` 长期开启第二套计时。Hermes 安装命令提示 gateway 未运行可以忽略；Windows 会直接调用它的 CLI。

检查、立即运行一次或暂停（**Windows PowerShell**）：

```powershell
Get-ScheduledTaskInfo -TaskName "HW3 Daily Email Briefing"
# 这条会立即发送一份真实日报
Start-ScheduledTask -TaskName "HW3 Daily Email Briefing"
# 暂停今后的自动推送
Disable-ScheduledTask -TaskName "HW3 Daily Email Briefing"
# 恢复自动推送
Enable-ScheduledTask -TaskName "HW3 Daily Email Briefing"
```

无需打开 VS Code、PowerShell 或 WSL 终端。电脑需要保持 Windows 用户已登录（可锁屏），并且开机联网；已开启唤醒请求，休眠/睡眠能否按时唤醒取决于设备电源设置。关机或注销时无法执行。错过后会在可运行时补执行一次，统计实际运行前 24 小时，不补齐更早的漏报。08:00 是开始生成的时间，Telegram 在生成完成后收到。Windows 忽略同一任务的并发启动，单次 Hermes 脚本最长 6 小时，Windows 最长 7 小时。

## 依据

- [Google：应用专用密码](https://support.google.com/accounts/answer/185833?hl=zh-Hans)
- [Google：Gmail 与其他客户端连接](https://support.google.com/mail/answer/7126229?hl=zh-Hans)
- [Hermes：发送脚本输出到消息平台](https://hermes-agent.nousresearch.com/docs/guides/pipe-script-output)
- [Hermes：Telegram 配置](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)

- [Hermes：定时脚本任务](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)
- [Microsoft：触发时间与时区](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-itrigger-put_startboundary)
- [IMAP：INTERNALDATE 与日期搜索](https://www.rfc-editor.org/rfc/rfc9051.html)

## 持久化摘要偏好

邮件摘要现在会加载本地 profile 中保存的用户偏好，包含自动日报。查看、修改和删除方法见[记忆说明](memory.md)。
