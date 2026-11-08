export type PluginTool = {
  name: string;
  description: string;
};

export type PluginInfo = {
  id: string;
  name: string;
  description: string;
  version: string;
  file: string;
  error?: string;
  tools: PluginTool[];
};

export type MCPTool = {
  name: string;
  description: string;
};

export type MCPServerInfo = {
  name: string;
  type?: "stdio" | "http";
  url?: string;
  command?: string;
  args?: string[];
  running: boolean;
  tools_count: number;
  tools: MCPTool[];
  error?: string;
};

export type AgentStatus = {
  bridge: string;
  agent_base: string;
  ssh_host: string;
  token_configured: boolean;
  tunnel?: { agent: boolean; desktop: boolean; error: string };
  remote: { reachable: boolean; body?: unknown; error?: string };
  plugins?: { total: number; items: PluginInfo[] };
  mcp?: { total: number; items: MCPServerInfo[] };
};

export type ActivityEntry = {
  step: number;
  kind: string;
  title: string;
  detail: string;
};

export type RootApproval = {
  id: string;
  command: string;
  reason: string;
  approval_token: string;
};

export type AgentTaskResult = {
  status: string;
  reply: string;
  activity: ActivityEntry[];
  question?: string;
  url?: string;
  screenshot_base64?: string;
  root_approval?: RootApproval;
};

export async function fetchStatus(): Promise<AgentStatus> {
  const r = await fetch("/api/status");
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchBots(): Promise<{ bots: unknown[]; activeId: string } | null> {
  const r = await fetch("/api/bots");
  if (!r.ok) return null;
  const data = (await r.json()) as { bots?: unknown[]; activeId?: string };
  if (!Array.isArray(data.bots)) return null;
  return { bots: data.bots, activeId: data.activeId || "" };
}

export async function saveBots(payload: { bots: unknown[]; activeId: string }): Promise<void> {
  const r = await fetch("/api/bots", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function sendChat(
  message: string,
  bot: { id: string; prompt: string },
): Promise<AgentTaskResult> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, bot_id: bot.id, persona: bot.prompt }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(detail || r.statusText);
  }
  return r.json();
}

export async function decideRoot(
  approval: RootApproval,
  allow: boolean,
): Promise<{ status: string; reply: string }> {
  const r = await fetch("/api/root/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: approval.id,
      approval_token: approval.approval_token,
      allow,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchPlugins(): Promise<PluginInfo[]> {
  const r = await fetch("/api/plugins");
  if (!r.ok) return [];
  return r.json();
}

export async function reloadPlugins(): Promise<PluginInfo[]> {
  const r = await fetch("/api/plugins/reload", { method: "POST" });
  if (!r.ok) return [];
  return r.json();
}

export async function fetchMCPServers(): Promise<MCPServerInfo[]> {
  const r = await fetch("/api/mcp");
  if (!r.ok) return [];
  return r.json();
}

export async function refreshMCPServers(): Promise<MCPServerInfo[]> {
  const r = await fetch("/api/mcp/refresh", { method: "POST" });
  if (!r.ok) return [];
  return r.json();
}

export async function addMCPServer(
  name: string,
  config: Record<string, unknown>,
): Promise<MCPServerInfo[]> {
  const r = await fetch("/api/mcp/server", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, config }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function deleteMCPServer(name: string): Promise<MCPServerInfo[]> {
  const r = await fetch(`/api/mcp/server/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
