# Rule register

Signer: 'Mathew' = signed instruction. 'TEXT PENDING FROM ROOM' = wording not yet written, no test on purpose.
'unsigned' = wording line from the draft, waiting for Physician. class is left blank for Physician.
Wording rows marked (blocked) depend on a pending rule and have no test yet.

| id | rule | signer | class | protects_role | test names |
|---|---|---|---|---|---|
| F-01 | Each question has id, version, text, alert_answer, safety_critical, clinician_must_confirm; ask_if optional | Mathew |  | all | test_question_fields_required |
| F-02 | ask_if is the only way a question can be not applicable | Mathew |  | patient | test_ask_if_only_way_not_applicable |
| F-03 | Negatively worded questions (no, not, never, without, none, n't) are refused at build | Mathew |  | patient | test_negative_wording_refused |
| F-04 | The store is the event log; bitsets are only a derived view | Mathew |  | all | test_bitsets_derived_from_log |
| F-05 | Answer event has question_id, question_version, value, source, actor, timestamp, episode_id | Mathew |  | all | test_answer_event_fields |
| F-06 | Values are strict bool; 1/0, strings and None are refused | Mathew |  | all | test_value_strict_bool |
| F-07 | Decline has no value, stays unanswered, shows chose not to answer, never read as no | Mathew |  | patient | test_decline_never_read_as_no |
| F-08 | An agent answer on a patient form stays the agent's until the patient confirms it | Mathew |  | patient | test_agent_answer_needs_patient_confirm |
| F-09 | An answer from a stale question version or another episode reverts the question to unanswered | Mathew |  | patient | test_stale_or_foreign_answer_reverts |
| F-10 | A clinician_must_confirm question is complete only with a clinician answer | Mathew |  | clinician | test_clinician_must_confirm_needs_clinician |
| F-11 | A decline blocks completion only on clinician_must_confirm questions | Mathew |  | patient | test_decline_blocks_only_clinician_must_confirm |
| F-12 | The alert answer raises a flag whatever the question's polarity | Mathew |  | clinician | test_alert_answer_flags_any_polarity |
| F-13 | On a safety_critical question, unanswered or declined raises the same alert | Mathew |  | clinician | test_safety_critical_unanswered_or_declined_alerts |
| F-14 | Agents never infer answers | Mathew |  | patient | test_agents_never_infer |
| F-15 | No WHO content | Mathew |  | all | test_no_who_content |
| F-16 | Schema has form_id, version and ordered questions with unique ids | Mathew |  | all | test_schema_unique_ids |
| F-17 | The schema hash is bound to the response | Mathew |  | all | test_schema_hash_bound |
| F-18 | status exits 0 complete, 1 incomplete, 2 invalid | Mathew |  | all | test_status_exit_codes |
| F-19 | export gives JSON | Mathew |  | all | test_export_json |
| F-20 | step() gates type and role; rejected actions give a reason and are not logged | Mathew |  | all | test_rejected_actions_not_logged |
| F-21 | decline and confirm are patient only | Mathew |  | patient | test_decline_confirm_patient_only |
| F-22 | replay(log) rebuilds the same check() report | Mathew |  | all | test_replay_equality |
| F-23 | observe() shows nothing from other episodes | Mathew |  | patient | test_observe_isolated_episode |
| F-24 | Two synthetic example schemas: patient history, pre-procedure safety check | Mathew |  | all | test_examples_build |
| F-25 | A scripted agent episode runs deterministically | Mathew |  | all | test_scripted_agent_episode |
| P-01 | roles fixed at session open | TEXT PENDING FROM ROOM |  |  |  |
| P-02 | separate patient and patient-agent roles | TEXT PENDING FROM ROOM |  |  |  |
| P-03 | patient grant and revoke | TEXT PENDING FROM ROOM |  |  |  |
| P-04 | jobs marked agent-doable or human-only | TEXT PENDING FROM ROOM |  |  |  |
| P-05 | tick evidence must reference a real record | TEXT PENDING FROM ROOM |  |  |  |
| P-06 | version lock on approval with a diff view | TEXT PENDING FROM ROOM |  |  |  |
| P-07 | propose tools with the checker run first | TEXT PENDING FROM ROOM |  |  |  |
| P-08 | source-line citations and a gap view | TEXT PENDING FROM ROOM |  |  |  |
| P-09 | three patient consent failures (safety gate) | TEXT PENDING FROM ROOM |  |  |  |
| W-PV-ANS-SELF | You answered | unsigned |  |  | test_line_pv_ans_self |
| W-PV-ANS-AGENT | Your assistant answered. You haven't checked this yet. | unsigned |  |  | test_line_pv_ans_agent |
| W-PV-DECLINED | You chose not to answer | unsigned |  |  | test_line_pv_declined |
| W-PV-SKIPPED | Not asked, because [condition plain wording] | unsigned |  |  | test_line_pv_skipped |
| W-PV-OPEN | Not answered yet | unsigned |  |  | test_line_pv_open |
| W-PV-GRANT | Your assistant can help with this form (from [date]) | unsigned |  |  | (blocked) |
| W-PV-REVOKE | Your assistant can no longer help with this form (from [date]) | unsigned |  |  | (blocked) |
| W-PV-REASK | We need to ask this again because the question changed or this is a new visit. | unsigned |  |  | test_line_pv_reask |
| W-PV-CONFIRM | Your assistant answered [Yes/No]. Is that right? | unsigned |  |  | test_line_pv_confirm |
| W-RF-ROLE-CONFIRM | Refused: only the patient's own session can confirm or decline this answer. | unsigned |  |  | test_line_rf_role_confirm |
| W-RF-NO-GRANT | Refused: the patient has not let an assistant help with this form. | unsigned |  |  | (blocked) |
| W-RF-REVOKED | Refused: the patient stopped this assistant helping on [date]. | unsigned |  |  | (blocked) |
| W-RF-NOT-BOOL | Refused: answers must be Yes or No. | unsigned |  |  | test_line_rf_not_bool |
| W-RF-NOT-APPROVED | Refused: this form or list is not approved by a clinician yet. | unsigned |  |  | (blocked) |
| W-CK-TWO-FACTS | Question [n] asks more than one thing. Split it. | unsigned |  |  | test_line_ck_two_facts |
| W-CK-NEGATIVE | Question [n] is worded as a negative. Reword it as a plain question. | unsigned |  |  | test_line_ck_negative |
| W-CK-NO-ALERT | Question [n] has no alert answer set. | unsigned |  |  | test_line_ck_no_alert |
| W-CK-COND-ORDER | Question [n] depends on a later question. | unsigned |  |  | test_line_ck_cond_order |
| W-CK-COND-WORDS | Question [n] has a condition with no plain wording. | unsigned |  |  | test_line_ck_cond_words |
| W-BK-UNANSWERED | Not finished: [k] questions still need an answer. | unsigned |  |  | test_line_bk_unanswered |
| W-BK-CLIN-CONFIRM | Not finished: a clinician must confirm question [n]. | unsigned |  |  | test_line_bk_clin_confirm |
| W-BK-STALE | Answer to question [n] is from another episode or an old version, so it must be asked again. | unsigned |  |  | test_line_bk_stale |
| W-FL-ALERT | Alert: question [n] was answered [alert answer]. | unsigned |  |  | test_line_fl_alert |
| W-FL-UNKNOWN | Alert: question [n] is safety-critical and was not answered. Treat as a risk. | unsigned |  |  | test_line_fl_unknown |
| W-FL-DECLINED | Alert: the patient chose not to answer question [n], which is safety-critical. Treat as a risk and ask in person. | unsigned |  |  | test_line_fl_declined |
