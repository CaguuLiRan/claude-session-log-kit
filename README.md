# Claude Code 会话日志自动记录 & 全局配置方案

## 背景

在使用 Claude Code 进行日常开发时，每次对话都会产生有价值的上下文：需求分析、技术方案、代码变更、问题排查记录等。但 Claude Code 本身不提供会话归档能力，关闭终端后对话就丢失了。

本方案提供两部分内容：

1. **会话日志自动记录** — 通过 Stop + SessionEnd Hook，零人工干预自动归档、合并、滚动归档
2. **全局配置模板** — 经过实战验证的 Claude Code 全局配置，包含行为约定、插件配置、MCP 服务等

## 效果展示

```
~/workspace/claudecode/
├── 2026-04-03/
│   └── gaia-product-143025/
│       └── session-log.md              # 当天该会话的日志（目录名：项目-时分秒）
├── 2026-04-07/
│   └── gaia-product-091548/
│       └── session-log.md
├── 2026-04-08/
│   └── gaia-product-164530/
│       └── session-log.md
└── merged/
    ├── gaia-product-session-log.md                                     # 最新合并日志（会话关闭时更新）
    └── gaia-product-session-log.2026-03-30-143025~2026-04-05-091548.md # 滚动归档（超 5MB 自动切分）
```

每个 `session-log.md` 包含：
- 会话元数据（Session ID、Git 分支、消息数）
- 完整的 User/Assistant 对话记录（带时间戳）
- 自动目录索引，可快速跳转

## 原理

```
┌──────────────────────────────────────────────────────────────┐
│                    Claude Code 会话                           │
│                                                              │
│  用户提问 → Claude 回答 → Stop Hook 触发（每次回答后）         │
│                              ↓                               │
│                   归档当前会话到日期目录                        │
│             {date}/{project}/session-log.md                   │
│                              ↓                               │
│              检查 .last_merge_ts（惰性合并）                   │
│              距上次合并 ≥ 30 分钟？                            │
│              ├── 是 → 执行全量合并 + 滚动归档                  │
│              └── 否 → 跳过（节流）                            │
│                                                              │
│  用户关闭会话（/exit 或 Ctrl+C）→ SessionEnd Hook 触发         │
│                              ↓                               │
│              ┌───────────────┴───────────────┐                │
│              ↓                               ↓                │
│       全量合并所有会话                  检查是否超 5MB          │
│  merged/{project}-session-log.md     超限则滚动归档            │
│                                  {project}-session-log.       │
│                                  {start}~{end}.md             │
└──────────────────────────────────────────────────────────────┘
```

**关键点**：
- **Stop Hook**（每次回答后）：归档当前会话 + 惰性合并（每 30 分钟自动触发全量合并）
- **SessionEnd Hook**（会话关闭时）：执行全量合并 + 超限滚动归档
- **惰性合并**：解决 IDEA 等 GUI 插件中 `SessionEnd` Hook 无法触发的问题
- **自动噪声过滤**：自动过滤 `git commit agent` 等内置工具产生的临时会话，保持归档整洁
- 合并文件超过 **5MB** 时，自动将旧会话按时间段切分为独立归档文件
- **目录命名优化**：使用 `项目-HHMMSS`（时分秒）格式，比时间戳更易读
- **`--merge-all` 模式**：独立运行，自动发现所有项目并合并，可用于 cron 兜底

---

## 快速安装

### 前置条件

| 条件 | 说明 |
|------|------|
| Python 3.6+ | 脚本运行环境（macOS/Linux 通常自带） |
| Claude Code CLI | 需要已安装并可正常使用 |

### 方式一：一键安装（推荐）

```bash
git clone https://github.com/CaguuLiRan/claude-session-log-kit.git
cd claude-session-log-kit
bash install.sh
```

脚本会自动：创建目录、复制脚本、合并 Hook 配置（不覆盖已有配置）。

### 方式二：手动安装（3 步）

#### 1. 复制脚本（必选）

```bash
mkdir -p ~/.claude/scripts
cp sync-session-log.py ~/.claude/scripts/
chmod +x ~/.claude/scripts/sync-session-log.py
```

#### 2. 配置 Hooks（必选）

将以下内容合并到 `~/.claude/settings.json`：

```jsonc
{
  "hooks": {
    // [必选] 每次回答后归档当前会话
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/sync-session-log.py",
            "timeout": 30,
            "statusMessage": "Syncing session log..."
          }
        ]
      }
    ],
    // [必选] 会话关闭时合并所有会话 + 滚动归档
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/sync-session-log.py --merge",
            "timeout": 60,
            "statusMessage": "Merging session logs..."
          }
        ]
      }
    ]
  }
}
```

> 完整的 `settings.json` 示例见 `settings-hook-only.json`。

#### 3. 创建输出目录（必选）

```bash
mkdir -p ~/workspace/claudecode/merged
```

安装完成！重新打开 Claude Code，每次对话结束后日志会自动同步。

---

## 安装组件一览

| 组件 | 必选 | 说明 |
|------|:----:|------|
| `sync-session-log.py` | **必选** | 核心脚本，负责解析 JSONL、生成 Markdown 日志、惰性合并、滚动归档 |
| Stop Hook | **必选** | 每次 Claude 回答后归档当前会话 + 惰性合并（每 30 分钟） |
| SessionEnd Hook | 推荐 | 会话关闭时合并所有会话 + 超限滚动归档（CLI 场景有效，GUI 插件可能不触发） |
| 输出目录 `~/workspace/claudecode/` | **必选** | 日志存储位置，脚本会自动创建子目录 |
| `CLAUDE.md` 全局约定 | 可选 | 定义 AI 在所有项目中的行为规范 |
| `/convention` 自定义命令 | 可选 | 快速查看当前全局约定规则 |
| `settings.json` 完整配置 | 可选 | 包含插件、MCP 服务等完整配置模板 |
| 环境变量自定义 | 可选 | 自定义输出目录、时区、合并间隔等 |

---

## 全局配置模板

`global-config/` 目录包含经过实战验证的 Claude Code 全局配置模板，可直接复制到 `~/.claude/` 使用。

### 目录结构

```
global-config/
├── CLAUDE.md              # 全局行为约定（适用于所有项目）
├── settings.json          # 完整配置模板（需填入你自己的 Token）
├── commands/
│   └── convention.md      # /convention 自定义命令
└── scripts/
    └── sync-session-log.py  # 会话日志同步脚本
```

### CLAUDE.md — 全局约定说明

这是 Claude Code 的全局指令文件，定义了 AI 在所有项目中的行为规范：

| 约定 | 内容 |
|------|------|
| **编码行为** | 严禁自动 git commit/push，所有提交需用户手动确认 |
| **会话日志** | 自动归档对话记录到 `~/workspace/claudecode/`，Hook 兜底同步 |
| **子 Agent** | 允许创建子 agent 做任务拆解和并行执行，但必须继承全局约定 |
| **默认约束** | 回答简洁专业、代码保证可运行、不擅自扩展范围 |

### settings.json — 配置说明

模板已脱敏，使用前需替换以下占位符：

| 占位符 | 必选 | 获取方式 |
|--------|:----:|----------|
| `<YOUR_ANTHROPIC_TOKEN>` | **必选** | [console.anthropic.com](https://console.anthropic.com/) |
| `<YOUR_API_PROXY_URL_IF_NEEDED>` | 可选 | 仅代理/自建网关场景需要，直连 API 可删除此行 |
| `<YOUR_GITHUB_TOKEN>` | 可选 | [github.com/settings/tokens](https://github.com/settings/tokens)，不使用 GitHub MCP 可删除 |
| `<YOUR_YUNXIAO_TOKEN>` | 可选 | [阿里云云效个人访问令牌](https://help.aliyun.com/zh/yunxiao/developer-reference/obtain-personal-access-token)，不使用云效 MCP 可删除 |
| `<YOUR_PROVIDER_ID>` | 可选 | 如未使用 Codemoss 可删除此行 |

### 配置功能一览

| 功能 | 必选 | 说明 |
|------|:----:|------|
| **Stop Hook** | **必选** | 每次回答后归档当前会话 + 惰性合并（每 30 分钟） |
| **SessionEnd Hook** | 推荐 | 会话关闭时合并 + 滚动归档（CLI 场景有效） |
| **模型配置** | 可选 | 默认 Sonnet（1M 上下文窗口），可切换 Opus |
| **插件** | 可选 | superpowers、context7、code-review、agent-sdk-dev |
| **语言** | 可选 | 默认中文交互 |
| **会话录制** | 可选 | 内置 Markdown 格式录制到 `~/Desktop/claude-sessions` |
| **MCP 服务** | 可选 | GitHub MCP Server（通过自然语言操作 GitHub） |
| **MCP 服务** | 可选 | 阿里云云效 DevOps MCP Server（代码管理、项目协作、流水线、制品库等） |

### 安装全局配置（可选）

```bash
# 复制全局约定（可选）
cp global-config/CLAUDE.md ~/.claude/CLAUDE.md

# 复制完整配置（可选，需先编辑替换 Token 占位符）
cp global-config/settings.json ~/.claude/settings.json

# 复制自定义命令（可选）
mkdir -p ~/.claude/commands
cp -r global-config/commands/* ~/.claude/commands/

# 复制脚本（必选，一键安装已自动完成）
mkdir -p ~/.claude/scripts
cp global-config/scripts/sync-session-log.py ~/.claude/scripts/
chmod +x ~/.claude/scripts/sync-session-log.py
```

> **注意**：如果你已有 `~/.claude/settings.json`，请手动合并而非直接覆盖。

### /convention 命令

安装后可在 Claude Code 中使用 `/convention` 命令，快速查看当前生效的全局约定规则。

---

## Copilot API 自动授权脚本

`copilot-api-auth.py` 是一个辅助脚本，用于自动化 [copilot-api](https://github.com/jjleng/copilot-api) 的 GitHub 设备授权流程，让你可以通过 GitHub Copilot 的 Token 来使用 Claude Code。

### 它做了什么

1. 启动 `npx @jeffreycao/copilot-api@latest start`
2. 监听输出，自动提取 GitHub Device 验证码
3. 自动打开浏览器跳转到授权页面 + 复制验证码到剪贴板
4. 等待授权完成后，自动将 token 写入 Claude Code 的 `settings.json`（`env.ANTHROPIC_AUTH_TOKEN`）

### 使用方式

```bash
python3 copilot-api-auth.py
```

支持透传参数给 copilot-api：

```bash
python3 copilot-api-auth.py --port 8080
```

### 跨平台支持

| 平台 | 剪贴板 | Token 路径 | Settings 路径 |
|------|--------|-----------|--------------|
| macOS | `pbcopy` | `~/.local/share/copilot-api/github_token` | `~/.claude/settings.json` |
| Windows | `clip` | `%LOCALAPPDATA%/copilot-api/github_token` | `%APPDATA%/Claude/settings.json` |
| Linux | `xclip` / `xsel` | `~/.local/share/copilot-api/github_token` | `~/.claude/settings.json` |

---

## 自定义配置

通过环境变量自定义日志行为（可在 `~/.zshrc` 或 `~/.bashrc` 中设置）：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CLAUDE_SESSION_LOG_DIR` | `~/workspace/claudecode` | 日志输出根目录 |
| `CLAUDE_SESSION_LOG_TZ_OFFSET` | `8`（UTC+8） | 时区偏移小时数 |
| `CLAUDE_SESSION_MERGE_INTERVAL` | `30` | 惰性合并间隔（分钟），Stop Hook 每隔此时间自动触发全量合并 |

脚本还支持命令行参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--merge` | 不启用 | 执行全量合并 + 滚动归档（SessionEnd hook 使用） |
| `--merge-all` | 不启用 | 自动发现所有项目并合并，无需 session_id（独立运行 / cron 使用） |
| `--max-size` | `5` (MB) | 合并文件超过此大小时触发滚动归档 |
| `--merge-interval` | `30` (分钟) | 惰性合并间隔，Stop Hook 中超过此时间自动合并 |

示例：

```bash
# 改为输出到 ~/claude-logs，时区 UTC+9（东京）
export CLAUDE_SESSION_LOG_DIR=~/claude-logs
export CLAUDE_SESSION_LOG_TZ_OFFSET=9

# 惰性合并间隔改为 15 分钟
export CLAUDE_SESSION_MERGE_INTERVAL=15

# 手动触发所有项目合并（可用于 cron 兜底）
python3 ~/.claude/scripts/sync-session-log.py --merge-all
```

---

## 常见问题

### Q: 日志没有生成？
1. 确认 `~/.claude/settings.json` 中 `hooks.Stop` 和 `hooks.SessionEnd` 配置正确
2. 确认脚本有执行权限：`chmod +x ~/.claude/scripts/sync-session-log.py`
3. 手动测试脚本：`echo '{"session_id":"任意id"}' | python3 ~/.claude/scripts/sync-session-log.py`

### Q: 合并日志没有更新？
合并操作在以下时机触发：
1. **惰性合并**（Stop Hook）：每 30 分钟自动触发一次全量合并
2. **显式合并**（SessionEnd Hook）：会话关闭时触发
3. **手动合并**：
```bash
# 合并所有项目（推荐）
python3 ~/.claude/scripts/sync-session-log.py --merge-all

# 合并指定会话
echo '{"session_id":"你的session_id"}' | python3 ~/.claude/scripts/sync-session-log.py --merge
```

### Q: 在 IDEA / Cursor 等 GUI 插件中日志不合并？
这是因为 GUI 插件关闭时不会触发 `SessionEnd` Hook。脚本已内置**惰性合并机制**：Stop Hook 每 30 分钟自动检查并触发全量合并，无需依赖 `SessionEnd`。如果需要调整间隔：
```bash
export CLAUDE_SESSION_MERGE_INTERVAL=15  # 改为每 15 分钟
```

### Q: 日志时间不对？
设置环境变量 `CLAUDE_SESSION_LOG_TZ_OFFSET` 为你所在时区的 UTC 偏移（如北京时间为 `8`）。

### Q: 会不会影响 Claude Code 性能？
不会。Stop hook 大部分时间仅归档当前单个会话（通常 < 0.5 秒）。惰性合并每 30 分钟才触发一次，合并操作也仅在需要时执行。

### Q: 多个项目会冲突吗？
不会。脚本按项目目录自动区分，每个项目有独立的日志目录和合并文件。

### Q: 合并文件太大怎么办？
脚本内置滚动归档机制：当合并文件超过 5MB 时，会自动将旧会话按时间段切分为独立归档文件，命名格式为 `project-session-log.2026-03-30-143025~2026-04-05-091548.md`（开始日期时间~结束日期时间），最新的合并文件只保留近期会话。如果同一时间范围多个归档文件，自动追加序号后缀（`.1.md`, `.2.md`）。可通过 `--max-size` 参数调整阈值。

### Q: settings.json 直接覆盖安全吗？
建议手动合并。如果你已有自定义配置（其他 MCP 服务、环境变量等），直接覆盖会丢失这些配置。

### Q: 为什么有些会话没有被归档？
脚本会自动过滤 `git commit agent` 等内置工具产生的临时自动化会话，这些会话通常是单次交互，不需要持久化归档。如果你认为某个会话被误过滤，可以关闭并重新打开会话。

---

## 文件清单

```
claude-session-log-kit/
├── README.md                          # 本文档
├── sync-session-log.py                # 核心脚本（放到 ~/.claude/scripts/）
├── settings-hook-only.json            # 最小化 settings.json（仅 Hook 部分）
├── install.sh                         # 一键安装脚本
├── copilot-api-auth.py                # Copilot API 自动授权脚本
└── global-config/                     # 全局配置模板（可选）
    ├── CLAUDE.md                      # 全局行为约定
    ├── settings.json                  # 完整配置（已脱敏，需填 Token）
    ├── commands/
    │   └── convention.md              # /convention 自定义命令
    └── scripts/
        └── sync-session-log.py        # 同步脚本
```
