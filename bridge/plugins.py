"""Local Plugins System for Grok Bot.

Discovers and loads modular Python plugins running directly on your machine.
Plugins define local tools that bots can call alongside cloud VPS tools and MCP servers.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("grok.plugins")

ROOT = Path(__file__).resolve().parents[1]
PROJECT_PLUGINS_DIR = ROOT / "plugins"

USER_DATA_DIR = Path(
    os.environ.get("GROK_USER_DATA")
    or (Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data")
).resolve()
USER_PLUGINS_DIR = USER_DATA_DIR / "plugins"


class LocalPlugin:
    def __init__(self, plugin_id: str, file_path: Path) -> None:
        self.plugin_id = plugin_id
        self.file_path = file_path
        self.meta: dict[str, Any] = {
            "id": plugin_id,
            "name": plugin_id.replace("_", " ").title(),
            "description": "",
            "version": "1.0.0",
        }
        self.tools: dict[str, dict[str, Any]] = {}
        self.module: Any = None
        self.error: str = ""

    def load(self) -> bool:
        self.tools.clear()
        self.error = ""
        try:
            spec = importlib.util.spec_from_file_location(
                f"grok_plugin_{self.plugin_id}", self.file_path
            )
            if not spec or not spec.loader:
                self.error = "Could not create module spec"
                return False

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.module = mod

            if hasattr(mod, "PLUGIN_META") and isinstance(mod.PLUGIN_META, dict):
                self.meta.update(mod.PLUGIN_META)

            if hasattr(mod, "TOOLS") and isinstance(mod.TOOLS, list):
                for t in mod.TOOLS:
                    if not isinstance(t, dict):
                        continue
                    name = t.get("name")
                    if not name:
                        continue
                    func = t.get("func")
                    if not callable(func):
                        func = getattr(mod, name, None)
                    if not callable(func):
                        continue

                    # Extract parameter schema or generate from type annotations
                    params = t.get("parameters") or self._inspect_parameters(func)

                    self.tools[name] = {
                        "name": name,
                        "description": t.get("description") or inspect.getdoc(func) or "",
                        "parameters": params,
                        "func": func,
                    }

            return True
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Failed to load plugin %s from %s", self.plugin_id, self.file_path)
            return False

    def _inspect_parameters(self, func: Callable[..., Any]) -> dict[str, Any]:
        """Generate a basic JSON schema from function signature if not provided."""
        sig = inspect.signature(func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for p_name, param in sig.parameters.items():
            if p_name in ("self", "cls"):
                continue
            prop: dict[str, Any] = {"type": "string"}
            if param.annotation is int:
                prop["type"] = "integer"
            elif param.annotation is float:
                prop["type"] = "number"
            elif param.annotation is bool:
                prop["type"] = "boolean"
            elif param.annotation in (list, list[str]):
                prop["type"] = "array"
                prop["items"] = {"type": "string"}
            elif param.annotation is dict:
                prop["type"] = "object"

            properties[p_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(p_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        tool = self.tools.get(tool_name)
        if not tool or not callable(tool.get("func")):
            raise ValueError(f"Tool '{tool_name}' not found in plugin '{self.plugin_id}'")
        try:
            return tool["func"](**args)
        except Exception as exc:
            return {"ok": False, "error": f"Plugin tool error: {exc}"}


class PluginRegistry:
    def __init__(self) -> None:
        self.plugins: dict[str, LocalPlugin] = {}
        self.reload()

    def reload(self) -> None:
        self.plugins.clear()
        search_dirs = [PROJECT_PLUGINS_DIR, USER_PLUGINS_DIR]

        for p_dir in search_dirs:
            if not p_dir.is_dir():
                continue
            for file_path in sorted(p_dir.glob("*.py")):
                if file_path.name.startswith(("_", ".")) or file_path.name == "__init__.py":
                    continue
                p_id = file_path.stem
                plugin = LocalPlugin(p_id, file_path)
                if plugin.load():
                    self.plugins[p_id] = plugin
                else:
                    self.plugins[p_id] = plugin  # Keep with error reported

    def get_definitions(self, enabled_plugins: list[str] | None = None) -> list[dict[str, Any]]:
        """Return OpenAI tool calling schemas for all active plugin tools."""
        definitions: list[dict[str, Any]] = []
        for p_id, plugin in self.plugins.items():
            if enabled_plugins is not None and p_id not in enabled_plugins:
                continue
            if plugin.error:
                continue

            for t_name, tool in plugin.tools.items():
                full_name = f"plugin__{p_id}__{t_name}"
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": full_name,
                        "description": f"[{plugin.meta.get('name', p_id)}] {tool.get('description', '')}",
                        "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                    },
                })
        return definitions

    def call_tool(self, full_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a plugin__<id>__<tool> call."""
        if not full_name.startswith("plugin__"):
            return {"ok": False, "detail": f"Invalid plugin tool format: {full_name}"}

        parts = full_name.split("__", 2)
        if len(parts) != 3:
            return {"ok": False, "detail": f"Malformed plugin tool name: {full_name}"}

        _, p_id, t_name = parts
        plugin = self.plugins.get(p_id)
        if not plugin:
            return {"ok": False, "detail": f"Plugin '{p_id}' not found"}
        if plugin.error:
            return {"ok": False, "detail": f"Plugin '{p_id}' is in error state: {plugin.error}"}

        try:
            res = plugin.call_tool(t_name, args)
            if isinstance(res, dict):
                return res
            return {"ok": True, "result": res}
        except Exception as exc:
            return {"ok": False, "detail": f"Plugin execution failed: {exc}"}

    def get_status(self) -> list[dict[str, Any]]:
        out = []
        for p_id, plugin in self.plugins.items():
            out.append({
                "id": p_id,
                "name": plugin.meta.get("name", p_id),
                "description": plugin.meta.get("description", ""),
                "version": plugin.meta.get("version", "1.0.0"),
                "file": str(plugin.file_path),
                "error": plugin.error,
                "tools": [
                    {"name": t_name, "description": t_info.get("description", "")}
                    for t_name, t_info in plugin.tools.items()
                ],
            })
        return out


REGISTRY = PluginRegistry()
