#!/usr/bin/env python3
"""
copilot-api-auth
1. 启动 npx @jeffreycao/copilot-api@latest start
2. 监听输出，提取 GitHub device 验证码
3. 自动打开浏览器 + 复制验证码到剪贴板
4. 等待 github_token 文件生成
5. 将 token 写入 Claude Code settings.json 的 env.ANTHROPIC_AUTH_TOKEN

跨平台支持：macOS / Windows / Linux
"""

import subprocess
import re
import json
import os
import sys
import threading
import time
import platform
import webbrowser
from pathlib import Path


# ── 平台检测 ──────────────────────────────────────────────────────────────────

SYSTEM = platform.system()  # "Darwin" | "Windows" | "Linux"


def get_token_file() -> Path:
    """返回 copilot-api 存放 github_token 的路径（跨平台）"""
    home = Path.home()
    if SYSTEM == "Windows":
        local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return local_appdata / "copilot-api" / "github_token"
    else:  # macOS / Linux
        return home / ".local" / "share" / "copilot-api" / "github_token"


def find_claude_settings() -> Path:
    """
    按优先级检测 Claude Code settings.json 的实际位置。
    若均不存在则返回默认路径（文件可能尚未创建）。
    """
    home = Path.home()

    if SYSTEM == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = [
            appdata / "Claude" / "settings.json",          # 最常见
            local_appdata / "Claude" / "settings.json",
            home / ".claude" / "settings.json",             # WSL 兼容路径
        ]
    else:  # macOS / Linux
        candidates = [
            home / ".claude" / "settings.json",
        ]

    for path in candidates:
        if path.exists():
            return path

    # 文件不存在时返回默认路径，后续写入时会自动创建
    return candidates[0]


def copy_to_clipboard(text: str):
    """跨平台复制到剪贴板"""
    try:
        if SYSTEM == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif SYSTEM == "Windows":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        else:  # Linux：优先 xclip，回退 xsel
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(), check=True
                )
            except FileNotFoundError:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode(), check=True
                )
        print(f"[auto] 验证码已复制到剪贴板: {text}")
    except Exception as e:
        print(f"[auto] 复制剪贴板失败（可手动粘贴）: {e}")


def open_browser(url: str):
    try:
        webbrowser.open(url)
        print(f"[auto] 已打开浏览器: {url}")
    except Exception as e:
        print(f"[auto] 打开浏览器失败: {e}")


# ── Settings 写入 ─────────────────────────────────────────────────────────────

def update_settings(token: str, settings_file: Path):
    token = token.strip()
    if not token:
        print("[auto] token 为空，跳过写入")
        return

    settings = {}
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[auto] 读取 settings.json 失败: {e}")
            return
    else:
        # 文件不存在时自动创建父目录
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"[auto] settings.json 不存在，将自动创建: {settings_file}")

    if "env" not in settings:
        settings["env"] = {}

    old_token = settings["env"].get("ANTHROPIC_AUTH_TOKEN", "")
    settings["env"]["ANTHROPIC_AUTH_TOKEN"] = token

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if old_token != token:
        print(f"[auto] ✓ ANTHROPIC_AUTH_TOKEN 已更新 -> {token[:8]}...{token[-4:]}")
    else:
        print(f"[auto] ✓ ANTHROPIC_AUTH_TOKEN 无变化，保持: {token[:8]}...{token[-4:]}")


# ── Token 监控 ────────────────────────────────────────────────────────────────

def watch_token_file(token_file: Path, settings_file: Path, stop_event: threading.Event):
    """监控 token 文件，出现或更新后写入 settings.json"""
    prev_token = token_file.read_text().strip() if token_file.exists() else None
    print(f"[auto] 等待 token 文件: {token_file}")

    while not stop_event.is_set():
        if token_file.exists():
            token = token_file.read_text().strip()
            if token and token != prev_token:
                prev_token = token
                update_settings(token, settings_file)
                print("[auto] Token 同步完成，继续运行服务...")
        time.sleep(2)


# ── 主流程 ────────────────────────────────────────────────────────────────────

# 匹配格式: Please enter the code "F55B-7C37" in https://github.com/login/device
CODE_PATTERN = re.compile(
    r'Please enter the code\s+"([A-Z0-9]{4}-[A-Z0-9]{4})"\s+in\s+(https://\S+)'
)


def main():
    token_file = get_token_file()
    settings_file = find_claude_settings()

    extra_args = sys.argv[1:]
    cmd = ["npx", "@jeffreycao/copilot-api@latest", "start"] + extra_args

    print(f"[auto] 平台: {SYSTEM}")
    print(f"[auto] 启动: {' '.join(cmd)}")
    print(f"[auto] Token 文件: {token_file}")
    print(f"[auto] Settings:   {settings_file}\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    stop_event = threading.Event()
    token_thread = threading.Thread(
        target=watch_token_file,
        args=(token_file, settings_file, stop_event),
        daemon=True,
    )
    token_thread.start()

    code_handled = False

    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

            if not code_handled:
                match = CODE_PATTERN.search(line)
                if match:
                    code = match.group(1)
                    url = match.group(2).rstrip("\"'.,")
                    code_handled = True
                    print()
                    copy_to_clipboard(code)
                    open_browser(url)
                    print()
    except KeyboardInterrupt:
        print("\n[auto] 收到中断信号，退出...")
    finally:
        stop_event.set()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
