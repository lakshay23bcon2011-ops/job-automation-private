"""
Google Form Auto-Filler  (uses Groq - FREE)
=============================================
Opens a Google Form URL in Playwright, scrapes every question,
uses Groq to generate answers from your profile, fills + submits.

Install: pip install playwright && playwright install chromium
"""

import re, json, time, logging
from dataclasses import dataclass
from typing import Optional

from src.groq_client import chat, GROQ_QUALITY

logger = logging.getLogger("form_filler")

_ANSWER_SYS = """You fill Google Form job application questions on behalf of a candidate.
RULES:
- Use ONLY facts from the candidate profile. Never invent anything.
- For yes/no questions: answer exactly "Yes" or "No".
- For multiple-choice: return the EXACT text of one option.
- Keep free-text answers under 3 sentences unless more is explicitly asked.
- Return ONLY valid JSON, no markdown:
  {"answers":[{"index":0,"answer":"..."},{"index":1,"answer":"..."}]}
"""


@dataclass
class FormFillResult:
    url: str
    questions_found: int
    questions_answered: int
    submitted: bool
    error: Optional[str] = None


class GoogleFormFiller:
    """
    Usage:
        filler = GoogleFormFiller(profile=my_profile_dict, llm_api_key="gsk_...")
        result = filler.fill("https://docs.google.com/forms/d/xxx/viewform")
    """
    def __init__(self, profile: dict, llm_api_key: str,
                 headless=True, dry_run=False):
        self.profile    = profile
        self.api_key    = llm_api_key
        self.headless   = headless
        self.dry_run    = dry_run

    def fill(self, form_url: str) -> FormFillResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("Run: pip install playwright && playwright install chromium")

        logger.info(f"Opening form: {form_url}")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page    = browser.new_page()
            try:
                page.goto(form_url, wait_until="networkidle", timeout=30000)
                time.sleep(2)

                questions = self._scrape(page)
                if not questions:
                    return FormFillResult(form_url, 0, 0, False,
                                         "No questions found (login required?)")

                answers   = self._get_answers(questions)
                answered  = self._fill(page, questions, answers)
                submitted = False
                if not self.dry_run and answered > 0:
                    submitted = self._submit(page)
                return FormFillResult(form_url, len(questions), answered, submitted)

            except Exception as e:
                logger.error(f"Form fill error: {e}")
                return FormFillResult(form_url, 0, 0, False, str(e))
            finally:
                browser.close()

    # ── scrape ────────────────────────────────────────────────────────────────
    def _scrape(self, page) -> list:
        qs = []
        containers = page.query_selector_all('[role="listitem"]')
        for i, c in enumerate(containers):
            try:
                title_el = (c.query_selector('.M7eMe') or
                            c.query_selector('[data-params]') or
                            c.query_selector('.HoXoMd'))
                if not title_el:
                    continue
                text = title_el.inner_text().strip()
                if not text:
                    continue
                required = c.query_selector('[aria-required="true"]') is not None
                if c.query_selector('input[type="radio"]'):
                    opts  = [e.inner_text().strip() for e in c.query_selector_all('[data-value]')]
                    ftype = "radio"
                elif c.query_selector('input[type="checkbox"]'):
                    opts  = [e.inner_text().strip() for e in c.query_selector_all('[data-value]')]
                    ftype = "checkbox"
                elif c.query_selector('[role="listbox"]') or c.query_selector('select'):
                    opts  = [e.inner_text().strip() for e in c.query_selector_all('[role="option"]')]
                    ftype = "dropdown"
                elif c.query_selector('textarea'):
                    opts, ftype = [], "textarea"
                elif c.query_selector('input[type="date"]'):
                    opts, ftype = [], "date"
                else:
                    opts, ftype = [], "text"
                qs.append({"index": i, "text": text, "type": ftype,
                           "options": [o for o in opts if o], "required": required})
            except Exception:
                continue
        return qs

    # ── Groq answers ──────────────────────────────────────────────────────────
    def _get_answers(self, questions: list) -> dict:
        pi  = self.profile.get("personal_information", {})
        exp = self.profile.get("experience_details", [])
        skills = []
        for e in exp[:2]:
            skills += e.get("skills_acquired", [])
        profile_summary = (
            f"Name: {pi.get('name','')} {pi.get('surname','')}\n"
            f"Email: {pi.get('email','')}\n"
            f"Phone: {pi.get('phone_prefix','')}{pi.get('phone','')}\n"
            f"Education: {self.profile.get('education_details',[{}])[0].get('institution','')}\n"
            f"Field: {self.profile.get('education_details',[{}])[0].get('field_of_study','')}\n"
            f"Skills: {', '.join(skills[:15])}\n"
            f"LinkedIn: {pi.get('linkedin','')}\n"
            f"GitHub: {pi.get('github','')}\n"
        )
        prompt = (
            f"CANDIDATE PROFILE:\n{profile_summary}\n\n"
            f"FORM QUESTIONS:\n{json.dumps(questions, indent=2)}\n\n"
            "Answer all questions. For choice-based types, match EXACT option text."
        )
        raw = chat(self.api_key,
                   [{"role":"system","content":_ANSWER_SYS},
                    {"role":"user","content":prompt}],
                   model=GROQ_QUALITY, temperature=0.2, max_tokens=1500)
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
        try:
            return {a["index"]: a["answer"] for a in json.loads(clean).get("answers", [])}
        except Exception:
            logger.error("Answer parse failed.")
            return {}

    # ── fill ──────────────────────────────────────────────────────────────────
    def _fill(self, page, questions, answers) -> int:
        filled = 0
        all_containers = page.query_selector_all('[role="listitem"]')
        for q in questions:
            ans = str(answers.get(q["index"], "")).strip()
            if not ans:
                continue
            try:
                c = all_containers[q["index"]]
                ft = q["type"]
                if ft in ("text", "textarea"):
                    inp = c.query_selector("textarea") or c.query_selector("input")
                    if inp:
                        inp.click(); inp.fill(ans); filled += 1
                elif ft == "radio":
                    for el in c.query_selector_all('[data-value]'):
                        if el.inner_text().strip().lower() == ans.lower():
                            el.click(); filled += 1; break
                elif ft == "checkbox":
                    targets = {a.strip().lower() for a in ans.split(",")}
                    for el in c.query_selector_all('[data-value]'):
                        if el.inner_text().strip().lower() in targets:
                            el.click(); filled += 1; break
                elif ft == "dropdown":
                    trigger = c.query_selector('[role="listbox"]') or c.query_selector("select")
                    if trigger:
                        trigger.click(); time.sleep(0.4)
                        for item in page.query_selector_all('[role="option"]'):
                            if item.inner_text().strip().lower() == ans.lower():
                                item.click(); filled += 1; break
                elif ft == "date":
                    inp = c.query_selector("input")
                    if inp:
                        inp.fill(ans); filled += 1
            except Exception as e:
                logger.warning(f"Fill Q{q['index']} ({ft}): {e}")
        return filled

    def _submit(self, page) -> bool:
        try:
            btn = (page.query_selector('[aria-label="Submit"]') or
                   page.query_selector('.uArJ5e[jsname="M2UYVd"]') or
                   page.query_selector('div[role="button"]:has-text("Submit")'))
            if btn:
                btn.click(); time.sleep(2)
                logger.info("Form submitted.")
                return True
            logger.warning("Submit button not found.")
            return False
        except Exception as e:
            logger.error(f"Submit error: {e}")
            return False
