# Reports library and extended study videos

The private rower-review website has a **Reports library** link and a directly addressable `/library` page. Start the review server on port8767, not the analysis server on8766. Consent/session checks still protect the videos and saved HTML; reports remain script-sandboxed.

Cards display the recording name, analyzed source window and provisional-report/diagnostic/unavailable status. Search by recording name. **Open report** opens that recording's report after consent and survives reload. **Review video** opens the matching rating view. Paired uploads remain separate entries with shared-recording labels. Missing files do not appear as successful report links.

Available model-overlay playback is selected initially; **Original footage** remains a separate view. The owner dashboard and version-bound ratings are unchanged. New analysis revisions do not overwrite or relabel prior feedback. Finish or withdraw sessions as documented in FEEDBACK.md.

## Longer dominant-crew analysis

From the outer strokesense directory, with the existing local pose model and dependencies:

```text
python -m strokesense.cli VIDEO --out results/extended --dominant-crew --fps 10 --threads 2
```

No duration limit means the full source clip is processed. The mode chooses the largest/clearest aligned group of pose detections from five pilot frames, then applies a spatial continuity gate. Other groups are excluded, and loss/camera changes leave gaps. It is geometric grouping, not a trained boat/hull detector or guaranteed correct identity tracking. It may fail or omit people when crews overlap, detections fragment or a boat becomes obscured. Existing explicit selection and legacy paths remain separate.

The mode uses observed intervals for stroke scoring. Leading/trailing absent frames do not force a zero-seat estimate, but those frames remain absent in output. It does not lower detection thresholds or invent measurements to fill a review form. The optional CPU thread count is1–64; the existing default is unchanged.

Annotations identify retained model tracks and supported body-motion DRIVE/RECOVERY phases, source time and observation counts. They are not verified physical seat numbers, blade-contact labels or coach-approved faults. Original videos and earlier reports should be retained.

Each report's validation section covers finite values, unique track IDs, ordered/in-range stroke boundaries, cycle counts and joint-observation denominators. Structural checks do not establish visual accuracy. SPM, projected angles and fault candidates still need independent human labels. Unsupported aspects remain unavailable rather than being padded.

## Private bundle

The updated user study contains full-length source previews, refreshed annotated videos, seven provisional reports and one diagnostic. No inference runs during review. The repository intentionally excludes these private recordings and metrics; obtain the private pack from the conversation rather than publishing it to GitHub.

Use the supplied updater to preserve an existing study's `.feedback` directory, or open the full package in a fresh folder for a new study. Do not distribute a folder containing participant databases or the owner key. This is not public hosting; localhost only works on the computer running the server.

Tests from repository root:

```text
python -m unittest discover -s strokesense/tests -p test_feedback_library.py -v
python -m unittest discover -s strokesense/tests -p test_dominant_crew.py -v
python strokesense/quality.py
python strokesense/tests/browser_feedback_library.py
```

Browser tests use synthetic fixtures and do not count as real participants or model-accuracy validation. The supplied clips used real local pose inference; no live Ollama inference or human accuracy certification is implied.
