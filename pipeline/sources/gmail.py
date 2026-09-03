"""Gmail adapter — pulls newsletter emails via Gmail API (OAuth read-only).

Security posture:
  - OAuth scope: gmail.readonly ONLY. Cannot write, delete, or send.
  - Sender allowlist: only emails from senders you list in sources.yaml are
    fetched. All other mail is invisible to the pipeline.
  - Refresh token, client_id, client_secret live only in GH Secrets or your
    local .env — never committed.
  - Token can be revoked instantly at:
       https://myaccount.google.com/permissions
    Revoking there stops the pipeline from reading your inbox immediately.

Config shape in sources.yaml:

  - name: gmail_newsletters
    type: gmail
    lookback_hours: 168
    max_items: 30
    senders:
      - platformer@substack.com
      - stratechery@stratechery.com
      - hi@morningbrew.com
"""
from __future__ import annotations
import base64
import os
import re
import time
from email.utils import parsedate_to_datetime, parseaddr

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .base import Candidate


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _get_creds() -> Credentials:
    """Build read-only Gmail creds from environment secrets.

    Required env vars (set as GH Secrets in prod, .env locally):
      GMAIL_REFRESH_TOKEN
      GMAIL_CLIENT_ID
      GMAIL_CLIENT_SECRET
    """
    refresh = os.environ.get("GMAIL_REFRESH_TOKEN")
    cid = os.environ.get("GMAIL_CLIENT_ID")
    csec = os.environ.get("GMAIL_CLIENT_SECRET")
    if not (refresh and cid and csec):
        raise RuntimeError(
            "Gmail source requires GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID, "
            "GMAIL_CLIENT_SECRET env vars. Run `python -m pipeline.gmail_auth` "
            "once locally to generate them, then push as GH Secrets."
        )
    creds = Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=csec,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _walk_parts(part)


def _decode_b64(s: str) -> str:
    if not s:
        return ""
    try:
        return base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body_and_first_link(msg: dict) -> tuple[str, str | None]:
    """Get plain text body + the first outbound article link, if any.

    Newsletters typically have a HTML part with formatted content. We prefer
    text/plain if it's substantive; otherwise strip the HTML.
    """
    plain = ""
    html = ""
    for part in _walk_parts(msg.get("payload", {})):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if not data:
            continue
        if mime == "text/plain" and not plain:
            plain = _decode_b64(data)
        elif mime == "text/html" and not html:
            html = _decode_b64(data)

    text = ""
    link: str | None = None
    if html:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            # Skip unsubscribe / view-in-browser / social share links
            low = (a.get_text() or "").lower() + " " + href.lower()
            if any(w in low for w in ("unsubscribe", "view in browser",
                                     "manage subscription", "view online",
                                     "list-unsubscribe", "?utm_")):
                # utm links often carry attribution garbage but may still be
                # the article — don't skip solely for utm. Skip only for the
                # explicit "unsubscribe" style links.
                if any(w in low for w in ("unsubscribe", "view in browser",
                                         "manage subscription")):
                    continue
            link = href
            break
    elif plain:
        text = plain
        m = re.search(r"https?://\S+", plain)
        link = m.group(0) if m else None

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, link


def fetch(cfg: dict) -> list[Candidate]:
    senders = cfg.get("senders") or []
    if not senders:
        return []
    max_items = int(cfg.get("max_items", 30))
    lookback_hours = int(cfg.get("lookback_hours", 168))
    label = cfg.get("label")   # optional additional filter

    creds = _get_creds()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    from_clause = " OR ".join(f"from:{s}" for s in senders)
    q_parts = [f"({from_clause})"]
    q_parts.append(f"newer_than:{max(1, lookback_hours // 24)}d")
    if label:
        q_parts.append(f"label:{label}")
    query = " ".join(q_parts)

    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_items,
    ).execute()
    ids = [m["id"] for m in resp.get("messages", [])]

    cutoff = int(time.time()) - lookback_hours * 3600
    out: list[Candidate] = []
    for mid in ids:
        try:
            msg = service.users().messages().get(
                userId="me", id=mid, format="full",
            ).execute()
        except Exception:
            continue

        subject = _header(msg, "Subject").strip()
        from_hdr = _header(msg, "From")
        _, sender_addr = parseaddr(from_hdr)
        date_hdr = _header(msg, "Date")
        try:
            ts = int(parsedate_to_datetime(date_hdr).timestamp())
        except Exception:
            ts = int(msg.get("internalDate", 0)) // 1000 or int(time.time())
        if ts < cutoff:
            continue
        if not subject:
            continue

        body, first_link = _extract_body_and_first_link(msg)
        if len(body.split()) < 80:
            continue

        out.append(Candidate(
            id=f"gmail-{mid}",
            source=cfg["name"],
            title=subject,
            url=first_link,                 # first substantive link in the email
            text=body,                      # newsletter body — pipeline can refine it directly
            author=sender_addr or from_hdr,
            score=cfg.get("default_score", 300),   # newsletters are curated → higher default
            created_at_ts=ts,
            permalink=first_link or f"https://mail.google.com/mail/u/0/#inbox/{mid}",
            extra={"sender": sender_addr, "gmail_id": mid},
        ))
    return out
