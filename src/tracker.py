"""
Application Tracker
===================
Logs every application with ATS score, status, timestamps.
Saves to: data_folder/applications.json + data_folder/applications.csv
"""

import csv, json, os, time, logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tracker")

CSV_COLS = ["applied_at","company","role","location","status",
            "ats_before","ats_after","via","cold_email","linkedin",
            "job_url","source","notes"]


@dataclass
class AppRecord:
    company:      str
    role:         str
    location:     str = ""
    job_url:      str = ""
    ats_before:   float = 0.0
    ats_after:    float = 0.0
    pdf_path:     str = ""
    via:          str = ""       # linkedin | form | email | manual
    source:       str = ""       # college_email | linkedin_search | manual
    status:       str = "applied"  # applied|interviewing|rejected|offer|withdrawn
    cold_email:   bool = False
    linkedin:     bool = False
    recruiter_email:   str = ""
    recruiter_linkedin: str = ""
    notes:        str = ""
    applied_at:   str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))


class ApplicationTracker:
    def __init__(self, json_path="data_folder/applications.json",
                 csv_path="data_folder/applications.csv"):
        self.jp = json_path
        self.cp = csv_path
        self._data: list[AppRecord] = self._load()

    def _load(self):
        if os.path.exists(self.jp):
            try:
                rows = json.loads(Path(self.jp).read_text())
                return [AppRecord(**r) for r in rows]
            except Exception as e:
                logger.warning(f"Tracker load error: {e}")
        return []

    def _save(self):
        Path(self.jp).parent.mkdir(parents=True, exist_ok=True)
        Path(self.jp).write_text(json.dumps([asdict(r) for r in self._data], indent=2))
        with open(self.cp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
            w.writeheader()
            for r in self._data:
                w.writerow(asdict(r))

    def add(self, r: AppRecord):
        if any(x.company.lower()==r.company.lower() and
               x.role.lower()==r.role.lower() for x in self._data):
            logger.info(f"Already tracked: {r.company} - {r.role}")
            return
        self._data.append(r)
        self._save()
        logger.info(f"Tracked: {r.company} - {r.role}  ATS:{r.ats_after}")

    def update(self, company: str, role: str, status: str, notes=""):
        for r in self._data:
            if r.company.lower()==company.lower() and r.role.lower()==role.lower():
                r.status = status
                if notes: r.notes = notes
                self._save()
                logger.info(f"Updated {company}-{role} -> {status}")
                return
        logger.warning(f"Not found: {company} - {role}")

    def summary(self):
        total = len(self._data)
        if not total:
            print("No applications tracked yet."); return
        by_status: dict = {}
        avg = sum(r.ats_after for r in self._data) / total
        for r in self._data:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        icons = {"applied":"📤","interviewing":"🎯","offer":"🎉",
                 "rejected":"❌","withdrawn":"↩️"}
        print("\n" + "="*50)
        print("  APPLICATION TRACKER")
        print("="*50)
        print(f"  Total      : {total}")
        print(f"  Avg ATS    : {avg:.1f}/100")
        for s, n in sorted(by_status.items()):
            print(f"  {icons.get(s,'•')} {s:<14}: {n}")
        print(f"\n  Cold emails: {sum(1 for r in self._data if r.cold_email)}")
        print(f"  LI connects: {sum(1 for r in self._data if r.linkedin)}")
        print(f"  CSV saved  : {self.cp}")
        print("="*50 + "\n")
