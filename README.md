# forms

Simple yes/no questionnaires that a program (or an agent) can build and fill in.

- A **schema** is a TOML file: `form_id`, `version`, and an ordered list of `[[question]]`, each with a unique `id` and a yes/no `text` ending in `?`.
- A **response** is a small JSON file holding two whole numbers used as bit rows. Bit *i* is question *i*.
  `answered` says which questions have an answer; `value` says which answers are yes. So "not answered" is never confused with "no".
- Answers must be real true/false. `1`, `0`, `"yes"` and empty values are refused.
- The response stores a fingerprint (SHA-256) of the schema. If the schema changes, the old response is refused.

```
python3 forms.py build  examples/pre_procedure_safety.toml
python3 forms.py fill   examples/pre_procedure_safety.toml r.json consent_signed=true site_marked=false
python3 forms.py status examples/pre_procedure_safety.toml r.json   # 0 complete, 1 incomplete, 2 invalid
python3 forms.py export examples/pre_procedure_safety.toml r.json   # JSON: true / false / null per question
```

Examples are made up. Python standard library only. Tests: `python3 -m pytest`.

## Agent environment

`FormEnv` wraps one episode for an agent: `reset(case_file, actor, role, episode_id)`, `observe()`,
`step(action)`, `check()`, `replay(log)`. Every action is a dict that passes a gate (right fields, right
types, right role) before anything changes. Rejected actions return a reason and are not logged.

Actions: `answer {id, value}`, `decline {id}` (patient only), `confirm` (patient only, needs no open
questions), `next` (read-only: the next open question). Replaying the log rebuilds the same state.

An MCP server is planned once the core passes. There isn't one yet.
