JOB APPLICATION AUTOMATION BOT
================================
Built on AIHawk + Groq (FREE - no credit card needed)


WHAT IT DOES
------------
  1. Watches your college Gmail for job/placement emails
     -> Finds Google Form links -> AI fills and submits them

  2. Searches LinkedIn for jobs matching your preferences
     -> Easy Apply via AIHawk (original feature)

  3. Tailors your CV for each JD using Groq LLM
     -> Shows ATS score before/after
     -> Saves optimised PDF

  4. Sends personalised cold emails to recruiters via Gmail

  5. Sends LinkedIn connection requests with personalised notes

  6. Tracks every application in applications.json + applications.csv


FREE TOOLS USED
---------------
  Groq API       -- free LLM (no CC needed)  https://console.groq.com
  Gmail API      -- free                      https://console.cloud.google.com
  LinkedIn       -- your existing account
  Playwright     -- free browser automation


SETUP (5 steps)
---------------

  Step 1: Install dependencies
    pip install -r requirements.txt
    playwright install chromium

  Step 2: Get your FREE Groq API key
    Go to: https://console.groq.com
    Sign up (no credit card) -> API Keys -> Create Key
    Copy the key (starts with gsk_...)

  Step 3: Fill in data_folder/secrets.yaml
    llm_api_key: "gsk_YOUR_GROQ_KEY_HERE"
    linkedin_email: "you@college.edu"
    linkedin_password: "yourpassword"
    cold_email_dry_run: true      <- change to false when ready
    linkedin_dry_run: true        <- change to false when ready

  Step 4: Fill in YOUR details
    Edit data_folder/plain_text_resume.yaml with your real info
    Edit data_folder/work_preferences.yaml for job search filters

  Step 5: Gmail API (for college email watcher + cold emails)
    a. Go to https://console.cloud.google.com
    b. Create project -> Enable Gmail API
    c. Credentials -> OAuth 2.0 -> Desktop App -> Download credentials.json
    d. Save to data_folder/credentials.json
    e. First run opens browser to authorise (one-time only)


RUNNING THE BOT
---------------
  python orchestrator.py                  # full auto mode
  python orchestrator.py --email-only     # only watch college email
  python orchestrator.py --apply-only     # only job search + apply
  python orchestrator.py --outreach-only  # only cold email + LinkedIn
  python orchestrator.py --status         # show stats


FREE GROQ MODELS USED (automatically set in code)
--------------------------------------------------
  llama-3.3-70b-versatile  = best quality  (1,000 req/day free)
  llama-3.1-8b-instant     = high volume   (14,400 req/day free)
  Auto rate-limit retry built in (waits and retries if limit hit)


OUTREACH TARGETS
----------------
  Add recruiters to data_folder/outreach_targets.yaml:
    - name: "Jane Smith"
      email: "jane@company.com"
      linkedin_url: "https://linkedin.com/in/jane-smith"
      company: "Google"
      role: "SWE Intern"
      jd_text: "Python, ML, GCP required..."


OUTPUT FILES
------------
  data_folder/applications.json      full log of every application
  data_folder/applications.csv       open in Excel or Google Sheets
  data_folder/tailored_resumes/      ATS-optimised PDF per company
  data_folder/sent_emails.json       cold email log
  data_folder/linkedin_sent.json     LinkedIn outreach log
  data_folder/automation.log         full run log


SAFETY NOTES
------------
  - LinkedIn: max 15 connections/day built in (ban threshold is ~25-30)
  - Everything defaults to dry_run: true -- nothing sends until you change it
  - credentials.json is in .gitignore -- never commit it
  - ATS threshold: bot skips if score < 35 (change minimum_score in tailor call)


TROUBLESHOOTING
---------------
  LinkedIn login fails?
    -> Set linkedin_headless: false, run once manually, solve CAPTCHA

  Gmail auth fails?
    -> Delete data_folder/gmail_token.json and re-run (browser re-auths)

  Form not filling?
    -> Set headless: False in form_filler call to watch it live

  Groq rate limit hit?
    -> The bot auto-retries after 20/40/60 seconds
    -> Switch to llama-3.1-8b-instant for higher volume (14,400/day)

  ATS score too low?
    -> Add more skills, projects, certifications to plain_text_resume.yaml
