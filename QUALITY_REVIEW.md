# Five quality questions for the alpha review

The review website now keeps the six existing aspect-level usefulness/perceived-accuracy ratings and adds exactly five **overall report-quality** questions. Answer them once per recording/report revision, after inspecting the applicable aspects.

1. **Clarity:** How clear and easy to understand is this report?
2. **Specificity:** How specific is the feedback to this crew, rather than generic rowing advice?
3. **Completeness:** How well does the report cover the rowers and movements visible in this clip?
4. **Evidence support:** How well do the annotations and examples support the report's claims?
5. **Actionability:** How useful is this report for deciding what to review or work on next?

Use1Very poor,2Poor,3Fair,4Good,5Excellent, or explicitly Cannot judge / Not applicable. No answer is selected automatically. An optional comment asks for the most important improvement. These ratings describe a reviewer experience, not calibrated model accuracy. A polished explanation can still be wrong.

## Save and export

The new section appears below the per-aspect workspace. Save quality separately with **Save quality assessment**. Reload restores the current reviewer's answers for that exact analysis and questionnaire version. Editing replaces that same assessment rather than creating duplicate submissions. The owner dashboard has **Quality ratings CSV** and **Quality ratings JSON** exports; existing aspect exports/counts remain separate. A missing/skip score remains null with an explicit reason.

Consent and session ownership are unchanged. The participant can withdraw both aspect and quality responses within their current session. Finish the session before the next person uses the computer. Do not share the private owner key. No names, email addresses or athlete-identifying comments are requested.

## Ten-clip study

The private delivery package contains the selected clips, reports, annotated media and a source-window guide; media are deliberately not committed publicly. Five strong existing recordings are retained and five additions are screened from the supplied archives. Duplicate archives and paired encodings are not independent clips. Some cases intentionally challenge crew separation; model success is not the selection criterion.

The plan remains **five rowers**, with four assigned clips per person. Across20clip reviews, each of the ten clips receives two participant judgments. Repeated clip/aspect judgments are not20 independent users. Allow roughly30–35minutes, confirm consent, show original video before model output, collect six aspect responses, then five report-quality answers once per clip. Keep Cannot judge and missing-output counts when summarizing results. Sessions remain planned, not completed.

The source includes the working form and tests; downloading source alone does not download private footage. Use the complete private pack for a new study or its guarded Upgrade-Existing command for the supported older pack. The upgrader preserves feedback/history, backs up app/catalog and does not delete old media. The local review URL remains http://127.0.0.1:8767/library; public hosting has not been deployed.

## Limits

Actual new videos were processed by the existing learned pose model plus deterministic StrokeSense calculations, not a new learned technique classifier. At least one intended four-person target returned seven model tracks and is clearly flagged as possible cross-crew contamination. Correct JSON/count checks are not true person identity, catch, angle or fault validation. Software tests use synthetic responses; no real rower feedback or coach approval is implied. See issue113 and the private guide for observed verification and remaining gaps.
