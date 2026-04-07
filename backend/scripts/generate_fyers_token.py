"""Generate Fyers access token via OAuth login.

Run this script once each trading day (tokens expire daily):
    cd backend
    python scripts/generate_fyers_token.py

Steps:
1. Script opens the Fyers login page in your default browser
2. You log in — Fyers redirects to http://127.0.0.1:8080/?auth_code=...
3. The local server captures the auth_code automatically
4. FYERS_ACCESS_TOKEN is written to backend/.env

IMPORTANT: In your Fyers app at https://myapi.fyers.in the Redirect URI
must be set to exactly:  http://127.0.0.1:8080
"""

import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Allow running from project root or backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

REDIRECT_URI = "http://127.0.0.1:8080"
_captured: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        auth_code = params.get("auth_code", [None])[0]
        s_param = params.get("s", [""])[0]
        code_param = params.get("code", [None])[0]  # some Fyers versions use 'code'

        captured_code = auth_code or code_param

        if captured_code:
            _captured["auth_code"] = captured_code
            body = b"<h2>Auth code captured! You can close this tab.</h2>"
            self.send_response(200)
        elif "error" in params:
            _captured["error"] = params["error"][0]
            body = b"<h2>Error: " + params["error"][0].encode() + b". Check the terminal.</h2>"
            self.send_response(400)
        else:
            body = b"<h2>Waiting... no auth_code yet.</h2>"
            self.send_response(200)

        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # suppress request logs


def main():
    app_id = os.getenv("FYERS_APP_ID", "").strip()
    secret_key = os.getenv("FYERS_SECRET_KEY", "").strip()

    if not app_id or not secret_key:
        print("ERROR: FYERS_APP_ID and FYERS_SECRET_KEY must be set in backend/.env")
        sys.exit(1)

    try:
        from fyers_apiv3 import fyersModel
    except ImportError:
        print("ERROR: fyers-apiv3 not installed. Run: pip install fyers-apiv3")
        sys.exit(1)

    session = fyersModel.SessionModel(
        client_id=app_id,
        secret_key=secret_key,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )

    auth_url = session.generate_authcode()

    print("\n=== Fyers Token Generation ===")
    print(f"\nPre-requisite: In your Fyers app (https://myapi.fyers.in),")
    print(f"set Redirect URI to exactly:  {REDIRECT_URI}")
    print(f"\nOpening browser for Fyers login...")
    print(f"URL: {auth_url}\n")

    webbrowser.open(auth_url)

    # Start local server to capture the redirect
    server = HTTPServer(("127.0.0.1", 8080), _Handler)
    print("Waiting for Fyers redirect on http://127.0.0.1:8080 ...")
    print("(Log in to Fyers in your browser — this will auto-complete)\n")

    while "auth_code" not in _captured and "error" not in _captured:
        server.handle_request()

    server.server_close()

    if "error" in _captured:
        print(f"ERROR: Fyers returned error: {_captured['error']}")
        sys.exit(1)

    auth_code = _captured["auth_code"]
    print(f"Auth code captured.")

    session.set_token(auth_code)
    response = session.generate_token()

    if response.get("s") != "ok":
        print(f"ERROR: Token generation failed: {response}")
        sys.exit(1)

    access_token = response["access_token"]

    # Write to .env
    env_path = Path(__file__).resolve().parents[1] / ".env"
    env_text = env_path.read_text(encoding="utf-8")

    if re.search(r"^FYERS_ACCESS_TOKEN=", env_text, re.MULTILINE):
        env_text = re.sub(
            r"^FYERS_ACCESS_TOKEN=.*$",
            f"FYERS_ACCESS_TOKEN={access_token}",
            env_text,
            flags=re.MULTILINE,
        )
    else:
        env_text += f"\nFYERS_ACCESS_TOKEN={access_token}\n"

    env_path.write_text(env_text, encoding="utf-8")
    print(f"\nFYERS_ACCESS_TOKEN written to {env_path}")
    print("Token is valid until midnight today. Run this script each morning before trading.")


if __name__ == "__main__":
    main()
