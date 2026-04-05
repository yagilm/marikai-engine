#!/usr/bin/env python3
"""Ollama session runner for Marikai.

Implements a tool-use agentic loop against any Ollama-hosted model,
outputting claude-compatible stream-json so live-display.py, process-transcript.sh,
and extract-log-entry.py all work unchanged.

Usage (mirrors the claude CLI flags wake.sh uses):
    python3 ollama-session.py \
        --model llama3.1 \
        --max-turns 30 \
        --add-dir /path/to/brain \
        --base-url http://localhost:11434/v1 \
        -p "wake prompt text"
"""

from __future__ import annotations

import argparse
import glob as glob_module
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# ── Stream-json emitters ──────────────────────────────────────────────────────

def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def emit_system(session_id: str) -> None:
    _emit({"type": "system", "session_id": session_id, "tools": []})


def emit_assistant_text(text: str) -> None:
    _emit({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    })


def emit_assistant_tool(name: str, tool_id: str, inp: dict) -> None:
    _emit({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}],
        },
    })


def emit_user_tool_result(tool_id: str, content: str) -> None:
    _emit({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}],
        },
    })


def emit_result(session_id: str, num_turns: int, duration_ms: int,
                final_text: str, subtype: str = "success") -> None:
    _emit({
        "type": "result",
        "subtype": subtype,
        "session_id": session_id,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
        "total_cost_usd": 0.0,
        "result": final_text,
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    })


# ── Tool implementations ──────────────────────────────────────────────────────

def _read_lines(path: Path, offset: int | None, limit: int | None) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return f"Error: {e}"
    start = max(0, (offset - 1) if offset else 0)
    end = (start + limit) if limit else None
    slice_ = lines[start:end]
    return "\n".join(f"{i + start + 1}\t{line}" for i, line in enumerate(slice_))


def tool_read(file_path: str, offset: int | None = None, limit: int | None = None) -> str:
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"
    if path.is_dir():
        return f"Error: {file_path} is a directory, not a file"
    return _read_lines(path, offset, limit) or "(empty file)"


def tool_write(file_path: str, content: str) -> str:
    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written {len(content)} characters to {file_path}"
    except OSError as e:
        return f"Error: {e}"


def tool_edit(file_path: str, old_string: str, new_string: str,
              replace_all: bool = False) -> str:
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error: {e}"
    if old_string not in content:
        return f"Error: old_string not found in {file_path}"
    count = content.count(old_string)
    if count > 1 and not replace_all:
        return (f"Error: old_string appears {count} times. "
                "Provide more context to make it unique, or set replace_all=true.")
    new_content = content.replace(old_string, new_string) if replace_all \
        else content.replace(old_string, new_string, 1)
    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as e:
        return f"Error: {e}"
    return f"Edited {file_path}"


def tool_glob(pattern: str, path: str | None = None) -> str:
    base = path or os.getcwd()
    full_pattern = os.path.join(base, pattern) if not os.path.isabs(pattern) else pattern
    matches = glob_module.glob(full_pattern, recursive=True)
    matches.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
    return "\n".join(matches) if matches else "(no matches)"


def tool_grep(pattern: str, path: str | None = None,
              glob: str | None = None,
              output_mode: str = "files_with_matches",
              context: int = 0,
              case_insensitive: bool = False) -> str:
    cmd = ["grep", "-r", "-E"]
    if case_insensitive:
        cmd.append("-i")
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:  # content
        cmd.append("-n")
        if context:
            cmd.extend(["-C", str(context)])
    if glob:
        cmd.extend(["--include", glob])
    cmd.append(pattern)
    cmd.append(path or ".")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        return out if out else "(no matches)"
    except subprocess.TimeoutExpired:
        return "Error: grep timed out"
    except FileNotFoundError:
        return "Error: grep not found"


def tool_bash(command: str, add_dir: str | None = None) -> str:
    cwd = add_dir or os.getcwd()
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=120, cwd=cwd,
        )
        out = result.stdout
        if result.stderr:
            out += ("\n" if out else "") + result.stderr
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"


def tool_web_fetch(url: str, max_chars: int = 8000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip HTML tags for a plain-text view
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except urllib.error.URLError as e:
        return f"Error fetching {url}: {e}"


def tool_web_search(query: str, api_key: str | None = None) -> str:
    if not api_key:
        return "Error: LANGSEARCH_API_KEY not set. Web search unavailable."
    payload = json.dumps({"query": query, "summary": True}).encode()
    req = urllib.request.Request(
        "https://api.langsearch.com/v1/web-search",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        results = data.get("data", {}).get("webPages", {}).get("value", [])
        lines = []
        for r in results[:5]:
            lines.append(f"**{r.get('name', '')}**\n{r.get('url', '')}\n{r.get('snippet', '')}")
        return "\n\n".join(lines) if lines else "(no results)"
    except Exception as e:
        return f"Error: {e}"


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file from the local filesystem. Returns file content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "offset": {"type": "integer", "description": "Line number to start from (1-based)"},
                    "limit": {"type": "integer", "description": "Max lines to read"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file, creating it if needed. Overwrites existing content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Make a targeted edit to a file by replacing an exact string. old_string must be unique in the file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "old_string": {"type": "string", "description": "Exact text to find and replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a glob pattern. Returns matching paths sorted by modification time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern e.g. '**/*.md'"},
                    "path": {"type": "string", "description": "Base directory to search in"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search file contents using regex. Returns matching files or lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search"},
                    "glob": {"type": "string", "description": "File glob filter e.g. '*.md'"},
                    "output_mode": {
                        "type": "string",
                        "enum": ["files_with_matches", "content", "count"],
                        "description": "Output format (default: files_with_matches)",
                    },
                    "context": {"type": "integer", "description": "Lines of context around matches"},
                    "case_insensitive": {"type": "boolean", "description": "Case-insensitive search"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a shell command. Use sparingly for operations not covered by other tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "WebFetch",
            "description": "Fetch and return the text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "WebSearch",
            "description": "Search the web using LangSearch. Returns top results with snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
]


# ── Ollama API call ───────────────────────────────────────────────────────────

def call_ollama(base_url: str, model: str, messages: list[dict],
                tools: list[dict]) -> dict:
    """Call the Ollama OpenAI-compatible chat completions endpoint."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)
    except urllib.error.URLError as e:
        sys.stderr.write(f"Ollama API error: {e}\n")
        raise


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch_tool(name: str, inp: dict, add_dir: str | None,
                  langsearch_key: str | None) -> str:
    try:
        if name == "Read":
            return tool_read(inp["file_path"], inp.get("offset"), inp.get("limit"))
        if name == "Write":
            return tool_write(inp["file_path"], inp["content"])
        if name == "Edit":
            return tool_edit(inp["file_path"], inp["old_string"], inp["new_string"],
                             inp.get("replace_all", False))
        if name == "Glob":
            return tool_glob(inp["pattern"], inp.get("path") or add_dir)
        if name == "Grep":
            return tool_grep(
                inp["pattern"],
                path=inp.get("path") or add_dir,
                glob=inp.get("glob"),
                output_mode=inp.get("output_mode", "files_with_matches"),
                context=int(inp.get("context", 0)),
                case_insensitive=bool(inp.get("case_insensitive", False)),
            )
        if name == "Bash":
            return tool_bash(inp["command"], add_dir)
        if name == "WebFetch":
            return tool_web_fetch(inp["url"])
        if name == "WebSearch":
            return tool_web_search(inp["query"], langsearch_key)
        return f"Error: unknown tool '{name}'"
    except KeyError as e:
        return f"Error: missing required parameter {e}"
    except Exception as e:
        return f"Error: {e}"


# ── Main agentic loop ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an AI assistant with direct access to the local filesystem. \
Use the provided tools to read, write, and modify files, run commands, and search through directories. \
Think step by step. After completing all your work, write a brief summary of what you did this session.\
"""


def run(args: argparse.Namespace) -> None:
    session_id = str(uuid.uuid4())
    start_time = time.time()

    emit_system(session_id)

    # Build system message with directory context
    system_content = SYSTEM_PROMPT
    if args.add_dir:
        system_content += f"\n\nYour primary working directory is: {args.add_dir}"

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": args.prompt},
    ]

    langsearch_key = os.environ.get("LANGSEARCH_API_KEY")
    num_turns = 0
    final_text = ""
    subtype = "success"

    for turn in range(args.max_turns):
        num_turns = turn + 1

        try:
            response = call_ollama(args.base_url, args.model, messages, TOOL_DEFINITIONS)
        except Exception as e:
            sys.stderr.write(f"Fatal API error on turn {num_turns}: {e}\n")
            subtype = "error_api"
            break

        choice = response.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "stop")
        text_content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        # Emit text if present
        if text_content:
            emit_assistant_text(text_content)
            final_text = text_content

        # Emit tool calls
        for tc in tool_calls:
            tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                tool_input = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_input = {}
            emit_assistant_tool(tool_name, tc_id, tool_input)

        # Add assistant turn to messages
        assistant_msg: dict = {"role": "assistant"}
        if text_content:
            assistant_msg["content"] = text_content
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # No tool calls → done
        if not tool_calls:
            break

        # Execute tools and add results
        tool_results = []
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                tool_input = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_input = {}
            result = dispatch_tool(tool_name, tool_input, args.add_dir, langsearch_key)
            emit_user_tool_result(tc_id, result)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })

        messages.extend(tool_results)

        if finish_reason == "stop" and not tool_calls:
            break
    else:
        # Hit max_turns
        subtype = "error_max_turns"

    duration_ms = int((time.time() - start_time) * 1000)
    emit_result(session_id, num_turns, duration_ms, final_text, subtype)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama agentic session runner for Marikai")
    parser.add_argument("--model", default="llama3.1",
                        help="Ollama model name (default: llama3.1)")
    parser.add_argument("--max-turns", type=int, default=50,
                        help="Maximum agentic turns (default: 50)")
    parser.add_argument("--add-dir", default=None,
                        help="Primary working directory (brain dir)")
    parser.add_argument("--base-url", default="http://localhost:11434/v1",
                        help="Ollama base URL (default: http://localhost:11434/v1)")
    parser.add_argument("-p", "--prompt", required=True,
                        help="Initial prompt / wake message")
    # Accept (and ignore) unknown flags for compatibility with wake.sh
    parser.add_argument("--output-format", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    parser.add_argument("--allowedTools", default=None)

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
