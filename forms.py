#!/usr/bin/env python3
"""Strict yes/no questionnaires. Schema: TOML. Response: JSON with two bitsets (answered, value).
Bit i = question i in schema order. answered=0 -> unanswered; answered=1,value=0 -> no; value=1 -> yes."""
import hashlib, json, re, sys, tomllib

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Invalid(Exception):
    pass


def check_schema(d):
    if set(d) != {"form_id", "version", "question"}:
        raise Invalid("schema needs exactly: form_id, version, [[question]]")
    for k in ("form_id", "version"):
        if not isinstance(d[k], str) or not d[k].strip():
            raise Invalid(f"'{k}' must be a non-empty string")
    qs = d["question"]
    if not isinstance(qs, list) or not qs:
        raise Invalid("at least one [[question]] is required")
    seen = set()
    for i, q in enumerate(qs, 1):
        if not isinstance(q, dict) or set(q) != {"id", "text"}:
            raise Invalid(f"question {i}: needs exactly 'id' and 'text'")
        if not isinstance(q["id"], str) or not ID_RE.match(q["id"]):
            raise Invalid(f"question {i}: id {q['id']!r} must be lower_snake_case")
        if q["id"] in seen:
            raise Invalid(f"question {i}: duplicate id {q['id']!r}")
        seen.add(q["id"])
        if not isinstance(q["text"], str) or not q["text"].strip().endswith("?"):
            raise Invalid(f"question {i}: text must be a yes/no question ending in '?'")
    return d


def schema_hash(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_schema(path):
    try:
        with open(path, "rb") as f:
            return check_schema(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise Invalid(f"cannot read schema: {e}")


def new_response(s):
    return {"form_id": s["form_id"], "version": s["version"], "schema_hash": schema_hash(s),
            "n": len(s["question"]), "answered": 0, "value": 0}


def check_response(r, s):
    if not isinstance(r, dict) or set(r) != set(new_response(s)):
        raise Invalid("response has wrong fields")
    if r["schema_hash"] != schema_hash(s) or r["form_id"] != s["form_id"] or r["version"] != s["version"]:
        raise Invalid("response belongs to a different schema (hash mismatch)")
    n = len(s["question"])
    if r["n"] != n:
        raise Invalid("response length differs from schema")
    for k in ("answered", "value"):
        v = r[k]
        if type(v) is not int or v < 0 or v >> n:
            raise Invalid(f"'{k}' must be a non-negative int of at most {n} bits")
    if r["value"] & ~r["answered"]:
        raise Invalid("a 'yes' bit is set on an unanswered question")
    return r


def set_answer(r, s, qid, val):
    if type(val) is not bool:
        raise Invalid(f"answer for {qid!r} must be bool True/False, got {type(val).__name__} {val!r}")
    ids = [q["id"] for q in s["question"]]
    if qid not in ids:
        raise Invalid(f"unknown question id {qid!r}")
    bit = 1 << ids.index(qid)
    r["answered"] |= bit
    r["value"] = (r["value"] | bit) if val else (r["value"] & ~bit)
    return r


def unanswered(r, s):
    return [q["id"] for i, q in enumerate(s["question"]) if not r["answered"] >> i & 1]


def export(r, s):
    a = {q["id"]: (bool(r["value"] >> i & 1) if r["answered"] >> i & 1 else None)
         for i, q in enumerate(s["question"])}
    return {"form_id": s["form_id"], "version": s["version"], "schema_hash": r["schema_hash"], "answers": a}


def load_response(path, s):
    try:
        with open(path) as f:
            return check_response(json.load(f), s)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        raise Invalid(f"cannot read response: {e}")


def cli_bool(s):
    """CLI text -> bool. Only the words true/false; anything else is rejected."""
    if s == "true":
        return True
    if s == "false":
        return False
    raise Invalid(f"answer must be 'true' or 'false', got {s!r}")


# ---------------- agentic environment ----------------
ROLES = {"patient", "clinician"}
ACTIONS = {"answer": {"id", "value"}, "decline": {"id"}, "confirm": set(), "next": set()}
PATIENT_ONLY = {"decline", "confirm"}


class FormEnv:
    """One episode of filling one form. All state changes go through step(); the log is the record."""

    def reset(self, case_file, actor, role, episode_id):
        if role not in ROLES:
            raise Invalid(f"role must be one of {sorted(ROLES)}")
        self.schema = case_file if isinstance(case_file, dict) else load_schema(case_file)
        check_schema(self.schema)
        self.actor, self.role, self.episode_id = actor, role, episode_id
        self.ids = [q["id"] for q in self.schema["question"]]
        self.resp, self.declined, self.confirmed, self.log = new_response(self.schema), set(), False, []
        return self.observe()

    def _open(self):
        return [q for q in unanswered(self.resp, self.schema) if q not in self.declined]

    def observe(self):
        return {"episode_id": self.episode_id, "form_id": self.schema["form_id"],
                "open": self._open(), "flags": self._flags(), "blocked": self._blocked()}

    def _flags(self):
        return [f"declined:{q}" for q in self.ids if q in self.declined]

    def _blocked(self):
        b = []
        if self._open():
            b.append(f"confirm blocked: {len(self._open())} question(s) open")
        if self.confirmed:
            b.append("form confirmed: no further changes")
        return b

    def _gate(self, a, role):
        if not isinstance(a, dict) or a.get("type") not in ACTIONS:
            return f"unknown action type {a.get('type') if isinstance(a, dict) else a!r}"
        t = a["type"]
        if set(a) != ACTIONS[t] | {"type"}:
            return f"{t} needs exactly fields {sorted(ACTIONS[t] | {'type'})}"
        if t in PATIENT_ONLY and role != "patient":
            return f"{t} is patient only"
        if t == "next":
            return None
        if self.confirmed:
            return "form already confirmed"
        if "id" in a and a["id"] not in self.ids:
            return f"unknown question id {a['id']!r}"
        if t == "answer" and type(a["value"]) is not bool:
            return "value must be bool True/False"
        if t == "decline" and a["id"] in self.declined:
            return "already declined"
        if t == "confirm" and self._open():
            return self._blocked()[0]
        return None

    def _apply(self, a):
        t = a["type"]
        if t == "answer":
            set_answer(self.resp, self.schema, a["id"], a["value"])
            self.declined.discard(a["id"])
        elif t == "decline":
            self.declined.add(a["id"])
            bit = 1 << self.ids.index(a["id"])
            self.resp["answered"] &= ~bit; self.resp["value"] &= ~bit
        elif t == "confirm":
            self.confirmed = True

    def step(self, action, _role=None):
        role = _role or self.role
        why = self._gate(action, role)
        if why:
            return {"accepted": False, "reason": why}
        if action["type"] == "next":
            o = self._open()
            return {"accepted": True, "next": o[0] if o else None}
        self._apply(action)
        self.log.append({"episode_id": self.episode_id, "actor": self.actor, "role": role,
                         "action": dict(action)})
        return {"accepted": True}

    def check(self):
        return {"complete": self.confirmed and not self._open(), "open": self._open(),
                "flags": self._flags(), "blocked": self._blocked(),
                "answers": export(self.resp, self.schema)["answers"]}

    def state(self):
        return (self.resp["answered"], self.resp["value"], tuple(sorted(self.declined)), self.confirmed)

    def replay(self, log):
        """Rebuild state from a log; every entry must pass the gate again."""
        self.resp, self.declined, self.confirmed, self.log = new_response(self.schema), set(), False, []
        for e in log:
            if e.get("episode_id") != self.episode_id:
                raise Invalid("log entry from another episode")
            r = self.step(e["action"], _role=e["role"])
            if not r["accepted"]:
                raise Invalid(f"log entry rejected on replay: {r['reason']}")
        return self.state()


USAGE = """usage: forms.py build SCHEMA
       forms.py fill SCHEMA RESPONSE id=true|false [...]
       forms.py status SCHEMA RESPONSE
       forms.py export SCHEMA RESPONSE"""


def main(argv):
    try:
        cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
        if cmd == "build" and len(args) == 1:
            s = load_schema(args[0])
            print(f"OK {s['form_id']} v{s['version']}: {len(s['question'])} questions, hash {schema_hash(s)[:12]}")
            return 0
        if cmd in ("fill", "status", "export") and len(args) >= 2:
            s = load_schema(args[0])
            r = load_response(args[1], s)
            if cmd == "fill":
                if len(args) < 3:
                    raise Invalid("fill needs at least one id=true|false")
                r = r or new_response(s)
                for a in args[2:]:
                    qid, eq, val = a.partition("=")
                    if not eq:
                        raise Invalid(f"expected id=true|false, got {a!r}")
                    set_answer(r, s, qid, cli_bool(val))
                with open(args[1], "w") as f:
                    json.dump(r, f, indent=1)
                cmd = "status"
            r = r or new_response(s)
            if cmd == "export":
                print(json.dumps(export(r, s), indent=1, ensure_ascii=False))
                return 0
            left = unanswered(r, s)
            for q in left:
                print(f"UNANSWERED {q}")
            print(f"{'COMPLETE' if not left else 'INCOMPLETE'} {len(s['question']) - len(left)}/{len(s['question'])}")
            return 1 if left else 0
        print(USAGE, file=sys.stderr)
        return 2
    except Invalid as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
