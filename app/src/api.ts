export type AgentStatus = {
  bridge: string;
  agent_base: string;
  ssh_host: string;
  token_configured: boolean;
  tunnel?: { agent: boolean; desktop: boolean; error: string };
  remote: { reachable: boolean; body?: unknown; error?: string };
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
