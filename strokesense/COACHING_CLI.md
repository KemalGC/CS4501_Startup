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


### Bounded provider requests

The optional HTTPS chat adapter rejects a whitelisted, serialized evidence
prompt larger than **64 KiB** before any network request. Requests include
`max_completion_tokens=512` as an explicit *output token* ceiling; response
bytes are independently capped at 128 KiB and the HTTPS call has an explicit
timeout. The prompt cap is a **byte limit**, not a guarantee of a particular
token count. These limits reduce unexpected cost/data transfer but cannot
guarantee the exact provider bill or model behavior. Some OpenAI-compatible
third-party endpoints may not support `max_completion_tokens`; compatibility
must be verified with authorized credentials before live use. A provider
request failure stays withheld and never changes local job release status.


### Candidate schema limits

The independent validator accepts only the documented exact candidate fields,
with nonblank `finding_id`, `seat_id`, `fault_code`, `cue_id` (each at most
128 characters), a nonblank explanation (at most 1,000 Unicode characters), and
1–5,000 unique stroke IDs (each nonblank and at most 128 characters).
Oversized fields fail closed with `invalid_candidate` before resolving
references or displaying generated text. These bounds supplement, rather than
replace, numeric/denominator, independent review, and eligibility checks.
Meeting size limits is **not** evidence that unconstrained explanation text
is accurate, safe, or coach-approved.


### Cue catalogue format

For any `cue_id` to be accepted by the **independent** validator, its
separately supplied `fault_codes` must be a nonempty JSON **array** of
distinct, recognized StrokeSense fault-code strings (no duplicates).
Strings, objects, null values and unknown fault codes cannot stand in
for that list, even when language-level membership operations would match.
The cue must also carry explicit `review_status="approved"` and a
nonblank `reviewed_by` value. These are software validation fields:
the CLI **cannot independently verify** a real coach signed off, and its
synthetic fixtures are fictional.

The opt-in HTTPS adapter applies the same nonempty, unique, known-code list
preflight **before sending any request**: malformed approved cue entries are
excluded from the outbound allowlist. If no valid reviewed cue remains, it
fails closed with `no_approved_cues`, without contacting the provider.
No model is asked to repair or approve cue catalogue metadata; the independent
release validator still checks it separately. This prevents avoidable requests,
not fraudulent reviewer claims or incorrect free-text coaching.
