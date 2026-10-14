"""The only place user-facing text lives. Every line is keyed by its wording-table id.
Text in [ ] is filled from schema/table fields only. Conditions with no wording line yet
return a machine code 'ERR:<name>' (not prose) so they stay visible as wording gaps."""
import re

LINES = {
    "PV-ANS-SELF": "You answered",
    "PV-ANS-AGENT": "Your assistant answered. You haven't checked this yet.",
    "PV-DECLINED": "You chose not to answer",
    "PV-SKIPPED": "Not asked, because [condition plain wording]",
    "PV-OPEN": "Not answered yet",
    "PV-GRANT": "Your assistant can help with this form (from [date])",
    "PV-REVOKE": "Your assistant can no longer help with this form (from [date])",
    "PV-REASK": "We need to ask this again because the question changed or this is a new visit.",
    "PV-CONFIRM": "Your assistant answered [Yes/No]. Is that right?",
    "RF-ROLE-CANCEL": "Refused: only a clinician's own session can cancel a safety job.",
    "RF-ROLE-CONFIRM": "Refused: only the patient's own session can confirm or decline this answer.",
    "RF-NO-GRANT": "Refused: the patient has not let an assistant help with this form.",
    "RF-REVOKED": "Refused: the patient stopped this assistant helping on [date].",
    "RF-NOT-BOOL": "Refused: answers must be Yes or No.",
    "RF-PERSON-JOB": "Refused: a person must do this job and tick it in their own session.",
    "RF-EVIDENCE": "Refused: a tick needs a record id, such as a result or a sent document.",
    "RF-WAITING": "Refused: this job waits on [job text], which is not done yet.",
    "RF-CANCEL-REASON": "Refused: cancelling needs a reason.",
    "RF-NOT-APPROVED": "Refused: this form or list is not approved by a clinician yet.",
    "CK-TWO-FACTS": "Question [n] asks more than one thing. Split it.",
    "CK-NEGATIVE": "Question [n] is worded as a negative. Reword it as a plain question.",
    "CK-NO-ALERT": "Question [n] has no alert answer set.",
    "CK-COND-ORDER": "Question [n] depends on a later question.",
    "CK-COND-WORDS": "Question [n] has a condition with no plain wording.",
    "CK-LOOP": "Jobs [a] and [b] wait on each other, so neither can be done.",
    "CK-NO-SOURCE": "Job [n] does not say which line it came from.",
    "BK-UNANSWERED": "Not finished: [k] questions still need an answer.",
    "BK-CLIN-CONFIRM": "Not finished: a clinician must confirm question [n].",
    "BK-STALE": "Answer to question [n] is from another episode or an old version, so it must be asked again.",
    "FL-ALERT": "Alert: question [n] was answered [alert answer].",
    "FL-UNKNOWN": "Alert: question [n] is safety-critical and was not answered. Treat as a risk.",
    "FL-DECLINED": "Alert: the patient chose not to answer question [n], which is safety-critical. Treat as a risk and ask in person.",
    "FL-OVERDUE": "Overdue: [job text], owner [owner], due [time].",
    "FL-GAP": "No job was made from source line [n]. Approve or add one.",
}
SLOT = re.compile(r"\[([^\]]+)\]")
KEY = {"condition plain wording": "condition", "Yes/No": "yesno", "alert answer": "yesno",
       "job text": "job_text", "n": "n", "k": "k", "a": "a", "b": "b", "date": "date",
       "owner": "owner", "time": "time"}


def msg(line_id, **f):
    def fill(m):
        v = f[KEY[m.group(1)]]
        return ("Yes" if v else "No") if isinstance(v, bool) else str(v)
    return SLOT.sub(fill, LINES[line_id])


def code(name):
    return "ERR:" + name
