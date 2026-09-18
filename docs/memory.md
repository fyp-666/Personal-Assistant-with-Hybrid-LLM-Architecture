# 持久化偏好

长期偏好保存在 Hermes 的 `~/.hermes/profiles/hw3-local/memories/USER.md`，下一次 Local 业务调用重新加载。Telegram、聊天命令和独立 memory 命令共用同一更新函数；邮件、批量摘要和日报读取同一份档案。

## 使用

在已激活项目环境、Ollama 可用的 **WSL 终端**执行：

```bash
hybrid-assistant memory "请记住：解释 Python 概念时，优先给一个简短示例。"
hybrid-assistant memory "修改我的 Python 讲解偏好：先解释概念，再给示例。"
hybrid-assistant memory "请忘记 Python 讲解偏好，保留其他偏好。"
```

这些命令会修改正式 USER.md，应按自己的需求执行。输出 `-` 为删除内容、`+` 为新增内容；没有变化时明确说明，不声称保存成功。

同样的明确请求可发送给 Telegram 或 `hybrid-assistant chat "请求"`。直接 `memory` 命令始终使用 Local；聊天的分类只读取当前消息，私有输入请加 `--private` 或 `/private`，实际偏好提取仍固定 Local。

“以后都按这个偏好”需要说清具体偏好；依赖历史但省略内容的“记住刚才那个”不保证能正确理解。“把这次回答改短”只是追问。询问已存偏好走 Local 聊天读取 USER.md。

## 提取、校验、保存

```text
chat / Telegram 识别为 memory_update，或直接 memory 命令
  → features.memory.update_user_memory(request)
  → 读取 USER.md 快照 before
  → 当前 request + before 作为 JSON 数据交给 Local Gemma
  → _apply_edits() 校验整组建议，计算 after
  → _save_user_memory() 加锁、复查 before、原子写入
  → MemoryUpdate(before, after)
  → render_memory_update() 生成真实变更反馈
```

模型只建议结构化数据，不使用写文件工具。整个提案在内存通过验证后才保存，后续操作验证失败不会留下前半部分写入。

| 操作 | 输入字段 | 含义 |
| --- | --- | --- |
| add | content | 追加条目；相同条目不重复追加 |
| replace | old_text、content | 唯一匹配的片段替换，保留该条目其他文字 |
| remove | old_text | 删除唯一包含该片段的整个条目 |

空操作为 `{"operations":[]}`。非法 JSON、未知字段、找不到原文、歧义匹配或超预算都会拒绝写入。项目的片段 replace 与 Hermes 原生 memory 工具的整条替换不同；前期原生工具参数不稳定，因此这里采用模型提取、程序执行，仍使用原有 USER.md 而不另建存储。

`src/features/memory.py` 负责业务，`src/cli/memory.py` 负责参数与错误显示；模型调用复用 `adapters.hermes.call_hermes()`。分类和提取均不自动注入历史，提取仅显式提供当前请求与档案。普通邮件和聊天不会自动变成长期记忆。

## 保存语义

- 条目以独立行的 `§` 分隔，兼容既有 Hermes USER.md。
- 推理后获取 `USER.md.lock`，确认当前文件仍等于快照；有并发修改则拒绝覆盖。
- 同目录临时文件加 `os.replace()` 原子保存，权限 600。
- 使用现有 1375 字符 USER 预算；若调整 Hermes 配置，需要同步这个限制。
- 成功反馈由实际 before/after 计算，不另外调用模型宣称“已记住”。

格式和并发校验不能证明模型完全理解用户意思，应阅读实际 diff。提示词要求只保存长期偏好，不保存凭据、邮件正文或临时待办；这不是对任意输入的完整内容分类器。

聊天中先提交 USER.md，再保存近期会话，最后发送回复。后两步失败不撤销已保存偏好，也不自动重试更新。业务失败时新锁定的私有状态仍需保存，不追加成功对话；若连会话保存都失败，CLI 提示修复前使用 `--private`，Telegram 提示后停止接收。删除长期偏好不删除历史对话、Hermes 日志或已经发送的消息；`/new` 和 `chat --new` 仅重置近期上下文。

## 查看与后续使用

```bash
code ~/.hermes/profiles/hw3-local/memories/USER.md
hybrid-assistant gmail
```

后一个命令读取真实最新邮件并预览摘要，不发送；`--send` 才发送 Telegram。`--daily` 及独立日报任务也读取最新偏好，无需重装调度。每次 Hermes 进程启动读取一份快照，建议在批量任务空闲时编辑。

仓库的 `config/hermes/user.example.md` 只是格式样例，不能覆盖已有正式档案。正式偏好已被用户实际请求更新，以当前文件和成功反馈为准。Local 开启 `memory.user_profile_enabled`，`memory.memory_enabled` 仍关闭；OpenAI/NIM 不加载这份私人档案。

## 验证

离线测试覆盖增改删、局部替换、保留无关条目、非法和歧义提案、并发冲突、原子写入、无变化回复及聊天接线。运行 `python -m pytest -q`。历史隔离模型验证和用户 Telegram 记忆联调记录在 `Task.md`；本轮审查不再次修改正式偏好来测试。

参考 [Hermes 持久化记忆说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/) 和本机已安装版本的 USER.md 格式。