import { useEffect, useRef, useState } from "react";

export function LiveDesktop({ active }: { active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Connecting to the computer…");

  useEffect(() => {
    if (!active || !host.current) return;
    const target = host.current;
    let client: { disconnect: () => void } | null = null;
    let cancelled = false;

    (async () => {
      const mod = await import("@novnc/novnc");
      if (cancelled) return;
      const rfb = new mod.default(target, "ws://127.0.0.1:6080");
      rfb.scaleViewport = true;
      rfb.resizeSession = false;
      rfb.background = "#3a4a6b";
      rfb.addEventListener("connect", () => {
        setStatus("");
        rfb.focus();
      });
      rfb.addEventListener("disconnect", (event: Event) => {
        const detail = (event as CustomEvent<{ clean?: boolean }>).detail;
        setStatus(detail?.clean ? "Desktop closed." : "Desktop disconnected.");
      });
      client = rfb;
    })().catch(() => setStatus("Could not open the computer."));

    return () => {
      cancelled = true;
      client?.disconnect();
      target.replaceChildren();
    };
  }, [active]);

  return (
    <div className="vnc-wrap">
      {status && <div className="screen-placeholder vnc-status">{status}</div>}
      <div className="vnc-host" ref={host} />
    </div>
  );
}
