# forms

forms - a checkpoint for clinical questionnaires: strict yes/no questions, filled in by patients, clinicians and their assistants, kept as an append-only log that any agent can replay and check.

> Example data is synthetic (`SYNTH-` ids, 1930s dates, made-up people). forms is a research prototype. It is not a medical device and has not been approved for use with real patient data.

## Purpose

forms runs yes/no questionnaires as an agentic environment. It works in any clinical setting: medicine, nursing, allied health, and forms that patients fill in themselves. Each question must be answered true or false, declined, or skipped by a stated condition. Nothing passes the checkpoint until every applicable answer is in and confirmed by the right person. forms does not give clinical advice and does not decide what an answer means; it records answers and refuses anything the rules don't allow.

## Model

- **Items.** A form is a versioned list of questions in TOML: `form_id`, `version`, `audience` (patient or clinician) and ordered `[[question]]` entries with `id`, `version`, `text`, `alert_answer`, `safety_critical` and `clinician_must_confirm`. Optional fields: `ask_if` (the only way to skip a question), `disciplines` (who may confirm a safety-critical question) and `two_item_ok`.
- **Log.** An append-only JSONL event log. Status, bitsets and flags are rebuilt by replaying the log. Every line is checked again on replay. Bitsets are only a fast view of that state.
- **Build checks.** Questions worded as negatives are refused, and so are questions joining two items with "and", "or", a comma or a slash. A question marked `two_item_ok` goes to a clinician queue file instead.
- **Approval.** Nothing can be filled in until a clinician approves that exact version. Any edit needs a fresh approval, and the approval view shows only what changed.

## Roles

There are four roles, fixed when a session opens. Anyone else is refused. Permissions live in one table (`PERMS` in `forms.py`).

| Role | May |
|---|---|
| `patient` | answer, decline, confirm, grant and revoke their assistant's access (patient forms only) |
| `patient_agent` | answer; never final until the patient confirms |
| `clinician` (with `--discipline`, e.g. medicine, nursing, physiotherapy, pharmacy) | answer, confirm, approve |
| `clinician_agent` (with `--scope`) | answer; never final until a clinician confirms in their own session |

Scope of practice applies per item: a safety-critical question can only be confirmed by its listed `disciplines`, or by the approving clinician's discipline when none are listed. A decline is never read as "no".

## Answers given for the patient

Version 1 gives parents, guardians and substitute decision-makers no session of their own. When one answers, a clinician records it in their own session and picks the role from a fixed list. The patient then sees who answered for them. Never use the patient's session for this.

In practice, when a parent, guardian or substitute decision-maker answers for the patient, a clinician records it in their own session with `--on_behalf parent|guardian|sdm` (the field `on_behalf` on an `answer` event). Only a clinician may set it, and only from that signed list; free text and other values such as `carer` are refused (exit 2). The log keeps the relationship with the answer, `export` shows it under `given_by`, and the patient sees "[relationship] answered for you, recorded by your care team on [date]." Never enter these answers through the patient's own session.

## Interface

`FormEnv` in `forms.py` is the agent environment:

- `reset(case_file, actor, role, episode_id, discipline=None, scope=())` opens a session on one form and episode.
- `observe()` returns the current state.
- `step(action)` passes the action through the gate (type, role, discipline) and appends it to the log, or refuses it with a fixed message.
- `check()` is a deterministic checker with no model. It returns `complete`, `open`, `blocked`, `flags`, `answers` and `given_by`.
- `replay(log)` rebuilds state from a log; the same log always gives the same state.

The command line wraps the same calls. Exit codes: 0 complete, 1 not yet complete, 2 invalid or refused.

## Quickstart

Python 3.11 or later, standard library only.

```bash
git clone https://github.com/wetware-hq/forms.git
cd forms
python3 forms.py build   examples/physio_falls_risk.toml
python3 forms.py approve examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1 --role clinician --discipline physiotherapy --actor SYNTH-pt-01 --ts 1936-05-02T09:00
python3 forms.py answer  examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1 stands_unaided=true --role clinician --discipline physiotherapy --actor SYNTH-pt-01 --ts 1936-05-02T09:05
python3 forms.py status  examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1
python3 forms.py export  examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1
```

An answer given by a guardian:

```bash
python3 forms.py approve examples/patient_history.toml ph.jsonl SYNTH-EP-2 --role clinician --discipline medicine --actor SYNTH-dr-01 --ts 1934-03-01T10:00
python3 forms.py answer  examples/patient_history.toml ph.jsonl SYNTH-EP-2 smokes=false --on_behalf guardian --role clinician --discipline medicine --actor SYNTH-dr-01 --ts 1934-03-01T10:05
```

Both examples stop at exit 1: the forms are not complete yet.

## Rules

Every rule is a row in `RULES.md` with its signer, class (safety or efficacy), the role it protects and the tests that plant its failure. Everything a person sees comes from `messages.py`, which must match the signed wording table `WORDING.md` word for word; a patient is never shown a machine code.

```bash
python3 scripts/rulecheck.py                  # exit 0: every rule has a test, all wording matches WORDING.md
python3 scripts/mutate.py forms.py _gate      # exit 0: every mutant of the gate is caught
```

## Tests

```bash
python3 -m pytest -q
```

Contributors run pytest and `scripts/rulecheck.py` before every commit. Agent rules are in [AGENTS.md](AGENTS.md).

## Status

An MCP server is planned. There isn't one yet. All wording lines are signed; `WORDING.md` is the signed table.

## Licence

MIT. See [LICENSE](LICENSE).
