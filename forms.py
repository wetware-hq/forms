#!/usr/bin/env python3
"""Strict yes/no questionnaires as an agent environment.
Schema: TOML. Store: append-only event log (JSONL). Bitsets, status and flags are derived by
replaying the log. Agents never infer: every answer is an explicit event; nothing is auto-filled.
All user-facing text comes from messages.py."""
import datetime, hashlib, json, re, sys, tomllib
from messages import msg, code

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NEG_RE = re.compile(r"\b(no|not|never|without|none)\b|n't\b", re.I)
TWO_RE = re.compile(r"\b(and|or)\b", re.I)
Q_KEYS = {"id", "version", "text", "alert_answer", "safety_critical", "clinician_must_confirm"}
ROLES = {"patient", "clinician", "agent"}
EVENT_KEYS = {t: {"question_id", "question_version", "source", "actor", "timestamp", "episode_id"}
              for t in ("answer", "decline", "confirm")}
EVENT_KEYS["answer"] = EVENT_KEYS["answer"] | {"value"}


class Invalid(Exception):
    pass


def check_schema(d):
    if not isinstance(d, dict) or set(d) != {"form_id", "version", "audience", "question"}:
        raise Invalid(code("schema_fields"))
    for k in ("form_id", "version"):
        if not isinstance(d[k], str) or not d[k].strip():
            raise Invalid(code("schema_" + k))
    if d["audience"] not in ("patient", "clinician"):
        raise Invalid(code("schema_audience"))
    qs = d["question"]
    if not isinstance(qs, list) or not qs:
        raise Invalid(code("schema_no_questions"))
    seen = {}
    for n, q in enumerate(qs, 1):
        if not isinstance(q, dict):
            raise Invalid(code("question_fields"))
        if "alert_answer" not in q:
            raise Invalid(msg("CK-NO-ALERT", n=n))
        if not Q_KEYS <= set(q) <= Q_KEYS | {"ask_if"}:
            raise Invalid(code("question_fields"))
        if not isinstance(q["id"], str) or not ID_RE.match(q["id"]):
            raise Invalid(code("question_id"))
        if q["id"] in seen:
            raise Invalid(code("duplicate_question_id"))
        if not isinstance(q["version"], str) or not q["version"].strip():
            raise Invalid(code("question_version"))
        t = q["text"]
        if not isinstance(t, str) or not t.strip().endswith("?"):
            raise Invalid(code("question_text"))
        if NEG_RE.search(t):
            raise Invalid(msg("CK-NEGATIVE", n=n))
        if TWO_RE.search(t):
            raise Invalid(msg("CK-TWO-FACTS", n=n))
        for k in ("alert_answer", "safety_critical", "clinician_must_confirm"):
            if type(q[k]) is not bool:
                raise Invalid(code("question_bool_" + k))
        if "ask_if" in q:
            a = q["ask_if"]
            if not isinstance(a, dict) or not {"id", "equals"} <= set(a) <= {"id", "equals", "wording"} \
                    or type(a["equals"]) is not bool:
                raise Invalid(code("ask_if_fields"))
            if a["id"] not in seen:
                raise Invalid(msg("CK-COND-ORDER", n=n))
            if not isinstance(a.get("wording"), str) or not a["wording"].strip():
                raise Invalid(msg("CK-COND-WORDS", n=n))
        seen[q["id"]] = q
    return d


def schema_hash(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_schema(path):
    try:
        with open(path, "rb") as f:
            return check_schema(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError):
        raise Invalid(code("schema_unreadable"))


class FormEnv:
    def reset(self, case_file, actor, role, episode_id):
        if role not in ROLES:
            raise Invalid(code("role"))
        self.schema = check_schema(case_file if isinstance(case_file, dict) else load_schema(case_file))
        self.q = {q["id"]: q for q in self.schema["question"]}
        self.ids = list(self.q)
        self.num = {i: n for n, i in enumerate(self.ids, 1)}
        self.actor, self.role, self.episode_id = actor, role, episode_id
        self.log = []
        return self.observe()

    def _fold(self):
        st = {i: {"state": "unanswered"} for i in self.ids}
        for e in self.log:
            i = e["question_id"]
            if i not in st:
                continue
            if e["episode_id"] != self.episode_id or e["question_version"] != self.q[i]["version"]:
                st[i] = {"state": "unanswered", "stale": True}
            elif e["type"] == "answer":
                agent_on_patient = e["source"] == "agent" and self.schema["audience"] == "patient"
                st[i] = {"state": "answered", "value": e["value"], "source": e["source"],
                         "confirmed": not agent_on_patient}
            elif e["type"] == "decline":
                st[i] = {"state": "declined"}
            elif e["type"] == "confirm" and st[i]["state"] == "answered":
                st[i] = dict(st[i], confirmed=True)
        return st

    def _applicable(self, st, i):
        a = self.q[i].get("ask_if")
        if not a:
            return True
        p = st[a["id"]]
        return not (p["state"] == "answered" and p["value"] != a["equals"])

    def _resolved(self, s, q):
        if q["clinician_must_confirm"]:
            return s["state"] == "answered" and s["source"] == "clinician"
        return s["state"] == "declined" or (s["state"] == "answered" and s["confirmed"])

    def check(self):
        st = self._fold()
        open_, flags, blocked, na, answers = [], [], [], [], {}
        for i in self.ids:
            s, q, n = st[i], self.q[i], self.num[i]
            if not self._applicable(st, i):
                na.append(i); answers[i] = "n/a"; continue
            answers[i] = s["value"] if s["state"] == "answered" else s["state"]
            if not self._resolved(s, q):
                open_.append(i)
                if q["clinician_must_confirm"]:
                    blocked.append(msg("BK-CLIN-CONFIRM", n=n))
                if s.get("stale"):
                    blocked.append(msg("BK-STALE", n=n))
            if s["state"] == "answered" and s["value"] == q["alert_answer"]:
                flags.append(msg("FL-ALERT", n=n, yesno=q["alert_answer"]))
            elif q["safety_critical"] and s["state"] == "declined":
                flags.append(msg("FL-DECLINED", n=n))
            elif q["safety_critical"] and s["state"] == "unanswered":
                flags.append(msg("FL-UNKNOWN", n=n))
        if open_:
            blocked.insert(0, msg("BK-UNANSWERED", k=len(open_)))
        return {"complete": not open_, "open": open_, "blocked": blocked, "flags": flags,
                "not_applicable": na, "answers": answers}

    def patient_view(self):
        st, out = self._fold(), {}
        for i in self.ids:
            s = st[i]
            if not self._applicable(st, i):
                out[i] = msg("PV-SKIPPED", condition=self.q[i]["ask_if"]["wording"])
            elif s.get("stale"):
                out[i] = msg("PV-REASK")
            elif s["state"] == "declined":
                out[i] = msg("PV-DECLINED")
            elif s["state"] == "unanswered":
                out[i] = msg("PV-OPEN")
            elif not s["confirmed"]:
                out[i] = msg("PV-ANS-AGENT") + " " + msg("PV-CONFIRM", yesno=s["value"])
            else:
                out[i] = msg("PV-ANS-SELF") if s["source"] == "patient" else msg("PV-ANS-AGENT")
        return out

    def bitsets(self):
        """Derived view only: bit i = question i."""
        st, a, v = self._fold(), 0, 0
        for n, i in enumerate(self.ids):
            if st[i]["state"] == "answered":
                a |= 1 << n
                v |= int(st[i]["value"]) << n
        return {"answered": a, "value": v, "schema_hash": schema_hash(self.schema)}

    def observe(self):
        c = self.check()
        return {"episode_id": self.episode_id, "form_id": self.schema["form_id"], "open": c["open"],
                "flags": c["flags"], "blocked": c["blocked"]}

    def _gate(self, e):
        t = e.get("type") if isinstance(e, dict) else None
        if t == "next":
            return None if set(e) == {"type"} else code("fields")
        if t not in EVENT_KEYS:
            return code("action_type")
        if set(e) != EVENT_KEYS[t] | {"type"}:
            return code("fields")
        if e["source"] not in ROLES:
            return code("source")
        if t in ("decline", "confirm") and e["source"] != "patient":
            return msg("RF-ROLE-CONFIRM")
        if e["question_id"] not in self.q:
            return code("question_id")
        if e["episode_id"] != self.episode_id or e["question_version"] != self.q[e["question_id"]]["version"]:
            return msg("BK-STALE", n=self.num[e["question_id"]])
        try:
            datetime.datetime.fromisoformat(e["timestamp"])
        except (TypeError, ValueError):
            return code("timestamp")
        if t == "answer" and type(e["value"]) is not bool:
            return msg("RF-NOT-BOOL")
        if t == "confirm":
            s = self._fold()[e["question_id"]]
            if s["state"] != "answered" or s["confirmed"]:
                return code("nothing_to_confirm")
        return None

    def step(self, action):
        a = dict(action) if isinstance(action, dict) else action
        if isinstance(a, dict) and a.get("type") in EVENT_KEYS:
            for k, v in (("source", self.role), ("actor", self.actor), ("episode_id", self.episode_id)):
                a.setdefault(k, v)
            if a.get("question_id") in self.q:
                a.setdefault("question_version", self.q[a["question_id"]]["version"])
            if a["source"] != self.role:
                return {"accepted": False, "reason": code("source_not_session_role")}
        why = self._gate(a)
        if why:
            return {"accepted": False, "reason": why}
        if a["type"] == "next":
            o = self.check()["open"]
            return {"accepted": True, "next": o[0] if o else None}
        self.log.append(a)
        return {"accepted": True}

    def replay(self, log):
        """Rebuild from a stored log. Stale or other-episode events are kept and revert their question."""
        self.log = []
        for e in log:
            t = e.get("type") if isinstance(e, dict) else None
            if t not in EVENT_KEYS or set(e) != EVENT_KEYS[t] | {"type"} or e["source"] not in ROLES \
                    or (t != "answer" and e["source"] != "patient") or (t == "answer" and type(e["value"]) is not bool):
                raise Invalid(code("log_event"))
            self.log.append(dict(e))
        return self.check()


def read_log(path):
    try:
        with open(path) as f:
            return [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        raise Invalid(code("log_unreadable"))


def cli_bool(s):
    if s in ("true", "false"):
        return s == "true"
    raise Invalid(msg("RF-NOT-BOOL"))


def main(argv):
    """build SCHEMA | status|export SCHEMA LOG EPISODE |
    answer|decline|confirm SCHEMA LOG EPISODE ROLE ACTOR TIMESTAMP item... (answer items: id=true|false)"""
    try:
        cmd, a = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
        if cmd == "build" and len(a) == 1:
            load_schema(a[0])
            return 0
        if cmd in ("status", "export") and len(a) == 3:
            env = FormEnv(); env.reset(a[0], "cli", "agent", a[2]); env.replay(read_log(a[1]))
        elif cmd in EVENT_KEYS and len(a) >= 7:
            env = FormEnv(); env.reset(a[0], a[4], a[3], a[2]); env.replay(read_log(a[1]))
            start = len(env.log)
            for item in a[6:]:
                ev = {"type": cmd, "timestamp": a[5]}
                if cmd == "answer":
                    qid, eq, val = item.partition("=")
                    ev.update(question_id=qid, value=cli_bool(val) if eq else None)
                else:
                    ev["question_id"] = item
                r = env.step(ev)
                if not r["accepted"]:
                    raise Invalid(r["reason"])
            with open(a[1], "a") as f:
                f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in env.log[start:])
            cmd = "status"
        else:
            print(code("usage"), file=sys.stderr)
            return 2
        c = env.check()
        if cmd == "export":
            print(json.dumps(dict(c, bitsets=env.bitsets()), indent=1, ensure_ascii=False))
            return 0
        for x in c["blocked"] + c["flags"]:
            print(x)
        return 0 if c["complete"] else 1
    except Invalid as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
