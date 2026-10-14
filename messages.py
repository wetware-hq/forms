"""Loads user-facing text from WORDING.md; no wording is written here. Every line is keyed by its wording-table id.
Text in [ ] is filled from schema/table fields only. Conditions with no wording line yet
return a machine code 'ERR:<name>' (not prose) so they stay visible as wording gaps."""
import re

import pathlib

# Every word a person sees comes from WORDING.md, generated from the signed table by scripts/sync_wording.py.
WORDING = pathlib.Path(__file__).resolve().parent / "WORDING.md"
_TEXT = WORDING.read_text()
_BODY = _TEXT.split("\n\n", 1)[1]
SHA256 = re.search(r"^sha256: ([0-9a-f]{64})$", _TEXT, re.M).group(1)
# Signed lines: id -> wording.
LINES = dict(re.findall(r"^\| ([A-Z]{2,4}-[A-Z0-9-]+) \| ([^|]*?) \|$", _BODY, re.M))
# Lines in use but not yet signed (reported by rulecheck as pending).
PENDING = dict(re.findall(r"^\| ([A-Z]{2,4}-[A-Z0-9-]+) \| ([^|]*?) \| pending \|$", _BODY, re.M))
# Signed legal decision-making roles: role id -> (patient wording, clinician wording), from rows REL-<ROLE>-PT/-CLIN.
RELATIONSHIP = {role: (LINES[f"REL-{role.upper()}-PT"], LINES[f"REL-{role.upper()}-CLIN"])
                for role in ("parent", "guardian", "sdm")}
# CQ-SAMEDAY-ALERT / CQ-BEFORE-PROC [status], from rows ST-<STATUS>.
SAMEDAY_STATUS = {k: LINES[f"ST-{k.upper()}"] for k in ("unconfirmed", "confirmed", "changed", "declined", "unknown")}
SLOT = re.compile(r"\[([^\]]+)\]")
KEY = {"condition plain wording": "condition", "Yes/No": "yesno", "alert answer": "yesno",
       "job text": "job_text", "n": "n", "k": "k", "a": "a", "b": "b", "date": "date",
       "owner": "owner", "time": "time",
       "question or job plain wording": "plain", "id": "id", "field": "field", "item": "item", "disciplines": "disciplines", "discipline": "discipline",
       "relationship": "relationship", "items": "items", "parent question text": "parent_text", "m": "m", "question text": "text", "item_id": "item_id", "event_id": "event_id", "status": "status"}


def msg(line_id, **f):
    def fill(m):
        v = f[KEY[m.group(1)]]
        return ("Yes" if v else "No") if isinstance(v, bool) else str(v)
    return SLOT.sub(fill, LINES[line_id] if line_id in LINES else PENDING[line_id])


def code(name):
    return "ERR:" + name
