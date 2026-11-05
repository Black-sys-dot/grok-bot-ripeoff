import look0 from "./assets/characters/look-0.jpg";
import look1 from "./assets/characters/look-1.jpg";
import look2 from "./assets/characters/look-2.jpg";
import look3 from "./assets/characters/look-3.jpg";
import look4 from "./assets/characters/look-4.jpg";
import look5 from "./assets/characters/look-5.jpg";

export const LOOKS = [look0, look1, look2, look3, look4, look5];
export const COLORS = ["#7dd3fc", "#2dd4bf", "#fb923c", "#f472b6", "#a78bfa", "#22d3ee"];

export function lookIndex(value: number | undefined, fallback: number) {
  if (!Number.isInteger(value)) return fallback % LOOKS.length;
  return (((value as number) % LOOKS.length) + LOOKS.length) % LOOKS.length;
}

export function Character({
  look,
  size,
  working = false,
}: {
  look: number;
  size: "rail" | "row" | "head" | "bubble" | "hero" | "pick";
  working?: boolean;
}) {
  const index = lookIndex(look, 0);
  return (
    <span
      className={`persona ${size}${working ? " working" : ""}`}
      style={{ ["--skin" as string]: COLORS[index] }}
      aria-hidden="true"
    >
      <img src={LOOKS[index]} alt="" draggable={false} />
    </span>
  );
}
