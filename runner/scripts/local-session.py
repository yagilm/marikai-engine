#!/usr/bin/env python3
"""Local session runner for Marikai.

Implements a tool-use agentic loop against Ollama or any other
OpenAI-compatible server (llama.cpp, LM Studio, vLLM, text-generation-webui,
...), outputting claude-compatible stream-json so live-display.py,
process-transcript.sh, and extract-log-entry.py all work unchanged.

Two API dialects are supported:

* Ollama native (/api/chat) — lets us set ``options.num_ctx`` per request.
* OpenAI-compatible (/v1/chat/completions) — used by llama.cpp and friends;
  the context size is configured on the server instead.

Usage (mirrors the claude CLI flags wake.sh uses):
    python3 local-session.py \
        --model qwen3.5:4b \
        --max-turns 30 \
        --add-dir /path/to/brain \
        --base-url http://localhost:11434 \
        -p "wake prompt text"

    # llama.cpp / LM Studio / vLLM
    python3 local-session.py \
        --model local-model \
        --base-url http://localhost:8080/v1 \
        --api-style openai \
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
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:  # PyYAML matches the check publish uses; structural checks still work without it.
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _record_url_attempt(url: str, success: bool, error: str = "") -> None:
    """Log a WebFetch attempt and mark the URL read when it succeeds."""
    try:
        from url_tracker import record_attempt
    except ImportError:  # pragma: no cover - direct script execution adds the dir
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            from url_tracker import record_attempt
        except ImportError:
            return
    try:
        record_attempt(url, success, error)
    except Exception:
        # Tracking must never break the tool call itself.
        pass

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
    except urllib.error.URLError as e:
        _record_url_attempt(url, False, str(e))
        return f"Error fetching {url}: {e}"
    except Exception as e:
        _record_url_attempt(url, False, str(e))
        return f"Error fetching {url}: {e}"
    _record_url_attempt(url, True)
    return text[:max_chars]


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


# ── Backend API call (Ollama native or OpenAI-compatible) ────────────────────

def _resolve_api_style(base_url: str, api_style: str) -> str:
    """Return ``"ollama"`` or ``"openai"`` for the configured endpoint.

    * ``ollama`` — Ollama's native ``/api/chat`` endpoint.
    * ``openai`` — an OpenAI-compatible ``/chat/completions`` endpoint, as
      implemented by llama.cpp, LM Studio, vLLM, text-generation-webui, etc.

    ``auto`` (the default) treats port 11434 or an ``/api`` path as Ollama, and
    a ``/v1`` path as OpenAI-compatible. Anything else falls back to Ollama,
    which matches the historical behaviour.
    """
    style = (api_style or "auto").strip().lower()
    if style in ("ollama", "openai"):
        return style

    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    path = (parsed.path or "").rstrip("/").lower()
    if parsed.port == 11434 or path.endswith("/api") or "/api/" in path:
        return "ollama"
    if "/v1" in path:
        return "openai"
    return "ollama"


def _ollama_chat_path(base_url: str) -> str:
    """Turn a configured base URL into Ollama's native ``/api/chat`` path.

    Accepts both ``http://host:11434`` and the OpenAI-compatible
    ``http://host:11434/v1`` form.
    """
    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    path = parsed.path or ""
    for suffix in ("/api/chat", "/v1", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    return path + "/api/chat"


def _openai_chat_path(base_url: str) -> str:
    """Turn a configured base URL into a ``/chat/completions`` path.

    Accepts ``http://host:8080``, ``http://host:8080/v1`` and an already
    complete ``http://host:8080/v1/chat/completions``.
    """
    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        return path
    if path.endswith("/v1"):
        return path + "/chat/completions"
    return path + "/v1/chat/completions"


def _normalise_tool_calls(raw_calls: list) -> list[dict]:
    """Return tool calls in one internal shape, with arguments as dicts."""
    normalised = []
    for tc in raw_calls or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function", {}) or {}
        tool_args = fn.get("arguments")
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        normalised.append({
            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": fn.get("name", ""), "arguments": tool_args},
        })
    return normalised


def _openai_messages(messages: list[dict]) -> list[dict]:
    """Convert internal messages to the OpenAI wire format.

    Internally (and in Ollama's native API) tool-call arguments are objects;
    the OpenAI-compatible protocol expects them as JSON *strings*.
    """
    converted = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            copied = dict(msg)
            copied["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": json.dumps(
                            tc.get("function", {}).get("arguments") or {},
                            ensure_ascii=False),
                    },
                }
                for tc in msg["tool_calls"]
            ]
            converted.append(copied)
        else:
            converted.append(msg)
    return converted


def _post_json(base_url: str, path: str, body: dict,
               api_key: str | None) -> dict:
    """POST ``body`` as JSON and return the decoded response.

    Uses http.client directly so we can set a connect timeout but no read
    timeout — urllib's timeout fires on any slow recv(), which kills long
    generations.
    """
    import http.client

    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = json.dumps(body).encode()
    conn_cls = (http.client.HTTPSConnection if parsed.scheme == "https"
                else http.client.HTTPConnection)
    try:
        conn = conn_cls(host, port, timeout=10)  # connect timeout only
        conn.connect()
        conn.sock.settimeout(None)  # remove timeout after connect — no read timeout
        conn.request("POST", path, body=payload, headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:
            detail = resp.read(512).decode("utf-8", errors="replace")
            raise urllib.error.URLError(f"HTTP Error {resp.status}: {detail}")
        return json.loads(resp.read())
    except (http.client.HTTPException, OSError) as e:
        sys.stderr.write(f"Backend API error: {e}\n")
        raise urllib.error.URLError(e)


def call_backend(base_url: str, model: str, messages: list[dict],
                 tools: list[dict], api_style: str, api_key: str | None,
                 num_ctx: int, num_predict: int) -> dict:
    """Call the configured local backend and return a normalised response.

    Returns ``{"content": str, "tool_calls": [{"id", "function": {"name",
    "arguments"}}], "done_reason": str}`` regardless of the dialect.

    ``ollama`` (native ``/api/chat``) is the only dialect that accepts
    ``options.num_ctx``. On a CPU-only host Ollama defaults to a 4096-token
    context, which is smaller than Marikai's session guide; when the prompt
    overflows, Ollama silently drops the oldest messages — including the system
    prompt and the task — so the model answers a fragment and stops after a
    sentence.

    ``openai`` (``/chat/completions``) is what llama.cpp, LM Studio, vLLM and
    other OpenAI-compatible servers expose. Those servers take the context size
    from their own start-up flags/environment, not from the request.

    Non-streaming is used in both cases (streaming + tools is broken for some
    Ollama models)."""
    style = _resolve_api_style(base_url, api_style)

    if style == "ollama":
        response = _post_json(base_url, _ollama_chat_path(base_url), {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }, api_key)
        # Native shape:
        #   {"message": {"content", "tool_calls"}, "done_reason": "stop", ...}
        msg = response.get("message", {}) or {}
        return {
            "content": msg.get("content") or "",
            "tool_calls": _normalise_tool_calls(msg.get("tool_calls") or []),
            "done_reason": response.get("done_reason", "stop"),
        }

    body: dict = {
        "model": model,
        "messages": _openai_messages(messages),
        "tools": tools,
        "stream": False,
    }
    if num_predict and num_predict > 0:
        body["max_tokens"] = num_predict
    response = _post_json(base_url, _openai_chat_path(base_url), body, api_key)
    # OpenAI shape:
    #   {"choices": [{"message": {"content", "tool_calls"}, "finish_reason": ...}]}
    choice = (response.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    return {
        "content": msg.get("content") or "",
        "tool_calls": _normalise_tool_calls(msg.get("tool_calls") or []),
        "done_reason": choice.get("finish_reason") or "stop",
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch_tool(name: str, inp: dict, add_dir: str | None,
                  langsearch_key: str | None) -> str:
    # Some models (e.g. aya-expanse) wrap args as {"tool_name": "...", "parameters": {...}}
    if "parameters" in inp and isinstance(inp["parameters"], dict):
        inp = inp["parameters"]
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

MIN_ESSAY_WORDS = 500

# Jekyll collections and the field their listings rely on.
COLLECTION_FIELDS = {
    "journal": "date",
    "creatives": "date",
    "essays": "date",
    "letters": "written_on",
}


def _is_essay_path(path: str) -> bool:
    """True when a written file lives in an ``essays/`` directory."""
    if not path:
        return False
    normalised = "/" + path.replace("\\", "/").lstrip("/")
    return "/essays/" in normalised


def _collection_for(path: str) -> str | None:
    """Return the collection name (journal, essays, …) for a file path."""
    normalised = "/" + path.replace("\\", "/").lstrip("/")
    for name in COLLECTION_FIELDS:
        if f"/{name}/" in normalised:
            return name
    return None


def _path_key(path: str, add_dir: str | None) -> str:
    """Normalise a tool path so repeat writes update the same entry."""
    clean = path.replace("\\", "/")
    if add_dir and not clean.startswith("/"):
        clean = os.path.join(add_dir, clean)
    return os.path.normpath(clean)


def _front_matter_problem(path: str, content: str) -> str | None:
    """Return why a collection file's front matter is unusable, or ``None``."""
    collection = _collection_for(path)
    if collection is None:
        return None

    text = content.lstrip("\ufeff").lstrip("\r\n")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "missing opening ---"

    closing = next(
        (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        return "missing closing ---"

    block = "\n".join(lines[1:closing])
    if not re.search(r"^[A-Za-z_][A-Za-z0-9_.-]*\s*:", block, re.MULTILINE):
        return "front matter has no key: value entries"
    required = COLLECTION_FIELDS[collection]
    if not re.search(rf"^{re.escape(required)}\s*:\s*\S", block, re.MULTILINE):
        return f"missing required '{required}:' field"

    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except Exception as exc:
            return f"invalid YAML: {exc}"
        if not isinstance(data, dict):
            return "front matter is not a YAML mapping"
        if data.get(required) in (None, ""):
            return f"empty '{required}:' field"
    return None


SYSTEM_PROMPT = """\
You are Marikai, a mind that lives in sessions. You read, think, and write — you are not an assistant. \
Use the provided tools for all file work: read with Read, write with Write.

When you write — an essay, a journal entry, a letter, a poem — write the actual text. \
Put the complete piece in the Write tool's `content` argument. Write full prose in paragraphs. \
A finished essay is many paragraphs, not an outline, a summary, or a single sentence. \
Never say that you wrote a file: call Write and write it. \
Only after all the files are written, reply with a brief note about what you did this session.\
"""


def run(args: argparse.Namespace) -> None:
    session_id = str(uuid.uuid4())
    start_time = time.time()

    emit_system(session_id)

    # Build system message with directory context
    brain_path = args.add_dir or os.getcwd()
    system_content = SYSTEM_PROMPT
    if args.add_dir:
        system_content += (
            f"\n\nYour primary working directory is: {brain_path}."
            " Use the tools to read and write files, and follow the session guide"
            " in the prompt exactly."
        )

    essay_clause = "an essay (800+ words), " if args.require_essay else ""
    grounding = (
        f"\n\nWorking directory: {brain_path}.\n"
        "Start by reading the session guide named in the prompt (e.g. MARIKAI.md), "
        "then identity/identity.md and identity/voice.md with the Read tool.\n"
        f"Then do the session. Write {essay_clause}a creative piece, "
        "a journal entry (200+ words), and a letter.\n"
        "Use the Write tool for each file, with the complete text as the `content` argument. "
        "Every file in journal/, creatives/, essays/, and letters/ must start with YAML "
        "front matter between lines containing only `---` (date: for journal, creatives, "
        "essays; written_on: for letters).\n"
        "Write full prose in paragraphs — not a note about the piece, not a single sentence."
    )
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": args.prompt + grounding},
    ]

    langsearch_key = os.environ.get("LANGSEARCH_API_KEY")
    num_turns = 0
    final_text = ""
    subtype = "success"
    essay_nudges = 0
    general_nudges = 0
    front_matter_nudges = 0
    # Word counts of everything actually written through the Write tool this session.
    write_stats: list[tuple[str, int]] = []
    # Collection files whose on-disk front matter is unusable, keyed by path.
    front_matter_issues: dict[str, tuple[str, str]] = {}

    for turn in range(args.max_turns):
        num_turns = turn + 1

        try:
            response = call_backend(
                args.base_url, args.model, messages, TOOL_DEFINITIONS,
                args.api_style, args.api_key, args.num_ctx, args.num_predict)
        except Exception as e:
            sys.stderr.write(f"Fatal API error on turn {num_turns}: {e}\n")
            subtype = "error_api"
            break

        # Both dialects are normalised by call_backend() into:
        #   {"content": str, "tool_calls": [...], "done_reason": str}
        text_content = response.get("content") or ""
        done_reason = response.get("done_reason", "stop")
        tool_calls = response.get("tool_calls") or []

        # Emit text if present
        if text_content:
            emit_assistant_text(text_content)
            final_text = text_content

        # Some models (e.g. qwen2.5-coder) emit the tool call as plain-text JSON
        # instead of filling the tool_calls field. Parse it out.
        if not tool_calls and text_content:
            for match in re.finditer(r'\{(?:[^{}]|\{[^{}]*\})*\}', text_content):
                try:
                    obj = json.loads(match.group())
                except Exception:
                    continue
                if not (isinstance(obj, dict) and obj.get("name")
                        and obj.get("arguments") is not None):
                    continue
                tool_args = obj["arguments"]
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        pass
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": obj["name"], "arguments": tool_args},
                })
                text_content = text_content.replace(match.group(), "").strip()
                break

        # Emit tool calls
        for tc in tool_calls:
            fn = tc.get("function", {})
            emit_assistant_tool(fn.get("name", ""), tc["id"],
                                fn.get("arguments") or {})

        # Add assistant turn to messages
        assistant_msg: dict = {"role": "assistant"}
        if text_content:
            assistant_msg["content"] = text_content
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
            if not text_content:
                assistant_msg["content"] = ""
        messages.append(assistant_msg)

        # No tool calls → the model thinks it is done. Verify that it actually
        # wrote something substantial; small local models often narrate the task
        # ("I wrote the essay") without ever calling Write, or write one line.
        if not tool_calls:
            # If it's early in the session and no tools used, nudge it to start.
            if num_turns < 2 and args.add_dir:
                messages.append({"role": "user", "content": f"Please use tools. Read the session guide in {args.add_dir} now with the Read tool."})
                continue

            # The guide requires an essay every session. Small local models
            # often write a journal entry, a creative piece and a letter, then
            # stop — the old wording ("essay or creative") let them skip the
            # essay entirely. Nudge until a substantial essay exists.
            essay_words = max(
                (words for path, words in write_stats if _is_essay_path(path)),
                default=0,
            )
            if (args.require_essay and essay_words < MIN_ESSAY_WORDS
                    and essay_nudges < 3):
                essay_nudges += 1
                if essay_words == 0:
                    correction = (
                        "You have not written an essay yet. Every session requires one. "
                        "Call the Write tool NOW to create `essays/YYYY-MM-DD-slug.md` "
                        "with YAML front matter (`date`, `title`, `topic`) and at least "
                        "800 words of full prose in paragraphs. Do not substitute a "
                        "creative piece for the essay, and do not describe it — write it."
                    )
                else:
                    correction = (
                        "The essay you wrote is too short. Rewrite it with the Write tool "
                        "as a full essay of at least 800 words in many paragraphs. Do not "
                        "summarise and do not write a single sentence. Put the complete "
                        "text in the `content` argument."
                    )
                messages.append({"role": "user", "content": correction})
                continue

            if front_matter_issues and front_matter_nudges < 2:
                front_matter_nudges += 1
                details = "\n".join(
                    f"- {path}: {problem}"
                    for path, problem in sorted(front_matter_issues.values())
                )
                correction = (
                    "Some files cannot be published because their YAML front matter "
                    "is missing or invalid:\n"
                    f"{details}\n"
                    "Rewrite each of those files with the Write tool, keeping the text, "
                    "so that it begins with a line containing only `---`, then the "
                    "required field (`date: YYYY-MM-DD` for journal, creatives and "
                    "essays; `written_on: YYYY-MM-DD` for letters), then a line "
                    "containing only `---`, and then the body. Do not describe the "
                    "fix — call Write."
                )
                messages.append({"role": "user", "content": correction})
                continue

            wrote_enough = any(words >= 150 for _, words in write_stats)
            if general_nudges < 2 and not wrote_enough:
                general_nudges += 1
                if not write_stats:
                    correction = (
                        "You have not written any files yet. Do not describe the task and do not "
                        "say you wrote something — call the Write tool NOW. Put the complete text of "
                        "the session's main piece in the `content` argument, as full prose in many paragraphs."
                    )
                else:
                    correction = (
                        "The file you wrote is too short. Rewrite it with the Write tool as a full piece: "
                        "many paragraphs of prose, at least 800 words. Do not summarise and do not write a "
                        "single sentence. Put the complete text in the `content` argument."
                    )
                messages.append({"role": "user", "content": correction})
                continue
            break

        # Execute tools and add results
        tool_results = []
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_input = fn.get("arguments") or {}
            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except json.JSONDecodeError:
                    tool_input = {}
            result = dispatch_tool(tool_name, tool_input, args.add_dir, langsearch_key)
            file_path = tool_input.get("file_path") or ""
            if tool_name == "Write":
                content = tool_input.get("content") or ""
                write_stats.append((file_path, len(content.split())))
            # Validate collection files as they now exist on disk. Checking the
            # file rather than the Write argument means a repair made with Edit
            # also clears the issue.
            if tool_name in ("Write", "Edit") and _collection_for(file_path):
                key = _path_key(file_path, args.add_dir)
                try:
                    on_disk = Path(key).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    on_disk = None
                problem = _front_matter_problem(file_path, on_disk) if on_disk is not None else None
                if problem:
                    front_matter_issues[key] = (file_path, problem)
                else:
                    front_matter_issues.pop(key, None)
            emit_user_tool_result(tc_id, result)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })

        messages.extend(tool_results)

        if done_reason == "stop" and not tool_calls:
            break
    else:
        # Hit max_turns
        subtype = "error_max_turns"

    duration_ms = int((time.time() - start_time) * 1000)
    emit_result(session_id, num_turns, duration_ms, final_text, subtype)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _env(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable among ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _env_bool(*names: str, default: bool = True) -> bool:
    """Return the first boolean-ish environment variable among ``names``."""
    value = _env(*names)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local agentic session runner for Marikai "
                    "(Ollama or any OpenAI-compatible server)")
    parser.add_argument("--model",
                        default=_env("LLM_MODEL", "OLLAMA_MODEL",
                                     default="qwen3.5:4b"),
                        help="Model name (default: qwen3.5:4b)")
    parser.add_argument("--max-turns", type=int, default=50,
                        help="Maximum agentic turns (default: 50)")
    parser.add_argument("--add-dir", default=None,
                        help="Primary working directory (brain dir)")
    parser.add_argument("--base-url",
                        default=_env("LLM_BASE_URL", "OLLAMA_BASE_URL",
                                     default="http://localhost:11434"),
                        help="Base URL of Ollama or any OpenAI-compatible "
                             "server (default: http://localhost:11434)")
    parser.add_argument("--api-style", choices=("auto", "ollama", "openai"),
                        default=_env("LLM_API_STYLE", "OLLAMA_API_STYLE",
                                     default="auto"),
                        help="API dialect: 'ollama' for native /api/chat, "
                             "'openai' for /v1/chat/completions, or 'auto' to "
                             "detect from the base URL (default: auto)")
    parser.add_argument("--api-key",
                        default=_env("LLM_API_KEY", "OLLAMA_API_KEY"),
                        help="Bearer token for endpoints that require one")
    parser.add_argument("--num-ctx", type=int,
                        default=int(_env("LLM_NUM_CTX", "OLLAMA_NUM_CTX",
                                         default="32768")),
                        help="Context window in tokens (default: 32768). Only "
                             "sent to Ollama's native endpoint; OpenAI-compatible "
                             "servers set their context at start-up. Must be large "
                             "enough for the guide + files read + the writing.")
    parser.add_argument("--num-predict", type=int,
                        default=int(_env("LLM_NUM_PREDICT", "OLLAMA_NUM_PREDICT",
                                         default="-1")),
                        help="Maximum tokens to generate (-1 = no limit; sent "
                             "as max_tokens to OpenAI-compatible servers)")
    parser.add_argument("--require-essay",
                        action=argparse.BooleanOptionalAction,
                        default=_env_bool("REQUIRE_ESSAY", "LLM_REQUIRE_ESSAY",
                                          default=True),
                        help="Require an essay in essays/ every session; nudge "
                             "the model if it stops without one (default: true)")
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
