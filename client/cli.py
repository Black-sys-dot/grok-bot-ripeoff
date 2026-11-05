#!/usr/bin/env python3
"""Send browser jobs or agent tasks to the VPS worker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok agent remote browser client")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default="")
    parser.add_argument("--actions", type=Path, help="JSON file with {actions: [...]}")
    parser.add_argument("--goal", help="Natural-language task for the OpenRouter agent")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--agent-status", action="store_true")
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    timeout = 600.0 if args.goal else 120.0
    with httpx.Client(base_url=args.base_url, timeout=timeout) as client:
        if args.health:
            r = client.get("/health", headers=headers)
            print(r.json())
            return 0 if r.is_success else 1

        if args.agent_status:
            r = client.get("/agent/status", headers=headers)
            print(r.json())
            return 0 if r.is_success else 1

        if args.goal:
            payload = {
                "goal": args.goal,
                "max_steps": args.max_steps,
                "use_vision": False if args.no_vision else None,
                "model": args.model,
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            r = client.post("/agent/task", headers=headers, json=payload)
            if not r.is_success:
                print(r.text, file=sys.stderr)
                return 1
            print(json.dumps(r.json(), indent=2))
            return 0

        if not args.actions:
            print(
                "pass --goal '...' or --actions job.json or --health",
                file=sys.stderr,
            )
            return 2

        payload = json.loads(args.actions.read_text())
        r = client.post("/run", headers=headers, json=payload)
        if not r.is_success:
            print(r.text, file=sys.stderr)
            return 1
        print(json.dumps(r.json(), indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
