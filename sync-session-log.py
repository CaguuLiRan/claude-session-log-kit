#!/usr/bin/env python3
"""
sync-session-log.py — Claude Code Hook 脚本（Stop + SessionEnd）

三种运行模式：
  1. 归档模式（默认，Stop Hook 使用）：
     将当前会话归档到按日期组织的目录。
     如果距上次合并超过 30 分钟，同时触发惰性合并。
     echo '{"session_id":"xxx"}' | python3 sync-session-log.py

  2. 合并模式（SessionEnd Hook 使用）：
     归档当前会话 + 合并所有会话 + 滚动归档。
     echo '{"session_id":"xxx"}' | python3 sync-session-log.py --merge

  3. 独立合并模式（cron / 手动执行）：
     自动发现所有项目并合并，无需 session_id。
     python3 sync-session-log.py --merge-all

环境变量：
  CLAUDE_SESSION_LOG_DIR — 日志输出根目录（默认: ~/workspace/claudecode）
  CLAUDE_SESSION_LOG_TZ_OFFSET — 时区偏移小时数（默认: 8，即 UTC+8）
  CLAUDE_SESSION_MERGE_INTERVAL — 惰性合并间隔分钟数（默认: 30）
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict


# ── 配置 ──
OUTPUT_ROOT = Path(os.environ.get("CLAUDE_SESSION_LOG_DIR",
                                   os.path.expanduser("~/workspace/claudecode")))
TZ_OFFSET_HOURS = int(os.environ.get("CLAUDE_SESSION_LOG_TZ_OFFSET", "8"))
TZ_OFFSET = timedelta(hours=TZ_OFFSET_HOURS)
CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

DEFAULT_MAX_SIZE_MB = 5
DEFAULT_MERGE_INTERVAL_MINUTES = int(os.environ.get(
    "CLAUDE_SESSION_MERGE_INTERVAL", "30"))

# 记录上次合并时间的标记文件
MERGE_TIMESTAMP_FILE = OUTPUT_ROOT / ".last_merge_ts"

# ── 噪声过滤 ──
NOISE_PREFIXES = (
    '<command-name>',
    '<local-command',
    '<system-reminder>',
    '<EXTREMELY_IMPORTANT>',
    '<search_results>',
    '<',
    'SessionStart hook',
    'Caveat:',
)


def is_noise(text: str) -> bool:
    """判断文本是否为系统噪声（应被过滤）。"""
    stripped = text.strip()
    if len(stripped) < 2:
        return True
    for prefix in NOISE_PREFIXES:
        if stripped.startswith(prefix):
            return True
    # 通用 XML/HTML 系统标签（但保留以 < 开头的普通文本）
    if stripped.startswith('<') and not stripped.startswith('<a ') and '>' in stripped[:80]:
        if any(stripped.startswith(f'<{tag}') for tag in
               ['system', 'command', 'local-', 'search', 'EXTREMELY', 'antml']):
            return True
    return False


# ── 参数解析与输入 ──

def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="同步 Claude Code 会话日志")
    parser.add_argument('--merge', action='store_true',
                        help='合并所有会话并执行滚动归档（SessionEnd Hook 使用）')
    parser.add_argument('--merge-all', action='store_true',
                        help='自动发现所有项目并合并，无需 session_id（独立运行 / cron 使用）')
    parser.add_argument('--max-size', type=int, default=DEFAULT_MAX_SIZE_MB,
                        help=f'合并文件超过此大小（MB）时触发滚动归档（默认: {DEFAULT_MAX_SIZE_MB}）')
    parser.add_argument('--merge-interval', type=int,
                        default=DEFAULT_MERGE_INTERVAL_MINUTES,
                        help=f'惰性合并间隔（分钟），Stop Hook 超过此时间自动合并（默认: {DEFAULT_MERGE_INTERVAL_MINUTES}）')
    parser.add_argument('session_id', nargs='?', default=None,
                        help='会话 ID（stdin 未提供时的备用输入）')
    return parser.parse_args()


def read_stdin_session_id() -> str:
    """从 stdin 的 JSON 载荷中读取 session_id（Claude Code Hook 格式）。"""
    try:
        data = json.loads(sys.stdin.read())
        return data.get("session_id", "")
    except (json.JSONDecodeError, EOFError):
        return ""


def find_project_dir(session_id: str) -> Optional[Path]:
    """查找包含指定会话 JSONL 文件的项目目录。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return None
    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir() or proj_dir.name.startswith('.'):
            continue
        jsonl_file = proj_dir / f"{session_id}.jsonl"
        if jsonl_file.exists():
            return proj_dir
    return None


def extract_project_name(proj_dir_name: str) -> str:
    """从项目目录名中提取项目名称。
    例如: '-Users-liran-workspace-IdeaProjects-gaia-gaia-product' -> 'gaia-product'
    """
    parts = proj_dir_name.strip('-').split('-')
    if len(parts) >= 2:
        return '-'.join(parts[-2:]) if parts[-2] in ('gaia',) else parts[-1]
    return parts[-1] if parts else "unknown"


# ── 会话解析 ──

def parse_session(jsonl_path: Path) -> Optional[dict]:
    """将单个 JSONL 会话文件解析为结构化数据。"""
    messages = []
    session_start_ts = None
    git_branch = None

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get('type', '')
            if msg_type not in ('user', 'assistant'):
                continue

            is_meta = obj.get('isMeta', False)
            ts_str = obj.get('timestamp', '')

            if not git_branch:
                git_branch = obj.get('gitBranch', '')
            if ts_str and not session_start_ts:
                try:
                    session_start_ts = datetime.fromisoformat(
                        ts_str.replace('Z', '+00:00'))
                except ValueError:
                    pass

            if is_meta:
                continue

            role = obj.get('message', {}).get('role', '')
            content = obj.get('message', {}).get('content', '')

            text_parts = []
            if isinstance(content, str):
                if not is_noise(content):
                    text_parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        t = item['text']
                        if not is_noise(t):
                            text_parts.append(t)

            if not text_parts:
                continue

            combined = '\n'.join(text_parts).strip()
            if not combined:
                continue

            display_ts = ''
            if ts_str:
                try:
                    utc = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    local = utc + TZ_OFFSET
                    display_ts = local.strftime('%H:%M:%S')
                except ValueError:
                    pass

            messages.append({
                'role': role,
                'content': combined,
                'display_ts': display_ts,
            })

    if not messages or not session_start_ts:
        return None

    local_ts = session_start_ts + TZ_OFFSET
    return {
        'session_id': jsonl_path.stem,
        'date': local_ts.strftime('%Y-%m-%d'),
        'start_time': local_ts.strftime('%H:%M:%S'),
        'epoch': int(local_ts.timestamp()),
        'git_branch': git_branch or 'unknown',
        'messages': messages,
        'msg_count': len(messages),
    }


# ── Markdown 生成 ──

def generate_markdown(sessions: list, project_name: str) -> str:
    """根据解析后的会话列表生成 session-log.md 内容。"""
    sessions.sort(key=lambda s: s['epoch'])

    by_date = defaultdict(list)
    for s in sessions:
        by_date[s['date']].append(s)

    total_sessions = len(sessions)
    total_messages = sum(s['msg_count'] for s in sessions)

    L = []

    # 文件头
    L.append(f"# {project_name} — Claude Code Session Log")
    L.append("")
    L.append(f"> Auto-generated from {total_sessions} sessions "
             f"({sessions[0]['date']} ~ {sessions[-1]['date']})")
    L.append(f"> Total dialogue rounds: {total_messages}")
    L.append(f"> Branch: `{sessions[0]['git_branch']}`")
    L.append("")

    # 目录索引
    L.append("## Table of Contents")
    L.append("")
    global_idx = 0
    for date_str in sorted(by_date.keys()):
        date_sessions = by_date[date_str]
        L.append(f"### {date_str} ({len(date_sessions)} sessions)")
        L.append("")
        for s in date_sessions:
            global_idx += 1
            first_msg = ""
            for m in s['messages']:
                if m['role'] == 'user':
                    first_msg = m['content'][:60].replace('\n', ' ')
                    break
            L.append(f"- [{global_idx}. {s['start_time']}]"
                     f"(#session-{global_idx}) — {first_msg}...")
        L.append("")

    L.append("---")
    L.append("")

    # 会话正文
    global_idx = 0
    for date_str in sorted(by_date.keys()):
        date_sessions = by_date[date_str]
        L.append(f"# {date_str}")
        L.append("")

        for s in date_sessions:
            global_idx += 1
            anchor = f'<a id="session-{global_idx}"></a>'

            L.append(f"## {anchor}Session {global_idx} — "
                     f"{date_str} {s['start_time']}")
            L.append("")
            L.append("| Key | Value |")
            L.append("|-----|-------|")
            L.append(f"| Session ID | `{s['session_id']}` |")
            L.append(f"| Branch | `{s['git_branch']}` |")
            L.append(f"| Messages | {s['msg_count']} |")
            L.append("")

            for msg in s['messages']:
                role_label = "User" if msg['role'] == 'user' else "Assistant"
                ts_label = f" `{msg['display_ts']}`" if msg['display_ts'] else ""
                L.append(f"### {role_label}{ts_label}")
                L.append("")
                L.append(msg['content'])
                L.append("")

            L.append("---")
            L.append("")

    # 页脚
    now = datetime.utcnow() + TZ_OFFSET
    L.append(f"*Generated at {now.strftime('%Y-%m-%d %H:%M:%S')} "
             f"(UTC+{TZ_OFFSET_HOURS})*")

    return '\n'.join(L)


# ── 归档：将单个会话写入按日期组织的目录 ──

def archive_current_session(session_id: str, proj_dir: Path, project_name: str):
    """将单个会话的 JSONL 归档为按日期组织的 Markdown 文件。"""
    jsonl_file = proj_dir / f"{session_id}.jsonl"
    if not jsonl_file.exists():
        return

    parsed = parse_session(jsonl_file)
    if not parsed:
        return

    # 写入按日期组织的目录
    dir_name = f"{project_name}-{parsed['epoch']}"
    out_dir = OUTPUT_ROOT / parsed['date'] / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    content = generate_markdown([parsed], project_name)
    out_file = out_dir / "session-log.md"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)


# ── 合并：将所有会话合并为单个文件 ──

def merge_all_sessions(proj_dir: Path, project_name: str):
    """将项目中的所有会话合并为单个 Markdown 文件。"""
    sessions = []
    for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
        parsed = parse_session(jsonl_file)
        if parsed:
            sessions.append(parsed)

    if not sessions:
        return sessions

    # 同时将每个会话归档到对应日期目录（幂等操作）
    by_date = defaultdict(list)
    for s in sessions:
        by_date[s['date']].append(s)

    for date_str in sorted(by_date.keys()):
        date_sessions = by_date[date_str]
        first_epoch = date_sessions[0]['epoch']
        dir_name = f"{project_name}-{first_epoch}"
        out_dir = OUTPUT_ROOT / date_str / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)

        date_content = generate_markdown(date_sessions, project_name)
        out_file = out_dir / "session-log.md"
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(date_content)

    # 写入合并文件
    content = generate_markdown(sessions, project_name)
    merged_dir = OUTPUT_ROOT / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged_file = merged_dir / f"{project_name}-session-log.md"
    with open(merged_file, 'w', encoding='utf-8') as f:
        f.write(content)

    return sessions


# ── 惰性合并与独立合并 ──

def should_lazy_merge(interval_minutes: int) -> bool:
    """检查距上次合并是否已超过指定间隔，决定是否触发惰性合并。"""
    if not MERGE_TIMESTAMP_FILE.exists():
        return True  # 从未合并过
    try:
        last_ts = float(MERGE_TIMESTAMP_FILE.read_text().strip())
        elapsed_minutes = (time.time() - last_ts) / 60
        return elapsed_minutes >= interval_minutes
    except (ValueError, OSError):
        return True  # 文件损坏或不可读，触发合并


def update_merge_timestamp():
    """将当前时间记录为上次合并时间戳。"""
    MERGE_TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MERGE_TIMESTAMP_FILE.write_text(str(time.time()))


def merge_all_projects(max_size_mb: int):
    """自动发现所有项目并逐一合并。用于独立运行或 cron 定时任务。"""
    if not CLAUDE_PROJECTS_DIR.exists():
        return
    for proj_dir in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith('.'):
            continue
        # 跳过没有 JSONL 文件的目录
        jsonl_files = list(proj_dir.glob("*.jsonl"))
        if not jsonl_files:
            continue
        project_name = extract_project_name(proj_dir.name)
        sessions = merge_all_sessions(proj_dir, project_name)
        if sessions:
            rotate_if_needed(project_name, max_size_mb, sessions)
    update_merge_timestamp()


# ── 滚动归档：合并文件超限时自动切分 ──

def rotate_if_needed(project_name: str, max_size_mb: int,
                     sessions: Optional[List[dict]] = None):
    """当合并文件超过 max_size_mb 时，将旧会话切分为独立归档文件。

    策略：按时间范围切分
      merged/
        {project}-session-log.md                              # 最新（始终存在）
        {project}-session-log.{startDate}~{endDate}.md        # 归档分片
    """
    merged_dir = OUTPUT_ROOT / "merged"
    merged_file = merged_dir / f"{project_name}-session-log.md"

    if not merged_file.exists():
        return

    max_size_bytes = max_size_mb * 1024 * 1024
    file_size = merged_file.stat().st_size

    if file_size <= max_size_bytes:
        return  # 无需滚动归档

    # 需要已解析的会话数据来执行切分
    if sessions is None:
        # 从合并文件反向读取不现实，需要原始会话数据
        # 此回退路径极少触发，因为 merge_all_sessions 会返回会话列表
        return

    if len(sessions) <= 1:
        return  # 单个会话无法切分

    sessions.sort(key=lambda s: s['epoch'])

    # 确定需要归档多少会话：
    # 从末尾开始逐步减少会话数量生成 Markdown，
    # 直到剩余文件大小在限制以内。
    # 优先保留最新的会话在主文件中。

    # 查找切分点：sessions[split_point:] 生成的内容 <= max_size_bytes
    split_point = _find_split_point(sessions, project_name, max_size_bytes)

    if split_point <= 0:
        return  # 无需归档

    # 待归档的会话：sessions[:split_point]
    archive_sessions = sessions[:split_point]
    remaining_sessions = sessions[split_point:]

    if not remaining_sessions:
        return  # 不能归档全部会话

    # 生成归档文件
    start_date = archive_sessions[0]['date']
    end_date = archive_sessions[-1]['date']
    archive_filename = f"{project_name}-session-log.{start_date}~{end_date}.md"
    archive_path = merged_dir / archive_filename

    # 如果归档文件已存在（时间范围重叠），追加序号后缀
    if archive_path.exists():
        counter = 1
        while archive_path.exists():
            archive_filename = (f"{project_name}-session-log."
                                f"{start_date}~{end_date}.{counter}.md")
            archive_path = merged_dir / archive_filename
            counter += 1

    archive_content = generate_markdown(archive_sessions, project_name)
    with open(archive_path, 'w', encoding='utf-8') as f:
        f.write(archive_content)

    # 用剩余会话重写主合并文件
    remaining_content = generate_markdown(remaining_sessions, project_name)
    with open(merged_file, 'w', encoding='utf-8') as f:
        f.write(remaining_content)


def _find_split_point(sessions: list, project_name: str,
                      max_size_bytes: int) -> int:
    """查找切分点，使 sessions[index:] 生成的 Markdown 大小 <= max_size_bytes。

    使用从前向后的线性扫描 —— 逐个移出会话，直到剩余集合足够小。
    """
    total = len(sessions)

    for i in range(1, total):
        remaining = sessions[i:]
        content = generate_markdown(remaining, project_name)
        if len(content.encode('utf-8')) <= max_size_bytes:
            return i

    # 即使单个会话也超限，归档除最后一个以外的所有会话
    return total - 1


# ── 主入口 ──

def main():
    args = parse_args()

    # 模式 3：独立合并所有项目（无需 session_id）
    if args.merge_all:
        merge_all_projects(args.max_size)
        print(json.dumps({"suppressOutput": True}))
        return

    # 从 stdin 读取 session_id（Hook 载荷）
    session_id = read_stdin_session_id()
    if not session_id:
        # 备用：尝试从命令行参数获取
        if args.session_id:
            session_id = args.session_id
        else:
            sys.exit(0)  # 无 session_id，静默退出

    # 查找项目目录
    proj_dir = find_project_dir(session_id)
    if not proj_dir:
        sys.exit(0)

    project_name = extract_project_name(proj_dir.name)

    # 始终归档当前会话
    archive_current_session(session_id, proj_dir, project_name)

    # 判断是否需要合并：
    #   --merge 标志（显式 SessionEnd）→ 始终合并
    #   否则（Stop Hook）→ 超过间隔时惰性合并
    do_merge = args.merge or should_lazy_merge(args.merge_interval)

    if do_merge:
        sessions = merge_all_sessions(proj_dir, project_name)
        if sessions:
            rotate_if_needed(project_name, args.max_size, sessions)
        update_merge_timestamp()

    # 输出成功标记（Hook 模式下被静默）
    print(json.dumps({"suppressOutput": True}))


if __name__ == "__main__":
    main()
