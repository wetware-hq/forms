# forms — the bar

What a green means in forms, and what it does not. A green here is not the same assurance as a green in a sibling repo; read this before quoting one.

**Not a medical device; not approved for real patient data.** A pass means the checks behaved as signed on synthetic data, nothing more.

## The bar

```bash
python3 -m pytest -q            # the suite
python3 scripts/rulecheck.py    # every rule has a test; WORDING.md matches its header hash; no lines pending
python3 scripts/mutate.py       # every mutant of every function in safety_functions.toml is caught
```

`pytest` green plus `rulecheck.py` exit 0 is forms' bar; `mutate.py` is the mutation gate over `safety_functions.toml`. Before pushing, maintainers also run `python3 scripts/prepush.py SIGNED_TABLE.md` (see below).

## What a green covers

- **Gate and roles** — `CALL_PERMS` lets a session reach only `observe`/`step`; `reset`, `replay`, `check`, `export` are harness-only; `PERMS` enforces the four roles, scope of practice, and that an assistant's answer is provisional until the right person confirms.
- **Append-only log** — state is rebuilt by replay; every logged submission result is recomputed; a correction is a new event, never a rewrite.
- **Build checks** — negative-worded questions and two-item ("and/or/,//") questions are refused; `two_item_ok` routes to the clinician queue.
- **Same-day / before-procedure queue** — a yes, decline, or still-unknown answer on a safety-critical question opens an entry; the form cannot pass until `review` or `close_sameday` with a signed status; a later "no" keeps the entry until reviewed.
- **Approval & export** — nothing is filled until a clinician approves that exact version; `export` refuses any episode whose first log event is not the harness-written `synthetic: true` flag.
- **Wording** — tests check `WORDING.md` against its header hash and that every line id used in code exists in it; `messages.py` holds no wording of its own.
- **Rules register** — `rulecheck.py` confirms every `RULES.md` row has a test that plants its failure.
- **Jurisdiction scan** — `tests/test_jurisdiction_scan.py` fails on any planted term in each category below, each on its own id.

The scan's category ids are not copied here: duplicating the registry would drift from it, and can trip the scan on an id that itself contains a scanned term. The authoritative list is the `[categories]` table in `jurisdiction_scan.toml`, and `test_bar.py` checks this bar points to it.

## What a green does NOT cover

- **Live-model behaviour.** S05 and S07 were checked with a scripted stand-in, not a real AI model; the runs show the checks catch those mistakes, not how a model behaves. Those tests are still to come.
- **The pre-push signed-table comparison.** `scripts/prepush.py SIGNED_TABLE.md` compares `WORDING.md` with the signed table and fails on internal names or local paths; it is a maintainer pre-push step and is not part of a plain `pytest` green.
- **The mutation sweep unless run.** `mutate.py` is a separate gate; a `pytest` green alone does not include it.
- **Clinical validity or real patients.** A green is a code check on synthetic data; forms gives no clinical advice and is not a medical device.

## Name guard

`test_bar.py` checks this bar names `jurisdiction_scan.toml` as the authoritative scan registry, rather than copying the category ids (a copy would drift from the registry and can trip the scan itself). The registry's own test (`test_each_category_planted_term_fails_on_its_own_id`) holds every category to one declared, planted id, so no scan check runs under a name the registry does not name.
