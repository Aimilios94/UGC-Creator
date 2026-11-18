"""Copy secrets from backend/.env into Google Secret Manager. Never prints a value.

Usage (from backend/, after `gcloud auth login`):
    python scripts/put_secrets.py

Each value is piped to gcloud on stdin (never on the command line, so it is not in
the process list or shell history). An existing secret gets a new version only
when its value changed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
PROJECT = "ugc-ad-builder"
SECRETS = {  # Secret Manager name -> backend/.env variable
    "fal-key": "FAL_KEY",
    "openai-api-key": "OPENAI_API_KEY",
    "database-url": "DATABASE_URL",
    "access-codes": "ACCESS_CODES",
}


def read_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def gcloud(*args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise SystemExit("gcloud not found on PATH")
    return subprocess.run([exe, *args, f"--project={PROJECT}"], input=data, capture_output=True)  # noqa: S603


def main() -> int:
    env = read_env()
    for name, var in SECRETS.items():
        value = env.get(var, "")
        if not value:
            print(f"{name}: {var} is empty in .env, skipped")
            continue
        data = value.encode()
        exists = gcloud("secrets", "describe", name).returncode == 0
        if exists:
            current = gcloud("secrets", "versions", "access", "latest", f"--secret={name}")
            if current.returncode == 0 and current.stdout == data:
                print(f"{name}: unchanged")
                continue
            r = gcloud("secrets", "versions", "add", name, "--data-file=-", data=data)
            print(f"{name}: new version {'added' if r.returncode == 0 else 'FAILED'}")
        else:
            r = gcloud(
                "secrets",
                "create",
                name,
                "--replication-policy=user-managed",
                "--locations=europe-west4",
                "--data-file=-",
                data=data,
            )
            print(f"{name}: {'created' if r.returncode == 0 else 'FAILED'}")
        if r.returncode != 0:
            print("   " + r.stderr.decode(errors="replace").strip().splitlines()[-1][:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
