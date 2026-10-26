# Pulse

一个分层架构的本地 Agent：**UI 无关的 core + Textual TUI 前端**。

Pulse 由 `Practice02/chat.py` 重构而来，保留原有的系统提示词、10 个本地工具及全部安全护栏，
并新增联网搜索工具；同时把界面、网络、工具、会话彻底解耦。未来新增 Web、Desktop 或 Mobile
前端时，只需复用 `core/`，不必改动业务逻辑。

## 特性

- **流式对话**：基于 httpx 异步 SSE，边生成边渲染 Markdown。
- **联网搜索**：`searchWeb` 工具调用百度千帆智能搜索生成 API，返回搜索摘要与参考来源标题/URL。
- **网页正文抓取**：`fetchWeb` 工具用本地 curl 下载网页，再由 trafilatura 提取 Markdown 正文
  （保留标题、段落、列表、表格与链接，去除导航、广告、页脚）。
- **本地 CLI 调用**：`RunCli` 以参数列表方式执行任意已安装程序（`shell=False`），
  返回 stdout、stderr 和退出码，供模型判断下一步。
- **工具调用可视化**：工具名、参数与结果以可折叠卡片内联展示。
- **右侧会话侧栏**：展示模型、接口、工作目录、会话 ID、轮次、消息数与全部工具说明，可随时隐藏。
- **破坏性操作确认**：删除文件/目录前弹出确认框，拒绝后模型会收到"用户取消"。
- **可取消生成**：随时按 `Esc` 中止当前回合，历史消息保持合法。
- **UI 无关核心**：`core` 不依赖 Textual/Rich，可直接被 Web/Desktop 复用。
- **可测试**：注入 Fake 模型即可离线跑完整 Agent 循环，无需网络。

## 架构

```
tui  ──▶  core
core ──▶  Python 标准库、httpx
core ──✕  textual / rich / tui / web / desktop / mobile
```

```
Pulse/
├── core/                  # 业务核心（无 UI 依赖）
│   ├── config.py          # 配置读取
│   ├── models.py          # Message / ToolCall / ToolResult
│   ├── events.py          # 引擎 → 前端的事件契约
│   ├── session.py         # 会话历史
│   ├── agent.py           # AgentEngine.run_turn() 事件流
│   ├── confirmation.py    # 确认协议（各前端实现）
│   ├── llm/               # ChatModel 协议 + OpenAI 兼容客户端
│   └── tools/             # 工具声明、注册表、内置工具
├── tui/                   # Textual 前端
│   ├── app.py             # App、Worker、事件渲染、命令
│   ├── confirmation.py    # 确认协议 → ModalScreen
│   ├── widgets/           # 消息、工具卡片、状态栏、确认框、输入框
│   └── styles.tcss
├── tests/                 # 离线测试（core + TUI）
└── docs/ARCHITECTURE.md   # 分层细节与扩展新前端指南
```

更详细的分层说明、事件流程与"新增 Web 前端"步骤见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

```bash
cd Agent/Pulse

# 1. 创建虚拟环境（已创建可跳过）
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1
# Git Bash / cmd
source .venv/Scripts/activate

# 2. 安装依赖
pip install -e ".[dev]"
```

运行：

```bash
python -m tui
```

或在安装后从任意目录运行：

```bash
pulse
```

> 推荐在 Windows Terminal 中运行，中文输入与配色效果更好。

## 配置

默认复用 `Agent/config.ini`（Pulse 会从 `core/config.py` 所在位置逐级向上查找）：

```ini
[llm]
base_url = https://api.deepseek.com
api_key = sk-...
model = deepseek-flash

# 可选
request_timeout = 60
max_tool_rounds = 20

[search]
# 可选：缺少该段时 Pulse 仍可运行，调用 searchWeb 会返回明确的配置提示
baidu_qianfan_api_key = bce-v3/...
# 可选：智能搜索生成使用的模型，默认 ernie-4.5-turbo-32k
model = ernie-4.5-turbo-32k
```

查找优先级：

1. `python -m tui --config <路径>`
2. 环境变量 `PULSE_CONFIG`
3. `Pulse/core/config.ini` → `Pulse/config.ini` → `Agent/config.ini` → `LLM/config.ini`

`config.ini` 含明文密钥，已被仓库 `.gitignore` 忽略。

## 工作区

文件工具的相对路径以 **workspace** 为基准；绝对路径仍可访问任意位置（与原行为一致）。
workspace 默认为启动命令时的当前目录，可用以下方式指定：

```bash
python -m tui --workspace ..
# 或
PULSE_WORKSPACE=C:/Users/HUAWEI/Desktop/LLM/Agent python -m tui
```

当前工作区会显示在底部状态栏。删除操作始终拒绝磁盘根目录、workspace 及进程当前目录
及其父目录。

## 使用

| 操作 | 说明 |
| --- | --- |
| `Enter` | 发送消息 |
| `Shift+Enter` | 输入框内换行 |
| `Esc` | 取消当前生成（确认框打开时先关闭确认框） |
| `Ctrl+B` | 显示/隐藏右侧栏 |
| `Ctrl+N` | 新会话 |
| `Ctrl+L` | 清屏（保留会话历史） |
| `F1` | 显示帮助 |
| `Ctrl+Q` | 退出 |

命令：

| 命令 | 说明 |
| --- | --- |
| `/help` | 显示帮助 |
| `/tools` | 列出可用工具 |
| `/clear` | 开始新会话（清空历史与聊天记录，等同 `Ctrl+N`） |
| `/quit` | 退出 |

内置工具：`getdate`、`isLeapYear`、`getcwd`、`listDirectory`、`getFileType`、
`readTextFile`、`createDirectory`、`deleteDirectory`、`deleteFile`、`renamePath`、
`searchWeb`、`fetchWeb`、`RunCli`。

`searchWeb` 需要 `[search]` 段的 `baidu_qianfan_api_key`，用于调用
[百度千帆智能搜索生成 API](https://cloud.baidu.com/doc/qianfan-api/s/Hmbu8m06u)；
未配置、网络失败或 API 返回错误时，工具结果会带有清晰的错误说明，Agent 会如实转告用户。

`fetchWeb` 通过 `subprocess` 以参数列表方式调用本地 `curl`（不使用 `shell=True`），
再用 `trafilatura` 提取正文并转换为 Markdown；返回内容限制在约 20000 字符以内。
Windows 10/11 自带 `curl.exe`，其他系统需确保 `curl` 在 `PATH` 中。

`RunCli` 把 `command` 与 `args` 拼装为参数列表后执行，`shell=False`，在 workspace 中运行，
stdin 接到 `DEVNULL`，超时 30 秒；stdout / stderr 各截断到 8000 字符并明确标注。
命令以运行 Pulse 的当前用户权限执行。

> **安全提示**：本阶段为了教学演示，`RunCli` 不实现命令白名单、黑名单或审批机制。
> 请仅在受控实验环境中使用，不要在生产或不受信任的输入场景中开放该工具。

## 测试

```bash
python -m pytest
```

测试全部使用 FakeChatModel 与临时目录，不需要网络，也不依赖 Git Bash；
其中 `test_core_is_ui_agnostic.py` 会通过 AST 扫描强制检查 `core` 没有导入任何界面层。

## 与 Practice02/chat.py 的差异

除架构重构外，以下行为是有意改进：

1. **工具参数非法 JSON 时不再执行工具**：原实现会退化为 `{}` 后继续执行，可能误触发
   破坏性操作；Pulse 返回错误结果，让模型重试。
2. **工具调用轮数上限**（默认 20）：原实现无上限，存在死循环风险。
3. **异常与取消后的历史一致性**：不再留下"有 tool_calls 但没有对应 tool 消息"的非法历史。
4. **相对路径以显式 workspace 为基准**：避免从不同目录启动时操作到意外位置。
5. **所有输出事件化**：核心不再 `print` / `input`。

原有 10 个工具的名称与顺序、参数 schema、中文结果文案、文本编码与 200KB 截断、
删除护栏均保持不变；系统提示词在原有内容基础上增加了 `searchWeb` / `fetchWeb` /
`RunCli` 的使用要求，这三个工具排在原有工具之后。

## 扩展新前端

1. 实现 `core.confirmation.ConfirmationProvider`（如 WebSocket 推送确认请求）。
2. 创建 `AgentEngine(model, registry)`，其中 registry 的 `confirmation` 指向你的实现。
3. 消费 `engine.run_turn(text)` 的事件流：
   - `TurnStarted` / `TextDelta` / `ToolCallRequested` / `ToolCallCompleted`
   - `ErrorOccurred` / `TurnFinished`
4. 不要导入 `tui/`，也不要在 `core/` 中增加界面相关代码。

可参考 `tui/app.py` 的 `_consume_turn()`，它完整展示了事件到界面的映射方式。
