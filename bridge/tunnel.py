"""Keep the SSH tunnel up for as long as the app is open."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
from pathlib import Path

PORTS = (8765, 6080)
DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data" / "logs"


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class Tunnel:
    def __init__(self, host: str) -> None:
        self.host = host
        self.error = ""
        self._procs: dict[int, subprocess.Popen[str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._err_files: dict[int, Any] = {}

        data_dir = Path(os.environ.get("GROK_USER_DATA") or (Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data"))
        self.log_dir = data_dir / "logs"
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ssh-tunnel", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for port, proc in list(self._procs.items()):
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        for f in self._err_files.values():
            try:
                f.close()
            except Exception:
                pass
        self._err_files.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, object]:
        return {
            "agent": port_open(8765),
            "desktop": port_open(6080),
            "error": self.error,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            missing = [port for port in PORTS if not port_open(port)]
            if not missing:
                self.error = ""
                self._stop.wait(3)
                continue

            for port in missing:
                proc = self._procs.get(port)
                if proc and proc.poll() is None:
                    continue

                log_path = self.log_dir / f"tunnel-{port}.log"
                try:
                    err_file = open(log_path, "a", encoding="utf-8")
                    self._err_files[port] = err_file
                except OSError:
                    err_file = subprocess.DEVNULL  # type: ignore

                # Use -- to prevent host option injection and -o BatchMode=yes to avoid hanging
                self._procs[port] = subprocess.Popen(
                    [
                        "ssh",
                        "-N",
                        "-o", "ExitOnForwardFailure=yes",
                        "-o", "ServerAliveInterval=20",
                        "-o", "ServerAliveCountMax=3",
                        "-o", "ConnectTimeout=8",
                        "-o", "BatchMode=yes",
                        "-L", f"{port}:127.0.0.1:{port}",
                        "--",
                        self.host,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=err_file,
                    text=True,
                )

            self._stop.wait(3)
            errors: list[str] = []
            for port in missing:
                proc = self._procs.get(port)
                if proc is None or proc.poll() is None:
                    continue
                # If process died, inspect last few lines of log
                log_path = self.log_dir / f"tunnel-{port}.log"
                err_text = ""
                if log_path.is_file():
                    try:
                        lines = log_path.read_text(encoding="utf-8").splitlines()
                        err_text = lines[-1] if lines else ""
                    except Exception:
                        pass
                errors.append(err_text or f"tunnel for :{port} exited (code {proc.returncode})")

            if errors:
                self.error = errors[-1]
                self._stop.wait(4)
