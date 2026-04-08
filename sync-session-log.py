#!/usr/bin/env python3
"""
sync-session-log.py — Claude Code Stop Hook
Reads the current session JSONL, generates session-log.md.
Called automatically via Stop hook every time Claude finishes responding.

Usage:
  echo '{"session_id":"xxx"}' | python3 sync-session-log.py

Relies on stdin JSON from Claude Code Stop hook to get session_id,
then reads the JSONL from ~/.claude/projects/<project-key>/<session_id>.jsonl

Environment:
  CLAUDE_SESSION_LOG_DIR — override output root (default: ~/workspace/claudecode)
  CLAUDE_SESSION_LOG_TZ_OFFSET — timezone offset hours (default: 8 for UTC+8)
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict


# ── Config ──
OUTPUT_ROOT = Path(os.environ.get("CLAUDE_SESSION_LOG_DIR",
                                   os.path.expanduser("~/workspace/claudecode")))
TZ_OFFSET_HOURS = int(os.environ.get("CLAUDE_SESSION_LOG_TZ_OFFSET", "8"))
TZ_OFFSET = timedelta(hours=TZ_OFFSET_HOURS)
CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

# ── Noise filters ──
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
    stripped = text.strip()
    if len(stripped) < 2:
        return True
    for prefix in NOISE_PREFIXES:
        if stripped.startswith(prefix):
            return True
    # Generic XML/HTML system tags (but keep normal text starting with <)
    if stripped.startswith('<') and not stripped.startswith('<a ') and '>' in stripped[:80]:
        # Likely a system tag, but be conservative
        if any(stripped.startswith(f'<{tag}') for tag in
               ['system', 'command', 'local-', 'search', 'EXTREMELY', 'antml']):
            return True
    return False


def read_stdin_session_id():
    """Read session_id from stdin JSON (Claude Code Stop hook payload)."""
    try:
        data = json.loads(sys.stdin.read())
        return data.get("session_id", "")
    except (json.JSONDecodeError, EOFError):
        return ""


def find_project_dir(session_id: str) -> Optional[Path]:
    """Find the project directory containing this session JSONL."""
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
    """Extract project name from project directory name.
    e.g. '-Users-liran-workspace-IdeaProjects-gaia-gaia-product' -> 'gaia-product'
    """
    parts = proj_dir_name.strip('-').split('-')
    # Take last 1-2 meaningful segments
    if len(parts) >= 2:
        # Check if second-to-last is a common parent like 'gaia'
        return '-'.join(parts[-2:]) if parts[-2] in ('gaia',) else parts[-1]
    return parts[-1] if parts else "unknown"


def parse_session(jsonl_path: Path) -> Optional[dict]:
    """Parse a single JSONL session file into structured data."""
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

            # Always try to extract metadata
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

            # Extract text parts
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

            # Format display timestamp
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


def generate_markdown(sessions: list, project_name: str) -> str:
    """Generate merged session-log.md content."""
    from collections import defaultdict

    sessions.sort(key=lambda s: s['epoch'])

    by_date = defaultdict(list)
    for s in sessions:
        by_date[s['date']].append(s)

    total_sessions = len(sessions)
    total_messages = sum(s['msg_count'] for s in sessions)

    L = []

    # Header
    L.append(f"# {project_name} — Claude Code Session Log")
    L.append("")
    L.append(f"> Auto-generated from {total_sessions} sessions "
             f"({sessions[0]['date']} ~ {sessions[-1]['date']})")
    L.append(f"> Total dialogue rounds: {total_messages}")
    L.append(f"> Branch: `{sessions[0]['git_branch']}`")
    L.append("")

    # Table of Contents
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

    # Session Content
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

    # Footer
    now = datetime.utcnow() + TZ_OFFSET
    L.append(f"*Generated at {now.strftime('%Y-%m-%d %H:%M:%S')} "
             f"(UTC+{TZ_OFFSET_HOURS})*")

    return '\n'.join(L)


def main():
    # Read session_id from hook stdin
    session_id = read_stdin_session_id()
    if not session_id:
        # Fallback: try to find from env or args
        if len(sys.argv) > 1:
            session_id = sys.argv[1]
        else:
            sys.exit(0)  # No session_id, silently exit

    # Find project directory
    proj_dir = find_project_dir(session_id)
    if not proj_dir:
        sys.exit(0)

    project_name = extract_project_name(proj_dir.name)

    # Parse ALL sessions in this project (not just current one)
    sessions = []
    for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
        parsed = parse_session(jsonl_file)
        if parsed:
            sessions.append(parsed)

    if not sessions:
        sys.exit(0)

    # Generate markdown
    content = generate_markdown(sessions, project_name)

    # Write to date-organized directory
    # Group by date, write per-date files
    from collections import defaultdict
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

    # Also write a merged file to the output root for this project
    merged_dir = OUTPUT_ROOT / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged_file = merged_dir / f"{project_name}-session-log.md"
    with open(merged_file, 'w', encoding='utf-8') as f:
        f.write(content)

    # Output success (suppressed by hook unless error)
    print(json.dumps({"suppressOutput": True}))


if __name__ == "__main__":
    main()
