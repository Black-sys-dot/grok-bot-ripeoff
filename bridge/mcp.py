"""Local MCP (Model Context Protocol) Client for Grok Bot.

Runs local MCP servers (stdio) on your machine, discovers their tools,
and makes them available to the bots.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import httpx

from bridge.sanitize import sanitize_sensitive_data

logger = logging.getLogger("grok.mcp")

ROOT = Path(__file__).resolve().parents[1]
USER_DATA_DIR = Path(
    os.environ.get("GROK_USER_DATA")
    or (Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data")
).resolve()

USER_CONFIG_FILE = USER_DATA_DIR / "mcp_servers.json"
PROJECT_CONFIG_FILE = ROOT / "mcp_servers.json"
EXTERNAL_GEMINI_CONFIG = Path.home() / ".gemini" / "config" / "mcp_config.json"


def get_mcp_config_path() -> Path:
    if USER_CONFIG_FILE.is_file():
        return USER_CONFIG_FILE
    if PROJECT_CONFIG_FILE.is_file():
        return PROJECT_CONFIG_FILE
    return USER_CONFIG_FILE


def load_mcp_config() -> dict[str, Any]:
    path = get_mcp_config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning("Failed to parse %s: %exc", path, exc)

    # Auto-import from existing gemini mcp config if first run
    if EXTERNAL_GEMINI_CONFIG.is_file():
        try:
            gemini_data = json.loads(EXTERNAL_GEMINI_CONFIG.read_text(encoding="utf-8"))
            if isinstance(gemini_data, dict) and "mcpServers" in gemini_data:
                save_mcp_config(gemini_data)
                return gemini_data
        except Exception:
            pass

    default_config: dict[str, Any] = {"mcpServers": {}}
    return default_config


def save_mcp_config(config: dict[str, Any]) -> None:
    USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = USER_CONFIG_FILE.with_name(f"mcp_servers.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(USER_CONFIG_FILE)


class MCPServerSession:
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.proc: subprocess.Popen[str] | None = None
        self.tools: list[dict[str, Any]] = []
        self.error: str = ""
        self._req_id = 0
        self._lock = threading.Lock()
        self._pending_requests: dict[int, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def start(self) -> bool:
        self.stop()
        self.error = ""
        command = self.config.get("command")
        if not command:
            self.error = "No 'command' specified in server config"
            return False

        resolved_bin = shutil.which(command)
        if not resolved_bin:
            self.error = f"Command '{command}' not found on system PATH"
            return False

        args = self.config.get("args", [])
        env = os.environ.copy()
        if isinstance(self.config.get("env"), dict):
            for k, v in self.config["env"].items():
                env[str(k)] = str(v)

        cmd = [resolved_bin] + [str(a) for a in args]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as exc:
            self.error = f"Failed to spawn process: {exc}"
            logger.error("Failed to start MCP server %s: %s", self.name, exc)
            return False

        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._read_stdout, name=f"mcp-{self.name}-reader", daemon=True
        )
        self._reader_thread.start()

        # Perform MCP initialize handshake
        if not self._handshake():
            self.stop()
            return False

        # Query tools/list
        self._refresh_tools()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def _read_stdout(self) -> None:
        while not self._stop_event.is_set() and self.proc and self.proc.stdout:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue

                req_id = msg.get("id")
                if req_id is not None:
                    with self._lock:
                        fut = self._pending_requests.get(req_id)
                    if fut:
                        fut["response"] = msg
                        fut["event"].set()
            except Exception:
                break

    def _send_request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 12.0) -> dict[str, Any]:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError(f"MCP server '{self.name}' is not running")

        with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
            }
            if params is not None:
                payload["params"] = params

            event = threading.Event()
            fut_obj = {"event": event, "response": None}
            self._pending_requests[req_id] = fut_obj

        try:
            line = json.dumps(payload) + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except Exception as exc:
            with self._lock:
                self._pending_requests.pop(req_id, None)
            raise RuntimeError(f"Write to MCP server failed: {exc}") from exc

        if not event.wait(timeout=timeout):
            with self._lock:
                self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"MCP request '{method}' timed out after {timeout}s")

        with self._lock:
            res = self._pending_requests.pop(req_id, None)
        return res["response"] if res and res.get("response") else {}

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.proc or not self.proc.stdin:
            return
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            line = json.dumps(payload) + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except Exception:
            pass

    def _handshake(self) -> bool:
        try:
            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "grok-ripeoff", "version": "1.0.0"},
                },
                timeout=10.0,
            )
            if "error" in resp:
                self.error = f"MCP init error: {resp['error']}"
                return False

            self._send_notification("notifications/initialized")
            return True
        except Exception as exc:
            self.error = f"Handshake failed: {exc}"
            return False

    def _refresh_tools(self) -> None:
        try:
            resp = self._send_request("tools/list", {}, timeout=10.0)
            result = resp.get("result", {})
            self.tools = result.get("tools", [])
        except Exception as exc:
            logger.warning("tools/list failed on MCP server %s: %s", self.name, exc)
            self.tools = []

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.proc or self.proc.poll() is not None:
            if not self.start():
                return {"ok": False, "error": sanitize_sensitive_data(f"Server '{self.name}' is not running: {self.error}")}

        try:
            resp = self._send_request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=60.0,
            )
            if "error" in resp:
                return {"ok": False, "error": sanitize_sensitive_data(str(resp["error"]))}
            result = resp.get("result", {})
            content = result.get("content", [])
            is_error = result.get("isError", False)

            # Format text content
            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif item.get("type") == "image":
                        texts.append("[image content]")
                    else:
                        texts.append(json.dumps(item))
                else:
                    texts.append(str(item))

            joined = sanitize_sensitive_data("\n".join(texts))
            return {
                "ok": not is_error,
                "content": joined or result,
                "is_error": is_error,
            }
        except Exception as exc:
            return {"ok": False, "error": sanitize_sensitive_data(f"MCP tool execution failed: {exc}")}


class MCPHttpSession:
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.url = str(config.get("url", "")).rstrip("/")
        self.tools: list[dict[str, Any]] = []
        self.error: str = ""
        self.running: bool = False
        self._session_id: str | None = None
        self._client: httpx.Client | None = None
        self._req_id = 0
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def is_running(self) -> bool:
        return self.running

    def start(self) -> bool:
        self.stop()
        self.error = ""
        if not self.url or not self.url.startswith(("http://", "https://")):
            self.error = f"Invalid HTTP URL: {self.url}"
            return False

        try:
            self._client = httpx.Client(timeout=25.0)
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if isinstance(self.config.get("headers"), dict):
                for k, v in self.config["headers"].items():
                    headers[str(k)] = str(v)

            # 1. Initialize
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "grok-ripeoff", "version": "1.0.0"},
                },
            }
            r = self._client.post(self.url, json=init_payload, headers=headers)
            if not r.is_success:
                self.error = f"Initialize failed: HTTP {r.status_code}"
                return False

            self._session_id = r.headers.get("mcp-session-id")
            if self._session_id:
                headers["mcp-session-id"] = self._session_id

            # 2. Notification initialized
            self._client.post(
                self.url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=headers,
            )

            # 3. Fetch tools/list
            r_tools = self._client.post(
                self.url,
                json={"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}},
                headers=headers,
            )
            if not r_tools.is_success:
                self.error = f"tools/list failed: HTTP {r_tools.status_code}"
                return False

            data = r_tools.json()
            if "error" in data:
                self.error = str(data["error"])
                return False

            self.tools = data.get("result", {}).get("tools", [])
            self.running = True
            logger.info("MCP HTTP server %s started with %d tools", self.name, len(self.tools))
            return True
        except Exception as exc:
            self.error = sanitize_sensitive_data(f"Failed to connect to MCP HTTP server: {exc}")
            self.running = False
            return False

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.running or self._client is None:
            if not self.start():
                return {"ok": False, "error": self.error or "HTTP MCP server offline"}

        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
            if isinstance(self.config.get("headers"), dict):
                for k, v in self.config["headers"].items():
                    headers[str(k)] = str(v)

            call_payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }
            r = self._client.post(self.url, json=call_payload, headers=headers, timeout=60.0)
            if not r.is_success:
                return {"ok": False, "error": f"MCP HTTP error {r.status_code}"}

            data = r.json()
            if "error" in data:
                return {"ok": False, "error": sanitize_sensitive_data(str(data["error"]))}

            result = data.get("result", {})
            content = result.get("content", [])
            is_error = result.get("isError", False)

            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif item.get("type") == "image":
                        texts.append("[image content]")
                    else:
                        texts.append(json.dumps(item))
                else:
                    texts.append(str(item))

            joined = sanitize_sensitive_data("\n".join(texts))
            return {
                "ok": not is_error,
                "content": joined or result,
                "is_error": is_error,
            }
        except Exception as exc:
            return {"ok": False, "error": sanitize_sensitive_data(f"MCP tool call failed: {exc}")}

    def stop(self) -> None:
        self.running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def _create_mcp_session(name: str, config: dict[str, Any]) -> MCPServerSession | MCPHttpSession | None:
    if not isinstance(config, dict):
        return None
    if config.get("url"):
        return MCPHttpSession(name, config)
    if config.get("command"):
        return MCPServerSession(name, config)
    return None


class MCPRegistry:
    def __init__(self) -> None:
        self.sessions: dict[str, MCPServerSession | MCPHttpSession] = {}
        self._load()

    def _load(self) -> None:
        config = load_mcp_config()
        servers = config.get("mcpServers", {})
        for name, s_cfg in servers.items():
            sess = _create_mcp_session(name, s_cfg)
            if sess:
                self.sessions[name] = sess

    def refresh(self) -> None:
        """Reload configuration and start/restart sessions."""
        self.stop_all()
        self.sessions.clear()
        self._load()
        for session in self.sessions.values():
            session.start()

    def get_definitions(self, enabled_servers: list[str] | None = None) -> list[dict[str, Any]]:
        """Return OpenAI tool calling schemas for all active MCP tools."""
        definitions = []
        for name, session in self.sessions.items():
            if enabled_servers is not None and name not in enabled_servers:
                continue
            if not session.tools and not session.is_running() and not session.error:
                # Lazy start if not started
                session.start()

            for t in session.tools:
                t_name = t.get("name")
                if not t_name:
                    continue
                full_name = f"mcp__{name}__{t_name}"
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": full_name,
                        "description": f"[{name}] {t.get('description', '')}",
                        "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                })
        return definitions

    def call_tool(self, full_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a mcp__<server>__<tool> call."""
        if not full_name.startswith("mcp__"):
            return {"ok": False, "detail": f"Invalid MCP tool name: {full_name}"}

        parts = full_name.split("__", 2)
        if len(parts) != 3:
            return {"ok": False, "detail": f"Malformed MCP tool name: {full_name}"}

        _, server_name, tool_name = parts
        session = self.sessions.get(server_name)
        if not session:
            return {"ok": False, "detail": f"MCP server '{server_name}' not registered"}

        return session.call_tool(tool_name, arguments)

    def get_status(self) -> list[dict[str, Any]]:
        out = []
        for name, session in self.sessions.items():
            url = session.config.get("url")
            cmd = session.config.get("command")
            out.append({
                "name": name,
                "type": "http" if url else "stdio",
                "url": url,
                "command": cmd,
                "args": session.config.get("args", []),
                "running": session.is_running(),
                "tools_count": len(session.tools),
                "tools": [
                    {"name": t.get("name"), "description": t.get("description", "")}
                    for t in session.tools
                ],
                "error": sanitize_sensitive_data(session.error),
            })
        return out

    def add_server(self, name: str, config: dict[str, Any]) -> None:
        full_cfg = load_mcp_config()
        if "mcpServers" not in full_cfg:
            full_cfg["mcpServers"] = {}
        full_cfg["mcpServers"][name] = config
        save_mcp_config(full_cfg)

        if name in self.sessions:
            self.sessions[name].stop()
        sess = _create_mcp_session(name, config)
        if not sess:
            raise ValueError("Server config must have either 'command' or 'url'")
        sess.start()
        self.sessions[name] = sess

    def remove_server(self, name: str) -> None:
        full_cfg = load_mcp_config()
        if "mcpServers" in full_cfg and name in full_cfg["mcpServers"]:
            del full_cfg["mcpServers"][name]
            save_mcp_config(full_cfg)

        session = self.sessions.pop(name, None)
        if session:
            session.stop()

    def stop_all(self) -> None:
        for session in self.sessions.values():
            session.stop()


REGISTRY = MCPRegistry()
