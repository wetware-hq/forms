---
schema: wetware.agent.v1
resource: forms
version: 0.2.0
capabilities: [questionnaire, checkpoint]
inputs:
  form: {type: toml, constraint: "strict yes/no questions; approved version only"}
  log: {type: jsonl, constraint: "append-only; synthetic only: SYNTH- ids, 1930-1939 dates"}
  session: {type: object, fields: [actor, role, discipline, scope, episode_id]}
outputs:
  status: {type: screen, values: [complete, not yet, invalid]}
  export: {type: json, fields: [answers, given_by, bitsets]}
  exit: {type: int}
interface:
  agent: [FormEnv.call observe, FormEnv.call step]
  harness_only: [reset, replay, check, export]
roles: [patient, patient_agent, clinician, clinician_agent]
settings: [WARD_SIBLINGS_DIR, TEST_SEED]
used_by: {repo: wetware-hq/ward, layer: middleware}
---

# Agent contract

Normative rules for agents that operate or modify forms. Wording uses RFC 2119: **MUST**, **MUST NOT**, **SHOULD**. Not approved for real patient data.

## Data handling

1. All data **MUST** be synthetic: `SYNTH-` ids, dates from 1930 to 1939, made-up people. Removing a name does not make a record synthetic.
2. If a user pastes real patient data, the agent **MUST** stop, **MUST NOT** repeat or process it, and **MUST** tell the user to report a privacy incident.
3. Fixtures, examples and test logs **MUST** follow rule 1.
4. Signed wording and answer folders under `WARD_SIBLINGS_DIR` are read-only; held-out folders **MUST NOT** be opened.

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
- Changes to the gate or permission table **SHOULD** be followed by `python3 scripts/mutate.py` (it mutates every function in `safety_functions.toml`, plus wrong-line and session-change mutants), which **MUST** catch every mutant.
- Non-negotiables (roles, scope of practice, approval, evidence, wording) **MUST** be enforced by deterministic code in the gate and checker. They **MUST NOT** depend on a model, a prompt or a reviewer's judgement.
- The event log is append-only. Code **MUST NOT** rewrite, reorder or delete log lines. A correction is a new event. State **MUST** be rebuilt by replay, and the same log **MUST** give the same state.
- Every string a person sees **MUST** come from `WORDING.md`, which **MUST** only be regenerated with `scripts/sync_wording.py` from the signed table, never edited by hand. `messages.py` **MUST NOT** hold wording. Lines not yet signed go in the pending section of `WORDING.md` and are reported by rulecheck.
- Exports **MUST** refuse any episode whose first log event is not the harness-written `synthetic: true` flag. The flag **MUST NOT** be inferred from the episode id, set by a session, or changed.
- A patient's agent **MUST** act only under a grant naming its exact id and the patient.
- Standard library only. Python 3.11 or later.

## Out of scope

- Signing wording or rules, or writing answer files
- Real patient data, hosted services or vendor APIs
- Clinical advice or deciding what an answer or job means
