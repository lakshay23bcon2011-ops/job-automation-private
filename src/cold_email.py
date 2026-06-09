"""
Cold Email Sender  (uses Groq - FREE)
======================================
Writes personalised recruiter emails using Groq (Llama),
then sends via Gmail API.

Needs same credentials.json as college_email_watcher.
Token saved as data_folder/gmail_send_token.json
"""

import os, base64, json, re, time, logging
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

from src.groq_client import chat, GROQ_QUALITY

logger = logging.getLogger("cold_email")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_EMAIL_SYS = """You write cold outreach emails for job seekers.
RULES:
- Subject: under 60 chars, specific to company/role
- Body: max 130 words, conversational, NOT template-sounding
- Reference the company or role specifically
- End with ONE low-friction CTA (e.g. "Happy to share my portfolio if useful")
- Use REAL data provided -- no [brackets] or placeholders
- Return ONLY valid JSON, no markdown:
  {"subject":"...","body":"..."}
"""


@dataclass
class EmailTarget:
    name: str
    email: str
    company: str
    role: str
    jd_text: str = ""


@dataclass
class EmailResult:
    target: EmailTarget
    sent: bool
    subject: str = ""
    preview: str = ""
    error: Optional[str] = None


def _build_service(cred_path: str):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError("pip install google-auth google-auth-oauthlib google-api-python-client")
    token = str(Path(cred_path).parent / "gmail_send_token.json")
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


class ColdEmailSender:
    def __init__(self, profile: dict, llm_api_key: str,
                 credentials_path="data_folder/credentials.json",
                 dry_run=True,
                 delay_secs=30,
                 log_path="data_folder/sent_emails.json"):
        self.profile   = profile
        self.api_key   = llm_api_key
        self.cred_path = credentials_path
        self.dry_run   = dry_run
        self.delay     = delay_secs
        self.log_path  = log_path
        self._svc      = None
        self._log: list = self._load_log()

    def _load_log(self):
        if os.path.exists(self.log_path):
            try: return json.loads(Path(self.log_path).read_text())
            except Exception: pass
        return []

    def _save_log(self):
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_path).write_text(json.dumps(self._log, indent=2))

    def _already_sent(self, email, company):
        return any(e["email"]==email and e["company"]==company for e in self._log)

    def _get_svc(self):
        if not self._svc:
            self._svc = _build_service(self.cred_path)
        return self._svc

    def _write(self, target: EmailTarget) -> tuple:
        pi  = self.profile.get("personal_information", {})
        edu = self.profile.get("education_details", [{}])[0]
        exp = self.profile.get("experience_details", [])
        skills = []
        for e in exp[:2]: skills += e.get("skills_acquired", [])
        prompt = (
            f"CANDIDATE: {pi.get('name','')} {pi.get('surname','')}, "
            f"{edu.get('institution','')}, {edu.get('field_of_study','')}\n"
            f"Skills: {', '.join(skills[:10])}\n"
            f"Email: {pi.get('email','')}\n"
            f"LinkedIn: {pi.get('linkedin','')}\n\n"
            f"TARGET: {target.name}, {target.company}, Role: {target.role}\n\n"
            f"JD: {target.jd_text[:700] if target.jd_text else 'N/A'}\n\n"
            f"Write a cold email from the candidate to {target.name} at {target.company} "
            f"for the {target.role} position."
        )
        raw = chat(self.api_key,
                   [{"role":"system","content":_EMAIL_SYS},
                    {"role":"user","content":prompt}],
                   model=GROQ_QUALITY, temperature=0.7, max_tokens=500)
        clean = re.sub(r"```(?:json)?","",raw).strip().rstrip("`")
        try:
            d = json.loads(clean)
            return d["subject"], d["body"]
        except Exception:
            return f"Interested in {target.role} at {target.company}", raw

    def send(self, target: EmailTarget) -> EmailResult:
        if self._already_sent(target.email, target.company):
            return EmailResult(target, False, error="already_sent")

        subject, body = self._write(target)
        logger.info(f"Email drafted -> {target.name} <{target.email}>  |  {subject}")

        if self.dry_run:
            logger.info("[DRY RUN] Not sending.")
            return EmailResult(target, False, subject, body[:200], "dry_run")

        try:
            pi  = self.profile.get("personal_information", {})
            msg = MIMEMultipart("alternative")
            msg["To"]      = target.email
            msg["Subject"] = subject
            msg["From"]    = pi.get("email", "")
            msg.attach(MIMEText(body, "plain"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            self._get_svc().users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            self._log.append({"email": target.email, "company": target.company,
                               "role": target.role, "subject": subject,
                               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
            self._save_log()
            logger.info(f"Email sent to {target.name} @ {target.company}")
            time.sleep(self.delay)
            return EmailResult(target, True, subject, body[:200])
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return EmailResult(target, False, subject, body[:200], str(e))

    def send_bulk(self, targets: list) -> list:
        return [self.send(t) for t in targets]
