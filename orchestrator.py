"""
Job Automation Orchestrator
============================
Runs the full pipeline:
  1. College email watcher (background) -- finds forms, fills them
  2. AIHawk job search + Easy Apply (background)
  3. Cold email + LinkedIn outreach (runs once then loops)
  4. Tracks every application to JSON + CSV

Usage:
  python orchestrator.py                  # full auto
  python orchestrator.py --email-only
  python orchestrator.py --apply-only
  python orchestrator.py --outreach-only
  python orchestrator.py --status
"""

import argparse, logging, sys, time, threading
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.college_email_watcher import CollegeEmailWatcher
from src.form_filler            import GoogleFormFiller
from src.ats_tailor             import ATSTailor
from src.cold_email             import ColdEmailSender, EmailTarget
from src.linkedin_messenger     import LinkedInMessenger, LinkedInTarget
from src.tracker                import ApplicationTracker, AppRecord

# ── logging ──────────────────────────────────────────────────────────────────
Path("data_folder").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data_folder/automation.log"),
    ]
)
logger = logging.getLogger("orchestrator")


# ── config loader ─────────────────────────────────────────────────────────────
def load_cfg() -> dict:
    cfg = {}
    for f in ["data_folder/plain_text_resume.yaml",
              "data_folder/secrets.yaml",
              "data_folder/work_preferences.yaml"]:
        try:
            cfg.update(yaml.safe_load(Path(f).read_text()) or {})
        except FileNotFoundError:
            logger.warning(f"Config missing: {f}")
    return cfg


# ── helpers ───────────────────────────────────────────────────────────────────
def profile_to_text(p: dict) -> str:
    lines = []
    pi = p.get("personal_information", {})
    lines.append(f"{pi.get('name','')} {pi.get('surname','')}")
    for edu in p.get("education_details", []):
        lines.append(f"{edu.get('education_level','')} in "
                     f"{edu.get('field_of_study','')} at {edu.get('institution','')}")
    for exp in p.get("experience_details", []):
        lines.append(f"{exp.get('position','')} at {exp.get('company','')}")
        for r in exp.get("key_responsibilities", []):
            lines.append(f"  - {r.get('responsibility','')}")
        lines.append("Skills: " + ", ".join(exp.get("skills_acquired", [])))
    for proj in p.get("projects", []):
        lines.append(f"Project: {proj.get('name','')} - {proj.get('description','')}")
    for cert in p.get("certifications", []):
        lines.append(f"Cert: {cert.get('name','')}")
    return "\n".join(lines)


# ── pipeline: college email ───────────────────────────────────────────────────
def run_email_pipeline(cfg: dict):
    api_key      = cfg.get("llm_api_key", "")
    cred_path    = cfg.get("credentials_path", "data_folder/credentials.json")
    resume_text  = profile_to_text(cfg)
    tailor       = ATSTailor(api_key)
    filler       = GoogleFormFiller(cfg, api_key, headless=True, dry_run=False)
    tracker      = ApplicationTracker()

    def on_job(info: dict):
        logger.info(f"College job email: {info['subject']}")
        jd = info.get("raw_body", "")
        for url in info.get("form_links", []):
            if api_key and jd:
                r = tailor.tailor(resume_text, jd,
                                  job_title=info["subject"][:60],
                                  company="College Placement",
                                  minimum_score=15.0)
                logger.info(f"ATS: {r.original_score} -> {r.tailored_score}")
            res = filler.fill(url)
            tracker.add(AppRecord(
                company="College Placement",
                role=info["subject"][:60],
                via="form", source="college_email",
                status="applied" if res.submitted else "draft",
                notes=f"Form: {url}",
            ))

    watcher = CollegeEmailWatcher(
        credentials_path=cred_path,
        poll_interval=int(cfg.get("email_poll_interval_seconds", 300)),
    )
    t = threading.Thread(target=watcher.watch, args=(on_job,), daemon=True)
    t.start()
    logger.info("College email watcher running in background.")
    return t


# ── pipeline: AIHawk job apply ────────────────────────────────────────────────
def run_apply_pipeline(cfg: dict):
    import subprocess
    logger.info("Starting AIHawk job search + apply...")
    try:
        proc = subprocess.Popen([sys.executable, "main.py"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            print(line, end="")
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    except Exception as e:
        logger.error(f"AIHawk error: {e}")


# ── pipeline: outreach ────────────────────────────────────────────────────────
def run_outreach(cfg: dict):
    api_key   = cfg.get("llm_api_key", "")
    targets_f = "data_folder/outreach_targets.yaml"
    try:
        raw = yaml.safe_load(Path(targets_f).read_text()) or []
    except FileNotFoundError:
        logger.warning(f"No outreach targets at {targets_f}. Skipping.")
        return

    email_targets = []
    li_targets    = []
    for t in raw:
        if t.get("email"):
            email_targets.append(EmailTarget(
                name=t.get("name","HR"), email=t["email"],
                company=t.get("company",""), role=t.get("role",""),
                jd_text=t.get("jd_text","")))
        if t.get("linkedin_url"):
            li_targets.append(LinkedInTarget(
                profile_url=t["linkedin_url"], name=t.get("name",""),
                company=t.get("company",""), role=t.get("role",""),
                jd_text=t.get("jd_text","")))

    cred = cfg.get("credentials_path","data_folder/credentials.json")

    if email_targets and Path(cred).exists():
        sender = ColdEmailSender(
            profile=cfg, llm_api_key=api_key,
            credentials_path=cred,
            dry_run=cfg.get("cold_email_dry_run", True))
        res = sender.send_bulk(email_targets)
        sent = sum(1 for r in res if r.sent)
        logger.info(f"Cold emails: {sent}/{len(email_targets)} sent.")
    elif email_targets:
        logger.warning("credentials.json not found -- skipping cold email.")

    li_email = cfg.get("linkedin_email","")
    li_pass  = cfg.get("linkedin_password","")
    if li_targets and li_email and li_pass:
        li = LinkedInMessenger(
            profile=cfg, linkedin_email=li_email, linkedin_password=li_pass,
            llm_api_key=api_key,
            headless=cfg.get("linkedin_headless", False),
            dry_run=cfg.get("linkedin_dry_run", True))
        res = li.bulk_connect(li_targets)
        ok  = sum(1 for r in res if r.action in ("connected","dry_run"))
        logger.info(f"LinkedIn: {ok}/{len(li_targets)} processed.")
        li.quit()


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Job Automation Bot (Groq-powered)")
    p.add_argument("--email-only",    action="store_true")
    p.add_argument("--apply-only",    action="store_true")
    p.add_argument("--outreach-only", action="store_true")
    p.add_argument("--status",        action="store_true")
    args = p.parse_args()

    if args.status:
        ApplicationTracker().summary(); return

    cfg = load_cfg()
    key = cfg.get("llm_api_key","")
    if not key or key.startswith("gsk_YOUR"):
        print("\nERROR: Add your Groq API key to data_folder/secrets.yaml")
        print("Get it FREE at https://console.groq.com\n")
        sys.exit(1)

    if args.email_only:
        run_email_pipeline(cfg)
        try:
            while True: time.sleep(60)
        except KeyboardInterrupt:
            pass

    elif args.apply_only:
        run_apply_pipeline(cfg)

    elif args.outreach_only:
        run_outreach(cfg)

    else:
        logger.info("="*55)
        logger.info("  FULL AUTO MODE")
        logger.info("="*55)
        run_email_pipeline(cfg)
        time.sleep(2)
        t = threading.Thread(target=run_apply_pipeline, args=(cfg,), daemon=True)
        t.start()
        time.sleep(5)
        run_outreach(cfg)
        logger.info("All pipelines running. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(300)
                ApplicationTracker().summary()
        except KeyboardInterrupt:
            logger.info("Stopped.")
            ApplicationTracker().summary()


if __name__ == "__main__":
    main()
