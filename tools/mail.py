"""Email tools — read/summarize the inbox and send mail via Gmail IMAP/SMTP.

Auth is a Gmail *app password* (https://myaccount.google.com/apppasswords, with
2-step verification on), set in .env as JADE_EMAIL_USER + JADE_EMAIL_APP_PASSWORD.
Reads (list_inbox / read_email) run immediately; send_email always confirms —
it's outward-facing and irreversible, so it returns the CONFIRM sentinel and the
agent loop asks the user for a yes/no first.

These tools are registered owner_only: tools.registry withholds them from (and
refuses them for) a non-owner speaker, so a household member or guest can't read
or send the owner's mail.

Fails open: with no credentials configured every function returns a short setup
hint instead of raising, so the voice loop never crashes on a missing key. This
module is named `mail` (not `email`) so it never shadows the stdlib `email`.
"""
import email
import imaplib
import os
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from tools.filesystem import _Result
from tools.safety import CONFIRM, bypass_enabled


_SETUP_HINT = (
    "Email isn't set up yet. Add JADE_EMAIL_USER and JADE_EMAIL_APP_PASSWORD to "
    ".env (make an app password at https://myaccount.google.com/apppasswords "
    "with 2-step verification on), then restart me."
)


def _cfg() -> dict:
    return {
        "user": os.environ.get("JADE_EMAIL_USER"),
        "password": os.environ.get("JADE_EMAIL_APP_PASSWORD"),
        "imap_host": os.environ.get("JADE_IMAP_HOST", "imap.gmail.com"),
        "smtp_host": os.environ.get("JADE_SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("JADE_SMTP_PORT", "465")),
    }


def _decode(s: str) -> str:
    """Decode RFC 2047 encoded-words ('=?UTF-8?...') into plain text."""
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def _extract_body(msg) -> str:
    """Best-effort plain-text body from a parsed message."""
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition", ""))
            if part.get_content_type() == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        return "(no plain-text body)"
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        return msg.get_payload() or ""


def list_inbox(n: int = 5, unread_only: bool = True) -> str:
    """Summarize the latest inbox messages (newest first). SAFE — read only."""
    cfg = _cfg()
    if not cfg["user"] or not cfg["password"]:
        return _SETUP_HINT
    try:
        M = imaplib.IMAP4_SSL(cfg["imap_host"])
        M.login(cfg["user"], cfg["password"])
        M.select("INBOX")
        _typ, data = M.search(None, "UNSEEN" if unread_only else "ALL")
        ids = data[0].split()
        if not ids:
            M.logout()
            return "No unread emails." if unread_only else "Inbox is empty."
        ids = ids[-max(1, int(n)):][::-1]  # newest first
        lines = []
        for i in ids:
            _typ, md = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            hdr = email.message_from_bytes(md[0][1])
            frm = _decode(hdr.get("From"))
            subj = _decode(hdr.get("Subject")) or "(no subject)"
            date = hdr.get("Date", "")
            lines.append(f"- [{i.decode()}] {parseaddr(frm)[1] or frm} — {subj}  ({date})")
        M.logout()
        head = f"{len(lines)} {'unread ' if unread_only else ''}email(s), newest first:\n"
        return head + "\n".join(lines)
    except Exception as e:
        return f"Email error: {type(e).__name__}: {e}"


def read_email(id: str) -> str:
    """Fetch and return the full text of one inbox message by its id (from
    list_inbox). SAFE — read only. Body capped like fetch_url."""
    cfg = _cfg()
    if not cfg["user"] or not cfg["password"]:
        return _SETUP_HINT
    try:
        M = imaplib.IMAP4_SSL(cfg["imap_host"])
        M.login(cfg["user"], cfg["password"])
        M.select("INBOX")
        _typ, md = M.fetch(str(id).encode(), "(RFC822)")
        if not md or md[0] is None:
            M.logout()
            return f"No email with id {id}."
        msg = email.message_from_bytes(md[0][1])
        M.logout()
        frm = _decode(msg.get("From"))
        subj = _decode(msg.get("Subject")) or "(no subject)"
        body = _extract_body(msg)
        if len(body) > 8000:
            body = body[:8000] + f"\n...(truncated, full length {len(body)} chars)"
        return f"From: {frm}\nSubject: {subj}\n\n{body}"
    except Exception as e:
        return f"Email error: {type(e).__name__}: {e}"


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. CONFIRM — returns the pending sentinel until the user OKs,
    then sends via SMTP-SSL on the bypass re-run."""
    cfg = _cfg()
    if not cfg["user"] or not cfg["password"]:
        return _SETUP_HINT
    if not bypass_enabled():
        return _Result(CONFIRM, f"send an email to {to} — subject: {subject!r}",
                       "send_email", {"to": to, "subject": subject, "body": body})
    try:
        m = EmailMessage()
        m["From"] = cfg["user"]
        m["To"] = to
        m["Subject"] = subject
        m.set_content(body)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=ctx) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(m)
        return f"Sent to {to}."
    except Exception as e:
        return f"Send failed: {type(e).__name__}: {e}"
