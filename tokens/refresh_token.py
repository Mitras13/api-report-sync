"""
Manual token refresh tool.

Usage:
    python refresh_token.py HK
    python refresh_token.py 54

The script requests the SMS OTP interactively and saves the resulting token
to this project's tokens/ directory. It is intentionally NOT called by
main.py because OTP requires manual user interaction.
"""
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
TOKEN_DIR = PROJECT_ROOT / "tokens"

CONFIG = {
    "HK": {
        "send_code_url": "https://api.hamkadeh.com/api/auth/login/send-code",
        "login_url": "https://api.hamkadeh.com/api/auth/login",
        "send_method": "post",
        "token_file": TOKEN_DIR / "tokenHK.txt",
    },
    "54": {
        "send_code_url": "https://api.5040.me/api/auth/send-login-code",
        "login_url": "https://api.5040.me/api/auth/login",
        "send_method": "put",
        "token_file": TOKEN_DIR / "token54.txt",
    },
}

REQUEST_TIMEOUT = (15, 30)


def refresh(company_code: str) -> bool:
    cfg = CONFIG.get(company_code)
    if not cfg:
        print(f"❌ Unknown company code: {company_code}")
        return False

    username = input("Username: ").strip()
    password = input("Password: ").strip()

    print("📲 Sending OTP...")
    send = getattr(requests, cfg["send_method"])

    try:
        r1 = send(
            cfg["send_code_url"],
            json={
                "type": "sms",
                "username": username,
                "password": password,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"❌ OTP request failed: {exc}")
        return False

    if r1.status_code != 200:
        print(f"❌ Failed to send OTP: HTTP {r1.status_code}")
        return False

    code = input("Enter SMS Code: ").strip()

    print("🔐 Verifying...")
    try:
        r2 = requests.post(
            cfg["login_url"],
            json={
                "username": username,
                "password": password,
                "code": code,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"❌ Login request failed: {exc}")
        return False

    if r2.status_code != 200:
        print(f"❌ Login request failed: HTTP {r2.status_code}")
        return False

    try:
        data = r2.json()
    except ValueError:
        print("❌ Login API returned non-JSON response.")
        return False

    if not data.get("status"):
        print(f"❌ Login failed: {data.get('message', 'Unknown error')}")
        return False

    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        print("❌ Login succeeded but no token was returned.")
        return False

    token_path = cfg["token_file"]
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token.strip(), encoding="utf-8")

    print(f"✅ Token saved to: {token_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
        print("Usage: python refresh_token.py [HK|54]")
        sys.exit(1)

    sys.exit(0 if refresh(sys.argv[1]) else 1)
