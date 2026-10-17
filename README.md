# forms

forms - a checkpoint for clinical questionnaires: strict yes/no questions, filled in by patients, clinicians and their assistants, kept as an append-only log that any agent can replay and check.

> Example data is synthetic (`SYNTH-` ids, 1930s dates, made-up people). forms is a research prototype. It is not a medical device and has not been approved for use with real patient data.

---

## Clinical abstract

Questionnaires before a clinic visit or a procedure are often the first place a safety problem shows up: an allergy, a blood thinner, a low mood. On paper or in a loose web form, a blank is easily read as "no", a decline vanishes, and an assistant's guess can look like the patient's own answer.

forms treats each questionnaire as a checkpoint. Every question is a plain yes/no. The patient, a clinician, or an assistant acting for one of them answers it; an assistant's answer stays provisional until the right person confirms it. A yes, a decline or an unknown on a safety-critical question opens a same-day (or before-procedure) entry for a clinician, and the form cannot pass until a clinician has looked at it. Nothing is ever overwritten: every answer and correction is kept in order, so the record can be replayed and checked.

What the clinician sees: complete, not yet, or invalid, with the reason, and a queue of items needing review. What forms is not: it gives no clinical advice, does not interpret answers, is not a medical device, and runs on synthetic data only.

---

## Purpose

forms runs yes/no questionnaires as an agentic environment. It works in any clinical setting: medicine, nursing, allied health, and forms that patients fill in themselves. Each question must be answered true or false, declined, or skipped by a stated condition. Nothing passes the checkpoint until every applicable answer is in and confirmed by the right person. forms does not give clinical advice and does not decide what an answer means; it records answers and refuses anything the rules don't allow.

## Engineering specification

System: one questionnaire environment over an append-only JSONL log. Actors reach it through `observe` and `step`; `reset`, `replay`, `check` and `export` are harness-only. Settings read: `WARD_SIBLINGS_DIR` (signed wording folder), `TEST_SEED` (test order). Standard library only, Python 3.11+.

## Model

- **Items.** A form is a versioned list of questions in TOML: `form_id`, `version`, `audience` (patient or clinician) and ordered `[[question]]` entries with `id`, `version`, `text`, `alert_answer`, `safety_critical` and `clinician_must_confirm`. Optional fields: `ask_if` (the only way to skip a question), `disciplines` (who may confirm a safety-critical question), `alert_route` (safety-critical questions only), `sensitive` (listed by export; queue lines never quote it) and `two_item_ok`.
- **Log.** An append-only JSONL event log. Status, bitsets and flags are rebuilt by replaying the log. Every line is checked again on replay. Bitsets are only a fast view of that state.
- **Build checks.** Questions worded as negatives are refused, and so are questions joining two items with "and", "or", a comma or a slash. A question marked `two_item_ok` goes to a clinician queue file instead.
- **Follow-up questions.** A question with `ask_if` waits while its parent is blank (listed in the clinician queue). It must be answered when the parent is answered yes, declined or not yet confirmed. It is skipped only when the parent is answered no.
- **Same-day queue.** On a safety-critical question, a yes (the alert answer), a decline, or an answer still unknown at a submission opens a same-day entry in the clinician queue, naming the question and event and a status from a signed list. The form cannot pass until a clinician reviews it (`review` closes all entries) or closes the entry with `close_sameday` and one of the signed statuses. If the patient later changes the answer to no, the entry stays (status: patient changed answer) until reviewed. The patient is told someone will contact them today for a confirmed yes, a decline or an unknown.
- **Alert routes.** A safety-critical question may set `alert_route` to `same_day` (the default) or `before_procedure`. A before-procedure question uses its own queue entry, with the same statuses, and tells the patient the care team will check the question with them before any treatment or procedure.
- **Approval.** Nothing can be filled in until a clinician approves that exact version. Any edit needs a fresh approval, and the approval view shows only what changed.

## Roles

There are four roles, fixed when a session opens. Anyone else is refused. Permissions live in one table (`PERMS` in `forms.py`).

| Role | May |
|---|---|
| `patient` | answer, decline, confirm, grant and revoke access for a named assistant (`--agent`; patient forms only) |
| `patient_agent` | answer, only with a grant naming its own id; never final until the patient confirms |
| `clinician` (with `--discipline`, e.g. medicine, nursing, physiotherapy, pharmacy) | answer, confirm, approve |
| `clinician_agent` (with `--scope`) | answer; never final until a clinician confirms in their own session |

Scope of practice applies per item: a safety-critical question can only be confirmed by its listed `disciplines`, or by the approving clinician's discipline when none are listed. A decline is never read as "no".

## Answers given for the patient

Version 1 gives parents, guardians and substitute decision-makers no session of their own. When one answers, a clinician records it in their own session and picks the role from a fixed list. The patient then sees who answered for them. Never use the patient's session for this.

In practice, when a parent, guardian or substitute decision-maker answers for the patient, a clinician records it in their own session with `--on_behalf parent|guardian|sdm` (the field `on_behalf` on an `answer` event). Only a clinician may set it, and only from that signed list; free text and other values such as `carer` are refused (exit 2). The log keeps the relationship with the answer, `export` shows it under `given_by`, and the patient sees "[relationship] answered for you, recorded by your care team on [date]." Never enter these answers through the patient's own session.

## Interface

`FormEnv` in `forms.py` is the environment. A session (person or agent) reaches it only through `call(method, ...)`, and the per-call table `CALL_PERMS` allows only `observe` and `step`. Everything else belongs to the harness and is refused with "Refused: only the system running this session can start it again or replay it."

- `reset(case_file, actor, role, episode_id, discipline=None, scope=())` (harness) opens a session on one form and episode.
- `observe(item=None)` (session) shows only what the role may see: a patient's agent sees only forms its patient granted; a clinician's agent sees only forms approved inside its clinician's scope. A refused read gets "Refused: you don't have access to this.", the same line whether or not the item exists.
- `step(action)` (session) passes the action through the gate (type, role, discipline) and appends it to the log, or refuses it with a fixed line.
- `step({"type": "submit", ...})` runs the check once and logs the submission with its result. A fail returns the missing items and the episode continues; only a pass is final. After 3 failed submissions in a row the episode goes to the clinician queue and agents are refused until a clinician sends `review`. A clinician can always finish in their own session.
- `check()` (harness) is a deterministic checker with no model.
- `replay(log)` (harness) rebuilds state from a log; the same log always gives the same state, and every logged submission result is recomputed.
- `open_episode(synthetic, timestamp)` (harness) writes the `synthetic` flag as the first log event. It can never be set again or changed.
- `export()` (harness) reads that flag, never the episode id, and refuses any episode not marked synthetic. Export carries the `interpreter` field (set only by a clinician session on answer events).

The command line wraps the same calls. Exit codes: 0 complete, 1 not yet complete, 2 invalid or refused.

## Quickstart

Python 3.11 or later, standard library only.

```bash
git clone https://github.com/wetware-hq/forms.git
cd forms
python3 forms.py build   examples/physio_falls_risk.toml
python3 forms.py open    examples/physio_falls_risk.toml log.jsonl SYNTH-EP-1 --synthetic true --ts 1936-05-02T08:59
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

Every rule is a row in `RULES.md` with its signer, class (safety or efficacy), the role it protects and the tests that plant its failure.

Everything a person sees comes from `WORDING.md`: the signed line ids and wording (every fill-in value, such as a queue status or a relationship word, is its own row) and any lines still pending signature. It is generated by `scripts/sync_wording.py` from the signed table and carries the SHA-256 of its content in its header. `messages.py` reads only `WORDING.md` and holds no wording of its own.

```bash
python3 scripts/rulecheck.py                  # exit 0: every rule has a test, WORDING.md matches its hash, register rows match it
python3 scripts/mutate.py     # exit 0: every mutant of every function in safety_functions.toml is caught
```

The tests check `WORDING.md` against its header hash and check that every line id used in the code exists in it. Before pushing, maintainers run `python3 scripts/prepush.py SIGNED_TABLE.md`, which compares `WORDING.md` with the signed table and fails on internal names or local paths.

## Tests

```bash
python3 -m pytest -q
```

Contributors run pytest and `scripts/rulecheck.py` before every commit. Agent rules are in [AGENTS.md](AGENTS.md). What a green covers and what it does not — so a green here is not read as the same assurance as a green elsewhere — is [BAR.md](BAR.md).

## Planned

An MCP server is planned. There isn't one yet. All lines in `WORDING.md` are signed. Lines still waiting for signature are in `messages.PENDING` (draft: `WORDING_PENDING.md`); `CQ-SAMEDAY-ALERT` is a placeholder until it is drafted.

## Licence

MIT. See [LICENSE](LICENSE).

## Live-model status

S05 and S07 were checked with a scripted stand-in, not a real AI model. The scripted runs show the checks catch the mistakes those two scenarios are for. They don't show how a real model behaves. Those tests are still to come.

## Status

Not for use with real patients.
