# Alpha engineering audit — November 4, 2026 Eastern

This is software evidence, not participant data or a coaching-accuracy claim.

## Pinned results
- Tested source: `9f37e9172c39ac7dec901f7a02369d609c454595`.
- Evidence run: https://github.com/KemalGC/CS4501_Startup/actions/runs/41939439412
- Python suite: **750 executions, 675 distinct printed unittest IDs, 75 repeated discoveries**, all passed; zero failures/errors/skips.
- Hosted HTTP suite: **24 distinct tests, 24 passed**, counted separately.
- Python line coverage: **6490/8044 = 80.68125310790651%**.
- Branch coverage: **2373/3278 = 72.39170225747407%**, not the same as line coverage.
- Scope: Python package `strokesense` under the declared unit command; excludes the independently hosted Site frontend and is not model accuracy.

Commands from `strokesense/`:
```sh
python -m unittest discover -s tests -p 'test_alpha_metrics*.py' -v
python -m coverage run --branch --source=strokesense -m unittest discover -s tests -p 'test_*.py' -v
python -m coverage json -o coverage.json
python -m unittest discover -s hosting_tests -p 'test_*.py' -v
```

## Exact counting method
The issue snapshot contains 109 non-PR issues: 77 closed, 32 open. These are checkpoint counts, not a claim about future issue states or Alpha completion. Nine core story groups map to 21 actual issue tickets. PR #118 is implementation evidence and excluded from the issue denominator; issue #16 is included for bounded correction.

`core-test-modules.json` selects full printed test IDs by their module prefix from the unit and hosted logs. Deduplicate IDs within each mapped issue and retain zero-test issues. This produces **292 test-to-issue links / 21 mapped issues = 13.904761904761905 tests per issue**. In this explicit map all 292 links are distinct. A mapping is acceptance traceability, not proof every listed issue is closed.

Per-issue counts: #29=8, #88=5, #94=17, #98=11, #100=12, #108=36, #95=4, #111=11, #14=15, #15=19, #16=7, #17=22, #50=7, #56=6, #120=5, #110=43, #115=32, #117=0, #119=14, #121=0, #122=18.

## Provenance and human review
The 18 tests in `test_alpha_metrics` and `test_alpha_metrics_multiline` were AI-authored during this reporting task. No human-refinement record is asserted for them. The other 657 distinct Python test IDs have unknown per-test authorship in this audit. Do not infer a full-suite AI/manual percentage or call unknown tests human-written. The team must inspect/refine the tests and record reviewer/date/change IDs separately.

## Test-first evidence
- RED commit `fb94067be7cce7afe564227ff60ce0a8ebc2f357`: 16 acceptance tests committed while the implementation module was absent.
- Observed failed run: https://github.com/KemalGC/CS4501_Startup/actions/runs/41937819625
- GREEN commit `90f1f7310e838c6d1bf206ada30beffc139e7277`; passing run https://github.com/KemalGC/CS4501_Startup/actions/runs/41938539018
- Additional regression commit `b228bcc0535246a30950f152b11c3cbba92b96f9`: multiline unittest descriptions and quiet-log identity behavior. The multiline case failed before its fix.
- Fix `9f37e9172c39ac7dec901f7a02369d609c454595`: 18 reporting tests pass; complete unit and hosted suites pass.

This proves a tests-first sequence for the reporting utility only. The committed history of `alpha_validation.py` and its tests does not independently establish tests-first order for that earlier calculator; do not retroactively claim every historical issue followed TDD. Preserve any genuine local evidence separately.

## Alpha scope and missing empirical evidence
The revised cohort is **7 rowers total, including 2 with prior coaching experience**. Names, verified inclusion/consent status, and per-person results remain unfilled until the team supplies them. R01–R07 are placeholders, not fabricated participants. The original hypothesis remains not yet validated without actual paired timings, preserved-detail responses and independent reference labels.

Keep #119 open for real validation, #120 open for a verified live generated/validated cue in the connected UI, and #121 open for the real public optional-demo upload flow until their acceptance evidence exists. Do not call the offline synthetic correction demo a live LLM run. Main and the independently hosted public Site are unchanged by this audit.

## Deliverables
The activities document contains the full nine core stories and their acceptance criteria, an outreach/participant ledger with placeholders, KPI definitions and missing-result fields, decisions, and this QA scope. The revised deck uses full explanatory sentences and slide-specific speaker notes. Course deadline: November 5, 2026 at 11:00 a.m. Eastern; submit slides PDF, separate activities PDF, and repository link.
