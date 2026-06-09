"""
College Email Watcher
=====================
Polls your college Gmail inbox every N seconds.
Detects job/placement emails containing Google Form links.
Calls on_job_found(job_info) for every new match.

Setup:
  1. https://console.cloud.google.com -> New project -> Enable Gmail API
  2. Credentials -> OAuth 2.0 -> Desktop App -> Download credentials.json
  3. Save to data_folder/credentials.json
  4. First run opens a browser tab to authorise (one-time)
"""

import os, base64, re, json, time, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger("email_watcher")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

JOB_KEYWORDS = [
    "internship", "job opening", "campus placement", "placement drive",
    "recruitment", "hiring", "apply now", "application form",
    "career opportunity", "walk-in", "off-campus", "on-campus",
    "google form", "application link", "register here", "last date to apply",
    "recruitment drive", "job fair", "campus connect",
]

URL_RE      = re.compile(r'https?://[^\s\'"<>]+')
FORM_URL_RE = re.compile(r'https://docs\.google\.com/forms/[^\s\'"<>]+')


def _build_service(cred_path: str):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Missing Google libs. Run:\n"
            "  pip install google-auth google-auth-oauthlib google-api-python-client"
        )
    token = str(Path(cred_path).parent / "gmail_token.json")
    creds = None
    if os.path.exists(token):
        creds = Credentials.from_authorized_user_file(token, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _body(payload: dict) -> str:
    text = ""
    if "parts" in payload:
        for p in payload["parts"]:
            text += _body(p)
    else:
        data = payload.get("body", {}).get("data", "")
        if data and "text" in payload.get("mimeType", ""):
            text += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return text


def _header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


class CollegeEmailWatcher:
    def __init__(self, credentials_path="data_folder/credentials.json",
                 poll_interval=300, lookback_hours=48,
                 seen_ids_path="data_folder/seen_email_ids.json"):
        self.cred_path   = credentials_path
        self.interval    = poll_interval
        self.lookback    = lookback_hours
        self.seen_path   = seen_ids_path
        self._svc        = None
        self._seen: set  = self._load_seen()

    def _load_seen(self):
        if os.path.exists(self.seen_path):
            try:
                return set(json.loads(Path(self.seen_path).read_text()))
            except Exception:
                pass
        return set()

    def _save_seen(self):
        Path(self.seen_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.seen_path).write_text(json.dumps(list(self._seen)))

    def _connect(self):
        self._svc = _build_service(self.cred_path)
        logger.info("Gmail connected.")

    def _fetch(self):
        after = int((datetime.now(timezone.utc) - timedelta(hours=self.lookback)).timestamp())
        res = self._svc.users().messages().list(
            userId="me", q=f"after:{after}", maxResults=50
        ).execute()
        return res.get("messages", [])

    def _parse(self, mid: str):
        raw = self._svc.users().messages().get(
            userId="me", id=mid, format="full"
        ).execute()
        hdrs    = raw["payload"].get("headers", [])
        subject = _header(hdrs, "Subject")
        sender  = _header(hdrs, "From")
        date    = _header(hdrs, "Date")
        body    = _body(raw["payload"])
        text    = (subject + " " + body).lower()
        if not any(k in text for k in JOB_KEYWORDS):
            return None
        forms  = list(set(FORM_URL_RE.findall(body)))
        others = list(set(u for u in URL_RE.findall(body) if u not in forms))
        if not forms and not others:
            return None
        return dict(id=mid, subject=subject, sender=sender, date=date,
                    form_links=forms, other_links=others, raw_body=body,
                    body_snippet=body[:400])

    def watch(self, on_job_found: Callable):
        if not self._svc:
            self._connect()
        logger.info(f"Watching college email every {self.interval}s ...")
        while True:
            try:
                for stub in self._fetch():
                    mid = stub["id"]
                    if mid in self._seen:
                        continue
                    self._seen.add(mid)
                    info = self._parse(mid)
                    if info:
                        logger.info(f"Job email: {info['subject']}")
                        try:
                            on_job_found(info)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                self._save_seen()
            except Exception as e:
                logger.error(f"Watch error: {e}")
            time.sleep(self.interval)
