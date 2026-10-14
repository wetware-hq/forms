---
schema: wetware.agent.v1
resource: forms
version: 0.1.0
capabilities: [questionnaire, checkpoint]
inputs:
  form: {type: toml, constraint: "strict yes/no questions; approved version only"}
  log: {type: jsonl, constraint: "append-only; synthetic only: SYNTH- ids, 1930-1939 dates"}
  session: {type: object, fields: [actor, role, discipline, scope, episode_id]}
outputs:
  status: {type: screen, values: [complete, not yet, invalid]}
  export: {type: json, fields: [answers, given_by, bitsets]}
  exit: {type: int}
---

# Agent contract

Normative rules for agents that operate or modify forms. Wording uses RFC 2119: **MUST**, **MUST NOT**, **SHOULD**. Not approved for real patient data.

## Data handling

1. All data **MUST** be synthetic: `SYNTH-` ids, dates from 1930 to 1939, made-up people. Removing a name does not make a record synthetic.
2. If a user pastes real patient data, the agent **MUST** stop, **MUST NOT** repeat or process it, and **MUST** tell the user to report a privacy incident.
3. Fixtures, examples and test logs **MUST** follow rule 1.

## Operating the environment

1. Agents **MUST** act through `FormEnv.call` with `observe` or `step` only, never by writing the log directly. `reset`, `replay`, `check` and `export` are harness-only.
2. A session's role is fixed at `reset`: `patient`, `patient_agent`, `clinician` (with a discipline) or `clinician_agent` (with a scope). An agent **MUST NOT** act in a role it was not given, and **MUST NOT** use a patient's session for anyone else.
3. A refusal from `step` is final for that action. The agent **MUST NOT** retry it under another role, discipline or wording.
4. Completion **MUST** come from a `submit` step (one check per submission), never judged by a model. After 3 failed submissions in a row the agent **MUST** wait for a clinician's review.
5. Answers **MUST** be real true/false. A decline **MUST NOT** be read as "no".
6. An answer from `patient_agent` or `clinician_agent` is not final until confirmed by the patient (patient forms) or a clinician in their own session (clinician forms).
7. An answer given by a parent, guardian or substitute decision-maker **MUST** be recorded by a clinician with `on_behalf` from the signed list (`parent`, `guardian`, `sdm`). No free text.

## Changing code

- `python3 -m pytest -q` and `python3 scripts/rulecheck.py` **MUST** both exit 0 before every commit. A commit **MUST NOT** be made while any test fails.
- Every rule **MUST** be a row in `RULES.md` with signer, class, protected role and at least one test that plants its failure.
- Changes to the gate or permission table **SHOULD** be followed by `python3 scripts/mutate.py forms.py _gate`, which **MUST** catch every mutant.
- Non-negotiables (roles, scope of practice, approval, evidence, wording) **MUST** be enforced by deterministic code in the gate and checker. They **MUST NOT** depend on a model, a prompt or a reviewer's judgement.
- The event log is append-only. Code **MUST NOT** rewrite, reorder or delete log lines. A correction is a new event. State **MUST** be rebuilt by replay, and the same log **MUST** give the same state.
- Every string a person sees **MUST** come from `messages.py`. Its fixed wording lines **MUST NOT** be edited, added or reworded ad hoc; `LINES` **MUST** match the signed table `WORDING.md` word for word. A line not yet signed goes in `messages.PENDING`, which rulecheck reports as pending.
- Exports **MUST** refuse any episode not marked synthetic.
- Standard library only. Python 3.11 or later.

## Out of scope

- Real patient data, hosted services or vendor APIs
- Clinical advice or deciding what an answer or job means
