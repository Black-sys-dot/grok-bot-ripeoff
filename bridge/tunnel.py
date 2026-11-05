"""Keep the SSH tunnel up for as long as the app is open."""

from __future__ import annotations

import socket
import subprocess
import threading

PORTS = (8765, 6080)


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

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="ssh-tunnel", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for proc in self._procs.values():
            if proc.poll() is None:
                proc.terminate()

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
                self._procs[port] = subprocess.Popen(
                    [
                        "ssh",
                        "-N",
                        "-o",
                        "ExitOnForwardFailure=yes",
                        "-o",
                        "ServerAliveInterval=30",
                        "-o",
                        "ConnectTimeout=8",
                        "-L",
                        f"{port}:127.0.0.1:{port}",
                        self.host,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            self._stop.wait(3)
            errors: list[str] = []
            for port in missing:
                proc = self._procs.get(port)
                if proc is None or proc.poll() is None:
                    continue
                err = proc.stderr.read()[-400:].strip() if proc.stderr else ""
                errors.append(err or f"tunnel for :{port} exited")
            if errors:
                self.error = errors[-1]
                self._stop.wait(4)
