# Claude Code 会话日志自动记录 & 全局配置方案

## 背景

在使用 Claude Code 进行日常开发时，每次对话都会产生有价值的上下文：需求分析、技术方案、代码变更、问题排查记录等。但 Claude Code 本身不提供会话归档能力，关闭终端后对话就丢失了。

本方案提供两部分内容：

1. **会话日志自动记录** — 通过 Stop Hook + Python 脚本，零人工干预自动归档每次对话
2. **全局配置模板** — 经过实战验证的 Claude Code 全局配置，包含行为约定、插件配置、MCP 服务等

## 效果展示

```
~/workspace/claudecode/
├── 2026-04-03/
│   └── gaia-product-1712108589/
│       └── session-log.md          # 当天所有会话
├── 2026-04-07/
│   └── gaia-product-1712345678/
│       └── session-log.md
├── 2026-04-08/
│   └── gaia-product-1712567890/
│       └── session-log.md
└── merged/
    └── gaia-product-session-log.md # 该项目全量合并日志
```

每个 `session-log.md` 包含：
- 会话元数据（Session ID、Git 分支、消息数）
- 完整的 User/Assistant 对话记录（带时间戳）
- 自动目录索引，可快速跳转

## 原理

```
用户提问 → Claude 回答 → Stop Hook 自动触发
                              ↓
                    sync-session-log.py 执行
                              ↓
        读取 ~/.claude/projects/<project>/<session>.jsonl
                              ↓
              ┌───────────────┴───────────────┐
              ↓                               ↓
     按日期归档写入                      全量合并更新
  {date}/{project}/session-log.md   merged/{project}-session-log.md
```

**关键点**：Claude Code 的每次对话都会写入 JSONL 文件（`~/.claude/projects/` 下），Stop Hook 在每次 Claude 回答结束后自动触发脚本，解析 JSONL 生成可读的 Markdown 日志。

---

## 快速安装

### 方式一：一键安装（推荐）

```bash
git clone https://github.com/CaguuLiRan/claude-session-log-kit.git
cd claude-session-log-kit
bash install.sh
```

脚本会自动：创建目录、复制脚本、合并 Hook 配置（不覆盖已有配置）。

### 方式二：手动安装（3 步）

#### 1. 复制脚本

```bash
mkdir -p ~/.claude/scripts
cp sync-session-log.py ~/.claude/scripts/
chmod +x ~/.claude/scripts/sync-session-log.py
```

#### 2. 配置 Stop Hook

将以下内容合并到 `~/.claude/settings.json`：

```jsonc
{
  "hooks": {
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
    ]
  }
}
```

> 完整的 `settings.json` 示例见 `settings-hook-only.json`。

#### 3. 创建输出目录

```bash
mkdir -p ~/workspace/claudecode/merged
```

安装完成！重新打开 Claude Code，每次对话结束后日志会自动同步。

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
| **会话日志** | 自动归档对话记录到 `~/workspace/claudecode/`，Stop Hook 兜底同步 |
| **子 Agent** | 允许创建子 agent 做任务拆解和并行执行，但必须继承全局约定 |
| **默认约束** | 回答简洁专业、代码保证可运行、不擅自扩展范围 |

### settings.json — 配置说明

模板已脱敏，使用前需替换以下占位符：

| 占位符 | 说明 | 获取方式 |
|--------|------|----------|
| `<YOUR_ANTHROPIC_TOKEN>` | Anthropic API Token | [console.anthropic.com](https://console.anthropic.com/) |
| `<YOUR_API_PROXY_URL_IF_NEEDED>` | API 代理地址（非必需） | 仅代理/自建网关场景需要，直连 API 可删除此行 |
| `<YOUR_GITHUB_TOKEN>` | GitHub Personal Access Token | [github.com/settings/tokens](https://github.com/settings/tokens) |
| `<YOUR_PROVIDER_ID>` | Codemoss Provider ID（非必需） | 如未使用 Codemoss 可删除此行 |

### 配置功能一览

| 功能 | 说明 |
|------|------|
| **模型配置** | 默认 Sonnet（1M 上下文窗口），可切换 Opus |
| **插件** | superpowers（增强工作流）、context7（文档查询）、code-review、agent-sdk-dev |
| **语言** | 默认中文交互 |
| **会话录制** | 内置 Markdown 格式录制到 `~/Desktop/claude-sessions` |
| **Stop Hook** | 每次回答后自动同步会话日志 |
| **MCP 服务** | GitHub MCP Server（通过自然语言操作 GitHub） |

### 安装全局配置

```bash
# 复制全局约定
cp global-config/CLAUDE.md ~/.claude/CLAUDE.md

# 复制完整配置（需先编辑替换 Token 占位符）
cp global-config/settings.json ~/.claude/settings.json

# 复制自定义命令
mkdir -p ~/.claude/commands
cp -r global-config/commands/* ~/.claude/commands/

# 复制脚本
mkdir -p ~/.claude/scripts
cp global-config/scripts/sync-session-log.py ~/.claude/scripts/
chmod +x ~/.claude/scripts/sync-session-log.py
```

> **注意**：如果你已有 `~/.claude/settings.json`，请手动合并而非直接覆盖。

### /convention 命令

安装后可在 Claude Code 中使用 `/convention` 命令，快速查看当前生效的全局约定规则。

---

## 自定义配置

通过环境变量自定义日志行为（可在 `~/.zshrc` 或 `~/.bashrc` 中设置）：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CLAUDE_SESSION_LOG_DIR` | `~/workspace/claudecode` | 日志输出根目录 |
| `CLAUDE_SESSION_LOG_TZ_OFFSET` | `8`（UTC+8） | 时区偏移小时数 |

示例：

```bash
# 改为输出到 ~/claude-logs，时区 UTC+9（东京）
export CLAUDE_SESSION_LOG_DIR=~/claude-logs
export CLAUDE_SESSION_LOG_TZ_OFFSET=9
```

---

## 常见问题

### Q: 日志没有生成？
1. 确认 `~/.claude/settings.json` 中 `hooks.Stop` 配置正确
2. 确认脚本有执行权限：`chmod +x ~/.claude/scripts/sync-session-log.py`
3. 手动测试脚本：`echo '{"session_id":"任意id"}' | python3 ~/.claude/scripts/sync-session-log.py`

### Q: 日志时间不对？
设置环境变量 `CLAUDE_SESSION_LOG_TZ_OFFSET` 为你所在时区的 UTC 偏移（如北京时间为 `8`）。

### Q: 会不会影响 Claude Code 性能？
不会。脚本执行时间通常 < 1 秒，超时上限 30 秒，且在 Claude 回答完成后才触发。

### Q: 多个项目会冲突吗？
不会。脚本按项目目录自动区分，每个项目有独立的日志目录和合并文件。

### Q: settings.json 直接覆盖安全吗？
建议手动合并。如果你已有自定义配置（其他 MCP 服务、环境变量等），直接覆盖会丢失这些配置。

---

## 文件清单

```
claude-session-log-kit/
├── README.md                          # 本文档
├── sync-session-log.py                # 核心脚本（放到 ~/.claude/scripts/）
├── settings-hook-only.json            # 最小化 settings.json（仅 Hook 部分）
├── install.sh                         # 一键安装脚本
└── global-config/                     # 全局配置模板
    ├── CLAUDE.md                      # 全局行为约定
    ├── settings.json                  # 完整配置（已脱敏，需填 Token）
    ├── commands/
    │   └── convention.md              # /convention 自定义命令
    └── scripts/
        └── sync-session-log.py        # 同步脚本
```
