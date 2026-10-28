# Local saved-evidence coaching verification (Alpha)

This is an **explicit, local validation runner**, not a published coaching
feature. The original analysis CLI, SQLite jobs, reports and browser are
unchanged. A JSON result with `status="released"` means that **the local
deterministic checks passed**, not that a coach approved the advice or that the
browser can show it. Every response includes `published=false`.

## Offline contract demo (no provider, video, or network required)

From the `strokesense/` directory:

```sh
python -m unittest discover -s tests -p test_coaching_cli.py -v
```

This runs synthetic fixtures that model an independently eligible finding and
fictional reviewer/approved cue. The tests demonstrate a rejected first
candidate corrected on the second attempt, three failed attempts withheld, an
unreviewed real-style v1 finding withheld, malformed inputs, and privacy
behavior. **The fictional review status is not a human review, and the
synthetic examples are not rowing accuracy measurements.**

To run with a prepared **private** saved metrics JSON, separate cue-catalog
JSON, and a *test-only* JSON array of 1–3 candidate objects:

```sh
python -m strokesense.coaching_cli --metrics /private/results/metrics.json --cues /private/approved_cues.json --candidates /private/fictional_candidates.json
```

`metrics.json` must contain the versioned `evidence` snapshot produced by
the analyzer. The separate cue JSON is a mapping from cue ID to an object with
`fault_codes`, `review_status="approved"`, and nonblank `reviewed_by`.
The runner cannot independently verify that these review assertions are real.
Unreviewed analyzer evidence remains **withheld**, even if a candidate and cue
file claim approval. The candidate array is deterministic offline input, **not
a live LLM response**; the output labels it `mode="offline_fixture"`.

Exit codes: `0` means the local candidate passed independent structural
validation; `1` means all supplied attempts were withheld; `2` means invalid
input or missing live configuration. Error output never includes raw rejected
advice, file paths, private candidate text, or provider exception strings.
Inputs are bounded to 16 MiB metrics, 256 KiB cues, and 256 KiB candidates.
The CLI does not modify any input files, saved job status, report, or database.

## Optional explicitly authorized real provider

**Only** for an operator who has appropriate rights, suitable independently
reviewed evidence, approval of external data sharing, and authorization for
provider spending:

```sh
# Set STROKESENSE_LLM_MODEL and STROKESENSE_LLM_API_KEY privately in your shell.
# STROKESENSE_LLM_ENDPOINT is an optional HTTPS OpenAI-compatible endpoint.
python -m strokesense.coaching_cli --metrics /private/results/metrics.json --cues /private/approved_cues.json --live
```

No provider request occurs unless `--live` is supplied. Missing credentials
fail closed before sending data. The adapter sends whitelisted evidence fields
and approved cue IDs, not footage/source paths or reviewer names. Network
errors and invalid output are withheld. The independent correction loop permits
**at most three total attempts**, never silently releases a rejected candidate.

**Release limitations:** valid IDs/counts and a cue-file `reviewed_by` string
do not prove truthful unconstrained prose, empirical accuracy, consent,
reviewer identity, safety, or coaching effectiveness. The snapshot checksum
is not a digital signature. The current analyzer leaves eligibility
unreviewed, so a production release path must wait for genuine reviewed
coverage, permission-cleared footage and an audited approval process.
Generated feedback is not propagated into the local browser or jobs.

Complete offline suite from repo root: `python strokesense/quality.py`.
Read-only preflight: `python strokesense/quality.py --doctor`.
