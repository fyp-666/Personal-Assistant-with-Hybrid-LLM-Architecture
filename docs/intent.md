# 任务识别与执行路由

这一小步让 GPT 判断用户要做什么，再复用现有路由决定执行模型。`examples/identify_task.py` 仍只展示结果；新增的 [统一入口](assistant.md) 已把普通对话与最新邮件摘要接到实际业务函数。

## 在 WSL 中运行

```bash
cd /mnt/d/ai_agent_projects/hw3
source .venv/bin/activate
python examples/identify_task.py "总结最新收到的一封邮件。"
python examples/identify_task.py "比较两种分布式任务队列方案，分析一致性、故障恢复和成本，给出迁移计划。"
```

第一条由 GPT 识别为 `latest_email_summary`，执行计划选择 `local`；第二条预期为 `chat` / `complex`，选择 `nim`。这里只产生计划，不会读取邮件或真的让 NIM 回答问题。

当前描述默认允许发给 GPT。输入本身包含私人内容时，使用 `--private`：

```bash
systemctl --user start hw3-ollama
python examples/identify_task.py --private "请处理这段私人内容……"
python examples/identify_task.py --offline "解释一下什么是二分查找。"
```

`--offline` 是应用的本地路由开关，不会关闭电脑网络。两种本地模式都需要 Ollama 可用。这些开关表达数据和网络限制，不是模型偏好选项。

## 对照代码看调用链

```text
examples/identify_task.py：当前消息 + 调用方提供的 RequestContext
  → runtime.create_providers(load_local_context=False)：构造模型调用函数
  → intent.identify_task(message, providers, context=context)
      → plan_route(识别用 context)：允许公开的消息走 GPT，受限输入走 Local
      → execute_plan() → call_hermes() → 对应 Hermes profile → 模型
      → _parse_intent()：验证三个字段
      → 构造 IdentifiedTask，保留并收紧执行上下文限制
  → plan_route(result.context)：生成业务执行计划
  → 打印结果，结束
```

`create_providers()` 只准备可调用函数，不会一次启动三个模型。识别时将 `load_local_context` 设为 `False`，因此即便由 Gemma 识别，也不会自动读取 USER.md 或 profile 上下文。已有业务调用仍使用默认值 `True`，Local 摘要继续读取之前保存的偏好。

`identify_task()` 把当前消息放进 `{"message": "…"}`，与固定识别说明一起交给模型。它不加载邮件、日历、记忆或聊天历史。识别阶段把复杂度临时设为 `NORMAL`：复杂问题也先让 GPT 分类，NIM 不参与识别。

模型只需返回三个字段，例如：

```json
{"task": "latest_email_summary", "complexity": "normal", "needs_private_context": true}
```

| 字段 | 含义 |
| --- | --- |
| `task` | `chat`、`follow_up`、`latest_email_summary`、`email_summary`、`email_briefing`、`calendar`、`memory_update` 或 `unknown` |
| `complexity` | `normal` 或 `complex`，供现有路由判断是否需要 NIM |
| `needs_private_context` | 是否需要邮件、日历、私人记忆或相关历史；例如“结合我的偏好给建议”为 true |

`_parse_intent()` 检查 JSON、允许的字段和值，不接受模型额外指定一个 provider。程序随后用 `dataclasses.replace()` 生成执行用的 `RequestContext`，保留原来的限制，并根据任务增加邮件/日历来源或敏感标记。`IdentifiedTask` 还记录实际识别模型和是否发生回退，供入口展示。

因此 GPT 负责理解任务，`plan_route()` 仍按已有策略选择执行模型：普通公共问题走 OpenAI，复杂公共问题走 NIM，私人数据相关任务走 Gemma。模型无法用一个 `chat` 或 `false` 清除调用方已经设置的私有来源、离线或禁止云端限制。

## 隐私与失败处理

用户已选择：GPT 只看当前聊天消息，不附加真实邮件、日历、私人记忆或含这些数据的历史。已知私有、来源/隐私未确认、离线或禁止云端的输入，连识别也走 Local。

这一入口不会自动保证随意粘贴的私人文字都被识别并拦截。CLI 用 `--private` 表明输入本身私有；Telegram 入口与 CLI 会根据已有会话状态，在分类前收紧私有会话的上下文；新会话中粘贴私人文字仍需显式使用私有模式。`needs_private_context` 只用于收紧执行路由，它返回 false 并不授权把私人资料传给远程模型。之后获取业务数据、组装执行 prompt 时，仍必须根据实际数据重新确认路由。

GPT 调用出现 `ProviderError` 时，既有执行器尝试 Gemma，并让本次请求后续继续走 Local。私有请求的 Local 失败则直接报错。模型返回非法 JSON 时停止，不执行任务，也不另加重试。`unknown` 表示需要后续澄清；本阶段只显示它，不猜测执行操作。

## 本次验证与下一步

最初的识别入口通过 351 项离线测试和 Ruff 检查，覆盖任务识别、私有约束、回退、JSON 校验和 CLI。该检查点的 11 个真实识别场景通过：8 次 GPT、2 次直接 Gemma、1 次模拟 GPT 不可用后由真实 Gemma 识别。元数据确认每次推理只有一次模型 API 调用、没有工具调用。失败注入不代表制造了实际服务故障，离线路由验证也不是物理断网实验。

测试包含邮件、简报、日历、记忆更新、私人偏好依赖和缺少上下文的追问。它们验证的是样例识别与路由计划，不代表所有自然语言都能正确分类；本次没有执行 NIM 业务回答、读取邮箱或发送 Telegram。既有配置、凭据和 USER.md 均未改变。

统一处理函数现已接入普通对话、最新邮件摘要以及 `follow_up`。Telegram 和 CLI 均使用项目自己的[共享上下文实现](conversation.md)，当前共有 452 项测试。针对已有内容的细节问答优先属于 `follow_up`；`email_summary` 用于新摘要请求，不能把邮件正文中的编号误当成选信条件。分类器只看当前消息，执行模型才读取允许的历史；没有历史的追问返回说明。

复杂讨论的追问由处理函数继承上一轮复杂度。私有会话在分类前就限定为 Local，`/new` 或 `--new` 可开始新的会话。每次通用请求仍多一次识别调用，这是用模型判断任务的时间和用量成本。明确的长期记忆变更现已接入 `memory_update` 分支，优先于一般追问；只要求改写当前回答仍归 `follow_up`。询问已有偏好是需要私人上下文的 `chat`，由 Local 读取档案回答。
