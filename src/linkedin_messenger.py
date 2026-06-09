"""
LinkedIn Cold Messenger  (uses Groq - FREE)
=============================================
Sends personalised connection requests + notes on LinkedIn.
Uses Selenium + undetected-chromedriver (already in AIHawk deps).

SAFETY LIMITS (built-in):
  Max 15 connections per day  <-- LinkedIn ban threshold is ~25-30/day
  5-15 second random delay between profiles

Run with linkedin_dry_run: true first to test without sending.
"""

import json, re, time, random, os, logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.groq_client import chat, GROQ_QUALITY

logger = logging.getLogger("linkedin")

MAX_DAILY = 15

_NOTE_SYS = """Write a LinkedIn connection request note for a job seeker.
RULES:
- Max 295 characters (hard LinkedIn limit)
- Sound human, not copy-paste
- Mention the company or role specifically
- Return ONLY valid JSON, no markdown:
  {"note":"..."}
"""


@dataclass
class LinkedInTarget:
    profile_url: str
    name: str
    company: str
    role: str
    jd_text: str = ""


@dataclass
class LinkedInResult:
    target: LinkedInTarget
    action: str   # connected | skipped | dry_run | failed
    note: str = ""
    error: Optional[str] = None


def _write_note(target: LinkedInTarget, profile: dict, api_key: str) -> str:
    pi  = profile.get("personal_information", {})
    edu = profile.get("education_details", [{}])[0]
    prompt = (
        f"Candidate: {pi.get('name','')} {pi.get('surname','')}, "
        f"studying {edu.get('field_of_study','')} at {edu.get('institution','')}\n"
        f"Reaching out to: {target.name} at {target.company} about {target.role}\n"
        f"Write a 295-char connection note."
    )
    raw = chat(api_key,
               [{"role":"system","content":_NOTE_SYS},
                {"role":"user","content":prompt}],
               model=GROQ_QUALITY, temperature=0.8, max_tokens=200)
    clean = re.sub(r"```(?:json)?","",raw).strip().rstrip("`")
    try:
        return json.loads(clean).get("note","")[:295]
    except Exception:
        return raw[:295]


class LinkedInMessenger:
    def __init__(self, profile: dict, linkedin_email: str,
                 linkedin_password: str, llm_api_key: str,
                 headless=False, dry_run=True,
                 log_path="data_folder/linkedin_sent.json"):
        self.profile   = profile
        self.email     = linkedin_email
        self.password  = linkedin_password
        self.api_key   = llm_api_key
        self.headless  = headless
        self.dry_run   = dry_run
        self.log_path  = log_path
        self._driver   = None
        self._logged   = False
        self._log: list = self._load_log()
        self._today    = self._count_today()

    def _load_log(self):
        if os.path.exists(self.log_path):
            try: return json.loads(Path(self.log_path).read_text())
            except Exception: pass
        return []

    def _save_log(self):
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_path).write_text(json.dumps(self._log, indent=2))

    def _count_today(self):
        today = time.strftime("%Y-%m-%d")
        return sum(1 for e in self._log if e.get("ts","").startswith(today))

    def _sent(self, url):
        return any(e["url"]==url for e in self._log)

    def _delay(self, lo=3, hi=10):
        time.sleep(random.uniform(lo, hi))

    def _init_driver(self):
        try:
            import undetected_chromedriver as uc
        except ImportError:
            raise ImportError("pip install undetected-chromedriver")
        opts = uc.ChromeOptions()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1280,900")
        self._driver = uc.Chrome(options=opts)

    def _login(self):
        if not self._driver:
            self._init_driver()
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        d = self._driver
        d.get("https://www.linkedin.com/login")
        self._delay(2, 4)
        wait = WebDriverWait(d, 20)
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(self.email)
        d.find_element(By.ID, "password").send_keys(self.password)
        self._delay(0.5, 1.5)
        d.find_element(By.CSS_SELECTOR, '[type="submit"]').click()
        self._delay(3, 5)
        if "feed" in d.current_url or "mynetwork" in d.current_url:
            self._logged = True
            logger.info("LinkedIn login ok.")
        else:
            raise RuntimeError(
                "LinkedIn login failed. Run with headless=False and complete CAPTCHA once."
            )

    def connect(self, target: LinkedInTarget) -> LinkedInResult:
        if self._today >= MAX_DAILY:
            logger.warning(f"Daily limit {MAX_DAILY} reached.")
            return LinkedInResult(target, "skipped", error="daily_limit")
        if self._sent(target.profile_url):
            return LinkedInResult(target, "skipped", error="already_sent")

        note = _write_note(target, self.profile, self.api_key)
        logger.info(f"Note for {target.name}: {note[:60]}...")

        if self.dry_run:
            return LinkedInResult(target, "dry_run", note)

        if not self._logged:
            self._login()

        try:
            action = self._send_request(target, note)
            if action == "connected":
                self._log.append({"url": target.profile_url, "name": target.name,
                                   "company": target.company,
                                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
                self._save_log()
                self._today += 1
            return LinkedInResult(target, action, note)
        except Exception as e:
            logger.error(f"LinkedIn error: {e}")
            return LinkedInResult(target, "failed", note, str(e))

    def _send_request(self, target: LinkedInTarget, note: str) -> str:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        d = self._driver
        d.get(target.profile_url)
        self._delay(3, 5)

        # Find Connect button (may be in "More" menu)
        connect_btn = None
        for btn in d.find_elements(By.CSS_SELECTOR, "button"):
            if btn.text.strip().lower() == "connect":
                connect_btn = btn; break

        if not connect_btn:
            for btn in d.find_elements(By.CSS_SELECTOR, "button"):
                if "more" in btn.text.lower():
                    btn.click(); self._delay(1, 2)
                    for item in d.find_elements(By.CSS_SELECTOR, '[role="menuitem"]'):
                        if "connect" in item.text.lower():
                            item.click(); self._delay(1, 2); break
                    break

        if connect_btn:
            connect_btn.click(); self._delay(1.5, 3)
            # Try adding a note
            try:
                add = WebDriverWait(d, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '[aria-label="Add a note"]'))
                )
                add.click(); self._delay(0.5, 1.5)
                ta = d.find_element(By.CSS_SELECTOR, "textarea#custom-message")
                ta.clear(); ta.send_keys(note); self._delay(1, 2)
            except Exception:
                pass  # note dialog didn't appear — still sends without note
            # Click Send
            try:
                send = WebDriverWait(d, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        '[aria-label="Send now"],[aria-label="Send invitation"]'))
                )
                send.click(); self._delay(2, 4)
                logger.info(f"Connected to {target.name}")
                return "connected"
            except Exception:
                pass
        logger.warning(f"Could not connect to {target.name}")
        return "failed"

    def bulk_connect(self, targets: list) -> list:
        results = []
        for t in targets:
            r = self.connect(t)
            results.append(r)
            if r.action == "skipped" and r.error == "daily_limit":
                break
            self._delay(5, 15)
        return results

    def quit(self):
        if self._driver:
            try: self._driver.quit()
            except Exception: pass
            self._driver = None
