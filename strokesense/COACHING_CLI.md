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

### Provider completion-state gate

Even an apparently schema-valid JSON object is **not** passed to the coaching
validator if the first HTTPS chat choice has a missing, filtered, truncated or
otherwise non-`stop` `finish_reason`. Such a response becomes a sanitized
`invalid_provider_response` / withheld generation failure, without exposing
model text or retrying that failed provider response. Offline fixtures use
explicit `finish_reason="stop"`. A provider reporting `stop` does **not**
prove the advice is true, consented, or professionally approved; independent
checks and the later human-review requirements remain necessary.


## One-command synthetic browser + coaching correction demo

From the `strokesense/` directory, run:

```sh
python -m strokesense.demo --verify-coaching
python -m strokesense.demo --simulate-failure --verify-coaching
```

The first command exercises a **temporary local loopback** upload → queued
synthetic job → pretend HTML report → saved evidence response, then independently
executes two deterministic coaching correction sequences: an incorrect
observed count is rejected and corrected on attempt 2; an invented stroke ID is
withheld after 3 attempts. Its small JSON summary includes
`coaching_validation` with attempt counts and `published=false`; the browser
job's `coaching_state` **remains `withheld`** and no candidate text is saved
or returned. The failure command exercises a failed job and outputs
`coaching_validation=null`; it never claims a successful release.

This is a **synthetic regression demonstration only**: the upload payload and
analyzer/report are fakes; the independently eligible finding and cue approval
are deliberately fictional; generated candidate responses are offline doubles,
**not live LLM completions**. No real recording is decoded, no pose model is
run, no network provider is contacted, no money is spent, and there are no
measured real-world technique metrics or real coach approvals. A local
`corrected_status="released"` represents structural validator success for a
fictional fixture, **not authorization to publish coaching**. The existing
`python -m strokesense.demo` command remains unchanged.


### Strict provider JSON decoding

The optional HTTPS adapter parses **both** the chat-response envelope and the
nested candidate JSON with the same fail-closed decoder. Repeated JSON object
field names at any nesting depth are rejected, including duplicates with the
same value. Python-specific non-JSON `NaN`, `Infinity` and `-Infinity`
literals and floating-point exponents that overflow to infinity are rejected.
A malformed response becomes sanitized `invalid_provider_response` and the
correction loop withholds it after a single provider error, with no candidate
text disclosed or repeated request. Conventional, finite, unambiguous JSON
remains subject to the independent evidence/cue validator.

These are **format and ambiguity checks**. They do not authenticate who
reviewed a cue, verify a provider's statements, infer athletic technique
accuracy, or certify the truth of any unstructured explanation. The
regression suite models responses offline; no live provider integration,
credential, charge, or real athlete data was used.


### Provider refusal and tool-call conflict gate

A chat choice with `finish_reason="stop"` is accepted only when its content
is an ordinary assistant reply: an explicitly non-assistant `role`, any
non-null `refusal`, a nonempty `tool_calls` value, or a non-null legacy
`function_call` cause sanitized `invalid_provider_response`, regardless of
whether a plausible JSON candidate is also present. The correction loop
withholds on such a provider error without showing the reply or retrying it.
A missing role is still supported for minimal OpenAI-compatible providers;
`role="assistant"`, `refusal=null`, `tool_calls=[]` and
`function_call=null` are accepted if all other format/evidence checks pass.

This is defense-in-depth against contradictory response metadata, **not**
proof that a message without a refusal is correct, reviewed or safe. The
contract tests use mock response objects and fictional approvals; real
provider compatibility, athlete consent and model-generated coaching
correctness remain untested.


### Malformed deeply nested model responses

The response body byte cap does not by itself prevent JSON with extreme nesting
depth. The provider adapter therefore treats JSON decoder `RecursionError`
as another **invalid provider response**, without exposing the raw reply or
retrying a generation error. This applies both to the outer API envelope and
to candidate JSON embedded in `message.content`, with independent validation
still required after decoding succeeds. Offline regression fixtures use 1,200
levels of short nested arrays; ordinary schema-valid complete responses remain
supported. This reduces crash risk from malformed HTTP replies; it is not a
general guarantee of bounded parsing CPU or memory for arbitrary input, nor a
claim about real model or coaching accuracy.


### Visible, render-safe candidate text

The independent release gate also rejects control characters that can conceal
text or alter a terminal/browser display, including NUL/ANSI escapes, C1
controls, and Unicode bidirectional override/isolate marks U+202A–U+202E and
U+2066–U+2069. This applies to candidate identifiers, stroke IDs and
explanations. Normal UTF-8 prose, accents and emoji joiners remain allowed;
explanations may still include conventional newline and tab characters.
Invalid candidate text is withheld as `invalid_candidate`, without returning
the rejected explanation. The regression fixtures insert **actual control
codepoints** rather than only their printed escape sequences.

This is a display-integrity precaution, **not** a general content-moderation
system or a guarantee against misinformation, prompt injection or all
invisible Unicode characters. Human reviewer authorization, empirical
technique accuracy and real footage validation remain separate requirements.
