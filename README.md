# Claude Code 会话日志自动记录方案

## 背景

在使用 Claude Code 进行日常开发时，每次对话都会产生有价值的上下文：需求分析、技术方案、代码变更、问题排查记录等。但 Claude Code 本身不提供会话归档能力，关闭终端后对话就丢失了。

本方案通过 **Stop Hook + Python 脚本** 实现了全自动的会话日志记录与归档，零人工干预。

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

## 快速安装（3 步）

### 1. 复制脚本

```bash
mkdir -p ~/.claude/scripts
cp sync-session-log.py ~/.claude/scripts/
chmod +x ~/.claude/scripts/sync-session-log.py
```

### 2. 配置 Stop Hook

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

> 如果你的 `settings.json` 已有其他配置，只需将 `hooks` 部分合并进去即可。
> 完整的 `settings.json` 示例见 `settings-hook-only.json`。

### 3. 创建输出目录

```bash
mkdir -p ~/workspace/claudecode/merged
```

安装完成！重新打开 Claude Code，每次对话结束后日志会自动同步。

## 自定义配置

通过环境变量自定义行为（可在 `~/.zshrc` 或 `~/.bashrc` 中设置）：

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

## （可选）全局 CLAUDE.md 约定

如果团队希望统一规范，可在 `~/.claude/CLAUDE.md` 中加入以下约定：

```markdown
## 会话日志自动归档约定

- 日志根目录：`~/workspace/claudecode/`
- 按日期归档：`{YYYY-MM-DD}/{project}-{epoch}/session-log.md`
- 全量合并：`~/workspace/claudecode/merged/{project}-session-log.md`
- Stop Hook 自动触发，无需手动操作
```

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

## 文件清单

```
claude-session-log-kit/
├── README.md                    # 本文档
├── sync-session-log.py          # 核心脚本（放到 ~/.claude/scripts/）
├── settings-hook-only.json      # 最小化 settings.json（仅 Hook 部分）
└── install.sh                   # 一键安装脚本
```
