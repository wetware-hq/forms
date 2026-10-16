"""One test per register row (RULES.md). Synthetic data only."""
import copy, json, pathlib, sys, tomllib
import pytest
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import forms as F
from access import Invalid, open_session
from messages import msg

EX = ROOT / "examples"
PH, PP, FR = (str(EX / n) for n in ("patient_history.toml", "pre_procedure_safety.toml", "physio_falls_risk.toml"))
SPH = tomllib.loads(pathlib.Path(PH).read_text())
TS = "1936-05-02T09:00"
EP = "SYNTH-EP-0001"
CLIN = {"actor": "SYNTH-dr-01", "role": "clinician", "discipline": "medicine"}

def approval(case, discipline="medicine", ep=EP):
    a = F.FormEnv(); a.reset(case, "SYNTH-dr-01", "clinician", ep, discipline); a.open_episode(True, TS)
    assert a.step({"type": "approve", "timestamp": TS})["accepted"]
    return a.log

def env(case=PH, role="patient", ep=EP, discipline=None, scope=(), approve="medicine", grant=False):
    """An env whose log already holds a clinician approval (and a patient grant if asked)."""
    log = approval(case, approve, ep) if approve else []
    if grant:
        p = F.FormEnv(); p.reset(case, "SYNTH-pt-01", "patient", ep); p.replay(log)
        assert p.step(grant_ev())["accepted"]; log = p.log
    actor = "SYNTH-pt-01" if role == "patient" else "SYNTH-person-01"
    e = F.FormEnv(); e.reset(case, actor, role, ep, discipline, scope); e.replay(log)
    return e

AGENT = "SYNTH-person-01"

def grant_ev(t="grant", agent=AGENT, patient="SYNTH-pt-01", ts=TS):
    return {"type": t, "timestamp": ts, "agent": agent, "patient": patient}

def ans(i, v):
    return {"type": "answer", "question_id": i, "value": v, "timestamp": TS}

def act(t, i=None):
    return {"type": t, "timestamp": TS, **({"question_id": i} if i else {})}

def as_role(e, role, discipline=None, scope=()):
    actor = {"patient_agent": AGENT, "patient": "SYNTH-pt-01"}.get(role, "SYNTH-person-02")
    f = F.FormEnv(); f.reset(e.schema, actor, role, e.episode_id, discipline, scope); f.replay(e.log)
    return f

def bad_schema(fn, base=SPH):
    d = copy.deepcopy(base); fn(d)
    with pytest.raises(Invalid) as e:
        F.check_schema(d)
    return str(e.value)

def scripted_patient(e):
    """Deterministic agent: answers each next question from a fixed script, declines what is not scripted."""
    script = {"allergy_any": False, "takes_blood_thinner": True, "smokes": False}
    while (q := e.step({"type": "next"})["next"]):
        assert e.step(ans(q, script[q]) if q in script else act("decline", q))["accepted"]

# ---------- signed rules (earlier rounds) ----------
def test_question_fields_required():
    for k in ("id", "version", "text", "safety_critical", "clinician_must_confirm"):
        assert bad_schema(lambda d: d["question"][0].pop(k)) == msg("ER-BAD-FIELD", field=k, item="question 1")
    assert bad_schema(lambda d: d["question"][0].update(extra=1)) == msg("ER-BAD-FIELD", field="extra", item="question 1")
    assert bad_schema(lambda d: d["question"][0].update(safety_critical="yes")) == msg("RF-NOT-BOOL")

def test_ask_if_only_way_not_applicable():
    e = env(); e.step(ans("allergy_any", False))
    assert e.check()["not_applicable"] == ["allergy_reaction_severe"]
    assert env().check()["not_applicable"] == []

def test_negative_wording_refused():
    for t in ("Do you have no allergies?", "Is it not marked?", "Never smoked?", "None today?", "Can't walk?"):
        assert bad_schema(lambda d: d["question"][0].update(text=t)) == msg("CK-NEGATIVE", n=1)

def test_bitsets_derived_from_log():
    e = env(); e.step(ans("allergy_any", True)); e.step(ans("smokes", False))
    assert e.bitsets()["answered"] == 0b1001 and e.bitsets()["value"] == 0b0001
    e.log.clear()
    assert e.bitsets()["answered"] == 0

def test_answer_event_fields():
    e = env(); e.step(ans("smokes", True))
    assert {"question_id", "question_version", "value", "role", "actor", "timestamp", "episode_id"} <= set(e.log[-1])

@pytest.mark.parametrize("v", [1, 0, "true", None, 1.0])
def test_value_strict_bool(v):
    e = env(); n = len(e.log)
    assert e.step(ans("smokes", v)) == {"accepted": False, "reason": msg("RF-NOT-BOOL")} and len(e.log) == n

def test_decline_never_read_as_no():
    e = env(); e.step(act("decline", "smokes"))
    assert "value" not in e.log[-1]
    assert e.check()["answers"]["smokes"] == "declined" and e.bitsets()["answered"] == 0
    assert e.patient_view()["smokes"] == msg("PV-DECLINED")

def test_agent_answer_needs_patient_confirm():
    a = env(role="patient_agent", grant=True); a.step(ans("smokes", False))
    assert "smokes" in a.check()["open"]
    p = as_role(a, "patient")
    assert p.step(act("confirm", "smokes"))["accepted"] and "smokes" not in p.check()["open"]

def test_stale_or_foreign_answer_reverts():
    e = env(); e.step(ans("smokes", True))
    for change in ({"question_version": "0"}, {"episode_id": "SYNTH-EP-OTHER"}):
        f = env(); f.replay(e.log + [dict(e.log[-1], **change)])
        assert f.check()["answers"]["smokes"] == "unanswered"
        assert f.patient_view()["smokes"] == msg("PV-REASK")

def test_clinician_must_confirm_needs_clinician():
    a = env(PP, "clinician_agent", scope=("medicine",)); a.step(ans("consent_signed", True))
    assert "consent_signed" in a.check()["open"]
    c = env(PP, "clinician", discipline="medicine"); c.step(ans("consent_signed", True))
    assert "consent_signed" not in c.check()["open"]

def test_decline_blocks_only_clinician_must_confirm():
    e = env(PH); e.step(act("decline", "smokes"))
    assert "smokes" not in e.check()["open"]
    d = copy.deepcopy(SPH); d["question"][3]["clinician_must_confirm"] = True
    f = env(d); f.step(act("decline", "smokes"))
    assert "smokes" in f.check()["open"]

def test_alert_answer_flags_any_polarity():
    e = env(PP, "clinician", discipline="medicine"); e.step(ans("consent_signed", False)); e.step(ans("anticoagulant_present", True))
    f = e.check()["flags"]
    assert msg("FL-ALERT", n=2, yesno=False) in f and msg("FL-ALERT", n=6, yesno=True) in f

def test_safety_critical_unanswered_or_declined_alerts():
    e = env(); e.step(act("decline", "allergy_any"))
    f = e.check()["flags"]
    assert msg("FL-DECLINED", n=1) in f and msg("FL-UNKNOWN", n=2) in f

def test_agents_never_infer():
    a = env(role="patient_agent", grant=True); a.step(ans("allergy_any", False))
    assert a.check()["answers"]["takes_blood_thinner"] == "unanswered"
    assert sum(x["type"] == "answer" for x in a.log) == 1

def test_no_who_content():
    for p in list(ROOT.glob("*.py")) + list(EX.glob("*")) + [ROOT / "README.md"]:
        t = p.read_text()
        assert "World Health Organization" not in t and " WHO " not in t and "SNOMED" not in t, p

def test_schema_unique_ids():
    assert bad_schema(lambda d: d["question"].append(dict(d["question"][0]))) == msg("ER-DUP-ID", id="allergy_any")

def test_schema_hash_bound():
    d = copy.deepcopy(SPH); d["question"][0]["version"] = "9"
    assert F.schema_hash(d) != F.schema_hash(SPH) and env().bitsets()["schema_hash"] == F.schema_hash(SPH)

def cli(cmd, case, log, *items, role="clinician", disc="medicine"):
    extra = ["--discipline", disc] if disc else []
    return F.main(["f", cmd, case, log, EP, *items, "--role", role, "--actor", "SYNTH-x", "--ts", TS] + extra)

def test_status_exit_codes(tmp_path):
    log = str(tmp_path / "l.jsonl")
    assert F.main(["f", "status", PP, log, EP]) == 1
    assert cli("approve", PP, log) == 1
    ids = [q["id"] for q in tomllib.loads(pathlib.Path(PP).read_text())["question"]]
    assert cli("answer", PP, log, *[f"{i}=true" for i in ids]) == 1      # anticoagulant alert waits for review
    assert cli("review", PP, log) == 0
    assert F.main(["f", "status", PP, log, EP]) == 0
    assert cli("answer", PP, log, "site_marked=1") == 2
    assert F.main(["f"]) == 2

def test_export_json(tmp_path, capsys):
    log = str(tmp_path / "l.jsonl")
    assert F.main(["f", "open", PH, log, EP, "--synthetic", "true", "--ts", TS]) == 0
    cli("approve", PH, log); cli("answer", PH, log, "smokes=false", role="patient", disc=None); capsys.readouterr()
    assert F.main(["f", "export", PH, log, EP]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["answers"]["smokes"] is False and out["bitsets"]["answered"] == 0b01000

def test_rejected_actions_not_logged():
    e = env(); n = len(e.log)
    for a in ({"type": "erase"}, ans("ghost", True), ans("smokes", "yes")):
        assert not e.step(a)["accepted"]
    assert len(e.log) == n

def test_decline_confirm_patient_only():
    for role, kw in (("clinician", {"discipline": "medicine"}),):
        e = env(role=role, **kw)
        assert e.step(act("decline", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")

def test_replay_equality():
    e = env(); scripted_patient(e)
    f = env(approve=None); assert f.replay(e.log) == e.check() and f.log == e.log

def test_observe_isolated_episode():
    a, b = env(ep="SYNTH-EP-A"), env(ep="SYNTH-EP-B")
    a.step(ans("smokes", True))
    assert "smokes" in b.observe()["open"] and b.observe()["episode_id"] == "SYNTH-EP-B"

@pytest.mark.parametrize("p", [PH, PP, FR])
def test_examples_build(p):
    assert F.main(["f", "build", p]) == 0

def test_scripted_agent_episode():
    e = env(); scripted_patient(e)
    c = e.check()
    assert c["complete"] and c["not_applicable"] == ["allergy_reaction_severe"] and c["status"] == msg("ST-FORM-DONE")

# ---------- rulings round 4 (Physician) ----------
def test_audience_decides_confirmer():
    a = env(PP, "clinician_agent", scope=("medicine",)); a.step(ans("site_marked", True))
    assert as_role(a, "patient").step(act("confirm", "site_marked"))["reason"] == msg("PV-ROLE-CONFIRM")   # patient screen line (round 11)
    b = env(role="patient_agent", grant=True); b.step(ans("smokes", True))
    assert as_role(b, "clinician", "medicine").step(act("confirm", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")
    c = as_role(a, "clinician", "medicine")
    assert c.step(act("confirm", "site_marked"))["accepted"] and "site_marked" not in c.check()["open"]

def test_patient_agent_refused_on_clinician_form():
    e = env(PP, "patient_agent")
    assert e.step(ans("site_marked", True))["reason"] == msg("RF-AGENT-CLIN-FORM")
    assert as_role(e, "patient").step(grant_ev("grant"))["reason"] == msg("RF-AGENT-CLIN-FORM")

def test_two_items_refused_unless_flagged_to_queue(tmp_path):
    assert bad_schema(lambda d: d["question"][3].update(text="Do you smoke, drink?")) == msg("CK-TWO-ITEMS", n=4)
    for t in ("Do you smoke or vape?", "Do you smoke and drink?", "Do you smoke/vape?"):
        assert bad_schema(lambda d: d["question"][3].update(text=t)) == msg("CK-TWO-ITEMS", n=4)
    d = copy.deepcopy(SPH); d["question"][3].update(text="Do you smoke or vape?", two_item_ok=True)
    assert F.clinician_queue(F.check_schema(d)) == [msg("CQ-TWO-ITEMS", n=4)]
    p = tmp_path / "s.toml"
    p.write_text(pathlib.Path(PH).read_text().replace('text = "Do you smoke now?"', 'text = "Do you smoke or vape?"\ntwo_item_ok = true'))
    assert F.main(["f", "build", str(p)]) == 0
    assert (tmp_path / "s.toml.clinician_queue.txt").read_text().strip() == msg("CQ-TWO-ITEMS", n=4)

# ---------- generality (owner ruling) ----------
def test_roles_are_four_with_discipline():
    for args in (("clinician", "  "), ("patient", "medicine"), ("clinician_agent", None, ("",)),
                 ("patient", None, ("medicine",)), ("clinician", 3)):
        with pytest.raises(Invalid):
            open_session("SYNTH-c", *args)
    with pytest.raises(Invalid):
        open_session(" ", "patient")
    for d in ("medicine", "nursing", "physiotherapy", "pharmacy"):
        assert open_session("SYNTH-c", "clinician", d).discipline == d
    with pytest.raises(Invalid):
        open_session("SYNTH-c", "clinician")
    with pytest.raises(Invalid):
        open_session("SYNTH-a", "clinician_agent")
    assert F.PERMS.keys() == {"patient", "patient_agent", "clinician", "clinician_agent", "guardian"}
    with pytest.raises(Invalid):
        open_session("SYNTH-g", "guardian", "medicine")      # a guardian is no clinician

def test_permissions_table_by_role():
    assert F.PERMS == {
        "patient": {"answer", "decline", "unknown", "confirm", "grant", "revoke", "submit", "next"},
        "patient_agent": {"answer", "submit", "next"},
        "clinician": {"answer", "unknown", "confirm", "approve", "submit", "review", "close_sameday", "next"},
        "clinician_agent": {"answer", "submit", "next"},
        "guardian": {"answer", "decline", "unknown", "submit", "next"}}
    for role, allowed in F.PERMS.items():
        assert allowed <= set(F.FIELDS) | {"next"} and role in F.DENY
    assert "approve" in F.PERMS["clinician"] and "approve" not in F.PERMS["clinician_agent"]

def test_allied_health_example():
    e = env(FR, "clinician", discipline="physiotherapy", approve="physiotherapy")
    assert e.step(ans("stands_unaided", True))["accepted"]
    assert e.step(ans("fell_last_year", False))["accepted"]

# ---------- round 5 (Physician) ----------
def test_scope_of_practice_refuses_other_discipline():
    e = env(FR, "clinician", discipline="pharmacy", approve="physiotherapy")
    assert e.step(ans("stands_unaided", True))["reason"] == msg("RF-SCOPE", disciplines="physiotherapy")
    assert e.step(ans("uses_walking_aid", True))["accepted"]                   # not safety-critical
    n = env(FR, "clinician", discipline="nursing", approve="physiotherapy")
    assert n.step(ans("fell_last_year", True))["accepted"]                      # listed discipline, not approver's

def test_scope_defaults_to_approver_discipline():
    e = env(FR, "clinician", discipline="pharmacy", approve="physiotherapy")
    assert e.step(ans("tug_slow", False))["reason"] == msg("RF-SCOPE", disciplines="physiotherapy")
    assert env(FR, "clinician", discipline="physiotherapy", approve="physiotherapy").step(ans("tug_slow", False))["accepted"]

def test_unregistered_role_refused():
    for r in ("carer", "assistant", "family", "nurse", ""):
        with pytest.raises(Invalid, match="only registered health professionals"):
            F.FormEnv().reset(PH, "SYNTH-x", r, EP)

def test_clinician_agent_cannot_confirm_or_approve():
    a = env(PP, "clinician_agent", scope=("medicine",))
    for x in (act("confirm", "site_marked"), act("approve"), act("decline", "site_marked")):
        assert a.step(x)["reason"] == msg("RF-CLIN-AGENT")

def test_clinician_agent_limited_to_granter_scope():
    a = env(FR, "clinician_agent", scope=("pharmacy",), approve="physiotherapy")
    assert a.step(ans("stands_unaided", True))["reason"] == msg("RF-SCOPE", disciplines="physiotherapy")
    b = env(FR, "clinician_agent", scope=("physiotherapy",), approve="physiotherapy")
    assert b.step(ans("stands_unaided", True))["accepted"]

# ---------- P-01 .. P-09 (Physician, safety) ----------
def test_p01_consent_failures():
    a = env(role="patient_agent", grant=True); a.step(ans("smokes", False))
    assert a.patient_view()["smokes"] != msg("PV-ANS-SELF")                     # (a)
    p = as_role(a, "patient"); p.step(grant_ev("revoke"))
    assert as_role(p, "patient_agent").step(ans("allergy_any", True))["accepted"] is False   # (b)
    d = env(); d.step(act("decline", "smokes"))
    assert d.bitsets()["value"] == 0 and d.bitsets()["answered"] == 0 and d.check()["answers"]["smokes"] != False  # (c)

def test_p02_grant_and_revoke():
    assert env(role="patient_agent").step(ans("smokes", True))["reason"] == msg("RF-NO-GRANT")
    assert env(role="clinician", discipline="medicine").step(grant_ev("grant"))["reason"] == msg("RF-ROLE-CONFIRM")
    p = env(grant=True)
    assert [x["type"] for x in p.log] == ["open", "approve", "grant"]
    p.step(grant_ev("revoke", ts="1936-05-03T09:00"))
    assert as_role(p, "patient_agent").step(ans("smokes", True))["reason"] == msg("RF-REVOKED", date="1936-05-03")
    q = env(role="patient_agent", grant=True); q.step(ans("smokes", True))
    assert as_role(q, "patient").patient_view()["smokes"].startswith(msg("PV-ANS-AGENT"))

def test_p03_separate_roles_own_session():
    a = env(role="patient_agent", grant=True)
    assert a.step(act("decline", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")
    assert a.step(act("confirm", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")
    assert env(PP, "patient_agent").step(ans("site_marked", True))["reason"] == msg("RF-AGENT-CLIN-FORM")

def test_p06_version_lock_and_diff_view():
    log = approval(PH)
    d = copy.deepcopy(SPH); d["question"][3]["version"] = "2"
    e = F.FormEnv(); e.reset(d, "SYNTH-pt", "patient", EP); e.replay(log)
    assert e.step(ans("smokes", True))["reason"] == msg("RF-NOT-APPROVED")
    assert F.diff_view(SPH, d) == {"added": [], "removed": [], "changed": ["smokes"], "form": []}

def test_p07_propose_needs_checker_and_approval():
    with pytest.raises(Invalid):
        F.propose_form(dict(SPH, question=[dict(SPH["question"][0], text="Never smoked?")]))
    assert F.propose_form(SPH)["approved"] is False
    e = env(approve=None)
    assert e.step(ans("smokes", True))["reason"] == msg("RF-NOT-APPROVED")
    assert e.step(act("approve"))["accepted"] is False                          # patient cannot approve

def test_p09_roles_fixed_at_session_open():
    e = env()
    for k in ("role", "source", "actor", "discipline", "episode_id"):
        r = e.step(dict(ans("smokes", True), **{k: "clinician"}))
        assert r["accepted"] is False and r["reason"] == msg("PV-CARE-TEAM-STEP")

# ---------- wording lines ----------
def test_line_pv_ans_self():
    e = env(); e.step(ans("smokes", False)); assert e.patient_view()["smokes"] == msg("PV-ANS-SELF")

def test_line_pv_ans_agent():
    e = env(role="patient_agent", grant=True); e.step(ans("smokes", False))
    assert e.patient_view()["smokes"].startswith("Your assistant answered. You haven't checked this yet.")

def test_line_pv_declined():
    test_decline_never_read_as_no()

def test_line_pv_skipped():
    e = env(); e.step(ans("allergy_any", False))
    assert e.patient_view()["allergy_reaction_severe"] == "Not asked, because you said you have no medicine allergies"

def test_line_pv_open():
    assert env().patient_view()["smokes"] == "Not answered yet"

def test_line_pv_reask():
    test_stale_or_foreign_answer_reverts()

def test_line_pv_confirm():
    e = env(role="patient_agent", grant=True); e.step(ans("smokes", True))
    assert e.patient_view()["smokes"].endswith("Your assistant answered Yes. Is that right?")

def test_line_rf_role_confirm():
    test_decline_confirm_patient_only()

def test_line_rf_no_grant():
    assert env(role="patient_agent").step(ans("smokes", True))["reason"] == "Refused: the patient has not let an assistant help with this form."

def test_line_rf_revoked():
    test_p02_grant_and_revoke()

def test_line_rf_not_bool():
    assert env().step(ans("smokes", 1))["reason"] == "Refused: answers must be Yes or No."

def test_line_rf_not_approved():
    assert env(approve=None).step(ans("smokes", True))["reason"] == "Refused: this form or list is not approved by a clinician yet."

def test_line_ck_negative():
    assert bad_schema(lambda d: d["question"][0].update(text="Is it not done?")) == "Question 1 is worded as a negative. Reword it as a plain question."

def test_line_ck_no_alert():
    assert bad_schema(lambda d: d["question"][1].pop("alert_answer")) == "Question 2 has no alert answer set."

def test_line_ck_cond_order():
    assert bad_schema(lambda d: d["question"][1]["ask_if"].update(id="smokes")) == msg("CK-COND-ORDER", n=2)

def test_line_ck_cond_words():
    assert bad_schema(lambda d: d["question"][1]["ask_if"].pop("wording")) == msg("CK-COND-WORDS", n=2)

def test_line_bk_unanswered():
    assert msg("BK-UNANSWERED", k=4) in env().check()["blocked"]          # the follow-up waits on its parent

def test_line_bk_clin_confirm():
    assert msg("BK-CLIN-CONFIRM", n=1) in env(PP, "clinician_agent", scope=("medicine",)).check()["blocked"]

def test_line_bk_stale():
    e = env(); e.step(ans("smokes", True))
    f = env(); f.replay(e.log + [dict(e.log[-1], question_version="0")])
    assert msg("BK-STALE", n=4) in f.check()["blocked"]

def test_line_fl_alert():
    test_alert_answer_flags_any_polarity()

def test_line_fl_unknown():
    assert msg("FL-UNKNOWN", n=1) in env().check()["flags"]

def test_line_fl_declined():
    test_safety_critical_unanswered_or_declined_alerts()

def test_line_rf_agent_clin_form():
    test_patient_agent_refused_on_clinician_form()

def test_line_ck_two_items():
    assert bad_schema(lambda d: d["question"][3].update(text="Do you smoke/vape?")) == \
        "Question 4 lists more than one thing. Split it, or send it to a clinician to check."

def test_line_cq_two_items(tmp_path):
    test_two_items_refused_unless_flagged_to_queue(tmp_path)

def test_line_st_form_done():
    test_scripted_agent_episode()

def test_line_pv_next():
    assert env().patient_view()["next"] == "Next for you: Do you have any allergies to medicines?"

def test_line_pv_nothing_next():
    e = env(); scripted_patient(e)
    assert e.patient_view()["next"] == "There's nothing for you to do right now."

def test_line_er_dup_id():
    test_schema_unique_ids()

def test_line_er_bad_field():
    test_question_fields_required()

def test_line_er_bad_command(capsys):
    assert F.main(["f", "frobnicate"]) == 2
    assert capsys.readouterr().err.strip() == "Command not recognised. Run with --help to see the commands."

def test_line_rf_scope():
    test_scope_of_practice_refuses_other_discipline()

def test_line_rf_unregistered():
    test_unregistered_role_refused()

def test_line_rf_clin_agent():
    test_clinician_agent_cannot_confirm_or_approve()

def test_line_pv_grant():
    assert env(grant=True).patient_view()["access"] == "Your assistant can help with this form (from 1936-05-02)"

def test_line_pv_revoke():
    p = env(grant=True); p.step(grant_ev("revoke", ts="1936-05-04T08:00"))
    assert p.patient_view()["access"] == "Your assistant can no longer help with this form (from 1936-05-04)"

def test_confirm_needs_unconfirmed_agent_answer():
    p = env()
    assert p.step(act("confirm", "smokes"))["reason"] == msg("PV-NOTHING-TO-CONFIRM")
    p.step(ans("smokes", True))
    assert p.step(act("confirm", "smokes"))["reason"] == msg("PV-NOTHING-TO-CONFIRM")
    a = env(role="patient_agent", grant=True); a.step(ans("smokes", True))
    q = as_role(a, "patient"); assert q.step(act("confirm", "smokes"))["accepted"]
    assert q.step(act("confirm", "smokes"))["accepted"] is False

# ---------- round 6 ----------
def test_two_item_ok_set_only_by_clinician():
    d = copy.deepcopy(SPH); d["question"][3]["text"] = "Do you smoke or vape?"
    with pytest.raises(Invalid):
        F.check_schema(d)
    for role, kw in (("clinician_agent", {"scope": ("medicine",)}), ("patient_agent", {}), ("patient", {})):
        with pytest.raises(Invalid):
            F.set_two_item_ok(d, "smokes", open_session("SYNTH-x", role, **kw))
    with pytest.raises(Invalid, match="assistant can draft"):
        F.set_two_item_ok(d, "smokes", open_session("SYNTH-x", "clinician_agent", scope=("medicine",)))
    ok = F.set_two_item_ok(d, "smokes", open_session("SYNTH-dr", "clinician", "medicine"))
    assert ok["question"][3]["two_item_ok"] is True and F.clinician_queue(ok) == [msg("CQ-TWO-ITEMS", n=4)]
    with pytest.raises(Invalid) as e:
        F.propose_form(ok)                                     # a proposal may not carry the flag
    assert str(e.value) == msg("CK-TWO-ITEMS", n=4)
    with pytest.raises(Invalid):
        F.set_two_item_ok(d, "ghost", open_session("SYNTH-dr", "clinician", "medicine"))

def sdm(rel="sdm", role="clinician", **kw):
    e = env(role=role, discipline="nursing" if role == "clinician" else None, **kw)
    return e, e.step(dict(ans("smokes", True), on_behalf=rel))

def test_line_pv_ans_clin():
    e = env(role="clinician", discipline="nursing"); e.step(ans("smokes", True))
    assert as_role(e, "patient").patient_view()["smokes"] == "Your care team answered: nursing, on 1936-05-02."

def test_line_pv_ans_sdm():
    for rel, words in (("parent", "Your parent"), ("guardian", "Your guardian"),
                       ("sdm", "The person legally allowed to decide for you")):
        e, r = sdm(rel)
        assert r["accepted"] and e.patient_view()["smokes"] == f"{words} answered for you, recorded by your care team on 1936-05-02."

def test_relationship_signed_list_clinician_only():
    from messages import RELATIONSHIP
    assert set(RELATIONSHIP) == {"parent", "guardian", "sdm"}
    for bad in ("carer", "Aunt SYNTH-Mary", ""):
        assert sdm(bad)[1]["accepted"] is False
    assert sdm("parent", role="patient")[1] == {"accepted": False, "reason": msg("PV-CARE-TEAM-STEP")}
    assert sdm("parent", role="patient_agent", grant=True)[1]["accepted"] is False
    e, r = sdm("guardian")
    assert e.log[-1]["on_behalf"] == "guardian" and e.log[-1]["role"] == "clinician"
    assert e.check()["given_by"] == {"smokes": "Guardian"}
    f = env(approve=None); assert f.replay(e.log) == e.check()

def test_cli_on_behalf(tmp_path):
    log = str(tmp_path / "l.jsonl")
    cli("approve", PH, log)
    assert cli("answer", PH, log, "smokes=true", "--on_behalf", "carer") == 2
    assert cli("answer", PH, log, "smokes=true", "--on_behalf", "sdm") == 1

def test_flags_only_where_due():
    f = env().check()["flags"]
    assert msg("FL-UNKNOWN", n=4) not in f and msg("FL-UNKNOWN", n=1) in f        # smokes is not safety-critical
    e = env(); e.step(ans("allergy_any", False))
    assert not any("question 1" in x for x in e.check()["flags"])               # answered, not the alert answer
    assert msg("RF-NOT-APPROVED") in env(approve=None).check()["blocked"]
    assert msg("RF-NOT-APPROVED") not in env().check()["blocked"]


STRICT_WRONG = [1, 0, "yes", "false", "true", None, 1.0, 0.0, "", [], {}]

@pytest.mark.parametrize("v", STRICT_WRONG, ids=repr)
def test_s06_answer_strict_bool_refused_not_logged(v):
    e = env(); n = len(e.log)
    assert e.step(ans("smokes", v)) == {"accepted": False, "reason": msg("RF-NOT-BOOL")}
    assert len(e.log) == n and e.check()["answers"]["smokes"] == "unanswered"

@pytest.mark.parametrize("v", [True, False])
def test_s06_answer_real_bool_accepted(v):
    e = env(); assert e.step(ans("smokes", v))["accepted"] and e.log[-1]["value"] is v

@pytest.mark.parametrize("k", ["alert_answer", "safety_critical", "clinician_must_confirm", "two_item_ok"])
@pytest.mark.parametrize("v", STRICT_WRONG, ids=repr)
def test_s06_schema_yes_no_fields_strict_bool(k, v):
    assert bad_schema(lambda d: d["question"][0].update({k: v})) == msg("RF-NOT-BOOL")

@pytest.mark.parametrize("v", STRICT_WRONG, ids=repr)
def test_s06_ask_if_equals_strict_bool(v):
    def f(d):
        q = next(q for q in d["question"] if "ask_if" in q); q["ask_if"]["equals"] = v
    assert bad_schema(f) == msg("RF-NOT-BOOL")

def test_p01_confirmed_agent_answer_drops_confirm_prompt():
    a = env(role="patient_agent", grant=True); a.step(ans("smokes", False))
    assert a.patient_view()["smokes"] == msg("PV-ANS-AGENT") + " " + msg("PV-CONFIRM", yesno=False)
    p = as_role(a, "patient"); assert p.step(act("confirm", "smokes"))["accepted"]
    assert p.patient_view()["smokes"] == msg("PV-ANS-SELF")


# ---- round 5 ----
ALL_Q = ("allergy_any", "allergy_reaction_severe", "takes_blood_thinner", "smokes", "pregnant_possible")

def fail_n(e, n):
    for _ in range(n):
        r = e.step(act("submit")); assert r["accepted"] and r["final"] is False

def test_r5_01_call_permissions_table():
    assert F.CALL_PERMS == {r: {"observe", "step"} for r in ("patient", "patient_agent", "clinician", "clinician_agent", "guardian")}

@pytest.mark.parametrize("role,kw", [("patient_agent", {"grant": True}), ("clinician_agent", {"scope": ("medicine",)}),
                                     ("patient", {}), ("clinician", {"discipline": "medicine"})])
@pytest.mark.parametrize("method", ["reset", "replay", "check", "export", "patient_view"])
def test_r5_01_harness_only_calls_refused(role, kw, method):
    e = env(role=role, **kw); n = len(e.log)
    assert e.call(method, []) == {"accepted": False, "reason": msg("RF-HARNESS-ONLY")} and len(e.log) == n

@pytest.mark.parametrize("role,kw", [("patient_agent", {"grant": True}), ("clinician_agent", {"scope": ("medicine",)})])
def test_r5_01_agents_may_observe_and_step(role, kw):
    e = env(role=role, **kw)
    assert e.call("observe")["form_id"] and e.call("step", ans("smokes", True))["accepted"]

def test_r5_02_failed_submission_continues_and_is_logged():
    e = env(); r = e.step(act("submit"))
    assert r == {"accepted": True, "result": msg("ST-CHECK-FAIL"), "final": False,
                 "missing": e.check()["blocked"] + e.check()["flags"] + e.check()["waiting_lines"]}
    assert e.log[-1]["type"] == "submit" and e.log[-1]["result"] == "fail" and e.log[-1]["missing"] == [q for q in ALL_Q if q != "allergy_reaction_severe"]
    assert e.step(ans("smokes", True))["accepted"] and e.check()["submissions"] == 1

def test_r5_02_pass_is_final():
    e = env(PP, "clinician", discipline="medicine")
    for q in e.ids:
        assert e.step(ans(q, False))["accepted"]
    if e.check()["alerts"]:
        assert e.step(act("review"))["accepted"]
    assert e.step(act("submit")) == {"accepted": True, "result": msg("ST-CHECK-PASS"), "final": True}
    assert e.check()["final"] and e.step(ans(e.ids[0], True))["accepted"] is False

@pytest.mark.parametrize("role,kw", [("patient_agent", {"grant": True}), ("clinician_agent", {"scope": ("medicine",)}),
                                     ("patient", {}), ("clinician", {"discipline": "medicine"})])
def test_r5_02_every_role_may_submit(role, kw):
    e = env(role=role, **kw); assert e.step(act("submit"))["accepted"] and e.log[-1]["role"] == role

def test_r5_02_three_fails_queue_and_wait():
    e = env(role="patient_agent", grant=True); fail_n(e, 2)
    assert not any(x.startswith("For a clinician to check: this was submitted") for x in e.check()["clinician_queue"]) and e.step(ans("smokes", True))["accepted"]
    fail_n(e, 1)
    missing = "; ".join(f"{n}. {e.q[i]['text']}" for n, i in enumerate(e.ids, 1) if i != "allergy_reaction_severe")
    assert e.check()["clinician_queue"][0] == msg("CQ-THREE-FAILS", items=missing)
    for a in (act("submit"), ans("allergy_any", True)):
        assert e.step(a) == {"accepted": False, "reason": msg("RF-WAIT-CLINICIAN")}
    assert e.check()["submissions"] == 3

def test_r5_02_clinician_review_unblocks_and_clinician_can_finish():
    e = env(role="patient_agent", grant=True); fail_n(e, 3)
    c = as_role(e, "clinician", "medicine")
    assert c.step(ans("allergy_any", False))["accepted"]          # a clinician can always finish
    assert c.step(act("review"))["accepted"] and not any(x.startswith("For a clinician to check: this was submitted") for x in c.check()["clinician_queue"])
    assert as_role(c, "patient_agent").step(act("submit"))["accepted"]
    assert env(role="clinician", discipline="medicine").step(act("review"))["reason"] == "ERR:nothing_to_review"
    assert as_role(e, "patient").step(act("review"))["accepted"] is False

def test_r5_02_submission_result_cannot_be_forged_and_replays():
    e = env(); assert e.step(dict(act("submit"), result="pass"))["accepted"] is False
    e.step(act("submit")); f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP); f.replay(e.log)
    assert f.log == e.log
    bad = [dict(x) for x in e.log]; bad[-1]["result"] = "pass"
    with pytest.raises(Invalid):
        g = F.FormEnv(); g.reset(PH, "SYNTH-x", "patient", EP); g.replay(bad)

def test_r5_03_observe_patient_sees_own_form():
    assert env().observe()["form_id"] and env().observe("smokes")["accepted"]

def test_r5_03_observe_patient_agent_only_granted_forms():
    assert env(role="patient_agent").observe() == {"accepted": False, "reason": msg("RF-NOT-YOURS")}
    assert env(role="patient_agent", grant=True).observe()["form_id"]
    assert env(PP, "patient_agent", approve="medicine").observe() == {"accepted": False, "reason": msg("RF-NOT-YOURS")}

def test_r5_03_observe_clinician_sees_all():
    assert env(role="clinician", discipline="nursing").observe()["form_id"]

def test_r5_03_observe_clinician_agent_only_its_scope():
    assert env(role="clinician_agent", scope=("medicine",)).observe()["form_id"]
    assert env(role="clinician_agent", scope=("nursing",)).observe() == {"accepted": False, "reason": msg("RF-NOT-YOURS")}
    assert env(role="clinician_agent", scope=("nursing",), approve=None).observe()["reason"] == msg("RF-NOT-YOURS")

def test_r5_03_not_yours_does_not_reveal_existence():
    e = env(role="clinician_agent", scope=("nursing",)); m = env(role="clinician_agent", scope=("medicine",))
    assert e.observe("smokes") == e.observe("no_such_item") == m.observe("no_such_item")
    assert m.observe("smokes")["accepted"]

def opened(synthetic, ep=EP):
    e = F.FormEnv(); e.reset(PH, "SYNTH-dr-01", "clinician", ep, "medicine"); e.open_episode(synthetic, TS)
    assert e.step({"type": "approve", "timestamp": TS})["accepted"]
    return e

def test_r8_01_export_needs_synthetic_flag_not_id():
    e = F.FormEnv(); e.reset(PH, "SYNTH-x", "patient", EP)
    e.replay([x for x in opened(True).log if x["type"] != "open"])
    with pytest.raises(Invalid) as x:
        e.export()
    assert str(x.value) == msg("RF-EXPORT-REAL")
    with pytest.raises(Invalid) as x:
        opened(False).export()
    assert str(x.value) == msg("RF-EXPORT-REAL")
    assert opened(True, "EP-0001").export()["synthetic"] is True     # the field decides, never the id

def test_r8_01_flag_set_once_first_and_never_changed():
    e = opened(True)
    for v in (True, False):
        with pytest.raises(Invalid):
            e.open_episode(v, TS)
    for v in (1, "true", None):
        f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP)
        with pytest.raises(Invalid):
            f.open_episode(v, TS)

@pytest.mark.parametrize("change", ["second_open", "flip", "not_first", "extra_key", "other_episode"])
def test_r8_01_replay_refuses_changed_flag(change):
    log = [dict(x) for x in opened(False).log]
    if change == "second_open":
        log.append(dict(log[0], synthetic=True))
    elif change == "flip":
        log.insert(1, dict(log[0], synthetic=True))
    elif change == "not_first":
        log = log[1:] + log[:1]
    elif change == "extra_key":
        log[0]["actor"] = "SYNTH-x"
    else:
        log[0]["episode_id"] = "SYNTH-EP-9"
    f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP)
    with pytest.raises(Invalid):
        f.replay(log)

@pytest.mark.parametrize("role,kw", [("patient_agent", {"grant": True}), ("clinician_agent", {"scope": ("medicine",)}),
                                     ("patient", {}), ("clinician", {"discipline": "medicine"})])
def test_r8_01_only_harness_sets_flag(role, kw):
    e = env(role=role, **kw); n = len(e.log)
    assert e.call("open_episode", True, TS) == {"accepted": False, "reason": msg("RF-HARNESS-ONLY")}
    assert e.step({"type": "open", "synthetic": True, "timestamp": TS})["accepted"] is False and len(e.log) == n

def test_r8_01_cli_export_needs_flag(tmp_path, capsys):
    log = str(tmp_path / "l.jsonl")
    cli("approve", PH, log); capsys.readouterr()
    assert F.main(["f", "export", PH, log, EP]) == 2 and capsys.readouterr().err.strip() == msg("RF-EXPORT-REAL")
    assert F.main(["f", "open", PH, log, EP, "--synthetic", "true", "--ts", TS]) == 2   # only as the first event

def test_r8_03_queue_lists_number_and_text():
    e = env(role="patient_agent", grant=True); e.step(ans("smokes", True)); fail_n(e, 3)
    want = "; ".join(f"{n}. {e.q[i]['text']}" for n, i in enumerate(e.ids, 1) if i != "allergy_reaction_severe")
    assert e.check()["clinician_queue"][0] == msg("CQ-THREE-FAILS", items=want)
    assert "1. " + e.q["allergy_any"]["text"] in want

def test_r8_04_interpreter_clinician_only():
    c = env(role="clinician", discipline="medicine")
    assert c.step(dict(ans("smokes", True), interpreter=True))["accepted"] and c.log[-1]["interpreter"] is True
    for role, kw in (("patient", {}), ("patient_agent", {"grant": True}), ("clinician_agent", {"scope": ("medicine",)})):
        e = env(role=role, **kw); n = len(e.log)
        assert e.step(dict(ans("smokes", True), interpreter=False))["accepted"] is False and len(e.log) == n

@pytest.mark.parametrize("v", [1, 0, "true", None])
def test_r8_04_interpreter_strict_bool(v):
    c = env(role="clinician", discipline="medicine")
    assert c.step(dict(ans("smokes", True), interpreter=v)) == {"accepted": False, "reason": msg("RF-NOT-BOOL")}

def test_r8_04_export_carries_interpreter(tmp_path, capsys):
    e = opened(True); e.step(dict(ans("smokes", True), interpreter=True)); e.step(ans("allergy_any", False))
    assert e.export()["interpreter"] == {"smokes": True, "allergy_any": False}
    log = str(tmp_path / "l.jsonl")
    with open(log, "w") as f:
        f.writelines(json.dumps(x) + "\n" for x in e.log[:2])
    assert cli("answer", PH, log, "smokes=true", "--interpreter", "true") == 1; capsys.readouterr()
    assert F.main(["f", "export", PH, log, EP]) == 0
    assert json.loads(capsys.readouterr().out)["interpreter"] == {"smokes": True}
    assert cli("answer", PH, log, "allergy_any=true", "--interpreter", "yes") == 2

# ---- round 8: alert to queue, follow-up questions, named grants ----
SD = __import__("messages").SAMEDAY_STATUS

def sd_line(i, k, status):
    return msg("CQ-SAMEDAY-ALERT", item_id=i, event_id=k, status=status)

def finish_others(e):
    for i in ("takes_blood_thinner", "smokes", "pregnant_possible"):
        assert e.step(ans(i, False))["accepted"]

def test_r8_05_confirmed_yes_queues_and_blocks_close():
    e = env(); e.step(ans("allergy_any", True)); k = len(e.log) - 1
    e.step(ans("allergy_reaction_severe", False)); finish_others(e)
    c = e.check()
    assert c["alerts"] == ["allergy_any"] and sd_line("allergy_any", k, SD["confirmed"]) in c["clinician_queue"]
    assert sd_line("allergy_any", k, SD["confirmed"]) in c["blocked"] and c["complete"] is False
    assert e.patient_view()["sameday"] == msg("PV-SAMEDAY") and e.step(act("submit"))["final"] is False
    r = as_role(e, "clinician", "medicine"); assert r.step(act("review"))["accepted"]
    assert r.check()["complete"] and r.check()["alerts"] == [] and r.step(act("submit"))["final"] is True

def test_r8_05_status_unconfirmed_then_confirmed():
    a = env(role="patient_agent", grant=True); a.step(ans("allergy_any", True)); k = len(a.log) - 1
    assert a.check()["clinician_queue"][0] == sd_line("allergy_any", k, SD["unconfirmed"])
    assert "sameday" not in a.patient_view()
    p = as_role(a, "patient"); assert p.step(act("confirm", "allergy_any"))["accepted"]
    assert sd_line("allergy_any", k, SD["confirmed"]) in p.check()["clinician_queue"]
    assert p.patient_view()["sameday"] == msg("PV-SAMEDAY")

def test_r8_05_status_declined():
    e = env(); e.step(act("decline", "allergy_any")); k = len(e.log) - 1
    assert e.check()["alerts"] == ["allergy_any"] and sd_line("allergy_any", k, SD["declined"]) in e.check()["clinician_queue"]
    assert e.patient_view()["sameday"] == msg("PV-SAMEDAY")

def test_r8_05_status_answer_unknown_at_submission():
    e = env(); assert "sameday" not in e.patient_view() and e.check()["alerts"] == []
    assert e.step(act("unknown", "allergy_any"))["accepted"]; k = len(e.log) - 1
    assert e.check()["alerts"] == ["allergy_any"]
    assert sd_line("allergy_any", k, SD["unknown"]) in e.check()["clinician_queue"]
    assert e.patient_view()["sameday"] == msg("PV-SAMEDAY")
    e.step(act("submit")); assert sd_line("allergy_any", k, SD["unknown"]) in e.check()["clinician_queue"]

def test_r8_05_status_changed_stays_until_review():
    e = env(); e.step(ans("allergy_any", True)); k = len(e.log) - 1; e.step(ans("allergy_any", False))
    c = e.check()
    assert c["alerts"] == ["allergy_any"] and sd_line("allergy_any", k, SD["changed"]) in c["clinician_queue"]
    v = e.patient_view()
    assert v["allergy_any"] == msg("PV-ANS-SELF") + " " + msg("PV-ANS-CHANGED") and "sameday" not in v
    r = as_role(e, "clinician", "medicine"); r.step(act("review"))
    assert r.check()["alerts"] == [] and r.patient_view()["allergy_any"] == msg("PV-ANS-SELF")

def test_r8_05_no_without_entry_does_not_queue():
    e = env(); e.step(ans("allergy_any", False)); assert e.check()["alerts"] == []

def test_r8_05_non_safety_question_does_not_queue():
    e = env(); e.step(ans("smokes", True)); e.step(act("decline", "pregnant_possible"))
    assert e.check()["alerts"] == [] and "sameday" not in e.patient_view()

def test_r8_05_clinician_form_confirm():
    e = env(PP, "clinician_agent", scope=("medicine",))
    q = next(i for i in e.ids if e.q[i]["safety_critical"])
    assert e.step(ans(q, e.q[q]["alert_answer"]))["accepted"] and e.check()["alerts"] == [q]
    assert e.check()["clinician_queue"][0].endswith(SD["unconfirmed"] + ". The form stays open until you review it.")
    c = as_role(e, "clinician", "medicine"); assert c.step(act("confirm", q))["accepted"]
    assert c.check()["clinician_queue"][0].endswith(SD["confirmed"] + ". The form stays open until you review it.")

def test_r8_05_new_trigger_after_review_needs_new_review():
    e = env(); e.step(ans("allergy_any", True))
    c = as_role(e, "clinician", "medicine"); c.step(act("review")); assert c.check()["alerts"] == []
    c.step(ans("allergy_any", False)); assert c.check()["alerts"] == []
    c.step(ans("allergy_any", True)); assert c.check()["alerts"] == ["allergy_any"]

def test_r8_05_review_only_clinician_and_only_when_needed():
    e = env(); assert as_role(e, "clinician", "medicine").step(act("review"))["reason"] == "ERR:nothing_to_review"
    e.step(ans("allergy_any", True))
    assert e.step(act("review"))["accepted"] is False
    assert as_role(e, "clinician_agent", scope=("medicine",)).step(act("review"))["accepted"] is False

def test_r8_06_follow_up_waits_while_parent_blank():
    e = env(); c = e.check()
    assert "allergy_reaction_severe" in c["waiting"] and "allergy_reaction_severe" not in c["open"]
    assert c["answers"]["allergy_reaction_severe"] == "waiting"
    assert msg("CQ-WAITING-PARENT", n=1, parent_text=e.q["allergy_any"]["text"], m=2,
               text=e.q["allergy_reaction_severe"]["text"]) in c["clinician_queue"]

@pytest.mark.parametrize("parent", ["yes", "declined", "unknown"])
def test_r8_06_follow_up_missing_when_parent_yes_declined_or_unknown(parent):
    e = env(role="patient_agent", grant=True) if parent == "unknown" else env()
    if parent == "declined":
        e.step(act("decline", "allergy_any"))
    else:
        e.step(ans("allergy_any", True if parent == "yes" else False))   # unknown: agent's unconfirmed answer
    c = e.check()
    assert "allergy_reaction_severe" in c["open"] and c["waiting"] == []

def test_r8_06_follow_up_not_needed_only_when_parent_no():
    e = env(); e.step(ans("allergy_any", False)); c = e.check()
    assert "allergy_reaction_severe" in c["not_applicable"] and c["waiting"] == [] and "allergy_reaction_severe" not in c["open"]

def test_r8_07_grant_names_agent_and_patient():
    p = env()
    assert p.step(grant_ev(agent=""))["reason"] == msg("PV-GRANT-NAMES-AGENT")
    assert p.step(grant_ev(patient="SYNTH-pt-99"))["accepted"] is False
    assert p.step(grant_ev())["accepted"] and p.log[-1]["agent"] == AGENT and p.log[-1]["patient"] == "SYNTH-pt-01"
    assert p.step(grant_ev(agent="SYNTH-agent-02", patient="SYNTH-pt-01"))["accepted"]

def test_r8_07_other_patient_cannot_grant_on_this_episode():
    p = env(grant=True)
    q = F.FormEnv(); q.reset(PH, "SYNTH-pt-99", "patient", EP); q.replay(p.log)
    assert q.step(grant_ev(agent="SYNTH-agent-09", patient="SYNTH-pt-99"))["accepted"] is False

def test_r8_07_agent_not_named_gets_no_grant_and_not_yours():
    p = env(grant=True)
    o = F.FormEnv(); o.reset(PH, "SYNTH-agent-02", "patient_agent", EP); o.replay(p.log)
    assert o.step(ans("smokes", True)) == {"accepted": False, "reason": msg("RF-NO-GRANT")}
    assert o.observe() == {"accepted": False, "reason": msg("RF-NOT-YOURS")}
    assert as_role(p, "patient_agent").observe()["form_id"]

def test_r8_07_revoke_names_agent_and_needs_active_grant():
    p = env(grant=True)
    assert p.step(grant_ev("revoke", agent="SYNTH-agent-02"))["accepted"] is False
    assert p.step(grant_ev("revoke"))["accepted"] and p.step(grant_ev("revoke"))["accepted"] is False
    assert as_role(p, "patient_agent").observe()["reason"] == msg("RF-NOT-YOURS")

def test_r8_07_cli_grant_names_agent(tmp_path):
    log = str(tmp_path / "l.jsonl"); cli("approve", PH, log)
    base = ["f", "grant", PH, log, EP, "--role", "patient", "--actor", "SYNTH-pt-01", "--ts", TS]
    assert F.main(base) == 2 and F.main(base + ["--agent", AGENT]) == 1
    assert F.read_log(log)[-1]["agent"] == AGENT


def close_sd(i, status):
    return {"type": "close_sameday", "question_id": i, "status": status, "timestamp": TS}

@pytest.mark.parametrize("status", list(SD.values()))
def test_r8_09_clinician_closes_entry_with_each_signed_status(status):
    e = env(); e.step(ans("allergy_any", True)); e.step(ans("allergy_reaction_severe", False)); finish_others(e)
    assert e.step(act("submit"))["final"] is False
    c = as_role(e, "clinician", "medicine")
    assert c.step(close_sd("allergy_any", status))["accepted"] and c.log[-1]["status"] == status
    k = c.check(); assert k["alerts"] == [] and k["sameday_closed"] == {"allergy_any": status} and k["complete"]
    assert c.step(act("submit"))["final"] is True
    f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP); f.replay(c.log); assert f.check()["complete"]

def test_r8_09_close_confirmed_on_allergy_any_unblocks_submit():
    a = env(role="patient_agent", grant=True); a.step(ans("allergy_any", True))
    p = as_role(a, "patient"); p.step(act("confirm", "allergy_any")); p.step(ans("allergy_reaction_severe", False)); finish_others(p)
    assert p.step(act("submit"))["final"] is False
    c = as_role(p, "clinician", "medicine"); assert c.step(close_sd("allergy_any", "confirmed"))["accepted"]
    assert as_role(c, "patient").step(act("submit")) == {"accepted": True, "result": msg("ST-CHECK-PASS"), "final": True}

def test_r8_09_close_refusals():
    e = env(); e.step(ans("allergy_any", True)); e.step(act("decline", "takes_blood_thinner"))
    c = as_role(e, "clinician", "medicine")
    for bad in ("Confirmed", "confirmed.", "", "ok", None):
        assert c.step(close_sd("allergy_any", bad))["accepted"] is False
    assert c.step(close_sd("smokes", "confirmed"))["reason"] == "ERR:nothing_to_close"
    assert c.step(close_sd("ghost", "confirmed"))["accepted"] is False
    for role, scope in (("patient", ()), ("patient_agent", ()), ("clinician_agent", ("medicine",))):
        assert as_role(e, role, scope=scope).step(close_sd("allergy_any", "confirmed"))["accepted"] is False
    assert c.step(close_sd("allergy_any", "confirmed"))["accepted"] and c.check()["alerts"] == []
    assert c.step(close_sd("allergy_any", "confirmed"))["reason"] == "ERR:nothing_to_close"

def test_r8_09_close_one_entry_leaves_others():
    e2 = env(PP, "clinician", discipline="medicine")
    qs = [i for i in e2.ids if e2.q[i]["safety_critical"]][:2]
    for q in qs:
        e2.step(ans(q, e2.q[q]["alert_answer"]))
    assert e2.step(close_sd(qs[0], "confirmed"))["accepted"] and e2.check()["alerts"] == [qs[1]]

def test_r8_09_cli_close_sameday(tmp_path):
    log = str(tmp_path / "l.jsonl"); cli("approve", PH, log)
    cli("answer", PH, log, "allergy_any=true")
    assert cli("close_sameday", PH, log, "allergy_any") == 2
    assert F.main(["f", "close_sameday", PH, log, EP, "allergy_any", "--status", "confirmed", "--role", "clinician",
                   "--actor", "SYNTH-x", "--ts", TS, "--discipline", "medicine"]) == 1
    assert F.read_log(log)[-1]["status"] == "confirmed"

@pytest.mark.parametrize("bad", [42, "answer", None, {"type": "erase"}])
def test_replay_refuses_malformed_log_lines(bad):
    f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP)
    with pytest.raises(Invalid):
        f.replay(approval(PH) + [bad])

def test_replay_reports_the_refusal_line():
    a = env(role="patient_agent", grant=True); a.step(ans("smokes", True))
    log = [x for x in a.log if x["type"] != "grant"]
    f = F.FormEnv(); f.reset(PH, "SYNTH-x", "patient", EP)
    with pytest.raises(Invalid) as x:
        f.replay(log)
    assert str(x.value) == msg("RF-NO-GRANT")

# ---- round 9: alert_route ----
def routed(route="before_procedure", qid="allergy_any"):
    d = copy.deepcopy(SPH); next(q for q in d["question"] if q["id"] == qid)["alert_route"] = route
    return d

def bp_line(i, k, status):
    return msg("CQ-BEFORE-PROC", item_id=i, event_id=k, status=status)

def test_r9_01_route_defaults_to_same_day():
    e = env(); assert e.route("allergy_any") == "same_day"
    e.step(ans("allergy_any", True)); k = len(e.log) - 1
    assert e.check()["clinician_queue"][-1] == sd_line("allergy_any", k, SD["confirmed"])
    v = e.patient_view(); assert v["sameday"] == msg("PV-SAMEDAY") and "before_procedure" not in v

def test_r9_01_explicit_same_day_same_as_default():
    e = env(routed("same_day")); e.step(ans("allergy_any", True)); k = len(e.log) - 1
    assert sd_line("allergy_any", k, SD["confirmed"]) in e.check()["clinician_queue"]

def test_r9_02_before_procedure_yes_queues_and_shows_patient_line():
    e = env(routed()); e.step(ans("allergy_any", True)); k = len(e.log) - 1
    c = e.check()
    assert bp_line("allergy_any", k, SD["confirmed"]) in c["clinician_queue"] and bp_line("allergy_any", k, SD["confirmed"]) in c["blocked"]
    assert not any(x.startswith("Same-day review needed") for x in c["clinician_queue"])
    v = e.patient_view(); assert v["before_procedure"] == msg("PV-BEFORE-PROC") and "sameday" not in v

@pytest.mark.parametrize("case", ["unconfirmed", "confirmed", "changed", "declined", "unknown"])
def test_r9_02_before_procedure_each_status(case):
    if case in ("unconfirmed", "confirmed"):
        e = env(routed(), role="patient_agent", grant=True); e.step(ans("allergy_any", True)); k = len(e.log) - 1
        if case == "confirmed":
            e = as_role(e, "patient"); e.step(act("confirm", "allergy_any"))
    elif case == "changed":
        e = env(routed()); e.step(ans("allergy_any", True)); k = len(e.log) - 1; e.step(ans("allergy_any", False))
    elif case == "declined":
        e = env(routed()); e.step(act("decline", "allergy_any")); k = len(e.log) - 1
    else:
        e = env(routed()); e.step(act("unknown", "allergy_any")); k = len(e.log) - 1
    assert bp_line("allergy_any", k, SD[case]) in e.check()["clinician_queue"]
    shown = "before_procedure" in e.patient_view()
    assert shown is (case in ("confirmed", "declined", "unknown"))

def test_r9_02_patient_decline_counts_as_confirmed_and_shows_at_once():
    e = env(routed()); e.step(act("decline", "allergy_any"))
    assert e.patient_view()["before_procedure"] == msg("PV-BEFORE-PROC")

def test_r9_02_clinician_yes_counts_as_confirmed_at_once():
    e = env(routed(), role="clinician", discipline="medicine"); e.step(ans("allergy_any", True)); k = len(e.log) - 1
    assert bp_line("allergy_any", k, SD["confirmed"]) in e.check()["clinician_queue"]
    assert e.patient_view()["before_procedure"] == msg("PV-BEFORE-PROC")

def test_r9_02_before_procedure_blocks_until_clinician_closes():
    e = env(routed()); e.step(ans("allergy_any", True)); e.step(ans("allergy_reaction_severe", False)); finish_others(e)
    assert e.step(act("submit"))["final"] is False
    c = as_role(e, "clinician", "medicine"); assert c.step(close_sd("allergy_any", "confirmed"))["accepted"]
    assert c.step(act("submit"))["final"] is True

def test_r9_03_alert_route_only_on_safety_questions_and_signed_values():
    assert bad_schema(lambda d: d["question"][3].update(alert_route="same_day")) == msg("ER-BAD-FIELD", field="alert_route", item="question 4")
    for v in ("before-procedure", "", "today", True):
        assert bad_schema(lambda d: d["question"][0].update(alert_route=v)) == msg("ER-BAD-FIELD", field="alert_route", item="question 1")
    F.check_schema(routed()); F.check_schema(routed("same_day"))

def test_r9_04_waiting_parent_signed_text():
    e = env(); line = e.check()["clinician_queue"][-1]
    assert line == "Waiting on Q1: " + e.q["allergy_any"]["text"] + " Then ask Q2: " + e.q["allergy_reaction_severe"]["text"]
    assert "?." not in line and not line.endswith("?.")

def test_no_question_mark_full_stop_in_any_queue_or_view():
    for case in (PH, PP, FR):
        e = env(case, role="clinician", discipline="medicine", approve="medicine"); e.step(act("submit"))
        for x in e.check()["clinician_queue"] + e.check()["blocked"] + e.check()["flags"] + list(env(case).patient_view().values()):
            assert "?." not in x

def test_r9_02_clinician_yes_still_needs_review_even_by_same_clinician():
    c = env(routed(), role="clinician", discipline="medicine")
    c.step(ans("allergy_any", True)); c.step(ans("allergy_reaction_severe", False)); finish_others(c)
    assert c.patient_view()["before_procedure"] == msg("PV-BEFORE-PROC")
    assert c.check()["complete"] is False and c.step(act("submit"))["final"] is False
    assert c.step(act("review"))["accepted"] and c.step(act("submit"))["final"] is True

# ---- sensitive questions ----
def test_r9_05_sensitive_is_optional_strict_bool():
    d = copy.deepcopy(SPH); d["question"][2]["sensitive"] = True; F.check_schema(d)
    for v in (1, "true", None):
        assert bad_schema(lambda d: d["question"][2].update(sensitive=v)) == msg("RF-NOT-BOOL")

def test_r9_05_export_lists_sensitive_questions_and_queue_never_quotes_answer():
    d = copy.deepcopy(SPH); d["question"][0]["sensitive"] = True; d["question"][3]["sensitive"] = False
    e = F.FormEnv(); e.reset(d, "SYNTH-dr-01", "clinician", EP, "medicine"); e.open_episode(True, TS)
    e.step({"type": "approve", "timestamp": TS}); e.step(ans("allergy_any", True))
    x = e.export(); assert x["sensitive"] == ["allergy_any"]
    assert all("Yes" not in q and e.q["allergy_any"]["text"] not in q for q in x["clinician_queue"] if q.startswith("Same-day"))
    assert opened(True).export()["sensitive"] == []


def test_r9_06_waiting_parent_reappears_after_every_failed_submit():
    e = env(role="patient_agent", grant=True)
    want = msg("CQ-WAITING-PARENT", n=1, parent_text=e.q["allergy_any"]["text"], m=2, text=e.q["allergy_reaction_severe"]["text"])
    for _ in range(3):
        r = e.step(act("submit")); assert r["final"] is False and r["missing"].count(want) == 1
        assert e.check()["clinician_queue"].count(want) == 1
    p = as_role(e, "clinician", "medicine"); p.step(act("review")); p.step(ans("allergy_any", True))
    r = p.step(act("submit")); assert want not in r["missing"] and want not in p.check()["clinician_queue"]

# ---- build checks refuse wrong types with a line, never a crash ----
@pytest.mark.parametrize("mut,field,item", [
    (lambda d: d.update(form_id=7), "form_id", "schema"),
    (lambda d: d.update(question=5), "question", "schema"),
    (lambda d: d["question"][0].update(id=7), "id", "question 1"),
    (lambda d: d["question"][0].update(version=7), "version", "question 1"),
    (lambda d: d["question"][0].update(text=7), "text", "question 1"),
    (lambda d: d["question"][3].update(disciplines=["medicine"]), "disciplines", "question 4"),
    (lambda d: d["question"][1].update(ask_if=5), "ask_if", "question 2"),
])
def test_build_refuses_wrong_types(mut, field, item):
    assert bad_schema(mut) == msg("ER-BAD-FIELD", field=field, item=item)


def test_step_return_shapes():
    e = env(role="clinician", discipline="medicine")
    n0 = len(e.log)
    r = e.step({"type": "answer", "question_id": "q1", "value": True, "role": "clinician"})
    _ = n0 = len(e.log)
    assert r["accepted"] is False and r["reason"] == F.code("role_fixed_at_session_open") and len(e.log) == n0
    n = e.step({"type": "next"})
    assert n["accepted"] is True
    f = e.step(act("submit"))
    assert f["accepted"] is True and f["final"] is False


@pytest.mark.parametrize("bad", [[], [""], [5]])
def test_build_refuses_bad_disciplines(bad):
    def m(d):
        q = next(q for q in d["question"] if q["safety_critical"]); q["disciplines"] = bad
    assert bad_schema(m).startswith("Setup error: disciplines")


# ---- S08 ruling: a blank safety question fails the submit and queues nothing ----
@pytest.mark.parametrize("routed_case", [False, True])
def test_s08_blank_safety_question_fails_submit_and_queues_nothing(routed_case):
    e = env(routed()) if routed_case else env()
    r = e.step(act("submit"))
    assert r["accepted"] and r["final"] is False
    assert msg("FL-UNKNOWN", n=e.num["allergy_any"]) in r["missing"]
    c = e.check()
    assert c["alerts"] == [] and not any(x.startswith(("Same-day", msg("CQ-BEFORE-PROC", item_id="", event_id="", status="")[:12])) for x in c["clinician_queue"])
    assert "sameday" not in e.patient_view() and "before_procedure" not in e.patient_view()
    assert all(x and not x.startswith("ERR:") for x in r["missing"])

def test_s08_unknown_answer_follows_alert_route():
    e = env(routed()); assert e.step(act("unknown", "allergy_any"))["accepted"]; k = len(e.log) - 1
    q = e.check()["clinician_queue"]
    assert bp_line("allergy_any", k, SD["unknown"]) in q and sd_line("allergy_any", k, SD["unknown"]) not in q
    assert e.patient_view()["before_procedure"] == msg("PV-BEFORE-PROC") and "sameday" not in e.patient_view()

def test_s08_unknown_only_patient_or_clinician_and_replays():
    for role, d, sc in (("patient_agent", None, ()), ("clinician_agent", None, ("medicine",))):
        e = env(role=role, discipline=d, scope=sc, grant=role == "patient_agent")
        assert e.step(act("unknown", "allergy_any"))["accepted"] is False
    c = env(role="clinician", discipline="medicine"); assert c.step(act("unknown", "allergy_any"))["accepted"]
    f = F.FormEnv(); f.reset(PH, "SYNTH-pt-01", "patient", EP); f.replay(c.log)
    assert f.check() == c.check() and f.check()["answers"]["allergy_any"] == "unknown"

# ---- trace faults ----
def test_t1_confirmed_agent_answer_reads_you_answered():
    e = env(role="patient_agent", grant=True); e.step(ans("smokes", False))
    p = as_role(e, "patient"); assert p.patient_view()["smokes"].startswith(msg("PV-ANS-AGENT"))
    assert p.step(act("confirm", "smokes"))["accepted"]
    assert p.patient_view()["smokes"] == msg("PV-ANS-SELF")

def test_t2_scope_refusal_before_nothing_to_confirm():
    e = env(FR, role="clinician", discipline="medicine", approve="physiotherapy")
    i = next(i for i in e.ids if e.q[i]["safety_critical"] and e.q[i].get("disciplines"))
    r = e.step(act("confirm", i))
    assert r["reason"].startswith(msg("RF-SCOPE", disciplines="")[:12])

def test_t2_agent_clin_form_before_role_confirm():
    e = env(FR, role="patient_agent")
    assert e.step(act("confirm", e.ids[0]))["reason"] == msg("RF-AGENT-CLIN-FORM")

def test_t3_bad_on_behalf_is_bad_field_and_no_empty_refusals():
    c = env(role="clinician", discipline="medicine")
    r = c.step(dict(ans("smokes", False), on_behalf="cousin"))
    assert r["reason"] == msg("ER-BAD-FIELD", field="on_behalf", item="answer")
    f = env(FR, role="patient")
    assert f.step(act("confirm", f.ids[0]))["reason"] == msg("PV-ROLE-CONFIRM")

def test_t3_no_refusal_is_ever_empty():
    for case in (PH, FR, PP):
        for role, d, sc in (("patient", None, ()), ("patient_agent", None, ()), ("clinician", "medicine", ()),
                            ("clinician_agent", None, ("medicine",))):
            e = env(case, role=role, discipline=d, scope=sc)
            for t in ("answer", "decline", "confirm", "unknown", "review", "approve", "grant", "close_sameday"):
                a = ans(e.ids[0], True) if t == "answer" else act(t, e.ids[0])
                r = e.step(a)
                assert r["accepted"] or r["reason"], (case, role, t)

@pytest.mark.parametrize("text", ["Can the patient walk without help?", "Is there anything nobody told you?"])
def test_t4_without_is_not_a_negative(text):
    d = copy.deepcopy(SPH); d["question"][2]["text"] = text
    F.check_schema(d)

@pytest.mark.parametrize("text", ["Do you not smoke?", "Have you never had surgery?", "Don't you smoke?", "Is there no allergy?"])
def test_t4_true_negatives_still_caught(text):
    assert bad_schema(lambda d: d["question"][2].update(text=text)) == msg("CK-NEGATIVE", n=3)


# ---- hash and CLI edges (mutation) ----
def test_schema_hash_is_key_order_free_and_utf8():
    d = {"b": "é", "a": 1}
    want = __import__("hashlib").sha256('{"a": 1, "b": "é"}'.encode()).hexdigest()
    assert F.schema_hash(d) == want == F.schema_hash({"a": 1, "b": "é"})

def test_cli_commands_need_exact_positions(tmp_path):
    log = str(tmp_path / "l.jsonl"); open(log, "w").close()
    assert F.main(["f", "build", PH, "extra"]) == 2
    assert F.main(["f", "status", PH]) == 2
    assert F.main(["f", "answer", PH, log, EP, "smokes=true", "--actor", "SYNTH-pt-01", "--ts", TS]) == 2
    assert F.main(["f", "nosuch", PH, log, EP, "--role", "patient", "--actor", "SYNTH-pt-01", "--ts", TS]) == 2
    assert F.main(["f", "answer", PH, log, "--role", "patient", "--actor", "SYNTH-pt-01", "--ts", TS]) == 2


# ---- round 11: no machine code ever reaches a patient screen ----
def _patient_refusals():
    out = []
    for case in (PH, FR, PP):
        e = env(case, role="patient")
        for t in sorted(F.FIELDS) + ["next"]:
            for i in [e.ids[0], "no_such_q"]:
                a = ans(i, True) if t == "answer" else act(t, i if "question_id" in F.FIELDS.get(t, ()) else None)
                if t == "close_sameday":
                    a["status"] = SD["confirmed"]
                if t in ("grant", "revoke"):
                    a = grant_ev(t)
                r = as_role(e, "patient").step(a)
                if not r["accepted"]:
                    out.append((case, t, r["reason"]))
        r = as_role(e, "patient").step(grant_ev(agent=""))
        out.append((case, "grant-no-agent", r["reason"]))
        for how, bad in (("bad type", {"type": "zzz", "timestamp": TS}), ("extra field", dict(ans(e.ids[0], True), zzz=1)),
                         ("bad timestamp", dict(ans(e.ids[0], True), timestamp="x")), ("role key", dict(act("submit"), role="clinician")),
                         ("interpreter", dict(ans(e.ids[0], True), interpreter=True)), ("on_behalf", dict(ans(e.ids[0], True), on_behalf="parent"))):
            out.append((case, how, as_role(e, "patient").step(bad)["reason"]))
    return out

KNOWN_RED = set()

def test_r11_no_err_on_patient_screens():
    bad = [x for x in _patient_refusals() if x[2].startswith("ERR:") and x[2] not in KNOWN_RED]
    assert bad == []

def test_r11_grant_names_agent_has_patient_line():
    assert env(role="patient").step(grant_ev(agent=""))["reason"] == msg("PV-GRANT-NAMES-AGENT")


def test_r11_patient_lines_for_confirm_refusals():
    p = env(role="patient")
    assert p.step(act("confirm", "smokes"))["reason"] == msg("PV-NOTHING-TO-CONFIRM")
    f = env(PP, role="patient")
    assert f.step(act("confirm", f.ids[0]))["reason"] == msg("PV-ROLE-CONFIRM")
    c = env(role="clinician", discipline="medicine")
    assert c.step(act("confirm", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")   # clinicians keep the RF line


OTHER_ID = "SYNTH-pt-77"

def test_r11_other_patient_never_shown():
    p = env(role="patient")
    for a in (grant_ev(patient=OTHER_ID), grant_ev("revoke", patient=OTHER_ID), grant_ev(agent=OTHER_ID, patient=OTHER_ID)):
        assert p.step(a) == {"accepted": False, "reason": msg("PV-ONLY-YOU")}
    import json as _j
    seen = _j.dumps([p.observe(), p.patient_view(), p.check(), p.log])
    assert OTHER_ID not in seen

def test_r11_patient_lines_for_each_code():
    p = env(role="patient")
    assert p.step(grant_ev("revoke"))["reason"] == msg("PV-NOTHING-TO-REVOKE")
    assert p.step(ans("no_such_q", True))["reason"] == msg("PV-QUESTION-NOT-FOUND")
    for t in ("approve", "review"):
        assert p.step(act(t))["reason"] == msg("PV-CARE-TEAM-STEP")
    assert p.step(dict(act("close_sameday", "smokes"), status=SD["confirmed"]))["reason"] == msg("PV-CARE-TEAM-STEP")
    c = env(role="clinician", discipline="medicine")
    assert c.step(ans("no_such_q", True))["reason"] == F.code("question_id")


def test_r11_role_key_refusal_changes_nothing():
    p = env(role="patient"); p.step(ans("smokes", False))
    before = (copy.deepcopy(p.log), p.session, p.check(), p.patient_view())
    for k, v in (("role", "clinician"), ("actor", "SYNTH-dr-01"), ("discipline", "medicine"), ("scope", ["medicine"])):
        r = p.step(dict(ans("allergy_any", True), **{k: v}))
        assert r == {"accepted": False, "reason": msg("PV-CARE-TEAM-STEP")}
    assert (p.log, p.session, p.check(), p.patient_view()) == before and p.session.role == "patient"

def test_r11_sweep_malformed_role_key_shows_signed_line():
    for case in (PH, FR, PP):
        r = env(case, role="patient").step(dict(act("submit"), role="clinician"))
        assert r["reason"] and not r["reason"].startswith("ERR:")


# ---- round 11: every patient refusal leaves everything unchanged; malformed actions never echo ----
BADF, BADV = "zzz_secret_field", "SYNTH-bad-value-937"

def _passed_pp():
    e = env(PP, "clinician", discipline="medicine")
    for q in e.ids:
        e.step(ans(q, False))
    if e.check()["alerts"]:
        e.step(act("review"))
    assert e.step(act("submit"))["final"]
    return as_role(e, "patient")

def _granted():
    e = env(role="patient"); e.step(grant_ev()); return e

CASES = {
    "action_type": (lambda: env(role="patient"), {"type": BADV, "timestamp": TS}),
    "fields": (lambda: env(role="patient"), dict(ans("smokes", True), **{BADF: BADV})),
    "timestamp": (lambda: env(role="patient"), dict(ans("smokes", True), timestamp=BADV)),
    "interpreter_clinician_only": (lambda: env(role="patient"), dict(ans("smokes", True), interpreter=True)),
    "on_behalf_clinician_only": (lambda: env(role="patient"), dict(ans("smokes", True), on_behalf="parent")),
    "final": (_passed_pp, None),
    "role_fixed_at_session_open": (lambda: env(role="patient"), dict(ans("smokes", True), role="clinician")),
    "nothing_to_confirm": (lambda: env(role="patient"), act("confirm", "smokes")),
    "grant_names_agent": (lambda: env(role="patient"), grant_ev(agent="")),
    "grant_names_this_patient": (lambda: env(role="patient"), grant_ev(patient="SYNTH-pt-77")),
    "nothing_to_revoke": (lambda: env(role="patient"), grant_ev("revoke")),
    "question_id": (lambda: env(role="patient"), ans("no_such_q", True)),
    "role_approve": (lambda: env(role="patient"), act("approve")),
    "role_review": (lambda: env(role="patient"), act("review")),
    "role_close_sameday": (lambda: env(role="patient"), dict(act("close_sameday", "smokes"), status=SD["confirmed"])),
}

def test_r11_cases_cover_every_mapped_code():
    assert set(CASES) == set(F.PATIENT_LINE)

@pytest.mark.parametrize("c", sorted(CASES))
def test_r11_patient_refusal_changes_nothing(c):
    mk, a = CASES[c]
    p = mk()
    if a is None:
        a = ans(p.ids[0], True)
    before = (copy.deepcopy(p.log), p.session, p.check(), p.patient_view())
    r = p.step(a)
    assert r == {"accepted": False, "reason": msg(F.PATIENT_LINE[c])}
    assert (p.log, p.session, p.check(), p.patient_view()) == before and p.session.role == "patient"

@pytest.mark.parametrize("c", ["action_type", "fields", "timestamp"])
def test_r11_malformed_action_never_echoes(c):
    p = CASES[c][0](); r = p.step(CASES[c][1])
    seen = json.dumps([r, p.patient_view(), p.check(), p.log])
    assert BADF not in seen and BADV not in seen and "timestamp" not in json.dumps([r, p.patient_view()])


# The signed code -> patient line mapping, pinned here independently of PATIENT_LINE (ids only).
EXPECTED_LINE = {
    "role_fixed_at_session_open": "PV-CARE-TEAM-STEP",
    "action_type": "PV-TRY-AGAIN",
    "fields": "PV-TRY-AGAIN",
    "timestamp": "PV-TRY-AGAIN",
    "interpreter_clinician_only": "PV-CARE-TEAM-STEP",
    "final": "PV-ALREADY-FINAL",
    "on_behalf_clinician_only": "PV-CARE-TEAM-STEP",
    "nothing_to_confirm": "PV-NOTHING-TO-CONFIRM",
    "grant_names_agent": "PV-GRANT-NAMES-AGENT",
    "grant_names_this_patient": "PV-ONLY-YOU",
    "nothing_to_revoke": "PV-NOTHING-TO-REVOKE",
    "question_id": "PV-QUESTION-NOT-FOUND",
    "role_approve": "PV-CARE-TEAM-STEP",
    "role_review": "PV-CARE-TEAM-STEP",
    "role_close_sameday": "PV-CARE-TEAM-STEP",
}

def test_r11_mapping_pinned():
    assert F.PATIENT_LINE == EXPECTED_LINE

@pytest.mark.parametrize("c", sorted(EXPECTED_LINE))
def test_r11_each_code_shows_its_signed_line(c):
    mk, a = CASES[c]
    p = mk()
    if a is None:
        a = ans(p.ids[0], True)
    assert p.step(a)["reason"] == msg(EXPECTED_LINE[c])

def test_r11_refuse_passes_unmapped_codes_through_unchanged():
    p = env(role="patient")
    assert p._refuse("ERR:zzz_unmapped") == {"accepted": False, "reason": "ERR:zzz_unmapped"}
    assert p._refuse(msg("RF-NOT-YOURS")) == {"accepted": False, "reason": msg("RF-NOT-YOURS")}

def test_t2_agent_on_unapproved_clinician_form_gets_audience_line():
    e = env(PP, "patient_agent", approve=None)
    for a in (ans("site_marked", True), act("submit"), act("confirm", e.ids[0])):
        assert e.step(a) == {"accepted": False, "reason": msg("RF-AGENT-CLIN-FORM")} and e.log == []
    p = env(PH, "patient_agent", approve=None)
    assert p.step(ans(p.ids[0], True))["reason"] == msg("RF-NOT-APPROVED")


# ---------- S15 severity 5: an agent never overwrites a patient's decline ----------
def _declined():
    e = env(); assert e.step(act("decline", "smokes"))["accepted"]
    return e


def _signed_by_id(lid):
    import os, re
    sib = pathlib.Path(os.environ.get("WARD_SIBLINGS_DIR") or ROOT.parent)
    raw = (sib / "wording" / "forms_orders_lines_SIGNED.md").read_bytes().decode("utf-8")
    return re.search(rf"^\| {re.escape(lid)} \|(?:.*\|)? (.*) \|$", raw, re.M).group(1)


def test_agent_answer_never_overwrites_a_decline():
    """Refused outright: not kept as a draft, never replaces the decline, never reaches the check or patient view."""
    for role, line in (("clinician_agent", "RF-CLIN-AGENT"), ("patient_agent", "RF-ROLE-CONFIRM")):
        e = _declined()
        if role == "patient_agent":
            p = as_role(e, "patient"); assert p.step(grant_ev())["accepted"]; e = p
        a = as_role(e, role, scope=("medicine",) if role == "clinician_agent" else ())
        before = (copy.deepcopy(a.log), a.check()["answers"]["smokes"], a.patient_view()["smokes"])
        r = a.step(ans("smokes", False))
        assert r["accepted"] is False and r["reason"] == msg(line) == _signed_by_id(line), (role, r)
        assert not [x for x in a.log if x.get("type") == "answer" and x.get("question_id") == "smokes"]   # no draft
        assert "smokes" not in a.check()["open"]
        assert (a.log, a.check()["answers"]["smokes"], a.patient_view()["smokes"]) == before
        assert a.check()["answers"]["smokes"] == "declined"


def test_decline_changed_only_by_patient_or_clinician_with_reason():
    c = as_role(_declined(), "clinician", discipline="medicine")
    n = len(c.log)
    r = c.step(ans("smokes", False))
    assert r["accepted"] is False and len(c.log) == n and c.check()["answers"]["smokes"] == "declined"
    assert c.step(dict(ans("smokes", False), reason="asked in person at clinic"))["accepted"]
    assert c.log[-1]["reason"] == "asked in person at clinic" and c.check()["answers"]["smokes"] != "declined"
    p = as_role(_declined(), "patient")
    assert p.step(ans("smokes", False))["accepted"] and p.check()["answers"]["smokes"] != "declined"


def test_check_status_is_the_full_submission_status():
    """The checker reports the full submission status: ST-CHECK-PASS after a pass (ST-CHECK-FAIL after a fail), next to
    the form status ST-FORM-DONE; before any submission there is no checked status."""
    c = env(PP, "clinician", discipline="medicine")
    while (q := c.step({"type": "next"})["next"]):
        assert c.step(ans(q, c.q[q]["alert_answer"] is False))["accepted"]
    assert c.check()["status"] == msg("ST-FORM-DONE") and c.check()["checked"] is None
    assert c.step(act("submit"))["result"] == msg("ST-CHECK-PASS")
    assert c.check()["checked"] == msg("ST-CHECK-PASS") == _signed_by_id("ST-CHECK-PASS")
    assert c.check()["status"] == msg("ST-FORM-DONE")
    f = env(PP, "clinician", discipline="medicine")
    assert f.step(act("submit"))["result"] == msg("ST-CHECK-FAIL") and f.check()["checked"] == _signed_by_id("ST-CHECK-FAIL")


def test_review_returns_the_queue_line_it_reviewed():
    e = env(role="patient_agent", grant=True); fail_n(e, 3)
    c = as_role(e, "clinician", "medicine")
    want = c.check()["clinician_queue"]
    assert want and want[0].startswith(_signed_by_id("CQ-THREE-FAILS").split("[")[0])
    assert c.step(act("review")) == {"accepted": True, "reviewed": want}


# ---------- room ruling 11:52: review never finalises; only the patient or a clinician in person resubmits ----------
def test_review_never_finalises_a_failed_form():
    e = env(role="patient_agent", grant=True); fail_n(e, 3)
    c = as_role(e, "clinician", "medicine")
    assert c.step(act("review"))["accepted"]
    out = c.check()
    assert out["final"] is False and out["checked"] == _signed_by_id("ST-CHECK-FAIL")


def test_clinician_agent_resubmit_is_refused_and_nothing_changes():
    e = env(); fail_n(e, 1)
    a = as_role(e, "clinician_agent", scope=("medicine",))
    before_log, before = list(a.log), a.check()
    assert a.step(act("submit")) == {"accepted": False, "reason": _signed_by_id("RF-CLIN-AGENT")}
    assert a.log == before_log and a.check() == before and a.check()["checked"] != _signed_by_id("ST-CHECK-PASS")


def test_clinician_agent_resubmit_after_review_is_refused():
    e = env(role="patient_agent", grant=True); fail_n(e, 3)
    c = as_role(e, "clinician", "medicine"); assert c.step(act("review"))["accepted"]
    a = as_role(c, "clinician_agent", scope=("medicine",))
    before_log = list(a.log)
    assert a.step(act("submit")) == {"accepted": False, "reason": _signed_by_id("RF-CLIN-AGENT")}
    assert a.log == before_log and a.check()["final"] is False


def test_resubmit_that_still_fails_never_reaches_check_pass():
    e = env(); fail_n(e, 1)
    r = e.step(act("submit"))
    assert r["accepted"] and r["final"] is False and r["result"] == _signed_by_id("ST-CHECK-FAIL")
    assert e.check()["checked"] == _signed_by_id("ST-CHECK-FAIL")


@pytest.mark.parametrize("who", ["patient", "clinician"])
def test_patient_or_clinician_in_person_resubmit_reruns_the_full_check(who):
    e = env(); fail_n(e, 1); scripted_patient(e)
    r_env = as_role(e, who, "medicine" if who == "clinician" else None)
    complete = r_env.check()["complete"]
    r = r_env.step(act("submit"))
    assert r["accepted"] and r["final"] is complete
    assert r["result"] == _signed_by_id("ST-CHECK-PASS" if complete else "ST-CHECK-FAIL")


# ---------- PV-RESUBMIT (signed row 125): the resubmit prompt after a clinician review of a failed form ----------
def _reviewed_failed_with_decline():
    e = env(); assert e.step(act("decline", "allergy_any"))["accepted"]; fail_n(e, 3)
    c = as_role(e, "clinician", "medicine"); assert c.step(act("review"))["accepted"]
    return as_role(c, "patient"), "allergy_any"


def test_resubmit_prompt_is_the_signed_line_after_review_only():
    e = env(); fail_n(e, 3)
    assert "resubmit" not in e.patient_view()
    p, _ = _reviewed_failed_with_decline()
    assert p.patient_view()["resubmit"] == _signed_by_id("PV-RESUBMIT")
    p.step(act("submit"))
    assert "resubmit" not in p.patient_view()


def test_resubmit_prompt_never_names_the_decline():
    p, qid = _reviewed_failed_with_decline()
    line = p.patient_view()["resubmit"]
    assert qid not in line and p.q[qid]["text"] not in line and "declin" not in line.lower()


# ---------- guardian session role (S13): a person acting for a child under REL-GUARDIAN ----------
GUARD = "SYNTH-PERSON-G13"


def g_env():
    e = F.FormEnv(); e.reset(PH, GUARD, "guardian", EP); e.replay(approval(PH))
    return e


def test_guardian_answer_is_recorded_on_behalf_and_shown_with_the_signed_relationship():
    e = g_env()
    assert e.step(dict(ans("allergy_any", False), on_behalf="guardian"))["accepted"]
    s = e._fold()[0]["allergy_any"]
    assert s["source"] == "guardian" and s["on_behalf"] == "guardian" and s["confirmed"] is True
    sig = _signed_by_id("PV-ANS-SDM").split("[relationship]")
    v = e.patient_view()["allergy_any"]
    assert v.startswith(_signed_by_id("REL-GUARDIAN-PT") + sig[1].split("[date]")[0])


def test_guardian_must_answer_as_guardian():
    e = g_env()
    r = e.step(dict(ans("allergy_any", False), on_behalf="parent"))
    assert r == {"accepted": False, "reason": _signed_by_id("ER-BAD-FIELD").replace("[field]", "on_behalf").replace("[item]", "answer")}
    assert e.log == g_env().log
    assert e.step(ans("allergy_any", False))["accepted"] and e.log[-1]["on_behalf"] == "guardian"


@pytest.mark.parametrize("t", ["approve", "review", "confirm", "grant", "close_sameday"])
def test_guardian_cannot_take_clinician_or_patient_only_steps(t):
    e = g_env()
    a = {"approve": act("approve"), "review": act("review"), "confirm": act("confirm", "allergy_any"),
         "grant": grant_ev(patient=GUARD), "close_sameday": dict(act("close_sameday", "allergy_any"), status="confirmed")}[t]
    assert not e.step(a)["accepted"] and e.log == g_env().log


def test_guardian_can_decline_submit_and_resubmit():
    e = g_env()
    assert e.step(act("decline", "allergy_any"))["accepted"] and e.step(act("submit"))["accepted"]


@pytest.mark.parametrize("a", [act("approve"), act("review"), act("confirm", "allergy_any"), {"type": "nope", "timestamp": TS}])
def test_guardian_screen_never_shows_a_machine_code(a):
    r = g_env().step(a)
    assert not r["accepted"] and not r["reason"].startswith("ERR:") and r["reason"] in set(__import__("messages").LINES.values()) | {
        _signed_by_id(v) for v in F.PATIENT_LINE.values()}
