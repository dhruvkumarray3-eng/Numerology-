#!/usr/bin/env python3
"""Run every tests/test_*.py as a standalone script (the repo's intended mode).

Many of these tests stub ``sys.modules`` at import time, so they must not share
a process.  This runner executes each file independently and prints a clear
pass/fail summary.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS = sorted(
    f for f in os.listdir(os.path.join(ROOT, "tests"))
    if f.startswith("test_") and f.endswith(".py")
)
env = dict(os.environ)
for k, v in {"BOT_TOKEN": "x", "API_ID": "1", "API_HASH": "x", "ADMIN_ID": "1"}.items():
    env.setdefault(k, v)

passed, failed = [], []
for name in TESTS:
    path = os.path.join(ROOT, "tests", name)
    try:
        p = subprocess.run(
            [sys.executable, path], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=120,
        )
        ok = p.returncode == 0
        out = (p.stdout + p.stderr).strip().splitlines()
        print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {(out[-1] if out else '')[:120]}")
        (passed if ok else failed).append(name)
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {name}")
        failed.append(name)

print("\n" + "=" * 60)
print(f" PASSED: {len(passed)}   FAILED: {len(failed)}   TOTAL: {len(TESTS)}")
for f in failed:
    print("   FAIL:", f)
print("=" * 60)
sys.exit(1 if failed else 0)
