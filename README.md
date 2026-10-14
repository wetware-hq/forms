# forms

Simple yes/no questionnaires that patients, clinicians and their assistants fill in. It works in any
clinical setting: medicine, nursing, allied health and patients' own forms.

- **Who can use it.** There are four roles, fixed when a session opens: patient, patient_agent (the patient's
  assistant), clinician (any registered health professional, with a discipline such as medicine,
  nursing, physiotherapy or pharmacy) and clinician_agent. Anyone else is refused. What each role may
  do is set in one permission table (`PERMS` in `forms.py`).
- **Schema** (TOML): `form_id`, `version`, `audience` (patient or clinician) and ordered
  `[[question]]` entries. Each question has `id`, `version`, `text`, `alert_answer`,
  `safety_critical` and `clinician_must_confirm`. Optional fields: `ask_if` (the only way a question
  is skipped), `disciplines` (who may confirm a safety-critical question) and `two_item_ok`.
- **Checks at build.** Questions worded as negatives are refused, and so are questions that join items
  with "and", "or", a comma or a slash. A question flagged `two_item_ok` goes to a clinician queue file instead.
- **Approval.** Nothing can be filled in until a clinician approves that exact version. Any edit needs
  a fresh approval, and the approval view shows only what changed.
- **Store.** An append-only event log. Bitsets, status and flags are all worked out from it.
- **Answers and confirms.** Answers must be real true/false. A decline is never read as "no". An
  assistant's answer is never final until it is confirmed: by the patient on a patient form, or by a
  clinician in their own session on a clinician form. The patient grants and revokes their assistant's
  access, and only on patient forms. A safety-critical question can only be confirmed by the listed
  disciplines, or by the approving clinician's discipline if none are listed.
- **Text.** Everything a person sees comes from `messages.py`, the fixed wording table. A patient is
  never shown a machine code. `scripts/rulecheck.py` checks the wording and checks that every rule in
  `RULES.md` has a test. `scripts/mutate.py` checks that the tests catch changes to the gate and
  permission code.

```
python3 forms.py build   examples/physio_falls_risk.toml
python3 forms.py approve examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1 --role clinician --discipline physiotherapy --actor SYNTH-pt-01 --ts 1936-05-02T09:00
python3 forms.py answer  examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1 stands_unaided=true --role clinician --discipline physiotherapy --actor SYNTH-pt-01 --ts 1936-05-02T09:05
python3 forms.py status  examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1   # 0 complete, 1 not yet, 2 invalid
```

## Known limit

Version 1 has no role for substitute decision-makers, such as parents, guardians or carers acting for the patient. Anything they enter through the patient's session would be recorded as "You answered", which would be wrong. Until then, a clinician records the answer in their own session and names who gave it. Never use the patient's session.

`FormEnv` offers `reset`, `observe`, `step`, `check` and `replay` for agents. An MCP server is
planned once the core passes. There isn't one yet. Example data is made up. Standard library only. MIT licence.
