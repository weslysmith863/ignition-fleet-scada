#!/usr/bin/env python3
"""Refuse to commit secrets.

Runs from the git pre-commit hook (.githooks/pre-commit) and can be run by hand: python scripts/check_secrets.py

Checks the STAGED version of every file that is about to be committed:
  1. No .env file and no gateway backup (*.gwbk) is staged.
  2. No secret value from the local .env (passwords, tokens, license keys) appears in any staged file.
  3. No line of a TEXT file looks like a leaked credential (JWE-style strings, long name-and-secret tokens, or a password
     assigned a literal value). A binary file (git's own test: a NUL byte in the first 8,000 bytes) skips this check only:
     compressed image data is long runs of letters and digits that match these shapes by chance, as the README's recorded GIF
     did, and a shape rule means nothing there. Checks 1 and 2 still apply to binary files. Wes approved this exception on
     2026-10-16.

It never prints a secret, only the file and line number. This is a local safety net; CI should also run a
dedicated scanner such as gitleaks.

A reviewed false alarm in check 3 can be allowed on that one line with a marker comment that names the check and gives a
reason: `check-secrets: allow <check> - <reason>`, where <check> is jwe, token, or password-literal. The marker covers only
that line and only that check, a marker without a reason or a check name is itself reported, and check 2 (your own .env
values) ignores markers completely. Adding a marker relaxes a security check, so it needs Wes's approval.
"""
import re
import subprocess
import sys

SECRET_KEY_PATTERN = re.compile(r"PASSWORD|TOKEN|LICENSE_KEY|SECRET", re.IGNORECASE)
PLACEHOLDERS = ("change-me", "paste-token-here", "XXXX-XXXX", "<")
CREDENTIAL_PATTERNS = [
    ("jwe", "JWE or JWT-looking string", re.compile(r"eyJ[A-Za-z0-9_-]{20,}")),
    ("token", "long name:secret token", re.compile(r"[A-Za-z0-9_-]{4,}:[A-Za-z0-9_-]{40,}")),
    ("password-literal", "password assigned a literal value", re.compile(r"password\s*[:=]\s*[\"']?[^\s\"'<{$]{6,}", re.IGNORECASE)),
]
MARKER_WORDS = re.compile(r"check-secrets:\s*allow")
ALLOW_MARKER = re.compile(r"check-secrets:\s*allow\s+([a-z-]+)\s+-\s+(\S.*)$")


def credential_problems(line):
    """What is wrong with one line: the credential patterns it matches, minus any the line carries a reasoned allow marker
    for, plus a note when an allow marker is malformed (no check name or no reason)."""
    if any(p in line for p in PLACEHOLDERS):
        return []
    marker = ALLOW_MARKER.search(line)
    allowed = {marker.group(1)} if marker else set()
    problems = [label for check, label, pattern in CREDENTIAL_PATTERNS if check not in allowed and pattern.search(line)]
    if MARKER_WORDS.search(line) and not marker:
        problems.append("allow marker without a check name and a reason")
    return problems


def env_value_problems(path, content, secrets):
    """Check 2: one problem per value from the local .env that appears anywhere in the file. Allow markers do not apply."""
    return [f"{path}: contains the value of {key} from your local .env" for key, value in secrets.items() if value in content]


BINARY_SNIFF_BYTES = 8000


def is_binary(raw):
    """Git's own test for a binary file: a NUL byte in the first 8,000 bytes."""
    return b"\0" in raw[:BINARY_SNIFF_BYTES]


def forbidden_file(path):
    """Check 1: a file that must never be committed, by name: .env, .env.<anything> except .env.example, or a gateway backup."""
    name = path.rsplit("/", 1)[-1]
    return name == ".env" or (name.startswith(".env.") and name != ".env.example") or name.endswith(".gwbk")


def file_problems(path, raw, secrets):
    """Checks 2 and 3 for one staged file's bytes. Check 2 (the values in your own .env) runs on every file. Check 3 (the
    credential shapes) runs only on text; see the module docstring for why a binary file skips it."""
    content = raw.decode("utf-8", errors="ignore")
    problems = env_value_problems(path, content, secrets)
    if is_binary(raw):
        return problems
    for lineno, line in enumerate(content.splitlines(), 1):
        for label in credential_problems(line):
            problems.append(f"{path}:{lineno}: looks like a leaked credential ({label})")
    return problems


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def load_env_secrets():
    secrets = {}
    try:
        with open(".env", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.rstrip("\r\n"))
                if m and SECRET_KEY_PATTERN.search(m.group(1)) and len(m.group(2)) >= 8:
                    secrets[m.group(1)] = m.group(2)
    except FileNotFoundError:
        pass
    return secrets


def main():
    staged = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines() if p]
    problems = []
    secrets = load_env_secrets()

    for path in staged:
        if forbidden_file(path):
            problems.append(f"{path}: this kind of file must never be committed")
            continue
        try:
            raw = subprocess.run(["git", "show", f":{path}"], capture_output=True, check=True).stdout
        except subprocess.CalledProcessError:
            continue
        problems += file_problems(path, raw, secrets)

    if problems:
        print("COMMIT BLOCKED: possible secrets found (values are not shown):")
        for p in problems:
            print("  -", p)
        print("Fix the files, or if this is a false alarm, review it before bypassing the hook.")
        return 1
    print(f"secret check passed ({len(staged)} staged files, {len(secrets)} local secret values checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
