"""Fetch Greenhouse verification codes from Gmail via IMAP."""

from __future__ import annotations

import email
import imaplib
import os
import re
import sys
from pathlib import Path

# Load .env from repo root
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fetch_greenhouse_code(company: str | None = None) -> str | None:
    """Fetch the latest Greenhouse security code from Gmail.

    Args:
        company: Optional company name to filter by subject line.

    Returns:
        The 8-character verification code, or None if not found.
    """
    addr = os.environ.get("GMAIL_EMAIL")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not password:
        print("GMAIL_EMAIL or GMAIL_APP_PASSWORD not set", file=sys.stderr)
        return None

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(addr, password)
        mail.select("INBOX")

        query = '(FROM "no-reply@us.greenhouse-mail.io" SUBJECT "Security code")'
        if company:
            query = f'(FROM "no-reply@us.greenhouse-mail.io" SUBJECT "Security code" SUBJECT "{company}")'

        _, data = mail.search(None, query)
        msg_ids = data[0].split()
        if not msg_ids:
            mail.logout()
            return None

        # Get the latest message
        _, msg_data = mail.fetch(msg_ids[-1], "(RFC822)")
        mail.logout()

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        # Extract body (prefer plain text, fall back to HTML)
        body = ""
        for part in msg.walk():
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode("utf-8", errors="replace")
            if part.get_content_type() == "text/plain" and text.strip():
                body = text
                break
            elif part.get_content_type() == "text/html" and not body:
                # Strip HTML tags
                body = re.sub(r"<[^>]+>", " ", text)

        # Greenhouse email says: "Copy and paste this code... <code>"
        # The code appears after "application:" on its own line
        match = re.search(r"application:\s*([A-Za-z0-9]{8})\b", body)
        if match:
            return match.group(1)
        # Fallback: code appears after "code" keyword with mixed content
        match = re.search(r"code[^A-Za-z0-9]*([A-Za-z0-9]{8})\b", body)
        if match and match.group(1).lower() not in ("security", "resubmit"):
            return match.group(1)

        return None
    except Exception as e:
        print(f"Gmail IMAP error: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else None
    code = fetch_greenhouse_code(company)
    if code:
        print(code)
    else:
        print("NO_CODE_FOUND", file=sys.stderr)
        sys.exit(1)
