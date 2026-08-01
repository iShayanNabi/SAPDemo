"""Run every quality gate this project actually enforces.

Run with::

    python scripts/check_quality.py            # everything
    python scripts/check_quality.py --fast     # skip the dependency audit (offline)

Four checks, in the order a failure is cheapest to fix:

1. **Lint** - ``ruff check``. Import order, naming, modern syntax, line length
   and the bug-shaped rules. See ``pyproject.toml`` for the two rules that are
   ignored and why. ``ruff format`` is deliberately not part of the gate; the
   reason is written next to the configuration.
2. **Secrets** - a scan of the tracked files for anything shaped like an API
   key. This is the check that has to pass before anything is pushed.
3. **Dependency vulnerabilities** - ``pip-audit`` against the installed
   versions. Needs network access; ``--fast`` skips it.
4. **Tests** - the full suite, unless ``--no-tests`` is passed.

Exit code 0 means every gate passed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGETS = ["app", "tests", "scripts", "streamlit_app", "migrations"]

#: Patterns that must never appear in a tracked file. Deliberately narrow: a
#: pattern that also matches the *placeholder* in .env.example would train
#: everybody to ignore this check.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Assigned password", re.compile(r"(?i)\bpassword\s*=\s*[\"'][^\"'\s]{8,}[\"']")),
    ("Bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{30,}")),
]

#: Files whose *job* is to show the shape of a credential.
SECRET_SCAN_EXEMPT = {
    ".env.example",
    "scripts/check_quality.py",
    "app/core/logging.py",
    "tests/e2e/test_security_contract.py",
}


def run(label: str, command: list[str]) -> bool:
    """Run a command, print a pass/fail line, return whether it succeeded."""
    print(f"\n=== {label} ===")
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    ok = completed.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    return ok


def tracked_files() -> list[Path]:
    """Every file git knows about - the ones that can leak a secret."""
    completed = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        print("  (not a git repository; scanning the working tree instead)")
        return [path for path in PROJECT_ROOT.rglob("*") if path.is_file()]
    return [PROJECT_ROOT / line for line in completed.stdout.splitlines() if line]


def scan_for_secrets() -> bool:
    """Look for credential-shaped strings in tracked files."""
    print("\n=== Secret scan ===")
    findings: list[str] = []
    scanned = 0

    for path in tracked_files():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if relative in SECRET_SCAN_EXEMPT:
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".xlsx", ".pdf", ".docx", ".db"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                findings.append(f"  {relative}:{line}  {label}")

    print(f"Scanned {scanned} tracked file(s).")
    if findings:
        print("Possible secrets found:")
        for finding in findings:
            print(finding)
        print("FAIL: Secret scan")
        return False

    # The .env file itself must never be tracked, whatever it contains.
    env_tracked = any(
        path.relative_to(PROJECT_ROOT).as_posix() == ".env" for path in tracked_files()
    )
    if env_tracked:
        print("  .env is tracked by git. It must stay ignored.")
        print("FAIL: Secret scan")
        return False

    print("PASS: Secret scan")
    return True


def main() -> int:
    """Run the gates and report."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fast", action="store_true", help="Skip the dependency audit.")
    parser.add_argument("--no-tests", action="store_true", help="Skip the test suite.")
    args = parser.parse_args()

    print("SAP AI Application Lab - quality gates")

    results: dict[str, bool] = {}
    results["Lint (ruff check)"] = run(
        "Lint (ruff check)", [sys.executable, "-m", "ruff", "check", *TARGETS]
    )
    results["Secret scan"] = scan_for_secrets()

    if args.fast:
        print("\n=== Dependency audit ===\nSKIPPED (--fast)")
    else:
        results["Dependency audit (pip-audit)"] = run(
            "Dependency audit (pip-audit)",
            [sys.executable, "-m", "pip_audit", "--progress-spinner", "off"],
        )

    if args.no_tests:
        print("\n=== Tests ===\nSKIPPED (--no-tests)")
    else:
        results["Tests (pytest)"] = run("Tests (pytest)", [sys.executable, "-m", "pytest", "-q"])

    print("\n" + "=" * 60)
    for label, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    failed = [label for label, passed in results.items() if not passed]
    if failed:
        print(f"\n{len(failed)} gate(s) failed.")
        return 1
    print("\nAll gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
