# 环境与模型配置

本文保留原 README 中的安装步骤。项目运行于 WSL Ubuntu，目标解释器为 Python 3.11。当前机器已完成配置，日常使用无需重建 profile、重复登录或覆盖凭据。这里记录的是本项目已验证的版本与路径，不是软件最新版本清单。

## 1. 项目 Python 环境

本机位置：

| 内容 | 路径 |
| --- | --- |
| Windows 项目 | `D:\ai_agent_projects\hw3` |
| WSL 项目 | `/mnt/d/ai_agent_projects/hw3` |
| Hermes 安装 | `~/.hermes/hermes-agent` |
| Hermes 环境 | `~/.hermes/hermes-agent/venv` |
| 项目环境 | `/mnt/d/ai_agent_projects/hw3/.venv` |

从 **Windows PowerShell** 进入 Ubuntu：

```powershell
wsl -d Ubuntu
```

新 checkout 在 **WSL** 创建环境。以下命令依赖本机已有 Hermes 提供的 uv 和受管理的 Python 3.11.16；`--offline` 不下载解释器：

```bash
cd /mnt/d/ai_agent_projects/hw3
~/.hermes/bin/uv venv --python 3.11.16 --offline .venv
source .venv/bin/activate
python --version
command -v python
~/.hermes/bin/uv sync --locked
```

应得到 Python 3.11.16 和项目 `.venv/bin/python`。WSL 系统 Python 与项目/Hermes 环境不同，不要使用未限定的系统解释器替代。另一台机器需要先准备兼容的 Python 3.11 和 uv；上述 offline 命令本身不安装它们。

`uv sync --locked` 以 editable 模式安装项目的五个包、`hybrid-assistant` 命令和锁定的开发依赖。五个包直接位于 `src/`，没有 `hybrid_assistant/` 外层。修改源码会直接生效；从旧目录结构更新后，先重新运行一次 `uv sync --locked`，刷新安装和入口。常规安装保持 `--locked`；有意修改依赖后才运行 `uv sync` 更新锁文件。项目没有第三方运行依赖，pytest/Ruff 只用于开发。

日常使用 `hybrid-assistant <子命令>`。在仓库根目录也可执行 `python src/main.py <子命令>`，两者共用相同的 CLI 实现。

VS Code 连接 WSL 后，在 WSL 安装 Python 扩展并使用 **Python: Select Interpreter** 选择项目 `.venv/bin/python`。激活只影响当前 shell；`deactivate` 退出环境，不删除它。

## 2. Hermes profiles 与认证

Hermes 独立安装在 WSL home，本项目通过公开 CLI 使用它，不复制 Hermes 源码。已验证 Hermes v0.21.0，CLI 为 `~/.local/bin/hermes`。新机器需先完成 Hermes 安装和根 profile 的 OpenAI OAuth 登录；本机使用已有 ChatGPT/Codex OAuth，无须另填 OpenAI API key。

| 项目路由 | 活跃配置 | 模型与认证 |
| --- | --- | --- |
| OpenAI | `~/.hermes/profiles/hw3-openai/config.yaml` | `gpt-5.6-sol`，Hermes 管理 OAuth |
| NIM | `~/.hermes/profiles/hw3-nim/config.yaml` | `nvidia/nemotron-3-super-120b-a12b`，profile `.env` |
| Local | `~/.hermes/profiles/hw3-local/config.yaml` | Ollama `gemma4:e4b-it-qat` |

在本机 `~` 为 `/home/fyp`。`config/hermes/*.yaml` 是安装模板，运行时读上表中的文件。新机器从项目目录运行下面的命令；已有 profile 不覆盖：

```bash
for provider_name in openai nim local; do
    profile_dir="$HOME/.hermes/profiles/hw3-$provider_name"
    if [ ! -d "$profile_dir" ]; then
        HERMES_HOME="$HOME/.hermes" ~/.local/bin/hermes --profile default profile create "hw3-$provider_name" --no-alias --no-skills &&
            install -m 600 "config/hermes/$provider_name.yaml" "$profile_dir/config.yaml"
    fi
done
```

模板关闭模型工具、自动 coding 模式、Hermes 自带回退、压缩、标题和后台 review。Local 开启 USER 档案读取，其他模型不读取私人档案。

项目的 `app.runtime.create_providers()` 惰性构造调用函数，所选 profile 实际使用时才检查配置。适配器固定 `HERMES_HOME`、profile 和工作目录，提示词通过 stdin 传递。默认 `--ignore-rules` 防止附带 profile 上下文；只有 Local 业务调用开启上下文。识别调用全部关闭上下文加载。

使用 `HERMES_SAFE_MODE=1` 关闭扩展但保留 profile；本机 Hermes 的 CLI `--safe-mode` 会丢弃 profile 配置，故项目不使用该参数。父 shell 中的 provider overrides 和密钥不传给子进程；`~/.hermes/bin` 仍在 PATH 中供已安装 scanner 使用。

## 3. Local Gemma / Ollama

本机使用 Ollama 0.33.3，安装在 `~/.local/opt/ollama-0.33.3`，命令链接为 `~/.local/bin/ollama`。模型数据位于 `~/.ollama/models`。采用官方 Linux 用户目录安装，不在项目 venv 安装 Ollama。新机器参考 [Ollama Linux 安装文档](https://docs.ollama.com/linux)。

模型使用明确的 `gemma4:e4b-it-qat` 标签；已验证模型 ID 为 `ee6656371218`，下载约 6.1 GB。模型和下载缓存不进入 Git。

Ollama 命令安装完成后，在 **WSL 项目目录**安装用户服务：

```bash
mkdir -p ~/.config/systemd/user
install -m 644 config/ollama/hw3-ollama.service ~/.config/systemd/user/hw3-ollama.service
systemctl --user daemon-reload
systemctl --user enable --now hw3-ollama
ollama pull gemma4:e4b-it-qat
```

服务监听 `127.0.0.1:11434`，`OLLAMA_NO_CLOUD=1` 禁用 Ollama Cloud，仅允许同时加载一个模型。服务与 Local profile 配置都使用实际 65,536-token context；本机 Hermes 拒绝低于 64,000 的 context。模板关闭 thinking，Local 输出限额为 256 tokens，修改时需要结合机器资源和实际任务复核。

日常操作：

```bash
systemctl --user start hw3-ollama
ollama list
ollama ps
hybrid-assistant chat --private --new "请只回答：本地模型可用。"
```

直接使用 Ollama 调试时可运行 `ollama run gemma4:e4b-it-qat --think=false`，用 `/bye` 退出。`ollama stop gemma4:e4b-it-qat` 卸载模型，`systemctl --user stop hw3-ollama` 停止服务。

交互使用时保持 WSL 终端或 VS Code WSL 会话打开；systemd 服务自身不能保证 WSL 一直存活。WSL 刚启动或模型刚加载时，响应比热调用慢。

## 4. NVIDIA NIM

[配置模板](../config/hermes/nim.yaml) 使用 Hermes 内置的 `nvidia` provider 和 `nvidia/nemotron-3-super-120b-a12b`。已验证 endpoint 为 `https://integrate.api.nvidia.com/v1`。NIM 不复用 Local 的 256-token 短输出配置。

新机器在 [NVIDIA 模型页面](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) 生成 API key，直接编辑已安装 profile 的 `.env`：

```bash
code ~/.hermes/profiles/hw3-nim/.env
```

设置 `NVIDIA_API_KEY=`。不要用 `config/hermes/nim.env.example` 覆盖已有 `.env`；模板只说明字段名称。项目不加载根目录 `.env`，也不转发父 shell 导出的 API key。

下面是可直接在项目 Python 中运行的合成路由检查，验证实际执行模型而不是仅看计划：

```python
from app.runtime import create_providers
from core.execution import execute_plan
from core.routing import (
    Complexity,
    Privacy,
    RequestContext,
    Source,
    plan_route,
)

plan = plan_route(
    RequestContext(
        privacy=Privacy.PUBLIC,
        source=Source.USER_INPUT,
        complexity=Complexity.COMPLEX,
    )
)
result = execute_plan(
    plan,
    "A takes 2 hours. B takes 3 hours after A; C takes 4 hours after A. "
    "B and C run in parallel. D takes 1 hour after both. Minimum total time?",
    create_providers(),
)
print(result.provider.value, result.text, result.used_fallback)
```

正确时间为 7 小时。实际 NIM 成功应显示 `nim` 和 `False`；`local` 和 `True` 表示 NIM 失败后本地回退成功，不能当成 NIM 联通。适配器保留 60 秒 Hermes run budget 和 90 秒进程超时，长推理可能触发 Local 回退。

## 5. Gmail、Telegram 和持久化偏好

Gmail 应用密码与 Telegram 绑定按[连接和调度指南](gmail-telegram.md)配置；Hermes 的发送依赖安装在它自己的环境。旧账号迁移已完成，本机无须重复设置。

长期偏好存放于 `~/.hermes/profiles/hw3-local/memories/USER.md`，只由 Local 业务调用加载。示例 `config/hermes/user.example.md` 不得覆盖已有正式偏好。新增、修改和删除使用[记忆命令](memory.md)或直接编辑文件。

## 6. 检查与日常启动

新 GitHub checkout 可在已激活的 WSL 项目环境中运行：

```bash
python -m ruff check .
python -m ruff format --check .
~/.hermes/bin/uv lock --check
hybrid-assistant --help
```

`tests/` 仅保留在本地，不纳入 Git，也不会随 GitHub checkout 提供。持有本地测试目录的维护者可额外运行 `python -m pytest -q`，执行离线测试。以上检查不调用真实模型或 Telegram。真实业务启动命令见 [README](../README.md)。活跃配置、凭据、模型记录及 USER.md 都保留在 WSL home，仓库只保存不含秘密的模板。