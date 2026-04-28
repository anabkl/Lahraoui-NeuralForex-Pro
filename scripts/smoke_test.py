#!/usr/bin/env python3
"""
Simple Docker stack smoke test.

Run after:
    docker compose up --build -d

The script checks the public local ports and fails fast with a readable message
if one service is not reachable.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def env_port(name: str, default: str) -> str:
    return os.getenv(name, default)


CHECKS = [
    ("brain health", f"http://localhost:{env_port('BRAIN_HOST_PORT', '8000')}/health"),
    ("brain prediction", f"http://localhost:{env_port('BRAIN_HOST_PORT', '8000')}/predict"),
    ("executor health", f"http://localhost:{env_port('EXECUTOR_HOST_PORT', '8080')}/health"),
    ("executor status", f"http://localhost:{env_port('EXECUTOR_HOST_PORT', '8080')}/status"),
    ("monitor health", f"http://localhost:{env_port('MONITOR_HOST_PORT', '3000')}/nginx-health"),
]


def get_json_or_text(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body.strip()


def main() -> int:
    failed = False
    for label, url in CHECKS:
        try:
            result = get_json_or_text(url)
            print(f"[ok] {label}: {result}")
        except (urllib.error.URLError, TimeoutError) as exc:
            failed = True
            print(f"[fail] {label}: {url} -> {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
