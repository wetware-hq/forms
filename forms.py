#!/usr/bin/env python3
"""Strict yes/no questionnaires as an agent environment, for any clinical setting.
Schema: TOML. Store: append-only event log (JSONL). Everything else is derived by replaying the log.
Agents never infer: every answer is an explicit event. All user-facing text comes from messages.py."""
import datetime, hashlib, json, re, sys, tomllib
from messages import msg, code, RELATIONSHIP
from access import Invalid, AGENTS, open_session, in_scope

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NEG_RE = re.compile(r"\b(no|not|never|without|none)\b|n't\b", re.I)
TWO_RE = re.compile(r"\b(and|or)\b|[,/]", re.I)
Q_REQ = {"id", "version", "text", "alert_answer", "safety_critical", "clinician_must_confirm"}
Q_OPT = {"ask_if", "two_item_ok", "disciplines"}

# ---- permission table: role -> actions it may take. Refusal line when an action is not allowed. ----
PERMS = {
    "patient": {"answer", "decline", "confirm", "grant", "revoke", "submit", "next"},
    "patient_agent": {"answer", "submit", "next"},
    "clinician": {"answer", "confirm", "approve", "submit", "review", "next"},
    "clinician_agent": {"answer", "submit", "next"},
}
# ---- per-call permissions: env methods a session may call through call(). reset, replay, check and export
# belong to the harness and are refused with RF-HARNESS-ONLY. ----
CALL_PERMS = {
    "patient": {"observe", "step"},
    "patient_agent": {"observe", "step"},
    "clinician": {"observe", "step"},
    "clinician_agent": {"observe", "step"},
}
MAX_FAILS = 3   # failed submissions in a row before the episode goes to the clinician queue
DENY = {"patient": None, "patient_agent": "RF-ROLE-CONFIRM", "clinician": "RF-ROLE-CONFIRM",
        "clinician_agent": "RF-CLIN-AGENT"}
CONFIRMER = {"patient": "patient", "clinician": "clinician"}   # audience -> who confirms an agent's answer
SCOPED = {"clinician", "clinician_agent"}                        # roles checked against scope of practice
FIELDS = {"answer": {"question_id", "value"}, "decline": {"question_id"}, "confirm": {"question_id"},
          "grant": set(), "revoke": set(), "approve": set(), "submit": set(), "review": set()}
OPTIONAL = {"answer": {"on_behalf"}, "decline": set(), "confirm": set(), "grant": set(), "revoke": set(), "approve": set(),
            "submit": set(), "review": set()}
DERIVED = {"submit": {"result", "missing"}}   # filled by the env at submission, checked again on replay
SESSION_KEYS = {"actor", "role", "discipline", "scope", "episode_id", "source"}


def check_schema(d):
    if not isinstance(d, dict):
        raise Invalid(msg("ER-BAD-FIELD", field="schema", item="file"))
    for k in ("form_id", "version", "audience", "question"):
        if k not in d:
            raise Invalid(msg("ER-BAD-FIELD", field=k, item="schema"))
    if set(d) - {"form_id", "version", "audience", "question"}:
        raise Invalid(msg("ER-BAD-FIELD", field=sorted(set(d) - {"form_id", "version", "audience", "question"})[0], item="schema"))
    for k in ("form_id", "version"):
        if not isinstance(d[k], str) or not d[k].strip():
            raise Invalid(msg("ER-BAD-FIELD", field=k, item="schema"))
    if d["audience"] not in CONFIRMER:
        raise Invalid(msg("ER-BAD-FIELD", field="audience", item="schema"))
    qs = d["question"]
    if not isinstance(qs, list) or not qs:
        raise Invalid(msg("ER-BAD-FIELD", field="question", item="schema"))
    seen = {}
    for n, q in enumerate(qs, 1):
        item = f"question {n}"
        if not isinstance(q, dict):
            raise Invalid(msg("ER-BAD-FIELD", field="question", item=item))
        if "alert_answer" not in q:
            raise Invalid(msg("CK-NO-ALERT", n=n))
        bad = sorted((Q_REQ - set(q)) | (set(q) - Q_REQ - Q_OPT))
        if bad:
            raise Invalid(msg("ER-BAD-FIELD", field=bad[0], item=item))
        if not isinstance(q["id"], str) or not ID_RE.match(q["id"]):
            raise Invalid(msg("ER-BAD-FIELD", field="id", item=item))
        if q["id"] in seen:
            raise Invalid(msg("ER-DUP-ID", id=q["id"]))
        if not isinstance(q["version"], str) or not q["version"].strip():
            raise Invalid(msg("ER-BAD-FIELD", field="version", item=item))
        t = q["text"]
        if not isinstance(t, str) or not t.strip().endswith("?"):
            raise Invalid(msg("ER-BAD-FIELD", field="text", item=item))
        if NEG_RE.search(t):
            raise Invalid(msg("CK-NEGATIVE", n=n))
        for k in ("alert_answer", "safety_critical", "clinician_must_confirm", "two_item_ok"):
            if k in q and type(q[k]) is not bool:
                raise Invalid(msg("RF-NOT-BOOL"))
        if TWO_RE.search(t) and not q.get("two_item_ok"):
            raise Invalid(msg("CK-TWO-ITEMS", n=n))
        if "disciplines" in q and (not q["safety_critical"] or not isinstance(q["disciplines"], list)
                                   or not q["disciplines"] or not all(isinstance(x, str) and x for x in q["disciplines"])):
            raise Invalid(msg("ER-BAD-FIELD", field="disciplines", item=item))
        if "ask_if" in q:
            a = q["ask_if"]
            if not isinstance(a, dict) or not {"id", "equals"} <= set(a) <= {"id", "equals", "wording"}:
                raise Invalid(msg("ER-BAD-FIELD", field="ask_if", item=item))
            if type(a["equals"]) is not bool:
                raise Invalid(msg("RF-NOT-BOOL"))
            if a["id"] not in seen:
                raise Invalid(msg("CK-COND-ORDER", n=n))
            if not isinstance(a.get("wording"), str) or not a["wording"].strip():
                raise Invalid(msg("CK-COND-WORDS", n=n))
        seen[q["id"]] = q
    return d


def clinician_queue(d):
    """Questions flagged two_item_ok are never auto-accepted: they go to a clinician queue."""
    return [msg("CQ-TWO-ITEMS", n=n) for n, q in enumerate(d["question"], 1) if q.get("two_item_ok")]


def propose_form(d):
    """A proposed form must pass the fixed checker; it takes effect only after a clinician approves it.
    A proposal may not set two_item_ok: only a clinician in their own session can (set_two_item_ok)."""
    check_schema(d)
    for n, q in enumerate(d["question"], 1):
        if q.get("two_item_ok"):
            raise Invalid(msg("CK-TWO-ITEMS", n=n))
    return {"schema_hash": schema_hash(d), "approved": False, "queue": clinician_queue(d)}


def set_two_item_ok(d, qid, session):
    """Only a clinician in their own session can flag a question two_item_ok. Returns a new schema."""
    if session.role != "clinician":
        raise Invalid(msg("RF-CLIN-AGENT") if session.role == "clinician_agent" else code("two_item_ok_clinician_only"))
    new = json.loads(json.dumps(d))
    hit = [q for q in new["question"] if q["id"] == qid]
    if not hit:
        raise Invalid(code("question_id"))
    hit[0]["two_item_ok"] = True
    return check_schema(new)


def diff_view(old, new):
    """Approval view: only what changed since the last approved version (question ids)."""
    o = {q["id"]: q for q in old["question"]}
    n = {q["id"]: q for q in new["question"]}
    return {"added": [i for i in n if i not in o], "removed": [i for i in o if i not in n],
            "changed": [i for i in n if i in o and n[i] != o[i]],
            "form": [k for k in ("form_id", "version", "audience") if old[k] != new[k]]}


def schema_hash(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_schema(path):
    try:
        with open(path, "rb") as f:
            return check_schema(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError):
        raise Invalid(code("schema_unreadable"))


class FormEnv:
    def reset(self, case_file, actor, role, episode_id, discipline=None, scope=()):
        self.session = open_session(actor, role, discipline, scope)
        self.schema = check_schema(case_file if isinstance(case_file, dict) else load_schema(case_file))
        self.hash = schema_hash(self.schema)
        self.q = {q["id"]: q for q in self.schema["question"]}
        self.ids = list(self.q)
        self.num = {i: n for n, i in enumerate(self.ids, 1)}
        self.episode_id = episode_id
        self.log = []
        return self.observe()

    # ---- derived view ----
    def _fold(self):
        st = {i: {"state": "unanswered"} for i in self.ids}
        meta = {"approver": None, "grant": None, "revoked_on": None, "granted_on": None,
                "submissions": 0, "fails": 0, "passed": False, "missing": []}
        for e in self.log:
            t = e["type"]
            if t == "approve":
                if e["schema_hash"] == self.hash and e["episode_id"] == self.episode_id:
                    meta["approver"] = e["discipline"]
                continue
            if t == "submit":
                meta["submissions"] += 1
                meta["passed"] = e["result"] == "pass"
                meta["fails"] = 0 if meta["passed"] else meta["fails"] + 1
                meta["missing"] = e["missing"]
                continue
            if t == "review":
                meta["fails"] = 0
                continue
            if t in ("grant", "revoke"):
                meta["grant"] = t == "grant"
                meta["revoked_on"] = None if t == "grant" else e["timestamp"][:10]
                meta["granted_on"] = e["timestamp"][:10] if t == "grant" else None
                continue
            i = e["question_id"]
            if e["episode_id"] != self.episode_id or e["question_version"] != self.q[i]["version"]:
                st[i] = {"state": "unanswered", "stale": True}
            elif t == "answer":
                st[i] = {"state": "answered", "value": e["value"], "source": e["role"],
                         "confirmed": e["role"] not in AGENTS, "confirmed_by": None,
                         "discipline": e["discipline"], "date": e["timestamp"][:10], "on_behalf": e.get("on_behalf")}
            elif t == "decline":
                st[i] = {"state": "declined"}
            elif t == "confirm":
                st[i] = dict(st[i], confirmed=True, confirmed_by=e["role"])
        return st, meta

    def _applicable(self, st, i):
        a = self.q[i].get("ask_if")
        return not a or not (st[a["id"]]["state"] == "answered" and st[a["id"]]["value"] != a["equals"])

    def _resolved(self, s, q):
        if q["clinician_must_confirm"]:
            return s["state"] == "answered" and s["confirmed"] and "clinician" in (s["source"], s["confirmed_by"])
        return s["state"] == "declined" or (s["state"] == "answered" and s["confirmed"])

    def allowed_disciplines(self, i, meta):
        return self.q[i].get("disciplines") or ([meta["approver"]] if meta["approver"] else [])

    def check(self):
        st, meta = self._fold()
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
        if meta["approver"] is None:
            blocked.insert(0, msg("RF-NOT-APPROVED"))
        done = not open_ and meta["approver"] is not None
        given_by = {i: RELATIONSHIP[st[i]["on_behalf"]][1] for i in self.ids if st[i].get("on_behalf")}
        queue = [msg("CQ-THREE-FAILS", items=", ".join(f"question {self.num[i]}" for i in meta["missing"]))] if meta["fails"] >= MAX_FAILS else []
        return {"complete": done, "status": msg("ST-FORM-DONE") if done else None, "open": open_,
                "blocked": blocked, "flags": flags, "not_applicable": na, "answers": answers, "given_by": given_by,
                "submissions": meta["submissions"], "final": meta["passed"], "clinician_queue": queue}

    def patient_view(self):
        """What the patient sees. Only table lines; nothing where no line exists."""
        st, meta = self._fold()
        out = {}
        if meta["grant"] is not None:
            out["access"] = msg("PV-GRANT", date=meta["granted_on"]) if meta["grant"] else msg("PV-REVOKE", date=meta["revoked_on"])
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
            elif s["source"] in AGENTS and not s["confirmed"]:
                out[i] = msg("PV-ANS-AGENT") + " " + msg("PV-CONFIRM", yesno=s["value"])
            elif s["source"] == "patient":
                out[i] = msg("PV-ANS-SELF")
            elif s["source"] == "patient_agent":
                out[i] = msg("PV-ANS-AGENT")
            elif s["on_behalf"]:
                out[i] = msg("PV-ANS-SDM", relationship=RELATIONSHIP[s["on_behalf"]][0], date=s["date"])
            elif s["source"] == "clinician":
                out[i] = msg("PV-ANS-CLIN", discipline=s["discipline"], date=s["date"])
            else:
                out[i] = ""
        nxt = [i for i in self.check()["open"] if st[i]["state"] == "unanswered"]
        out["next"] = msg("PV-NEXT", plain=self.q[nxt[0]]["text"]) if nxt else msg("PV-NOTHING-NEXT")
        return out

    def bitsets(self):
        """Derived view only: bit i = question i."""
        st, a, v = self._fold()[0], 0, 0
        for n, i in enumerate(self.ids):
            if st[i]["state"] == "answered":
                a |= 1 << n
                v |= int(st[i]["value"]) << n
        return {"answered": a, "value": v, "schema_hash": self.hash}

    def visible(self):
        """Read scope: a patient's agent sees only a form its patient granted; a clinician's agent sees only
        forms inside its clinician's scope (the approving discipline)."""
        s, meta = self.session, self._fold()[1]
        if s.role == "patient_agent":
            return self.schema["audience"] == "patient" and meta["grant"] is True
        if s.role == "clinician_agent":
            return in_scope(s, [meta["approver"]] if meta["approver"] else [])
        return True

    def observe(self, item=None):
        """Refused reads get RF-NOT-YOURS, the same line whether or not the item exists."""
        if not self.visible() or (item is not None and item not in self.q):
            return {"accepted": False, "reason": msg("RF-NOT-YOURS")}
        c = self.check()
        if item is not None:
            return {"accepted": True, "id": item, "text": self.q[item]["text"], "answer": c["answers"][item]}
        return {"episode_id": self.episode_id, "form_id": self.schema["form_id"], "open": c["open"],
                "flags": c["flags"], "blocked": c["blocked"]}

    def call(self, method, *args, **kw):
        """The only entry point for a session (person or agent): observe and step. Everything else is harness-only."""
        if method not in CALL_PERMS[self.session.role]:
            return {"accepted": False, "reason": msg("RF-HARNESS-ONLY")}
        return getattr(self, method)(*args, **kw)

    def export(self):
        """Harness-only. Refuses any episode not marked synthetic (episode id starting SYNTH-)."""
        if not (isinstance(self.episode_id, str) and self.episode_id.startswith("SYNTH-")):
            raise Invalid(msg("RF-EXPORT-REAL"))
        return dict(self.check(), bitsets=self.bitsets())

    # ---- gate: event + the session that made it ----
    def _gate(self, e, s):
        t = e["type"]
        if t not in PERMS[s.role]:
            return msg(DENY[s.role]) if DENY[s.role] else ""
        try:
            datetime.datetime.fromisoformat(e["timestamp"])
        except (TypeError, ValueError):
            return code("timestamp")
        st, meta = self._fold()
        if t == "approve":
            return code("already_approved") if meta["approver"] is not None else None
        if meta["approver"] is None:
            return msg("RF-NOT-APPROVED")
        if meta["passed"]:
            return code("final")
        if s.role in AGENTS and meta["fails"] >= MAX_FAILS:
            return msg("RF-WAIT-CLINICIAN")
        if t == "review":
            return None if meta["fails"] >= MAX_FAILS else code("nothing_to_review")
        if (s.role == "patient_agent" or t == "grant") and self.schema["audience"] != "patient":
            return msg("RF-AGENT-CLIN-FORM")
        if s.role == "patient_agent" and meta["grant"] is None:
            return msg("RF-NO-GRANT")
        if s.role == "patient_agent" and meta["grant"] is False:
            return msg("RF-REVOKED", date=meta["revoked_on"])
        if t in ("grant", "revoke", "submit"):
            return None
        i = e["question_id"]
        if i not in self.q:
            return code("question_id")
        if t == "answer" and type(e["value"]) is not bool:
            return msg("RF-NOT-BOOL")
        if "on_behalf" in e and s.role != "clinician":
            return code("on_behalf_clinician_only")
        if "on_behalf" in e and e["on_behalf"] not in RELATIONSHIP:
            return code("on_behalf_not_on_signed_list")
        if t == "confirm" and CONFIRMER[self.schema["audience"]] != s.role:
            return msg("RF-ROLE-CONFIRM") if self.schema["audience"] == "patient" else ""
        if t == "confirm" and not (st[i]["state"] == "answered" and not st[i]["confirmed"]):
            return code("nothing_to_confirm")
        if self.q[i]["safety_critical"] and s.role in SCOPED and not in_scope(s, self.allowed_disciplines(i, meta)):
            return msg("RF-SCOPE", disciplines=", ".join(self.allowed_disciplines(i, meta)))
        return None

    def _event(self, a, s):
        e = dict(a, actor=s.actor, role=s.role, discipline=s.discipline, scope=list(s.scope),
                 episode_id=self.episode_id)
        if a["type"] == "approve":
            e["schema_hash"] = self.hash
        if a["type"] == "submit":
            c = self.check()
            e.update(result="pass" if c["complete"] else "fail", missing=c["open"])
        if a.get("question_id") in self.q:
            e["question_version"] = self.q[a["question_id"]]["version"]
        return e

    def step(self, action):
        s = self.session
        if not isinstance(action, dict) or action.get("type") not in set(FIELDS) | {"next"}:
            return self._refuse(code("action_type"))
        if SESSION_KEYS & set(action):
            return self._refuse(code("role_fixed_at_session_open"))
        t = action["type"]
        if t == "next":
            o = self.check()["open"]
            return {"accepted": True, "next": o[0] if o else None}
        if not FIELDS[t] | {"type", "timestamp"} <= set(action) <= FIELDS[t] | {"type", "timestamp"} | OPTIONAL[t]:
            return self._refuse(code("fields"))
        e = self._event(action, s)
        why = self._gate(e, s)
        if why is not None:
            return self._refuse(why)
        self.log.append(e)
        if t == "submit":
            if e["result"] == "pass":
                return {"accepted": True, "result": msg("ST-CHECK-PASS"), "final": True}
            return {"accepted": True, "result": msg("ST-CHECK-FAIL"), "final": False, "missing": self.check()["blocked"]}
        return {"accepted": True}

    def _refuse(self, why):
        """A patient sees only table lines; machine codes are hidden from them."""
        if self.session.role == "patient" and why.startswith("ERR:"):
            why = ""
        return {"accepted": False, "reason": why}

    def replay(self, log):
        """Rebuild from a stored log; every in-episode event must pass the gate again."""
        self.log = []
        for e in log:
            if not isinstance(e, dict) or e.get("type") not in FIELDS:
                raise Invalid(code("log_event"))
            if e["type"] not in ("approve", "grant", "revoke", "submit", "review") and e.get("question_id") in self.q and (
                    e.get("episode_id") != self.episode_id or e.get("question_version") != self.q[e["question_id"]]["version"]):
                self.log.append(dict(e))       # kept: reverts its question to unanswered
                continue
            if e["type"] == "approve" and e.get("schema_hash") != self.hash:
                self.log.append(dict(e))       # approval of another version: kept, covers nothing here
                continue
            s = open_session(e.get("actor"), e.get("role"), e.get("discipline"), e.get("scope"))
            if self._event({k: e[k] for k in FIELDS[e["type"]] | OPTIONAL[e["type"]] | {"type", "timestamp"} if k in e}, s) != e:
                raise Invalid(code("log_event"))
            why = self._gate(e, s)
            if why is not None:
                raise Invalid(why or code("log_event_refused"))
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


def opts(rest):
    pos = [x for x in rest if not x.startswith("--")]
    flags = [i for i, x in enumerate(rest) if x.startswith("--")]
    o = {}
    for i in flags:
        if i + 1 >= len(rest):
            raise Invalid(msg("ER-BAD-COMMAND"))
        o[rest[i][2:]] = rest[i + 1]
    pos = [x for j, x in enumerate(rest) if not x.startswith("--") and j - 1 not in flags]
    return pos, o


def cli_bool(s):
    if s in ("true", "false"):
        return s == "true"
    raise Invalid(msg("RF-NOT-BOOL"))


def main(argv):
    """build SCHEMA | status|export SCHEMA LOG EPISODE |
    approve|grant|revoke|answer|decline|confirm SCHEMA LOG EPISODE [items] --role R --actor A --ts ISO
    [--discipline D] [--scope d1,d2]   (answer items: id=true|false; decline/confirm items: id)"""
    try:
        cmd = argv[1] if len(argv) > 1 else ""
        pos, o = opts(argv[2:])
        if cmd == "build" and len(pos) == 1:
            d = load_schema(pos[0])
            q = clinician_queue(d)
            if q:
                with open(pos[0] + ".clinician_queue.txt", "w") as f:
                    f.write("\n".join(q) + "\n")
            return 0
        if cmd in ("status", "export") and len(pos) == 3:
            env = FormEnv(); env.reset(pos[0], "cli", "patient", pos[2]); env.replay(read_log(pos[1]))
        elif cmd in FIELDS and len(pos) >= 3 and {"role", "actor", "ts"} <= set(o):
            env = FormEnv()
            env.reset(pos[0], o["actor"], o["role"], pos[2], o.get("discipline"),
                      tuple(x for x in o.get("scope", "").split(",") if x))
            env.replay(read_log(pos[1]))
            start = len(env.log)
            items = pos[3:] if FIELDS[cmd] else [None]
            if not items:
                raise Invalid(msg("ER-BAD-COMMAND"))
            for item in items:
                a = {"type": cmd, "timestamp": o["ts"]}
                if cmd == "answer":
                    qid, eq, val = item.partition("=")
                    a.update(question_id=qid, value=cli_bool(val) if eq else None)
                    if "on_behalf" in o:
                        a["on_behalf"] = o["on_behalf"]
                elif FIELDS[cmd]:
                    a["question_id"] = item
                r = env.step(a)
                if not r["accepted"]:
                    raise Invalid(r["reason"])
            with open(pos[1], "a") as f:
                f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in env.log[start:])
            cmd = "status"
        else:
            print(msg("ER-BAD-COMMAND"), file=sys.stderr)
            return 2
        c = env.check()
        if cmd == "export":
            print(json.dumps(env.export(), indent=1, ensure_ascii=False))
            return 0
        for x in c["blocked"] + c["flags"] + ([c["status"]] if c["status"] else []):
            print(x)
        return 0 if c["complete"] else 1
    except Invalid as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
