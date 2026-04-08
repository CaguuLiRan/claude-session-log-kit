#!/usr/bin/env python3
"""
sync-session-log.py — Claude Code Hook Script (Stop + SessionEnd)

Two modes:
  1. Archive mode (default, Stop hook):
     Only archives the current session to date-organized directory.
     echo '{"session_id":"xxx"}' | python3 sync-session-log.py

  2. Merge mode (SessionEnd hook):
     Archives current session + merges ALL sessions + rolling archive.
     echo '{"session_id":"xxx"}' | python3 sync-session-log.py --merge

Environment:
  CLAUDE_SESSION_LOG_DIR — override output root (default: ~/workspace/claudecode)
  CLAUDE_SESSION_LOG_TZ_OFFSET — timezone offset hours (default: 8 for UTC+8)
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict


# ── Config ──
OUTPUT_ROOT = Path(os.environ.get("CLAUDE_SESSION_LOG_DIR",
                                   os.path.expanduser("~/workspace/claudecode")))
TZ_OFFSET_HOURS = int(os.environ.get("CLAUDE_SESSION_LOG_TZ_OFFSET", "8"))
TZ_OFFSET = timedelta(hours=TZ_OFFSET_HOURS)
CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

DEFAULT_MAX_SIZE_MB = 5

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
        if any(stripped.startswith(f'<{tag}') for tag in
               ['system', 'command', 'local-', 'search', 'EXTREMELY', 'antml']):
            return True
    return False


# ── Args & Input ──

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Sync Claude Code session logs")
    parser.add_argument('--merge', action='store_true',
                        help='Merge all sessions and perform rolling archive (SessionEnd)')
    parser.add_argument('--max-size', type=int, default=DEFAULT_MAX_SIZE_MB,
                        help=f'Max merged file size in MB before rotation (default: {DEFAULT_MAX_SIZE_MB})')
    parser.add_argument('session_id', nargs='?', default=None,
                        help='Session ID (fallback if not provided via stdin)')
    return parser.parse_args()


def read_stdin_session_id() -> str:
    """Read session_id from stdin JSON (Claude Code hook payload)."""
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
    if len(parts) >= 2:
        return '-'.join(parts[-2:]) if parts[-2] in ('gaia',) else parts[-1]
    return parts[-1] if parts else "unknown"


# ── Session Parsing ──

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


# ── Markdown Generation ──

def generate_markdown(sessions: list, project_name: str) -> str:
    """Generate session-log.md content from a list of parsed sessions."""
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


# ── Archive: single session to date directory ──

def archive_current_session(session_id: str, proj_dir: Path, project_name: str):
    """Archive a single session's JSONL to date-organized markdown."""
    jsonl_file = proj_dir / f"{session_id}.jsonl"
    if not jsonl_file.exists():
        return

    parsed = parse_session(jsonl_file)
    if not parsed:
        return

    # Write to date directory
    dir_name = f"{project_name}-{parsed['epoch']}"
    out_dir = OUTPUT_ROOT / parsed['date'] / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    content = generate_markdown([parsed], project_name)
    out_file = out_dir / "session-log.md"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)


# ── Merge: all sessions into one file ──

def merge_all_sessions(proj_dir: Path, project_name: str):
    """Merge all sessions in the project into a single merged file."""
    sessions = []
    for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
        parsed = parse_session(jsonl_file)
        if parsed:
            sessions.append(parsed)

    if not sessions:
        return sessions

    # Also archive each session to its date directory (idempotent)
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

    # Write merged file
    content = generate_markdown(sessions, project_name)
    merged_dir = OUTPUT_ROOT / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged_file = merged_dir / f"{project_name}-session-log.md"
    with open(merged_file, 'w', encoding='utf-8') as f:
        f.write(content)

    return sessions


# ── Rolling archive: split if merged file exceeds max size ──

def rotate_if_needed(project_name: str, max_size_mb: int,
                     sessions: Optional[List[dict]] = None):
    """If merged file exceeds max_size_mb, split old sessions into archive files.

    Strategy: time-range splitting
      merged/
        {project}-session-log.md                              # latest (always exists)
        {project}-session-log.{startDate}~{endDate}.md        # archived chunk
    """
    merged_dir = OUTPUT_ROOT / "merged"
    merged_file = merged_dir / f"{project_name}-session-log.md"

    if not merged_file.exists():
        return

    max_size_bytes = max_size_mb * 1024 * 1024
    file_size = merged_file.stat().st_size

    if file_size <= max_size_bytes:
        return  # No rotation needed

    # We need the parsed sessions to split them
    if sessions is None:
        # Re-read from merged file is not practical; we need the raw sessions.
        # This fallback should rarely happen since merge_all_sessions returns them.
        return

    if len(sessions) <= 1:
        return  # Can't split a single session

    sessions.sort(key=lambda s: s['epoch'])

    # Determine how many sessions to archive:
    # Generate markdown for progressively fewer sessions (from the end)
    # until the remaining file is under the limit.
    # We try to keep the latest sessions in the main file.

    # First, figure out how much to move out.
    # Strategy: binary-search-ish — find the split point where
    # sessions[split_point:] generates content ≤ max_size_bytes
    split_point = _find_split_point(sessions, project_name, max_size_bytes)

    if split_point <= 0:
        return  # Nothing to archive

    # Sessions to archive: sessions[:split_point]
    archive_sessions = sessions[:split_point]
    remaining_sessions = sessions[split_point:]

    if not remaining_sessions:
        return  # Don't archive everything

    # Generate archive file
    start_date = archive_sessions[0]['date']
    end_date = archive_sessions[-1]['date']
    archive_filename = f"{project_name}-session-log.{start_date}~{end_date}.md"
    archive_path = merged_dir / archive_filename

    # If archive file already exists (overlapping range), append a counter
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

    # Rewrite the main merged file with only remaining sessions
    remaining_content = generate_markdown(remaining_sessions, project_name)
    with open(merged_file, 'w', encoding='utf-8') as f:
        f.write(remaining_content)


def _find_split_point(sessions: list, project_name: str,
                      max_size_bytes: int) -> int:
    """Find the index where sessions[index:] generates markdown ≤ max_size_bytes.

    Uses a simple linear scan from the front — we move sessions out one-by-one
    until the remaining set is small enough.
    """
    total = len(sessions)

    for i in range(1, total):
        remaining = sessions[i:]
        content = generate_markdown(remaining, project_name)
        if len(content.encode('utf-8')) <= max_size_bytes:
            return i

    # If even a single session is too large, archive all but the last
    return total - 1


# ── Main ──

def main():
    args = parse_args()

    # Read session_id from stdin (hook payload)
    session_id = read_stdin_session_id()
    if not session_id:
        # Fallback: try from command line arg
        if args.session_id:
            session_id = args.session_id
        else:
            sys.exit(0)  # No session_id, silently exit

    # Find project directory
    proj_dir = find_project_dir(session_id)
    if not proj_dir:
        sys.exit(0)

    project_name = extract_project_name(proj_dir.name)

    # Always archive the current session
    archive_current_session(session_id, proj_dir, project_name)

    # Only merge + rotate when --merge is specified (SessionEnd hook)
    if args.merge:
        sessions = merge_all_sessions(proj_dir, project_name)
        if sessions:
            rotate_if_needed(project_name, args.max_size, sessions)

    # Output success (suppressed by hook unless error)
    print(json.dumps({"suppressOutput": True}))


if __name__ == "__main__":
    main()
