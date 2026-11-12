# Overnight improvement report

The PDF records the implementation and evidence at the user's pause point on
10 November 2026. It distinguishes tracking coverage, synthetic accuracy tests,
selected source-frame audits, and remaining limitations.

`build_report.py` recreates the six-page report with ReportLab and verifies its
page count using pypdf. It reads the committed tracking evaluation and requires
the local source-overlay artifact at
`results/body-motion-evaluation/crop-edge-comparison/torso-comparison.jpg`.
That private visual is embedded in the delivered PDF; raw footage, model weights,
and intermediate inference caches are not included in the repository.

Run with an environment containing `reportlab` and `pypdf`:

```
python evaluation/reports/build_report.py
```

Render the PDF with Poppler and inspect every page after changes. The original
report was rendered and visually reviewed at delivery.
