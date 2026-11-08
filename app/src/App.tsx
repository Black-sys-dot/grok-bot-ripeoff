import { FormEvent, KeyboardEvent, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityEntry,
  AgentTaskResult,
  MCPServerInfo,
  PluginInfo,
  RootApproval,
  addMCPServer,
  decideRoot,
  deleteMCPServer,
  fetchBots,
  fetchStatus,
  refreshMCPServers,
  reloadPlugins,
  saveBots,
  sendChat,
} from "./api";
import { AmbientScene } from "./AmbientScene";
import { COLORS, LOOKS, Character, lookIndex } from "./characters";
import { LiveDesktop } from "./LiveDesktop";
import { EGG_ID, applyEggOps, dropStressBots, eggDefaults, eggPersona, ensureEgg, isEgg, parseBotOps } from "./egg";
import { Theme, applyTheme, currentTheme } from "./theme";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  activity?: ActivityEntry[];
  failed?: boolean;
  root?: RootApproval;
  rootSettled?: boolean;
  handoff?: boolean;
  handoffSettled?: boolean;
};

type Bot = {
  id: string;
  name: string;
  prompt: string;
  color: string;
  look: number;
  pinned?: boolean;
  messages: Message[];
  updatedAt: number;
};

type BotMenu = {
  id: string;
  x: number;
  y: number;
};

type Draft = {
  id?: string;
  name: string;
  prompt: string;
  look: number;
};

const STORE_KEY = "grok-ripeoff-bots-v1";
const OLD_KEY = "grok-ripeoff-chat-v2";

const OFFLINE_REPLY = "The cloud computer is unreachable, so that message did not go through.";

const DEFAULT_PROMPT =
  "You handle general web tasks on the shared computer. Open pages, fill forms, download files, and report what you find.";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function loadOldMessages(): Message[] {
  try {
    const raw = localStorage.getItem(OLD_KEY);
    const items = raw ? (JSON.parse(raw) as Message[]) : [];
    return items.map((item) => ({
      ...item,
      at: item.at || Date.now(),
      text:
        item.role === "assistant" && item.text.includes("No agent token") ? OFFLINE_REPLY : item.text,
    }));
  } catch {
    return [];
  }
}

function normalizeBot(bot: Bot, index: number): Bot {
  const look = lookIndex(bot.look, isEgg(bot.id) ? 4 : index);
  return { ...bot, look, color: COLORS[look], pinned: Boolean(bot.pinned) || isEgg(bot.id) };
}

function eggBot(messages: Message[] = []): Bot {
  return { ...eggDefaults(), messages, updatedAt: Date.now() };
}

function withEgg(bots: Bot[]): Bot[] {
  return ensureEgg(bots, eggBot).map((bot, index) => normalizeBot(bot, index));
}

function loadStore(): { bots: Bot[]; activeId: string } {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { bots: Bot[]; activeId: string };
      if (Array.isArray(parsed.bots) && parsed.bots.length > 0) {
        const bots = withEgg(dropStressBots(parsed.bots));
        const activeId = bots.some((bot) => bot.id === parsed.activeId)
          ? parsed.activeId
          : bots[0].id;
        return { bots, activeId };
      }
    }
  } catch {
    /* start fresh */
  }
  const browser: Bot = {
    id: "default",
    name: "Browser",
    prompt: DEFAULT_PROMPT,
    color: COLORS[0],
    look: 0,
    messages: loadOldMessages(),
    updatedAt: Date.now(),
  };
  const bots = withEgg([browser]);
  return { bots, activeId: EGG_ID };
}

function formatWhen(ts: number) {
  const date = new Date(ts);
  const now = new Date();
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return `Today, ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function clock(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function preview(bot: Bot) {
  const last = [...bot.messages].reverse().find((message) => message.text.trim());
  if (!last) return "No messages yet";
  const who = last.role === "user" ? "You: " : "";
  return `${who}${last.text}`.replace(/\s+/g, " ").slice(0, 72);
}

export default function App() {
  const stored = useRef(loadStore());
  const [bots, setBots] = useState<Bot[]>(stored.current.bots);
  const [activeId, setActiveId] = useState(stored.current.activeId);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [input, setInput] = useState("");
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [sshHost, setSshHost] = useState("webeye-vps");
  const [linkNote, setLinkNote] = useState("Connecting to the cloud computer…");
  const [lastShot, setLastShot] = useState<string | undefined>();
  const [lastUrl, setLastUrl] = useState<string | undefined>();
  const [pane, setPane] = useState<"computer" | "activity">("computer");
  const [controlling, setControlling] = useState(false);
  const [computerWide, setComputerWide] = useState(false);
  const [computerFull, setComputerFull] = useState(false);
  const [desktopSession, setDesktopSession] = useState(0);
  const [menu, setMenu] = useState<BotMenu | null>(null);
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPServerInfo[]>([]);
  const [showToolsModal, setShowToolsModal] = useState(false);
  const [toolsTab, setToolsTab] = useState<"plugins" | "mcp">("plugins");
  const [reloadingTools, setReloadingTools] = useState(false);
  const [newMcpName, setNewMcpName] = useState("");
  const [newMcpCmd, setNewMcpCmd] = useState("");
  const [newMcpArgs, setNewMcpArgs] = useState("");
  const [mcpFormError, setMcpFormError] = useState<string | null>(null);


  const bottomRef = useRef<HTMLDivElement>(null);
  const botsRef = useRef(bots);
  const workingRef = useRef<string | null>(null);
  const hydratedRef = useRef(false);
  const handoffsRef = useRef<{ id: string; text: string }[]>([]);
  botsRef.current = bots;

  const active = bots.find((bot) => bot.id === activeId) ?? bots[0];


  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const remote = await fetchBots();
        if (cancelled) return;
        let next = botsRef.current;
        if (remote && remote.bots.length > 0) {
          const remoteBots = withEgg(remote.bots as Bot[]);
          const localById = Object.fromEntries(botsRef.current.map((bot) => [bot.id, bot]));
          next = remoteBots.map((bot) => {
            const local = localById[bot.id];
            const messages = bot.messages?.length ? bot.messages : local?.messages || [];
            return { ...bot, messages };
          });
          if (next.some((bot) => bot.id === remote.activeId)) setActiveId(remote.activeId);
        }
        hydratedRef.current = true;
        setBots(withEgg(next));
      } catch {
        if (!cancelled) {
          hydratedRef.current = true;
          setBots(withEgg(botsRef.current));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(STORE_KEY, JSON.stringify({ bots, activeId }));
    if (!hydratedRef.current) return;
    void saveBots({ bots, activeId }).catch(() => undefined);
  }, [bots, activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages, workingId, activeId]);

  const refreshStatus = useCallback(async () => {
    try {
      const status = await fetchStatus();
      setSshHost(status.ssh_host);
      const up = status.remote.reachable && status.token_configured;
      setOnline(up);
      setLinkNote(
        up
          ? "Connected"
          : status.tunnel?.error
            ? `${status.ssh_host} is unreachable. It connects when that machine is back.`
            : "Connecting to the cloud computer…",
      );
      if (status.plugins?.items) {
        setPlugins(status.plugins.items);
      }
      if (status.mcp?.items) {
        setMcpServers(status.mcp.items);
      }
    } catch {
      setOnline(false);
    }
  }, []);

  async function handleReloadPlugins() {
    setReloadingTools(true);
    try {
      const updated = await reloadPlugins();
      setPlugins(updated);
    } catch {
      /* ignore */
    } finally {
      setReloadingTools(false);
    }
  }

  async function handleRefreshMcp() {
    setReloadingTools(true);
    try {
      const updated = await refreshMCPServers();
      setMcpServers(updated);
    } catch {
      /* ignore */
    } finally {
      setReloadingTools(false);
    }
  }

  async function handleAddMcp(e: FormEvent) {
    e.preventDefault();
    setMcpFormError(null);
    const name = newMcpName.trim();
    const command = newMcpCmd.trim();
    if (!name || !command) {
      setMcpFormError("Name and command (or URL) are required.");
      return;
    }

    const isUrl = command.startsWith("http://") || command.startsWith("https://");
    let args: string[] = [];
    const rawArgs = newMcpArgs.trim();
    if (!isUrl && rawArgs) {
      if (rawArgs.startsWith("[") && rawArgs.endsWith("]")) {
        try {
          const parsed = JSON.parse(rawArgs);
          args = Array.isArray(parsed) ? parsed.map(String) : [rawArgs];
        } catch {
          args = rawArgs.split(/\s+/).filter(Boolean);
        }
      } else {
        args = rawArgs.split(/\s+/).filter(Boolean);
      }
    }

    try {
      const config = isUrl ? { url: command } : { command, args };
      const updated = await addMCPServer(name, config);
      setMcpServers(updated);
      setNewMcpName("");
      setNewMcpCmd("");
      setNewMcpArgs("");
    } catch (err) {
      setMcpFormError(err instanceof Error ? err.message : "Failed to add MCP server");
    }
  }

  async function handleDeleteMcp(name: string) {
    try {
      const updated = await deleteMCPServer(name);
      setMcpServers(updated);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    refreshStatus();
    const timer = setInterval(refreshStatus, 3000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  const activity = useMemo(
    () => (active?.messages ?? []).flatMap((message) => message.activity ?? []),
    [active],
  );

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...bots]
      .filter((bot) => {
        if (!needle) return true;
        return (
          bot.name.toLowerCase().includes(needle) ||
          bot.prompt.toLowerCase().includes(needle) ||
          bot.messages.some((m) => m.text.toLowerCase().includes(needle))
        );
      })
      .sort((a, b) => {
        if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1;
        return b.updatedAt - a.updatedAt;
      });
  }, [bots, query]);

  const closeMenu = useCallback(() => setMenu(null), []);

  useEffect(() => {
    if (!menu) return;
    const onDocClick = () => closeMenu();
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    window.addEventListener("click", onDocClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", onDocClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu, closeMenu]);

  useEffect(() => {
    if (!computerFull) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setComputerFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [computerFull]);

  function expandComputer() {
    setPane("computer");
    setComputerFull(true);
  }

  function shrinkComputer() {
    setComputerFull(false);
    setComputerWide(false);
  }

  function appendMessage(botId: string, message: Message) {
    setBots((list) =>
      list.map((item) =>
        item.id === botId
          ? { ...item, messages: [...item.messages, message], updatedAt: message.at }
          : item,
      ),
    );
  }

  function patchMessage(botId: string, messageId: string, patch: Partial<Message>) {
    setBots((list) =>
      list.map((bot) =>
        bot.id === botId
          ? {
              ...bot,
              messages: bot.messages.map((m) => (m.id === messageId ? { ...m, ...patch } : m)),
            }
          : bot,
      ),
    );
  }

  async function takeOver() {
    setPane("computer");
    setControlling(true);
    setComputerWide(true);
    setDesktopSession((s) => s + 1);
    try {
      await fetch("/api/desktop/show", { method: "POST" });
    } catch {
      /* ignore */
    }
  }

  function releaseComputer() {
    setControlling(false);
    setComputerWide(false);
  }


  async function sendText(botId: string, text: string) {
    if (!text.trim() || workingRef.current) return;
    const bot = botsRef.current.find((b) => b.id === botId);
    if (!bot) return;

    workingRef.current = botId;
    setWorkingId(botId);
    appendMessage(botId, { id: uid(), role: "user", text, at: Date.now() });

    if (online === false) {
      appendMessage(botId, {
        id: uid(),
        role: "assistant",
        text: OFFLINE_REPLY,
        at: Date.now(),
        failed: true,
      });
      workingRef.current = null;
      setWorkingId(null);
      return;
    }

    try {
      const persona = isEgg(bot.id) ? eggPersona(botsRef.current) : bot.prompt;
      const result: AgentTaskResult = await sendChat(text, {
        id: bot.id,
        prompt: persona,
      });
      const shot = result.screenshot_base64
        ? `data:image/png;base64,${result.screenshot_base64}`
        : undefined;
      if (shot) {
        setLastShot(shot);
        setPane("computer");
      }
      if (result.url) setLastUrl(result.url);
      if ((result.activity?.length ?? 0) > 0 && !shot) setPane("activity");
      const parsed = isEgg(bot.id) ? parseBotOps(result.reply || "") : { clean: result.reply || "Done.", ops: [] };
      const applied = parsed.ops.length
        ? applyEggOps(botsRef.current, parsed.ops, uid)
        : { bots: botsRef.current, handoffs: [] };
      const reply: Message = {
        id: uid(),
        role: "assistant",
        text: parsed.clean || "Done.",
        at: Date.now(),
        activity: result.activity ?? [],
        failed: result.status === "failed",
        root: result.root_approval,
        handoff: result.status === "needs_user",
      };
      const nextBots = applied.bots.map((item) =>
        item.id === botId ? { ...item, messages: [...item.messages, reply], updatedAt: reply.at } : item,
      );
      botsRef.current = nextBots;
      setBots(nextBots);
      handoffsRef.current.push(...applied.handoffs);
      if (result.status === "needs_user") takeOver();
    } catch (err) {
      appendMessage(botId, {
        id: uid(),
        role: "assistant",
        text: err instanceof Error ? err.message : "Something went wrong.",
        at: Date.now(),
        failed: true,
      });
    } finally {
      workingRef.current = null;
      setWorkingId(null);
      refreshStatus();
      const next = handoffsRef.current.shift();
      if (next) void sendText(next.id, next.text);
    }
  }

  async function onSend() {
    const text = input.trim();
    if (!active) return;
    setInput("");
    await sendText(active.id, text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void onSend();
    }
  }

  async function onRoot(botId: string, messageId: string, approval: RootApproval, allow: boolean) {
    if (workingRef.current) return;
    workingRef.current = botId;
    setWorkingId(botId);
    try {
      const result = await decideRoot(approval, allow);
      patchMessage(botId, messageId, { rootSettled: true });
      appendMessage(botId, {
        id: uid(),
        role: "assistant",
        text: allow ? result.reply : "Denied. That root command did not run.",
        at: Date.now(),
        failed: result.status === "failed",
      });
    } catch (err) {
      appendMessage(botId, {
        id: uid(),
        role: "assistant",
        text: err instanceof Error ? err.message : "Root approval failed.",
        at: Date.now(),
        failed: true,
      });
    } finally {
      workingRef.current = null;
      setWorkingId(null);
    }
  }

  function saveDraft(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const name = draft.name.trim();
    const prompt = draft.prompt.trim();
    if (!name || !prompt) return;
    if (draft.id) {
      setBots((list) =>
        list.map((bot) =>
          bot.id === draft.id
            ? {
                ...bot,
                name,
                prompt,
                look: lookIndex(draft.look, bot.look),
                color: COLORS[lookIndex(draft.look, bot.look)],
              }
            : bot,
        ),
      );
      setDraft(null);
      return;
    }
    const bot: Bot = {
      id: uid(),
      name,
      prompt,
      color: COLORS[lookIndex(draft.look, 0)],
      look: lookIndex(draft.look, 0),
      pinned: false,
      messages: [],
      updatedAt: Date.now(),
    };
    setBots((list) => [bot, ...list]);
    setActiveId(bot.id);
    setDraft(null);
    setInput("");
  }

  function removeBot(id: string) {
    if (isEgg(id) || bots.length < 2) return;
    const next = bots.filter((bot) => bot.id !== id);
    setBots(next);
    if (activeId === id) setActiveId(next[0].id);
    setDraft(null);
    setMenu(null);
  }

  function togglePin(id: string) {
    if (isEgg(id)) {
      setMenu(null);
      return;
    }
    setBots((list) =>
      list.map((bot) => (bot.id === id ? { ...bot, pinned: !bot.pinned } : bot)),
    );
    setMenu(null);
  }

  function openBotMenu(event: MouseEvent, id: string) {
    event.preventDefault();
    event.stopPropagation();
    const width = 188;
    const height = 96;
    setMenu({
      id,
      x: Math.min(event.clientX, window.innerWidth - width - 8),
      y: Math.min(event.clientY, window.innerHeight - height - 8),
    });
  }

  function clearChat() {
    if (!active) return;
    setBots((list) =>
      list.map((bot) =>
        bot.id === active.id ? { ...bot, messages: [], updatedAt: Date.now() } : bot,
      ),
    );
  }

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next, true);
  }


  return (
    <div
      className={
        computerFull
          ? "shell screen-maximized"
          : controlling && computerWide
            ? "shell live"
            : "shell"
      }
    >
      <AmbientScene />
      <aside className="chat-list glass-panel">
        <div className="list-head">
          <div>
            <h1>Chats</h1>
            <p>Same computer, different bots</p>
          </div>
          <div className="head-actions">
            <button
              type="button"
              className="theme-btn"
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Light mode" : "Dark mode"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="4.2" />
                  <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20.2 15.1A8.6 8.6 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z" />
                </svg>
              )}
            </button>
            <button
              type="button"
              className="plus-btn"
              aria-label="New bot"
              onClick={() => setDraft({ name: "", prompt: "", look: bots.length % LOOKS.length })}
            >
              +
            </button>
          </div>
        </div>
        <label className="search-wrap">
          <input
            className="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search"
          />
        </label>
        <div className="roster">
          {shown.map((bot) => (
            <div
              key={bot.id}
              className={bot.id === activeId ? "bot-row active" : "bot-row"}
              onClick={() => setActiveId(bot.id)}
              onContextMenu={(event) => openBotMenu(event, bot.id)}
            >
              <Character look={bot.look} size="row" working={workingId === bot.id} />
              <div className="bot-meta">
                <div className="bot-name-row">
                  <span className="bot-name">{bot.name}</span>
                  {bot.pinned && <span className="pinned-dot" title="Pinned" />}
                  <span className="spacer" />
                  <span className="bot-time">{formatWhen(bot.updatedAt)}</span>
                </div>
                <div className="bot-preview">{preview(bot)}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="conn-status">
          <span className={`status-dot ${online ? "online" : "offline"}`} />
          <div>
            <div className="conn-title">{online ? "Computer connected" : "Not connected"}</div>
            <div className="conn-sub">{sshHost}</div>
          </div>
          <button
            type="button"
            className="tools-badge-btn"
            title="Manage local Plugins & MCP servers"
            onClick={() => setShowToolsModal(true)}
          >
            ⚙️ {plugins.length} plugins · {mcpServers.length} mcp
          </button>
        </div>
      </aside>

      <main className="thread glass-panel">
        {active && (
          <>
            <header className="thread-head">
              <Character look={active.look} size="head" working={workingId === active.id} />
              <div className="thread-id">
                <h2>{active.name}</h2>
                <p>{active.prompt}</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                title="Manage local Plugins & MCP servers"
                onClick={() => setShowToolsModal(true)}
              >
                Tools ({plugins.reduce((acc, p) => acc + p.tools.length, 0) + mcpServers.reduce((acc, m) => acc + m.tools_count, 0)})
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() =>
                  setDraft({
                    id: active.id,
                    name: active.name,
                    prompt: active.prompt,
                    look: active.look,
                  })
                }
              >
                Edit
              </button>
              <button type="button" className="icon-btn" onClick={clearChat}>
                Clear
              </button>
            </header>

            <div className="messages">
              {active.messages.length === 0 && (
                <div className="hero-stage">
                  <Character look={active.look} size="hero" working={workingId === active.id} />
                  <h2>{active.name}</h2>
                  <p>{active.prompt}</p>
                </div>
              )}
              {active.messages.map((message) => (
                <div key={message.id} className={`bubble-row ${message.role}`}>\
                  {message.role === "assistant" && (
                    <Character look={active.look} size="bubble" working={workingId === active.id} />
                  )}
                  <div className={`bubble ${message.role} ${message.failed ? "failed" : ""}`}>
                    <div className="bubble-text">{message.text}</div>
                    <div className="bubble-time">{clock(message.at)}</div>
                    {message.handoff && !message.handoffSettled && (
                      <div className="handoff-card">
                        <div className="handoff-label">Computer is ready</div>
                        <p>Do this step on the computer. Don’t paste passwords or codes into the chat.</p>
                        <div className="root-actions">
                          <button type="button" onClick={takeOver}>
                            Take control
                          </button>
                          <button
                            type="button"
                            className="deny"
                            disabled={workingId !== null}
                            onClick={() => {
                              patchMessage(active.id, message.id, { handoffSettled: true });
                              setControlling(false);
                              void sendText(active.id, "I'm done. Continue where you left off.");
                            }}
                          >
                            I'm done
                          </button>
                        </div>
                      </div>
                    )}
                    {message.root && !message.rootSettled && (
                      <div className="root-card">
                        <div className="root-label">Root command requested</div>
                        <code>{message.root.command}</code>
                        <div className="root-reason">{message.root.reason}</div>
                        <div className="root-actions">
                          <button
                            type="button"
                            disabled={workingId !== null}
                            onClick={() => onRoot(active.id, message.id, message.root!, true)}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="deny"
                            disabled={workingId !== null}
                            onClick={() => onRoot(active.id, message.id, message.root!, false)}
                          >
                            Deny
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            <footer className="composer">
              <div className="composer-box">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder={online ? `Message ${active.name}…` : linkNote}
                  disabled={online === false || workingId !== null}
                  rows={1}
                />
                <button
                  type="button"
                  className="send-btn"
                  aria-label="Send"
                  disabled={!input.trim() || workingId !== null || online === false}
                  onClick={onSend}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3.4 11.2 20 4.2c.7-.3 1.4.4 1.1 1.1l-7 16.6c-.3.8-1.5.7-1.7-.1l-2.2-7.2-7.2-2.2c-.8-.2-.9-1.4-.1-1.7Z" />
                  </svg>
                </button>
              </div>
            </footer>
          </>
        )}
      </main>

      <aside className="computer-pane glass-panel">
        <div className="pane-tabs">
          <button
            type="button"
            className={pane === "computer" ? "active" : ""}
            onClick={() => setPane("computer")}
          >
            Computer
          </button>
          <button
            type="button"
            className={pane === "activity" ? "active" : ""}
            onClick={() => setPane("activity")}
          >
            Activity
            {activity.length > 0 && <span className="tab-count">{activity.length}</span>}
          </button>
        </div>

        {pane === "computer" ? (
          <>
            <div className="computer-toolbar">
              {controlling ? (
                <button type="button" onClick={releaseComputer}>
                  Release
                </button>
              ) : (
                <button type="button" onClick={takeOver}>
                  Take control
                </button>
              )}
              <span>{controlling ? "You have the mouse and keyboard" : "Shared by every bot"}</span>
              <div className="screen-controls">
                <button
                  type="button"
                  className="screen-btn"
                  aria-label="Minimize computer"
                  title="Minimize"
                  disabled={!computerFull && !computerWide}
                  onClick={shrinkComputer}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M3.5 8h9" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="screen-btn"
                  aria-label={computerFull ? "Restore computer" : "Full screen computer"}
                  title={computerFull ? "Restore" : "Full screen"}
                  onClick={() => (computerFull ? setComputerFull(false) : expandComputer())}
                >
                  {computerFull ? (
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <rect x="5.5" y="2.5" width="8" height="8" rx="1.2" />
                      <rect x="2.5" y="5.5" width="8" height="8" rx="1.2" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <rect x="3.5" y="3.5" width="9" height="9" rx="1.5" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <div className="screen-frame">
              {controlling ? (
                <LiveDesktop key={desktopSession} active={controlling} />
              ) : lastShot ? (
                <img src={lastShot} alt="Cloud computer" />
              ) : (
                <div className="screen-placeholder">
                  Take control to use the cloud computer. Every bot works on this same screen.
                </div>
              )}
            </div>
            {lastUrl && (
              <div className="url-bar" title={lastUrl}>
                {lastUrl}
              </div>
            )}
          </>
        ) : (
          <div className="activity-log">
            {activity.length === 0 && (
              <div className="screen-placeholder">Steps from this chat show up here.</div>
            )}
            {activity.map((entry, index) => (
              <div key={`${entry.step}-${index}`} className={`log-row ${entry.kind}`}>
                <div className="log-title">
                  <span>
                    {entry.title.startsWith("mcp:")
                      ? `🔌 ${entry.title}`
                      : entry.title.startsWith("plugin:")
                        ? `🧩 ${entry.title}`
                        : entry.title}
                  </span>
                  <span className="log-step">step {entry.step}</span>
                </div>
                {entry.detail && <div className="log-detail">{entry.detail}</div>}
              </div>
            ))}
          </div>
        )}
      </aside>

      {menu && (
        <div
          className="ctx-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button type="button" disabled={isEgg(menu.id)} onClick={() => togglePin(menu.id)}>
            {isEgg(menu.id)
              ? "Pinned"
              : bots.find((bot) => bot.id === menu.id)?.pinned
                ? "Unpin bot"
                : "Pin bot"}
          </button>
          <button
            type="button"
            className="danger"
            disabled={isEgg(menu.id) || bots.length < 2}
            onClick={() => removeBot(menu.id)}
          >
            Delete bot
          </button>
        </div>
      )}

      {/* Edit / Draft Modal */}
      {draft && (
        <div className="modal-backdrop" onClick={() => setDraft(null)}>
          <form className="modal" onClick={(event) => event.stopPropagation()} onSubmit={saveDraft}>
            <h2>{draft.id ? "Edit bot" : "New bot"}</h2>
            <p>It uses the same computer as the others. Pick who they look like, then the prompt on top.</p>
            <div className="look-picker">
              {LOOKS.map((src, index) => (
                <button
                  key={src}
                  type="button"
                  className={draft.look === index ? "look active" : "look"}
                  aria-label={`Character ${index + 1}`}
                  onClick={() => setDraft({ ...draft, look: index })}
                >
                  <Character look={index} size="pick" />
                </button>
              ))}
            </div>
            <label className="field">
              Name
              <input
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                placeholder="Research"
                autoFocus
              />
            </label>
            <label className="field">
              Prompt
              <textarea
                value={draft.prompt}
                onChange={(event) => setDraft({ ...draft, prompt: event.target.value })}
                placeholder="You look up sources, save useful pages, and keep notes short."
                rows={5}
              />
            </label>
            <div className="modal-actions">
              {draft.id && bots.length > 1 && !isEgg(draft.id) && (
                <button type="button" className="danger" onClick={() => removeBot(draft.id!)}>
                  Delete
                </button>
              )}
              <span className="spacer" />
              <button type="button" className="icon-btn" onClick={() => setDraft(null)}>
                Cancel
              </button>
              <button type="submit" className="save-btn" disabled={!draft.name.trim() || !draft.prompt.trim()}>
                Save
              </button>
            </div>
          </form>
        </div>
      )}
      {/* Tools & MCP Modal */}
      {showToolsModal && (
        <div className="modal-backdrop" onClick={() => setShowToolsModal(false)}>
          <div className="modal tools-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2>Local Tools & Capabilities</h2>
              <p>Plugins and MCP servers execute locally on your laptop.</p>
              <div className="modal-tabs">
                <button
                  type="button"
                  className={`modal-tab ${toolsTab === "plugins" ? "active" : ""}`}
                  onClick={() => setToolsTab("plugins")}
                >
                  🧩 Local Plugins ({plugins.length})
                </button>
                <button
                  type="button"
                  className={`modal-tab ${toolsTab === "mcp" ? "active" : ""}`}
                  onClick={() => setToolsTab("mcp")}
                >
                  🔌 Local MCP Servers ({mcpServers.length})
                </button>
              </div>
            </div>

            <div className="tools-content">
              {toolsTab === "plugins" ? (
                <>
                  <div className="tools-actions-bar">
                    <p className="tools-intro">
                      Plugins live in <code>plugins/</code> or <code>user-data/plugins/</code> and run directly in the local bridge process.
                    </p>
                    <button
                      type="button"
                      className="action-btn"
                      disabled={reloadingTools}
                      onClick={handleReloadPlugins}
                    >
                      {reloadingTools ? "Reloading…" : "↻ Reload Plugins"}
                    </button>
                  </div>

                  <div className="tools-list">
                    {plugins.length === 0 ? (
                      <div className="tools-empty">No plugins detected. Place .py plugins in user-data/plugins/</div>
                    ) : (
                      plugins.map((plugin) => (
                        <div key={plugin.id} className="tool-card">
                          <div className="tool-card-head">
                            <div>
                              <span className="tool-card-title">{plugin.name}</span>
                              <span className="tool-card-version">v{plugin.version}</span>
                            </div>
                            <span className="tool-card-id">{plugin.id}</span>
                          </div>
                          <p className="tool-card-desc">{plugin.description}</p>
                          {plugin.error && <div className="tool-card-error">Error: {plugin.error}</div>}
                          <div className="tool-functions">
                            {plugin.tools.map((fn) => (
                              <span
                                key={fn.name}
                                className="tool-fn-pill"
                                title={fn.description}
                              >
                                ⚙️ {fn.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="tools-actions-bar">
                    <p className="tools-intro">
                      Model Context Protocol (MCP) servers run locally over stdio. They are defined in <code>user-data/mcp_servers.json</code>.
                    </p>
                    <button
                      type="button"
                      className="action-btn"
                      disabled={reloadingTools}
                      onClick={handleRefreshMcp}
                    >
                      {reloadingTools ? "Refreshing…" : "↻ Refresh MCP"}
                    </button>
                  </div>

                  <div className="tools-list">
                    {mcpServers.length === 0 ? (
                      <div className="tools-empty">No MCP servers configured yet. Add one below!</div>
                    ) : (
                      mcpServers.map((srv) => (
                        <div key={srv.name} className="tool-card">
                          <div className="tool-card-head">
                            <div>
                              <span className="tool-card-title">{srv.name}</span>
                              <span className={`status-dot ${srv.running ? "online" : "offline"}`} style={{ display: "inline-block", verticalAlign: "middle", marginLeft: "0.4rem" }} />
                            </div>
                            <button
                              type="button"
                              className="danger-btn-sm"
                              onClick={() => handleDeleteMcp(srv.name)}
                            >
                              Delete
                            </button>
                          </div>
                          <div className="tool-command-preview">
                            <code>{srv.url || `${srv.command || ""} ${(srv.args || []).join(" ")}`}</code>
                          </div>
                          {srv.error && <div className="tool-card-error">Error: {srv.error}</div>}
                          <div className="tool-functions">
                            {srv.tools.length === 0 ? (
                              <span className="tool-fn-empty">{srv.running ? "No tools exported" : "Offline"}</span>
                            ) : (
                              srv.tools.map((fn) => (
                                <span
                                  key={fn.name}
                                  className="tool-fn-pill"
                                  title={fn.description}
                                >
                                  🔌 {fn.name}
                                </span>
                              ))
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="mcp-add-section">
                    <h3>Add MCP Server</h3>
                    <form className="mcp-add-form" onSubmit={handleAddMcp}>
                      {mcpFormError && <div className="tool-card-error">{mcpFormError}</div>}
                      <input
                        placeholder="Server Name (e.g. filesystem)"
                        value={newMcpName}
                        onChange={(e) => setNewMcpName(e.target.value)}
                      />
                      <input
                        placeholder="Command (e.g. npx, python3) or URL (e.g. https://...)"
                        value={newMcpCmd}
                        onChange={(e) => setNewMcpCmd(e.target.value)}
                      />
                      <input
                        placeholder="Arguments (e.g. -y @modelcontextprotocol/server-filesystem /tmp)"
                        value={newMcpArgs}
                        onChange={(e) => setNewMcpArgs(e.target.value)}
                      />
                      <button type="submit" className="action-btn">
                        + Add MCP Server
                      </button>
                    </form>
                  </div>
                </>
              )}
            </div>

            <div className="modal-actions" style={{ marginTop: "1rem" }}>
              <span className="spacer" />
              <button
                type="button"
                className="icon-btn"
                onClick={() => setShowToolsModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
