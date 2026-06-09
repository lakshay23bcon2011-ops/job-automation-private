"""
ATS Resume Tailor  (uses Groq - FREE)
======================================
1. Keyword-scores resume vs JD  (0-100)
2. If score >= threshold, calls Groq to rewrite bullet points
3. Saves ATS-friendly PDF to data_folder/tailored_resumes/
"""

import re, json, logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.groq_client import chat, GROQ_QUALITY, GROQ_FAST

logger = logging.getLogger("ats_tailor")

_STOP = {
    "the","a","an","and","or","of","to","in","for","with","on","at","by","from",
    "is","are","was","were","be","been","have","has","will","would","should","may",
    "must","can","do","does","did","this","that","these","those","we","you","they",
    "our","your","their","its","as","up","if","but","not","all","any","each","more",
    "also","other","new","good","able","well","both","own","same","so","than","too",
    "very","just","into","about","over","after","above","below","between","through",
}

MULTI_WORD = re.compile(
    r'\b(?:machine learning|deep learning|natural language processing|computer vision|'
    r'data science|software engineering|full[- ]stack|back[- ]end|front[- ]end|'
    r'ci[/ ]cd|rest api|graphql|agile|scrum|kanban|product management|'
    r'cloud computing|devops|mlops|data engineering|'
    r'aws|azure|gcp|google cloud|amazon web services|'
    r'react(?:\.js)?|node(?:\.js)?|next(?:\.js)?|vue(?:\.js)?|'
    r'spring boot|\.net|asp\.net|postgresql|mysql|mongodb|redis|elasticsearch|'
    r'docker|kubernetes|terraform|ansible|jenkins|github actions)\b'
)

_TAILOR_PROMPT = """You are an expert resume writer and ATS optimisation specialist.

STRICT RULES:
1. NEVER fabricate skills, companies, or experience that are not in the original resume.
2. Rephrase bullet points to naturally include missing keywords ONLY if the underlying skill is real.
3. Add a concise "Key Skills" line at the top if missing.
4. Keep total resume under 600 words.
5. Return ONLY valid JSON, no markdown, no extra text:
   {"tailored_resume":"<full resume text with \\n newlines>","changes_made":["change1","change2"],"still_missing":["kw1"]}
"""


@dataclass
class ATSResult:
    original_score: float
    tailored_score: float
    missing_keywords: list
    matched_keywords: list
    tailored_resume_text: str
    suggestions: list
    pdf_path: str = ""
    skipped: bool = False


def _extract_kw(text: str) -> list:
    t = text.lower()
    multi  = MULTI_WORD.findall(t)
    single = [w for w in re.findall(r'\b[a-z][a-z0-9#+]{2,}\b', t)
              if w not in _STOP and len(w) >= 3]
    return list(set(multi + single))


def _score(resume_kw, jd_kw):
    if not jd_kw:
        return 0.0, [], []
    rs = set(resume_kw)
    matched = [k for k in jd_kw if k in rs]
    missing = [k for k in jd_kw if k not in rs]
    def w(k): return 2.0 if len(k.split()) == 1 and len(k) <= 12 else 1.0
    tw = sum(w(k) for k in jd_kw)
    mw = sum(w(k) for k in matched)
    return round((mw / tw) * 100, 1) if tw else 0.0, matched, missing


def _save_pdf(text: str, path: str):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.enums import TA_LEFT
    except ImportError:
        Path(path.replace(".pdf", ".txt")).write_text(text, encoding="utf-8")
        logger.warning("reportlab not installed — saved .txt instead")
        return path.replace(".pdf", ".txt")

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    normal = ParagraphStyle("N", fontName="Times-Roman", fontSize=10, leading=14, alignment=TA_LEFT)
    bold   = ParagraphStyle("B", fontName="Times-Bold",  fontSize=11, leading=16, alignment=TA_LEFT)
    story  = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 5))
        elif line.isupper() or (len(line) < 50 and line.endswith(":")):
            story.append(Paragraph(line, bold))
        else:
            safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            story.append(Paragraph(safe, normal))
    doc.build(story)
    return path


class ATSTailor:
    def __init__(self, llm_api_key: str,
                 output_dir="data_folder/tailored_resumes"):
        self.api_key    = llm_api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def score_only(self, resume_text: str, jd_text: str):
        return _score(_extract_kw(resume_text), _extract_kw(jd_text))

    def tailor(self, resume_text: str, jd_text: str,
               job_title="Unknown Role", company="Unknown",
               save_pdf=True, minimum_score=35.0) -> ATSResult:

        orig_score, matched, missing = self.score_only(resume_text, jd_text)
        logger.info(f"ATS original: {orig_score}/100 for {job_title} @ {company}")

        if orig_score < minimum_score:
            logger.warning(f"Score {orig_score} < {minimum_score}. Skipping {job_title}.")
            return ATSResult(orig_score, orig_score, missing, matched,
                             resume_text, [], skipped=True)

        prompt = (
            f"JOB TITLE: {job_title}\nCOMPANY: {company}\n\n"
            f"JOB DESCRIPTION:\n{jd_text[:2500]}\n\n"
            f"CURRENT RESUME:\n{resume_text[:2500]}\n\n"
            f"MISSING KEYWORDS TO ADD NATURALLY:\n{json.dumps(missing[:25])}\n\n"
            "Tailor the resume following all system rules."
        )

        raw = chat(self.api_key,
                   [{"role": "system", "content": _TAILOR_PROMPT},
                    {"role": "user",   "content": prompt}],
                   model=GROQ_QUALITY, temperature=0.3, max_tokens=2000)

        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("LLM JSON parse failed — using original resume.")
            data = {"tailored_resume": resume_text, "changes_made": [], "still_missing": missing}

        tailored      = data.get("tailored_resume", resume_text)
        suggestions   = data.get("changes_made", [])
        new_score, new_matched, new_missing = self.score_only(tailored, jd_text)
        logger.info(f"ATS tailored: {orig_score} -> {new_score}/100")

        pdf_path = ""
        if save_pdf:
            safe   = re.sub(r'[^\w\-]', '_', f"{company}_{job_title}")[:55]
            pdf_path = str(self.output_dir / f"{safe}.pdf")
            _save_pdf(tailored, pdf_path)

        return ATSResult(orig_score, new_score, new_missing, new_matched,
                         tailored, suggestions, pdf_path=pdf_path)
