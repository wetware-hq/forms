# forms

Simple yes/no questionnaires that a program or an agent can fill in, one episode at a time.

- **Schema** (TOML): `form_id`, `version`, `audience` (patient or clinician) and an ordered list of
  `[[question]]`. Each question has `id`, `version`, `text`, `alert_answer`, `safety_critical`,
  `clinician_must_confirm`, and optionally `ask_if = {id, equals, wording}`. That is the only way a
  question can be skipped. Negatively worded questions and questions that ask two things are refused.
- **Store**: an append-only event log (answer, decline, confirm). Each event carries the question
  version and the episode. The bitsets (`answered`, `value`) are only a view worked out from the log.
- Answers must be real true/false. A decline has no value and is never read as "no".
- An assistant's answer on a patient form stays marked as the assistant's until the patient confirms it.
- An answer from an old question version or another episode puts the question back to unanswered.
- Questions marked `clinician_must_confirm` count only with a clinician's answer.
- The alert answer always raises a flag. On a safety-critical question, no answer or a decline raises an alert too.
- Agents never guess. Every answer is an explicit event.
- All text shown to people comes from `messages.py`, keyed by wording line id.
  `scripts/rulecheck.py` checks that and checks that every rule in `RULES.md` has a test.

```
python3 forms.py build  examples/pre_procedure_safety.toml
python3 forms.py answer examples/pre_procedure_safety.toml log.jsonl SYNTH-EP-1 clinician SYNTH-dr 1936-05-02T09:00 consent_signed=true
python3 forms.py status examples/pre_procedure_safety.toml log.jsonl SYNTH-EP-1   # 0 complete, 1 not yet, 2 invalid
python3 forms.py export examples/pre_procedure_safety.toml log.jsonl SYNTH-EP-1
```

`FormEnv` offers `reset`, `observe`, `step`, `check` and `replay` for agents. An MCP server is
planned once the core passes. There isn't one yet. Example data is made up. Standard library only.
