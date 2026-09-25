"""
Set or update the login password for the Global Security Analyser app.

Usage:
    python3 scripts/set_password.py <username> <password>

Example:
    python3 scripts/set_password.py admin "MyNewPassword123"
"""
import hashlib
import os
import sys

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE, "config")
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.yaml")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]

    os.makedirs(CONFIG_DIR, exist_ok=True)
    creds = {}
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH) as f:
            creds = yaml.safe_load(f) or {}

    creds[username] = hashlib.sha256(password.encode("utf-8")).hexdigest()

    with open(CREDENTIALS_PATH, "w") as f:
        yaml.safe_dump(creds, f)

    print(f"Password set for user '{username}'.")


if __name__ == "__main__":
    main()
