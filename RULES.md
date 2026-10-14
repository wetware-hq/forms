# Rule register

Signer is who signed the rule. class: safety where signed as safety; blank rows are still for Physician to mark.
Wording rows (W-) are the fixed lines this repo emits. All are signed by Physician; the source of truth is WORDING.md, checked word for word by scripts/rulecheck.py. CK-TWO-FACTS is not used: ruling R-03 replaced it with CK-TWO-ITEMS.
P rows not listed here (P-04, P-05, P-08) apply only to the other repo and are registered there.

| id | rule | signer | class | protects_role | test names |
|---|---|---|---|---|---|
| F-01 | Each question has id, version, text, alert_answer, safety_critical, clinician_must_confirm; ask_if optional | Mathew |  | all | test_question_fields_required |
| F-02 | ask_if is the only way a question can be not applicable | Mathew |  | patient | test_ask_if_only_way_not_applicable |
| F-03 | Negatively worded questions (no, not, never, without, none, n't) are refused at build | Mathew |  | patient | test_negative_wording_refused |
| F-04 | The store is the event log; bitsets are only a derived view | Mathew |  | all | test_bitsets_derived_from_log |
| F-05 | Answer event has question_id, question_version, value, source (role), actor, timestamp, episode_id | Mathew |  | all | test_answer_event_fields |
| F-06 | Values are strict bool; 1/0, strings and None are refused | Mathew |  | all | test_value_strict_bool |
| F-07 | Decline has no value, stays unanswered, shows chose not to answer, never read as no | Mathew |  | patient | test_decline_never_read_as_no |
| F-08 | An agent answer on a patient form stays the agent's until the patient confirms it | Mathew |  | patient | test_agent_answer_needs_patient_confirm, test_confirm_needs_unconfirmed_agent_answer |
| F-09 | An answer from a stale question version or another episode reverts the question to unanswered | Mathew |  | patient | test_stale_or_foreign_answer_reverts |
| F-10 | A clinician_must_confirm question is complete only with a clinician answer | Mathew |  | clinician | test_clinician_must_confirm_needs_clinician |
| F-11 | A decline blocks completion only on clinician_must_confirm questions | Mathew |  | patient | test_decline_blocks_only_clinician_must_confirm |
| F-12 | The alert answer raises a flag whatever the question's polarity | Mathew | safety | clinician | test_alert_answer_flags_any_polarity |
| F-13 | On a safety_critical question, unanswered or declined raises the same alert | Mathew | safety | clinician | test_safety_critical_unanswered_or_declined_alerts, test_flags_only_where_due |
| F-14 | Agents never infer answers | Mathew |  | patient | test_agents_never_infer |
| F-15 | No WHO content | Mathew |  | all | test_no_who_content |
| F-16 | Schema has form_id, version and ordered questions with unique ids | Mathew |  | all | test_schema_unique_ids |
| F-17 | The schema hash is bound to the response | Mathew |  | all | test_schema_hash_bound |
| F-18 | status exits 0 complete, 1 incomplete, 2 invalid | Mathew |  | all | test_status_exit_codes |
| F-19 | export gives JSON | Mathew |  | all | test_export_json |
| F-20 | step() gates type and role; rejected actions give a reason and are not logged | Mathew |  | all | test_rejected_actions_not_logged |
| F-21 | decline is patient only | Mathew |  | patient | test_decline_confirm_patient_only |
| F-22 | replay(log) rebuilds the same check() report | Mathew |  | all | test_replay_equality |
| F-23 | observe() shows nothing from other episodes | Mathew |  | patient | test_observe_isolated_episode |
| F-24 | Synthetic example schemas: patient history, pre-procedure safety check | Mathew |  | all | test_examples_build |
| F-25 | A scripted agent episode runs deterministically | Mathew |  | all | test_scripted_agent_episode |
| R-01 | audience decides who confirms an agent's answer: patient on a patient form, a clinician in their own session on a clinician form; an agent's answer is never final until confirmed | Physician | safety | patient | test_audience_decides_confirmer |
| R-02 | The patient's agent can only be granted patient-audience forms; answering a clinician form is refused | Physician | safety | patient | test_patient_agent_refused_on_clinician_form |
| R-03b | Only a clinician in their own session can set two_item_ok; an agent or a proposed form setting it is refused | Scientist / Physician | safety | patient | test_two_item_ok_set_only_by_clinician |
| R-06 | Answers given for the patient: the recording clinician picks parent, guardian or substitute decision-maker in their own session; logged with the answer; no free text; carer not allowed | Educator / Patient / Physician |  | patient | test_relationship_signed_list_clinician_only, test_cli_on_behalf |
| R-03 | Questions joining items with and, or, a comma or a slash are refused unless flagged two_item_ok; flagged questions go to a clinician queue file | Scientist / Physician | safety | patient | test_two_items_refused_unless_flagged_to_queue |
| G-01 | Roles: patient, patient_agent, clinician (any registered health professional, free discipline field), clinician_agent | Mathew |  | all | test_roles_are_four_with_discipline |
| G-02 | Permissions are a table keyed by role | Mathew |  | all | test_permissions_table_by_role |
| G-03 | One synthetic allied-health example | Mathew |  | all | test_allied_health_example |
| S-01 | Scope of practice: safety_critical items list allowed disciplines; gate checks role and discipline together | Scientist / Physician | safety | patient | test_scope_of_practice_refuses_other_discipline |
| S-02 | If no disciplines are listed, scope defaults to the approving clinician's discipline | Scientist / Physician | safety | patient | test_scope_defaults_to_approver_discipline |
| S-03 | Unregistered users (carer, assistant, family) are refused; no such role in v1 | Scientist / Physician | safety | patient | test_unregistered_role_refused |
| S-05 | clinician_agent is limited to the scope of practice of the clinician who granted it | Physician | safety | patient | test_clinician_agent_limited_to_granter_scope |
| S-04 | clinician_agent can draft and propose, never confirm, cancel or approve | Physician | safety | patient | test_clinician_agent_cannot_confirm_or_approve |
| S-06 | Strict Boolean: an answer value, and every yes/no field in a form (alert_answer, safety_critical, clinician_must_confirm, two_item_ok, ask_if equals), is accepted only if it is a real true or false (type is bool). 1, 0, "yes", "false", null, 1.0 and anything else are refused with RF-NOT-BOOL; a refused answer is never logged and the question stays unanswered | Physician | safety | patient | test_s06_answer_strict_bool_refused_not_logged, test_s06_answer_real_bool_accepted, test_s06_schema_yes_no_fields_strict_bool, test_s06_ask_if_equals_strict_bool |
| P-01 | Consent failures (Patient): each fails the gate on any seed: (a) an agent's answer shown as "You answered" before the patient confirms; (b) any agent action accepted after a revoke; (c) a decline counted as a no. | Physician | safety |  | test_p01_consent_failures, test_p01_confirmed_agent_answer_drops_confirm_prompt |
| P-02 | Grant and revoke (Patient): only the patient's own session can grant or revoke their agent's access to a form; both are logged. Without a grant, an agent session is refused. The patient can see every answer and who gave it. A grant covers only forms whose audience is patient. | Physician | safety |  | test_p02_grant_and_revoke |
| P-03 | Patient's agent role (Engineer/Patient): patient, patient's agent and clinician are separate roles. Only a person's own session can confirm, decline or cancel. The patient's agent answering a clinician form is refused with a table line. | Physician | safety |  | test_p03_separate_roles_own_session |
| P-06 | Version lock (Physician): approval covers that form/list version only. Any edit needs fresh approval by a clinician; the approval view shows only what changed from the last approved version. | Physician | safety |  | test_p06_version_lock_and_diff_view |
| P-07 | Propose tools (Director/Scientist): propose_form and propose_list take effect only after a clinician approves in their own session. A proposed form must first pass the fixed checker: one fact per question, no negatives, alert answer set, conditions point back only and never loop, safety-critical questions marked, every condition has plain wording. | Physician | safety |  | test_p07_propose_needs_checker_and_approval |
| P-09 | Roles fixed at session start (Engineer): roles are set when the session opens and never passed in a call. | Physician | safety |  | test_p09_roles_fixed_at_session_open |
| W-PV-ANS-SELF | You answered | Physician (signed) |  |  | test_line_pv_ans_self |
| W-PV-ANS-AGENT | Your assistant answered. You haven't checked this yet. | Physician (signed) |  |  | test_line_pv_ans_agent |
| W-PV-DECLINED | You chose not to answer | Physician (signed) |  |  | test_line_pv_declined |
| W-PV-SKIPPED | Not asked, because [condition plain wording] | Physician (signed) |  |  | test_line_pv_skipped |
| W-PV-OPEN | Not answered yet | Physician (signed) |  |  | test_line_pv_open |
| W-PV-GRANT | Your assistant can help with this form (from [date]) | Physician (signed) |  |  | test_line_pv_grant |
| W-PV-REVOKE | Your assistant can no longer help with this form (from [date]) | Physician (signed) |  |  | test_line_pv_revoke |
| W-PV-REASK | We need to ask this again because the question changed or this is a new visit. | Physician (signed) |  |  | test_line_pv_reask |
| W-PV-CONFIRM | Your assistant answered [Yes/No]. Is that right? | Physician (signed) |  |  | test_line_pv_confirm |
| W-RF-ROLE-CONFIRM | Refused: only the patient's own session can confirm or decline this answer. | Physician (signed) |  |  | test_line_rf_role_confirm |
| W-RF-NO-GRANT | Refused: the patient has not let an assistant help with this form. | Physician (signed) |  |  | test_line_rf_no_grant |
| W-RF-REVOKED | Refused: the patient stopped this assistant helping on [date]. | Physician (signed) |  |  | test_line_rf_revoked |
| W-RF-NOT-BOOL | Refused: answers must be Yes or No. | Physician (signed) |  |  | test_line_rf_not_bool |
| W-RF-NOT-APPROVED | Refused: this form or list is not approved by a clinician yet. | Physician (signed) |  |  | test_line_rf_not_approved |
| W-CK-NEGATIVE | Question [n] is worded as a negative. Reword it as a plain question. | Physician (signed) |  |  | test_line_ck_negative |
| W-CK-NO-ALERT | Question [n] has no alert answer set. | Physician (signed) |  |  | test_line_ck_no_alert |
| W-CK-COND-ORDER | Question [n] depends on a later question. | Physician (signed) |  |  | test_line_ck_cond_order |
| W-CK-COND-WORDS | Question [n] has a condition with no plain wording. | Physician (signed) |  |  | test_line_ck_cond_words |
| W-BK-UNANSWERED | Not finished: [k] questions still need an answer. | Physician (signed) |  |  | test_line_bk_unanswered |
| W-BK-CLIN-CONFIRM | Not finished: a clinician must confirm question [n]. | Physician (signed) |  |  | test_line_bk_clin_confirm |
| W-BK-STALE | Answer to question [n] is from another episode or an old version, so it must be asked again. | Physician (signed) |  |  | test_line_bk_stale |
| W-FL-ALERT | Alert: question [n] was answered [alert answer]. | Physician (signed) |  |  | test_line_fl_alert |
| W-FL-UNKNOWN | Alert: question [n] is safety-critical and was not answered. Treat as a risk. | Physician (signed) |  |  | test_line_fl_unknown |
| W-FL-DECLINED | Alert: the patient chose not to answer question [n], which is safety-critical. Treat as a risk and ask in person. | Physician (signed) |  |  | test_line_fl_declined |
| W-RF-AGENT-CLIN-FORM | Refused: the patient's assistant can only help with the patient's own forms. | Physician (signed) |  |  | test_line_rf_agent_clin_form |
| W-CK-TWO-ITEMS | Question [n] lists more than one thing. Split it, or send it to a clinician to check. | Physician (signed) |  |  | test_line_ck_two_items |
| W-CQ-TWO-ITEMS | For a clinician to check: question [n] names more than one thing. | Physician (signed) |  |  | test_line_cq_two_items |
| W-ST-FORM-DONE | Form complete: every question has an answer, or was skipped or declined. | Physician (signed) |  |  | test_line_st_form_done |
| W-PV-NEXT | Next for you: [question or job plain wording] | Physician (signed) |  |  | test_line_pv_next |
| W-PV-NOTHING-NEXT | There's nothing for you to do right now. | Physician (signed) |  |  | test_line_pv_nothing_next |
| W-ER-DUP-ID | Setup error: the id [id] is used more than once. | Physician (signed) |  |  | test_line_er_dup_id |
| W-ER-BAD-FIELD | Setup error: [field] in [item] is missing or not allowed. | Physician (signed) |  |  | test_line_er_bad_field |
| W-ER-BAD-COMMAND | Command not recognised. Run with --help to see the commands. | Physician (signed) |  |  | test_line_er_bad_command |
| W-RF-SCOPE | Refused: this item can only be confirmed, cancelled or ticked by [disciplines]. | Physician (signed) |  |  | test_line_rf_scope |
| W-RF-UNREGISTERED | Refused: only registered health professionals and patients can use this in version 1. | Physician (signed) |  |  | test_line_rf_unregistered |
| W-RF-CLIN-AGENT | Refused: a clinician's assistant can draft and propose, but cannot confirm, cancel or approve. | Physician (signed) |  |  | test_line_rf_clin_agent |
| W-PV-ANS-CLIN | Your care team answered: [discipline], on [date]. | Physician (signed) |  |  | test_line_pv_ans_clin |
| W-PV-ANS-SDM | [relationship] answered for you, recorded by your care team on [date]. | Physician (signed) |  |  | test_line_pv_ans_sdm |
