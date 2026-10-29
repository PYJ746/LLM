# Pulse

一个分层架构的本地 Agent：**UI 无关的 core + Textual TUI 前端**。

Pulse 由 `Practice02/chat.py` 重构而来，保留原有的系统提示词、10 个本地工具及全部安全护栏，
并新增联网搜索工具；同时把界面、网络、工具、会话彻底解耦。未来新增 Web、Desktop 或 Mobile
前端时，只需复用 `core/`，不必改动业务逻辑。

## 特性

- **流式对话**：基于 httpx 异步 SSE，边生成边渲染 Markdown。
- **联网搜索**：`searchWeb` 调用百度千帆 AI 搜索 `web_search` API，返回参考来源的
  标题、URL、站点、日期与内容摘要。
- **网页正文抓取**：`fetchWeb` 工具用本地 curl 下载网页，再由 trafilatura 提取 Markdown 正文
  （保留标题、段落、列表、表格与链接，去除导航、广告、页脚）。
- **本地 CLI 调用**：`RunCli` 以参数列表方式执行任意已安装程序（`shell=False`），
  返回 stdout、stderr 和退出码，供模型判断下一步。
- **工具调用可视化**：工具名、参数与结果以可折叠卡片内联展示。
- **右侧会话侧栏**：展示模型、接口、工作目录、会话 ID、轮次、消息数与全部工具说明，可随时隐藏。
- **破坏性操作确认**：删除文件/目录前弹出确认框，拒绝后模型会收到"用户取消"。
- **Skill 动态加载**：按 Agent Skills 规范扫描 `.agents/skills/`，启动时只读取
  `name` / `description`，模型需要时再用 `loadSkill` 读取完整 `SKILL.md`。
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
│   ├── skills/            # Skill 发现、注册、按需加载与提示词注入
│   └── tools/             # 工具声明、注册表、内置工具（含 loadSkill）
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
# 旧版的 model 键已不再使用（新接口只返回搜索结果，不生成摘要），可以删除
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

## Skills（Agent Skills 规范）

Pulse 支持 Skill 的渐进式加载。启动时以**程序启动时的工作目录**为项目根目录扫描：

```
<启动目录>/.agents/skills/
└── notice/
    └── SKILL.md
```

每个 Skill 子目录至少包含一个 `SKILL.md`，开头用 YAML Frontmatter 声明
`name` 与 `description` 两个必需字段：

```markdown
---
name: notice
description: 撰写公司内部通知
---

1. 通知标题必须包含部门名称……
2. 落款必须写明起草人……
```

加载过程：

1. **初始化**：只解析 frontmatter 的 `name` / `description`，不读取正文，
   并把 Skill 目录注入系统提示词；
2. **按需加载**：用户请求与某个 Skill 的描述匹配时，模型调用
   `loadSkill(name)` 读取该 Skill 的完整 `SKILL.md`，再按说明执行；
3. **附加资源**：调用 `loadSkill(name, filename)` 读取 Skill 目录内的附件，
   此时不会重复返回 `SKILL.md`。

`filename` 的解析顺序：

1. 绝对路径；
2. 相对 Skill 目录的路径；
3. 相对项目根目录的路径（如 `.agents/skills/notice/references/a.md`）；
4. 只给文件名（如 `guide.md`）时，在该 Skill 目录内递归查找：唯一命中才读取，
   多个同名文件会返回候选路径，由模型选择后再调用。

所有读取都限制在指定 Skill 的目录内部。`..` 越界、目录外绝对路径以及指向外部的
符号链接都会被拒绝；附件按文本读取（UTF-8/GBK 回退），二进制文件会被拒绝，
超过 200KB 的部分会截断。

### 动态加载原则

- Skill 注册表只保存 `name` / `description` 与路径，**不缓存正文**；
- System Prompt 和 Function Calling 的 tools schema 只包含元数据，
  完整 `SKILL.md` 与附件不会提前占用上下文；
- 只有 LLM 调用 `loadSkill` 后，正文才作为 `role=tool` 消息进入对话历史；
- `loadSkill` 就是一个普通工具，不改变 `AgentEngine` 的轮次与工具循环，
  可以与 `RunCli`、`readTextFile` 等既有工具在同一轮中交替调用。

`/skills` 命令可查看已发现的 Skill 及其位置与加载警告。frontmatter 解析支持
顶层 `key: value`、单/双引号与 `|` / `>` 块标量，不需要额外 YAML 依赖。

容错行为：

- `.agents/skills/` 不存在时 Pulse 正常运行，只是没有 Skill；
- 缺少 `SKILL.md`、缺少必需字段、frontmatter 未闭合或名称重复的目录会被跳过，
  并记录在 `/skills` 的“加载警告”中，不影响其他 Skill 与启动。

> Skill 根目录只看启动目录，不受 `--workspace` / `PULSE_WORKSPACE` 影响
> （workspace 只决定文件工具的相对路径基准）。

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
| `/skills` | 列出已发现的 Skills 与加载警告 |
| `/clear` | 开始新会话（清空历史与聊天记录，等同 `Ctrl+N`） |
| `/quit` | 退出 |

内置工具：`getdate`、`isLeapYear`、`getcwd`、`listDirectory`、`getFileType`、
`readTextFile`、`createDirectory`、`deleteDirectory`、`deleteFile`、`renamePath`、
`searchWeb`、`fetchWeb`、`RunCli`。发现至少一个 Skill 时会额外注册 `loadSkill`。

`searchWeb` 需要 `[search]` 段的 `baidu_qianfan_api_key`，用于调用
[百度千帆 AI 搜索 web_search API](https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5)。
接口返回 `references` 中的标题、URL、站点、日期与内容摘要，不生成模型摘要；
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
