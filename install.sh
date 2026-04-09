#!/bin/bash
# Claude Code 会话日志自动记录 & 全局配置 - 一键安装脚本
# 用法:
#   bash install.sh          # 仅安装日志功能
#   bash install.sh --full   # 安装日志功能 + 全局配置

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_SCRIPT_DIR="$HOME/.claude/scripts"
TARGET_COMMANDS_DIR="$HOME/.claude/commands"
SETTINGS_FILE="$HOME/.claude/settings.json"
LOG_DIR="${CLAUDE_SESSION_LOG_DIR:-$HOME/workspace/claudecode}"
INSTALL_FULL=false

# 解析参数
for arg in "$@"; do
    case $arg in
        --full) INSTALL_FULL=true ;;
    esac
done

if [ "$INSTALL_FULL" = true ]; then
    echo "============================================"
    echo "  Claude Code 全套配置 - 一键安装"
    echo "============================================"
    TOTAL_STEPS=6
else
    echo "============================================"
    echo "  Claude Code 会话日志 - 一键安装"
    echo "============================================"
    TOTAL_STEPS=4
fi
echo ""

# ── Step 1: 创建目录 ──
echo "[1/$TOTAL_STEPS] 创建必要目录..."
mkdir -p "$TARGET_SCRIPT_DIR"
mkdir -p "$LOG_DIR/merged"
echo "  ✓ $TARGET_SCRIPT_DIR"
echo "  ✓ $LOG_DIR/merged"

# ── Step 2: 复制脚本 ──
echo ""
echo "[2/$TOTAL_STEPS] 安装同步脚本..."
cp "$SCRIPT_DIR/sync-session-log.py" "$TARGET_SCRIPT_DIR/sync-session-log.py"
chmod +x "$TARGET_SCRIPT_DIR/sync-session-log.py"
echo "  ✓ $TARGET_SCRIPT_DIR/sync-session-log.py"

# ── Step 3: 配置 Hooks (Stop + SessionEnd) ──
echo ""
echo "[3/$TOTAL_STEPS] 配置 Hooks..."

if [ ! -f "$SETTINGS_FILE" ]; then
    if [ "$INSTALL_FULL" = true ] && [ -f "$SCRIPT_DIR/global-config/settings.json" ]; then
        cp "$SCRIPT_DIR/global-config/settings.json" "$SETTINGS_FILE"
        echo "  ✓ 使用完整配置模板创建 $SETTINGS_FILE"
        echo "  ⚠ 请编辑 $SETTINGS_FILE 替换 <YOUR_*> 占位符为你的实际 Token"
    else
        cp "$SCRIPT_DIR/settings-hook-only.json" "$SETTINGS_FILE"
        echo "  ✓ 创建新的 $SETTINGS_FILE"
    fi
else
    # 已有 settings.json，合并 Hook 配置
    python3 -c "
import json, sys

with open('$SETTINGS_FILE') as f:
    data = json.load(f)

if 'hooks' not in data:
    data['hooks'] = {}

changed = False

# ── Stop Hook (必选：每次回答后归档当前会话) ──
stop_exists = False
for hook_group in data.get('hooks', {}).get('Stop', []):
    for h in hook_group.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            stop_exists = True
            break

if not stop_exists:
    if 'Stop' not in data['hooks']:
        data['hooks']['Stop'] = []
    data['hooks']['Stop'].append({
        'hooks': [{
            'type': 'command',
            'command': 'python3 ~/.claude/scripts/sync-session-log.py',
            'timeout': 30,
            'statusMessage': 'Syncing session log...'
        }]
    })
    changed = True
    print('  ✓ Stop Hook 已配置（每次回答后自动归档）')
else:
    print('  ✓ Stop Hook 已存在，跳过')

# ── SessionEnd Hook (必选：会话关闭时合并+滚动归档) ──
end_exists = False
for hook_group in data.get('hooks', {}).get('SessionEnd', []):
    for h in hook_group.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            end_exists = True
            break

if not end_exists:
    if 'SessionEnd' not in data['hooks']:
        data['hooks']['SessionEnd'] = []
    data['hooks']['SessionEnd'].append({
        'hooks': [{
            'type': 'command',
            'command': 'python3 ~/.claude/scripts/sync-session-log.py --merge',
            'timeout': 60,
            'statusMessage': 'Merging session logs...'
        }]
    })
    changed = True
    print('  ✓ SessionEnd Hook 已配置（会话关闭时自动合并）')
else:
    print('  ✓ SessionEnd Hook 已存在，跳过')

if changed:
    with open('$SETTINGS_FILE', 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
"
fi

# ── Step 4: 验证基础安装 ──
echo ""
echo "[4/$TOTAL_STEPS] 验证基础安装..."

VERIFY_OK=true

if [ -f "$TARGET_SCRIPT_DIR/sync-session-log.py" ]; then
    echo "  ✓ 脚本已就位"
else
    echo "  ✗ 脚本安装失败！"
    VERIFY_OK=false
fi

if python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    data = json.load(f)
hooks = data.get('hooks', {})
# Check Stop hook
stop_ok = False
for hg in hooks.get('Stop', []):
    for h in hg.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            stop_ok = True
# Check SessionEnd hook
end_ok = False
for hg in hooks.get('SessionEnd', []):
    for h in hg.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            end_ok = True
if not (stop_ok and end_ok):
    raise Exception('Hook not found')
" 2>/dev/null; then
    echo "  ✓ Stop Hook 已配置"
    echo "  ✓ SessionEnd Hook 已配置"
else
    echo "  ✗ Hook 配置异常！请手动检查 $SETTINGS_FILE"
    VERIFY_OK=false
fi

if [ "$VERIFY_OK" = false ]; then
    echo ""
    echo "基础安装存在问题，请检查上述错误。"
    exit 1
fi

# ── Full mode: Step 5 & 6 ──
if [ "$INSTALL_FULL" = true ]; then

    # Step 5: 安装全局约定和自定义命令
    echo ""
    echo "[5/$TOTAL_STEPS] 安装全局约定和自定义命令..."

    if [ -f "$SCRIPT_DIR/global-config/CLAUDE.md" ]; then
        if [ -f "$HOME/.claude/CLAUDE.md" ]; then
            # 备份已有的 CLAUDE.md
            BACKUP_FILE="$HOME/.claude/CLAUDE.md.bak.$(date +%s)"
            cp "$HOME/.claude/CLAUDE.md" "$BACKUP_FILE"
            echo "  ⚠ 已备份现有 CLAUDE.md → $(basename $BACKUP_FILE)"
        fi
        cp "$SCRIPT_DIR/global-config/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
        echo "  ✓ 全局约定 CLAUDE.md 已安装"
    fi

    if [ -d "$SCRIPT_DIR/global-config/commands" ]; then
        mkdir -p "$TARGET_COMMANDS_DIR"
        cp -r "$SCRIPT_DIR/global-config/commands/"* "$TARGET_COMMANDS_DIR/"
        echo "  ✓ 自定义命令已安装到 $TARGET_COMMANDS_DIR"
        # 列出已安装的命令
        for cmd_file in "$SCRIPT_DIR/global-config/commands/"*.md; do
            if [ -f "$cmd_file" ]; then
                cmd_name=$(basename "$cmd_file" .md)
                echo "    - /$cmd_name"
            fi
        done
    fi

    # Step 6: 验证全局配置
    echo ""
    echo "[6/$TOTAL_STEPS] 验证全局配置..."

    if [ -f "$HOME/.claude/CLAUDE.md" ]; then
        echo "  ✓ CLAUDE.md 已就位"
    else
        echo "  ✗ CLAUDE.md 安装失败"
    fi

    if [ -f "$TARGET_COMMANDS_DIR/convention.md" ]; then
        echo "  ✓ /convention 命令已就位"
    else
        echo "  ⚠ /convention 命令未找到（可选）"
    fi

    # 检查 settings.json 中是否有未替换的占位符
    if grep -q '<YOUR_' "$SETTINGS_FILE" 2>/dev/null; then
        echo ""
        echo "  ⚠ settings.json 中发现未替换的占位符:"
        grep -o '<YOUR_[A-Z_]*>' "$SETTINGS_FILE" 2>/dev/null | sort -u | while read placeholder; do
            echo "    - $placeholder"
        done
        echo "  请编辑 $SETTINGS_FILE 替换为你的实际值"
    fi
fi

echo ""
echo "============================================"
echo "  安装完成！"
echo "============================================"
echo ""
echo "日志输出目录: $LOG_DIR"
echo ""
echo "重新打开 Claude Code 即可生效。"
echo "  - Stop Hook:         每次回答后自动归档当前会话"
echo "  - 惰性合并:          Stop Hook 每 30 分钟自动触发全量合并（兼容 GUI 插件）"
echo "  - SessionEnd Hook:   会话关闭时自动合并所有会话（CLI 场景）"
echo "  - 自动噪声过滤:       自动过滤 git commit agent 等内置工具产生的临时会话"
echo "  - 滚动归档:           合并文件超过 5MB 时自动按时间段切分，同一日期多次归档自动序号区分"
echo "  - 独立合并:           python3 ~/.claude/scripts/sync-session-log.py --merge-all"
echo ""
echo "输出路径:"
echo "  - 按日期: $LOG_DIR/{YYYY-MM-DD}/{project}-HHMMSS/session-log.md"
echo "  - 合并:   $LOG_DIR/merged/{project}-session-log.md"
echo "  - 归档:   $LOG_DIR/merged/{project}-session-log.{startDateTime}~{endDateTime}.md"

if [ "$INSTALL_FULL" = true ]; then
    echo ""
    echo "全局配置已安装，包含:"
    echo "  - CLAUDE.md（全局行为约定）"
    echo "  - /convention 命令"
    echo "  - 完整 settings.json 模板"
fi

echo ""
