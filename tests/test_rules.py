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
    a = F.FormEnv(); a.reset(case, "SYNTH-dr-01", "clinician", ep, discipline)
    assert a.step({"type": "approve", "timestamp": TS})["accepted"]
    return a.log

def env(case=PH, role="patient", ep=EP, discipline=None, scope=(), approve="medicine", grant=False):
    """An env whose log already holds a clinician approval (and a patient grant if asked)."""
    log = approval(case, approve, ep) if approve else []
    if grant:
        p = F.FormEnv(); p.reset(case, "SYNTH-pt-01", "patient", ep); p.replay(log)
        assert p.step({"type": "grant", "timestamp": TS})["accepted"]; log = p.log
    e = F.FormEnv(); e.reset(case, "SYNTH-person-01", role, ep, discipline, scope); e.replay(log)
    return e

def ans(i, v):
    return {"type": "answer", "question_id": i, "value": v, "timestamp": TS}

def act(t, i=None):
    return {"type": t, "timestamp": TS, **({"question_id": i} if i else {})}

def as_role(e, role, discipline=None, scope=()):
    f = F.FormEnv(); f.reset(e.schema, "SYNTH-person-02", role, e.episode_id, discipline, scope); f.replay(e.log)
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

# ---------- signed rules (Mathew, earlier rounds) ----------
def test_question_fields_required():
    for k in ("id", "version", "text", "safety_critical", "clinician_must_confirm"):
        assert bad_schema(lambda d: d["question"][0].pop(k)) == msg("ER-BAD-FIELD", field=k, item="question 1")
    assert bad_schema(lambda d: d["question"][0].update(extra=1)) == msg("ER-BAD-FIELD", field="extra", item="question 1")
    assert bad_schema(lambda d: d["question"][0].update(safety_critical="yes")).startswith("Setup error")

def test_ask_if_only_way_not_applicable():
    e = env(); e.step(ans("allergy_any", False))
    assert e.check()["not_applicable"] == ["allergy_reaction_severe"]
    assert env().check()["not_applicable"] == []

def test_negative_wording_refused():
    for t in ("Do you have no allergies?", "Is it not marked?", "Never smoked?", "Without pain?", "None today?", "Can't walk?"):
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
    assert cli("answer", PP, log, *[f"{i}=true" for i in ids]) == 0
    assert F.main(["f", "status", PP, log, EP]) == 0
    assert cli("answer", PP, log, "site_marked=1") == 2
    assert F.main(["f"]) == 2

def test_export_json(tmp_path, capsys):
    log = str(tmp_path / "l.jsonl")
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
    assert as_role(a, "patient").step(act("confirm", "site_marked"))["reason"] == ""   # no line: patient sees nothing
    b = env(role="patient_agent", grant=True); b.step(ans("smokes", True))
    assert as_role(b, "clinician", "medicine").step(act("confirm", "smokes"))["reason"] == msg("RF-ROLE-CONFIRM")
    c = as_role(a, "clinician", "medicine")
    assert c.step(act("confirm", "site_marked"))["accepted"] and "site_marked" not in c.check()["open"]

def test_patient_agent_refused_on_clinician_form():
    e = env(PP, "patient_agent")
    assert e.step(ans("site_marked", True))["reason"] == msg("RF-AGENT-CLIN-FORM")
    assert as_role(e, "patient").step(act("grant"))["reason"] == msg("RF-AGENT-CLIN-FORM")

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

# ---------- generality (Mathew) ----------
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
    assert F.PERMS.keys() == {"patient", "patient_agent", "clinician", "clinician_agent"}

def test_permissions_table_by_role():
    assert F.PERMS == {
        "patient": {"answer", "decline", "confirm", "grant", "revoke", "next"},
        "patient_agent": {"answer", "next"},
        "clinician": {"answer", "confirm", "approve", "next"},
        "clinician_agent": {"answer", "next"}}
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
    p = as_role(a, "patient"); p.step(act("revoke"))
    assert as_role(p, "patient_agent").step(ans("allergy_any", True))["accepted"] is False   # (b)
    d = env(); d.step(act("decline", "smokes"))
    assert d.bitsets()["value"] == 0 and d.bitsets()["answered"] == 0 and d.check()["answers"]["smokes"] != False  # (c)

def test_p02_grant_and_revoke():
    assert env(role="patient_agent").step(ans("smokes", True))["reason"] == msg("RF-NO-GRANT")
    assert env(role="clinician", discipline="medicine").step(act("grant"))["reason"] == msg("RF-ROLE-CONFIRM")
    p = env(grant=True)
    assert [x["type"] for x in p.log] == ["approve", "grant"]
    p.step({"type": "revoke", "timestamp": "1936-05-03T09:00"})
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
        assert r["accepted"] is False and r["reason"] == ""                      # patient sees no code

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
    assert msg("BK-UNANSWERED", k=5) in env().check()["blocked"]

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
    p = env(grant=True); p.step({"type": "revoke", "timestamp": "1936-05-04T08:00"})
    assert p.patient_view()["access"] == "Your assistant can no longer help with this form (from 1936-05-04)"

def test_confirm_needs_unconfirmed_agent_answer():
    p = env()
    assert p.step(act("confirm", "smokes"))["reason"] == ""                      # nothing answered
    p.step(ans("smokes", True))
    assert p.step(act("confirm", "smokes"))["reason"] == ""                      # own answer: already final
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
        assert r["accepted"] and e.patient_view()["smokes"] == f"{words} answered, recorded by your care team on 1936-05-02."

def test_relationship_signed_list_clinician_only():
    from messages import RELATIONSHIP
    assert set(RELATIONSHIP) == {"parent", "guardian", "sdm"}
    for bad in ("carer", "Aunt SYNTH-Mary", ""):
        assert sdm(bad)[1]["accepted"] is False
    assert sdm("parent", role="patient")[1] == {"accepted": False, "reason": ""}
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
