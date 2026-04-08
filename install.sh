#!/bin/bash
# Claude Code 会话日志自动记录 - 一键安装脚本
# 用法: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_SCRIPT_DIR="$HOME/.claude/scripts"
SETTINGS_FILE="$HOME/.claude/settings.json"
LOG_DIR="${CLAUDE_SESSION_LOG_DIR:-$HOME/workspace/claudecode}"

echo "=========================================="
echo "  Claude Code 会话日志 - 一键安装"
echo "=========================================="
echo ""

# 1. 创建目录
echo "[1/4] 创建必要目录..."
mkdir -p "$TARGET_SCRIPT_DIR"
mkdir -p "$LOG_DIR/merged"
echo "  ✓ $TARGET_SCRIPT_DIR"
echo "  ✓ $LOG_DIR/merged"

# 2. 复制脚本
echo ""
echo "[2/4] 安装同步脚本..."
cp "$SCRIPT_DIR/sync-session-log.py" "$TARGET_SCRIPT_DIR/sync-session-log.py"
chmod +x "$TARGET_SCRIPT_DIR/sync-session-log.py"
echo "  ✓ $TARGET_SCRIPT_DIR/sync-session-log.py"

# 3. 配置 settings.json
echo ""
echo "[3/4] 配置 Stop Hook..."

if [ ! -f "$SETTINGS_FILE" ]; then
    # 没有 settings.json，直接用模板
    cp "$SCRIPT_DIR/settings-hook-only.json" "$SETTINGS_FILE"
    echo "  ✓ 创建新的 $SETTINGS_FILE"
else
    # 已有 settings.json，检查是否已配置
    if python3 -c "
import json, sys
with open('$SETTINGS_FILE') as f:
    data = json.load(f)
hooks = data.get('hooks', {}).get('Stop', [])
for hook_group in hooks:
    for h in hook_group.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
        echo "  ✓ Stop Hook 已存在，跳过"
    else
        # 合并 Hook 配置
        python3 -c "
import json

with open('$SETTINGS_FILE') as f:
    data = json.load(f)

new_hook = {
    'hooks': [{
        'type': 'command',
        'command': 'python3 ~/.claude/scripts/sync-session-log.py',
        'timeout': 30,
        'statusMessage': 'Syncing session log...'
    }]
}

if 'hooks' not in data:
    data['hooks'] = {}
if 'Stop' not in data['hooks']:
    data['hooks']['Stop'] = []

data['hooks']['Stop'].append(new_hook)

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
"
        echo "  ✓ 已将 Stop Hook 合并到 $SETTINGS_FILE"
    fi
fi

# 4. 验证
echo ""
echo "[4/4] 验证安装..."

if [ -f "$TARGET_SCRIPT_DIR/sync-session-log.py" ]; then
    echo "  ✓ 脚本已就位"
else
    echo "  ✗ 脚本安装失败！"
    exit 1
fi

if python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    data = json.load(f)
found = False
for hook_group in data.get('hooks', {}).get('Stop', []):
    for h in hook_group.get('hooks', []):
        if 'sync-session-log' in h.get('command', ''):
            found = True
if not found:
    raise Exception('Hook not found')
" 2>/dev/null; then
    echo "  ✓ Stop Hook 已配置"
else
    echo "  ✗ Stop Hook 配置异常！请手动检查 $SETTINGS_FILE"
    exit 1
fi

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "日志输出目录: $LOG_DIR"
echo ""
echo "重新打开 Claude Code 即可生效。"
echo "每次 Claude 回答后，会话日志将自动同步到:"
echo "  - 按日期: $LOG_DIR/{YYYY-MM-DD}/{project}/session-log.md"
echo "  - 全量:   $LOG_DIR/merged/{project}-session-log.md"
echo ""
