"""
Generate a password hash to paste into your app's Secrets when deploying to
Streamlit Community Cloud (or any host that supports st.secrets) -- see the
deployment guide for the full walkthrough.

This does NOT touch your local config/credentials.yaml -- for that, use
set_password.py instead. This script only prints the hash you need to paste
into the cloud dashboard's Secrets box.

Usage:
    python3 scripts/hash_password.py <username> <password>

Example:
    python3 scripts/hash_password.py seth "MyNewPassword123"
"""
import hashlib
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]
    hashed = hashlib.sha256(password.encode("utf-8")).hexdigest()
    print("\nAdd this line under the [credentials] section in your app's Secrets box:\n")
    print(f'{username} = "{hashed}"\n')


if __name__ == "__main__":
    main()
