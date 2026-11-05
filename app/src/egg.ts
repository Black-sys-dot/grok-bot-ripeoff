import { COLORS, lookIndex } from "./characters";

export const EGG_ID = "dr-egg";

export const EGG_PROMPT =
  "I make bots from what you want, wire them together, and pass messages so they can work on this computer.";

const STRESS_NAMES = new Set(["Sys", "Research", "Files", "Forms", "Notes"]);

export type EggOp =
  | { op: "create"; name: string; prompt: string; look?: number }
  | { op: "message"; name?: string; id?: string; text: string };

export function isEgg(id: string | undefined) {
  return id === EGG_ID;
}

export function eggDefaults() {
  return {
    id: EGG_ID,
    name: "Dr. Egg",
    prompt: EGG_PROMPT,
    color: COLORS[4],
    look: 4,
    pinned: true as const,
  };
}

export function dropStressBots<T extends { name: string }>(bots: T[]): T[] {
  const cleaned = bots.filter((bot) => !STRESS_NAMES.has(bot.name));
  return cleaned.length > 0 ? cleaned : bots;
}

export function ensureEgg<T extends { id: string; name: string; pinned?: boolean }>(
  bots: T[],
  create: () => T,
): T[] {
  const index = bots.findIndex((bot) => bot.id === EGG_ID || bot.name.trim().toLowerCase() === "dr. egg");
  if (index < 0) return [create(), ...bots];
  const current = bots[index];
  const egg = { ...current, id: EGG_ID, pinned: true };
  if (index === 0) return [egg, ...bots.slice(1)];
  return [egg, ...bots.slice(0, index), ...bots.slice(index + 1)];
}

export function eggPersona(bots: { id: string; name: string; prompt: string }[]): string {
  const roster =
    bots
      .filter((bot) => bot.id !== EGG_ID)
      .map((bot) => `- ${bot.name}: ${bot.prompt.replace(/\s+/g, " ").slice(0, 90)}`)
      .join("\n") || "(none yet)";
  const text = `${EGG_PROMPT}

You are the bot-maker. Talk with Black normally too.

When he wants a new bot, create it. Write a short name and a tight prompt from his requirement. When he wants bots to work together, message the right one with a clear task. Do not open the browser unless he asked for a web task.

After any create or message, append this XML. The app strips it so Black never sees it:
<bot-ops>[{"op":"create","name":"Short name","prompt":"You ...","look":0},{"op":"message","name":"Short name","text":"Do ..."}]</bot-ops>
look is 0-5. Skip bot-ops when you are only chatting. Never say you created a bot unless you emit create. Do not create another Dr. Egg.

Current bots:
${roster}`;
  return text.length > 1900 ? text.slice(0, 1900) : text;
}

export function parseBotOps(reply: string): { clean: string; ops: EggOp[] } {
  const ops: EggOp[] = [];
  let clean = reply || "";

  const blocks = [
    ...clean.matchAll(/<bot-ops>([\s\S]*?)<\/bot-ops>/gi),
    ...clean.matchAll(/```(?:bot-ops|json)\s*([\s\S]*?)```/gi),
  ];

  for (const match of blocks) {
    const parsed = readOps(match[1]);
    if (parsed.length) {
      ops.push(...parsed);
      clean = clean.replace(match[0], "");
    }
  }

  if (!ops.length) {
    const loose = clean.match(/\[\s*\{\s*"op"\s*:\s*"(?:create|message)"[\s\S]*\]/);
    if (loose) {
      const parsed = readOps(loose[0]);
      if (parsed.length) {
        ops.push(...parsed);
        clean = clean.replace(loose[0], "");
      }
    }
  }

  return { clean: clean.replace(/\n{3,}/g, "\n\n").trim(), ops };
}

function readOps(raw: string): EggOp[] {
  try {
    const data = JSON.parse(raw.trim());
    const items = Array.isArray(data) ? data : [data];
    return items.flatMap((item): EggOp[] => {
      if (!item || typeof item !== "object") return [];
      const op = String(item.op || "").toLowerCase();
      if (op === "create") {
        const name = String(item.name || "").trim();
        const prompt = String(item.prompt || "").trim();
        if (!name || !prompt || name.toLowerCase() === "dr. egg") return [];
        const look = Number.isInteger(item.look) ? Number(item.look) : undefined;
        return [{ op: "create", name, prompt, look }];
      }
      if (op === "message") {
        const text = String(item.text || item.message || "").trim();
        const name = String(item.name || item.to || "").trim();
        const id = String(item.id || "").trim();
        if (!text || (!name && !id)) return [];
        return [{ op: "message", name: name || undefined, id: id || undefined, text }];
      }
      return [];
    });
  } catch {
    return [];
  }
}

export function applyEggOps<
  T extends {
    id: string;
    name: string;
    prompt: string;
    color: string;
    look: number;
    pinned?: boolean;
    messages: unknown[];
    updatedAt: number;
  },
>(
  bots: T[],
  ops: EggOp[],
  uid: () => string,
): { bots: T[]; handoffs: { id: string; text: string }[] } {
  let list = [...bots];
  const handoffs: { id: string; text: string }[] = [];

  for (const op of ops) {
    if (op.op === "create") {
      const look = lookIndex(op.look, list.length);
      const existing = list.find((bot) => bot.name.toLowerCase() === op.name.toLowerCase());
      if (existing) {
        list = list.map((bot) =>
          bot.id === existing.id
            ? { ...bot, prompt: op.prompt, look, color: COLORS[look], updatedAt: Date.now() }
            : bot,
        );
        continue;
      }
      const created = {
        id: uid(),
        name: op.name,
        prompt: op.prompt,
        color: COLORS[look],
        look,
        pinned: false,
        messages: [],
        updatedAt: Date.now(),
      } as unknown as T;
      const eggAt = list.findIndex((bot) => bot.id === EGG_ID);
      const at = eggAt < 0 ? 0 : eggAt + 1;
      list = [...list.slice(0, at), created, ...list.slice(at)];
    } else {
      const target = list.find(
        (bot) =>
          bot.id !== EGG_ID &&
          ((op.id && bot.id === op.id) ||
            (op.name && bot.name.toLowerCase() === op.name.toLowerCase())),
      );
      if (target) handoffs.push({ id: target.id, text: op.text });
    }
  }

  return { bots: list, handoffs };
}
