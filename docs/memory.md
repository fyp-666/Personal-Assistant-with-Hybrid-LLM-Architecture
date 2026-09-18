# 聊天中的持久化偏好

使用 Hermes 的 `USER.md` 保存偏好，下一次独立模型调用重新读取。现在可以通过 Telegram、统一 CLI 或独立 `remember.py` 命令用自然语言新增、修改和忘记偏好，也可以直接编辑文件。单封邮件、批量摘要和每日简报共享这份档案。

## 在 Telegram 或统一 CLI 使用

启动 `python examples/telegram_bot.py` 后，可在已绑定私聊发送明确的长期偏好请求。例如：

```text
请记住：解释 Python 概念时，优先给一个简短示例。
修改我的 Python 讲解偏好：先解释概念，再给示例。
请忘记 Python 讲解偏好，保留其他偏好。
```

这些消息会实际修改正式 USER.md，按自己的需要选择发送。统一 CLI 同样支持：

```bash
python examples/assistant.py "请记住：解释 Python 概念时，优先给一个简短示例。"
```

如果新会话输入本身包含私人内容，用 `/private 你的请求` 或 `--private`；普通允许分享的当前消息可由 GPT 识别，已经私有的会话由 Gemma 识别。识别器始终不读取 USER.md。无论谁识别，后续记忆提取和文件修改都固定留在本地。

“以后都按这个偏好”与“把这次回答改短一点”不同：前者需要明确说明长期偏好，后者只修改当前回答。当前记忆提取只收到本条请求和已有档案，省略了具体偏好且依赖旧聊天的“把刚才那个记住”不保证能被正确理解；请直接说出希望记住的内容。

询问“我的邮件摘要偏好是什么”走私有聊天回答，读取已保存的 USER.md。`/new` 清空近期上下文后仍能使用长期偏好；删除长期偏好不会删除旧聊天、Hermes 原生记录或已经发送的消息。

## 独立命令


在 **WSL 项目终端**执行：

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
systemctl --user start hw3-ollama
python examples/remember.py "修改我的邮件摘要偏好：先列截止时间，再列行动，保留中文。"
```

命令会直接更新正式档案，并显示实际差异：`-` 是删除内容，`+` 是新增内容。没有变化时明确显示“长期记忆没有变化”，不会声称已经保存。新增和删除示例，按需要选择执行：

```bash
python examples/remember.py "请记住：我喜欢简短的邮件摘要。"
python examples/remember.py "请忘记整个邮件摘要偏好条目，保留其他偏好。"
```

观察后续摘要是否采用新偏好：

```bash
python examples/email_summary.py
```

这个摘要示例使用合成邮件，不发送消息。真实收件箱可用 `python examples/gmail_summary.py`，加 `--daily` 生成过去 24 小时简报；只有加 `--send` 才向 Telegram 推送。每天 08:00 的任务会读取最新档案，无须重新安装。

## 提取、校验、保存的调用链

```text
Telegram / examples/assistant.py
  → identify_task(仅当前消息) → memory_update
  → handle_message(..., update_memory=update_user_memory)
  → update_memory(message)

或 remember.py 接收用户的 request
  → update_user_memory(request)
      → 读取 USER.md，得到 before
      → 将 request 和 before 放入 JSON，交给本地 Gemma
      → call_hermes(prompt, profile=hw3-local)，得到修改建议 reply
      → _apply_edits(before, reply)：解析、校验，算出 after
      → _save_user_memory(path, before, after)：核对并保存
      → 返回 MemoryUpdate(before, after)
  → render_memory_update() 展示实际文件差异
  → 聊天入口记录为私有会话，再显示或发送回复

后续独立的邮件摘要调用
  → Hermes 加载 USER.md 到系统提示词
  → 本地 Gemma 按最新偏好生成摘要
```

`examples/remember.py` 负责命令行输入和错误提示；它与聊天入口共用 `render_memory_update()`，从 `MemoryUpdate.before/after` 计算实际差异，只显示变更行，不重复展示未改变的其他偏好。回复格式由程序生成，不增加一次模型润色调用。`src/hybrid_assistant/memory.py` 负责提取请求、校验修改和写入。模型调用复用原有 `call_hermes()`，摘要读取复用原有 `runtime.create_providers()` 和 `summarize_email()`。

模型只生成数据，不在这一步调用写文件工具。比如用户说“邮件摘要改用英文”，模型可以返回：

```json
{
  "operations": [
    {"action": "replace", "old_text": "使用中文", "content": "使用英文"}
  ]
}
```

程序只替换唯一匹配的这段文字；同一条里的截止时间要求以及其他条目保持原样。三种操作的含义：

| action | 模型提供的字段 | 程序执行 |
| --- | --- | --- |
| add | content | 追加一个偏好条目，完全相同的条目不重复追加 |
| replace | old_text、content | 在唯一匹配的条目中，只替换该原文片段 |
| remove | old_text | 删除唯一包含该原文片段的整个条目 |

没有需要保存的信息时返回 `{"operations":[]}`。模型若返回普通文字、未知字段、找不到的旧片段或有歧义的匹配，程序拒绝写入。多个操作先全部在内存里验证，通过后才一次保存，因此后面的操作失败不会留下前面的半成品。

这里的 `replace` 是项目定义的局部替换，不是 Hermes 原生 memory 工具的整条替换。前期真实验证发现当前 Gemma 调用原生工具时会漏参数、抄错旧文本或重复操作，所以最终采用“模型提取修改建议，程序执行”的小接口。没有修改 Hermes 源码，也没有另建数据库。

## 文件如何保存

实际路径：`~/.hermes/profiles/hw3-local/memories/USER.md`。

- 使用 Hermes 已有的条目格式，以独立一行的 `§` 分隔条目，摘要照常读取。
- 模型调用结束后获取 `USER.md.lock`，再次检查文件是否仍等于 `before`；若其他进程已经修改，拒绝覆盖，请重新发起请求。
- 写入同目录的临时文件，再用 `os.replace()` 替换目标文件，避免读到写了一半的档案。新文件权限为 600。
- 当前入口采用 Hermes 默认的 1375 字符 USER 档案预算，超出则拒绝写入；以后若调整 Hermes 的容量配置，需要同步调整这个常量。

`before` 是提取前的快照，`reply` 是模型返回的 JSON 字符串，`after` 是校验通过后要保存的内容。`MemoryUpdate.changed` 比较 `before != after`，不是相信模型一句“记住了”。局部替换和字段校验不能证明模型完全理解了用户意图，仍应阅读命令展示的 diff。

这一步只有明确的用户记忆请求才进入。邮件摘要和每日简报不会自动把正文传入记忆更新函数。模型提取使用固定默认 Local profile，关闭上下文自动注入，将当前档案作为明确的数据输入；后续摘要仍通过 Local 的 `load_context=True` 加载保存的档案。`profile` 参数供可信调用方使用隔离本地测试档案，命令行不提供模型选择。

所有模型工具仍然关闭，OpenAI/NIM 不加载这份私人档案。没有新增运行依赖。提示词要求只提取长期偏好，不保存凭据、邮件正文或临时待办；这属于模型行为要求，不是对任意输入的完整内容分类器。

## 手动查看和维护

在 WSL 终端打开：

```bash
code ~/.hermes/profiles/hw3-local/memories/USER.md
```

编辑并保存后，下一次 Local 调用会重新加载。移除相应条目可以忘记该偏好；保留其他条目和分隔符即可。删除偏好不删除过去的会话记录或已发送的消息。

下面是仓库提供的示例偏好；正式档案可能已通过用户的聊天请求更新，以本地 USER.md 和变更反馈为准：

> 用户的邮件摘要偏好：使用中文，先说明需要采取的行动，再说明截止时间；偏好“行动：…”和“截止：…”两行格式。原文未给出行动或截止时间时，对应项写“未提及”。

仓库中的 `config/hermes/user.example.md` 只是示例，不要用它覆盖已有档案。正式 profile 已开启 `memory.user_profile_enabled`，`memory.memory_enabled` 仍为 false；普通模型工具集、压缩及后台 review 仍关闭。其他机器可使用配置模板开启 USER 档案读取。

Hermes 每个新进程读取一份快照。运行中的调用继续使用启动时的内容；批量摘要逐封启动，因此建议在任务空闲时修改偏好。

Telegram 接收器先验证绑定私聊身份，随后由统一处理函数调用记忆更新回调。只在更新成功后生成成功反馈；模型或文件失败不会追加成功对话。USER.md 提交、近期会话保存、Telegram 发送是三个连续操作，后两步失败不撤销已保存的偏好，也不自动重试更新。

## 验证

聊天入口接线检查点（2026-09-17）：452 项测试和 Ruff 检查通过。新增测试验证明确记忆请求的增改删、无变化反馈、固定 Local 执行、仅当前请求与档案进入提取、失败不追加成功历史，以及 CLI 和 Telegram 接线。

隔离的真实 Local profile 通过 5 个场景：聊天新增英文摘要偏好；清空近期会话后仍能回答已有偏好；合成邮件摘要采用英文；重启恢复会话后改为中文；最后只删除邮件偏好，保留无关界面偏好。共 10 次真实推理、每次零工具调用，耗时约 32 秒。证据在忽略目录 `chat-memory-smoke.json`；这一组验证未修改正式 USER.md、配置或凭据，也未读取真实 Gmail 或发送 Telegram。

用户随后通过已绑定 Telegram 私聊发送了一条真实偏好请求。实际链路为 GPT 识别 `memory_update` → Local Gemma 提取 → 正式 USER.md 更新 → Hermes 发送回复，`--once` 进程退出码为 0。核对确认保存的当前请求与提取输入一致、回复与实际文件差异一致、会话标为私有；Local 推理为一次 API 调用、零工具调用。状态证据 `telegram-memory-smoke.json` 不保存偏好正文。正式 USER.md 的这次变更来自用户亲自发送的请求，未回退。接收器已退出，持续使用需启动普通模式。

原独立记忆命令检查点（2026-09-17）：

- 321 项离线测试及 Ruff 检查通过，包含结构化提取、局部替换、无变化、非法或歧义操作、多个操作失败不落盘、并发变更和原子写入失败。
- 隔离的 Local profile 使用与正式档案相同的邮件偏好，另加一条界面偏好。真实自然语言请求将摘要语言改为英文，保留同条“未提及”要求和无关的界面偏好；下一次摘要实际输出英文。
- 真实删除请求只删除邮件条目；随后新增中文、截止时间在前的偏好，新一次摘要输出中文且截止时间在前。
- 五次独立 Hermes 调用共约 24.84 秒，均为 `gemma4:e4b-it-qat`、本地 Ollama、1 次模型调用、0 次工具调用。临时 profile 已清理，正式档案和已核对的配置/凭据文件未变，没有发送 Telegram 消息。
- 成功记录在忽略目录 `.hermes-runtime/memory-write-validated.json`。早期原生工具试验中的失败不是最终实现的验证结果。

此前 2026-09-09 的手动保存、更新、清除及正式 profile 读取检查保留在 `memory-smoke.json` 和 `memory-active-smoke.json`。上述检查验证存储和调用链，不代表所有自然语言请求都能被正确提取或所有邮件摘要都有完整事实校验。

存储与读取参考：[Hermes 官方持久化记忆说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)，以及本机 Hermes v0.21.0 的 USER.md 格式与锁路径。
