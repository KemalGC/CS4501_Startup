"""Inline, self-contained CSS for the private loopback StrokeSense workspace.

No external assets or requests: compatible with the local server's restrictive CSP.
"""
PAGE_CSS = r"""
:root {
  color-scheme: light;
  --ink: #17263b;
  --muted: #5b6b7c;
  --night: #101c2f;
  --night-light: #1b3049;
  --teal: #087f70;
  --teal-deep: #075e55;
  --mint: #dff5ee;
  --line: #dce6eb;
  --surface: #ffffff;
  --canvas: #f2f6f7;
  --focus: #b45309;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; min-width: 280px; color: var(--ink); background: var(--canvas); font-size: 16px; line-height: 1.55; }
a { color: var(--teal-deep); text-underline-offset: .18em; overflow-wrap: anywhere; }
a:hover { color: #053e38; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }
.skip-link { position: absolute; top: -90px; left: 1rem; z-index: 100; padding: .7rem 1rem; border-radius: .65rem; color: #fff; background: #1f2937; font-weight: 700; }
.skip-link:focus { top: .7rem; }
.topbar { background: var(--night); color: #fff; border-bottom: 1px solid #31445e; }
.topbar-inner { max-width: 1160px; margin: 0 auto; padding: .85rem 1.4rem; display: flex; align-items: center; gap: 1.4rem; flex-wrap: wrap; }
.brand { display: inline-flex; align-items: center; gap: .7rem; text-decoration: none; color: #fff; font-size: 1.2rem; font-weight: 800; letter-spacing: -.04em; }
.brand:hover { color: #fff; }
.brand-mark { display: grid; place-items: center; width: 2.5rem; height: 2.5rem; border-radius: .7rem; color: #0b473e; background: #80ead0; font-size: 1.5rem; }
.brand-accent { color: #8ee9d5; }
.topbar nav { display: flex; flex-wrap: wrap; gap: .3rem; margin-left: auto; }
.topbar nav a { display: inline-flex; align-items: center; min-height: 2.6rem; padding: .45rem .85rem; border-radius: .65rem; color: #e7f2f6; text-decoration: none; font-weight: 650; }
.topbar nav a:hover { background: var(--night-light); color: #fff; }
.local-pill { border: 1px solid #53736e; border-radius: 99px; padding: .25rem .75rem; color: #ccf9e8; font-size: .83rem; font-weight: 700; white-space: nowrap; }
.local-pill::before { content: ""; display: inline-block; background: #6be7b7; width: .5rem; height: .5rem; margin-right: .5rem; border-radius: 50%; }
.workspace { max-width: 1160px; padding: 0 1.4rem 3.5rem; margin: 0 auto; }
.hero { padding: 2.8rem 0 1.65rem; }
.eyebrow { color: var(--teal-deep); text-transform: uppercase; font-size: .78rem; font-weight: 800; letter-spacing: .16em; }
.eyebrow span { color: var(--muted); }
.hero h1 { margin: .5rem 0 .45rem; font-size: clamp(2rem, 5vw, 3.25rem); line-height: 1.14; letter-spacing: -.055em; color: var(--night); }
.hero p { color: var(--muted); font-size: 1.06rem; margin: 0; max-width: 52rem; }
.content-surface { background: var(--surface); border: 1px solid var(--line); border-radius: 1.15rem; padding: clamp(1.1rem, 3vw, 2.4rem); box-shadow: 0 12px 40px rgb(25 59 79 / 7%); }
main > p:first-child { background: #ecf8f3; border-left: 4px solid var(--teal); padding: .9rem 1.05rem; margin: 0 0 1.6rem; border-radius: 0 .65rem .65rem 0; }
h2 { margin: 2.3rem 0 .8rem; padding-top: .35rem; border-top: 1px solid var(--line); font-size: 1.32rem; letter-spacing: -.035em; line-height: 1.3; scroll-margin-top: 1.5rem; }
main > h2:first-of-type { border-top: none; margin-top: 1.6rem; }
h3 { margin-top: 1.5rem; font-size: 1.08rem; }
p { overflow-wrap: anywhere; }
main p { max-width: 78ch; }
form { border: 1px solid var(--line); background: #fbfdfe; padding: 1.1rem; border-radius: .9rem; margin: .9rem 0; display: flex; align-items: end; gap: .95rem; flex-wrap: wrap; }
form label { display: block; flex: 1 1 205px; min-width: 0; margin: 0; color: #32465b; font-size: .92rem; font-weight: 650; }
form[action="/upload"] { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); background: #f5fbf9; border-color: #b5ddd3; }
form[action="/upload"] label:first-child { grid-column: 1 / -1; }
form[action="/upload"] label:has(input[type="checkbox"]) { display: flex; align-items: flex-start; gap: .5rem; font-weight: 550; }
form[action="/upload"] label:has(input[type="checkbox"]) input { margin-top: .32rem; }
form[action="/upload"] button { justify-self: start; }
input, select, button { font: inherit; }
input[type="text"], select { display: block; width: 100%; margin-top: .4rem; padding: .66rem .72rem; color: var(--ink); border: 1px solid #aabec8; border-radius: .58rem; background: #fff; min-height: 2.7rem; }
input[type="file"] { display: block; width: 100%; margin-top: .45rem; border: 2px dashed #80bbb0; border-radius: .8rem; padding: 1.1rem; background: #fff; color: var(--ink); cursor: pointer; }
input[type="file"]::file-selector-button { border: 0; border-radius: .5rem; background: var(--night); color: #fff; font-weight: 700; padding: .65rem .85rem; cursor: pointer; margin-right: .8rem; }
input[type="checkbox"] { width: 1.1rem; height: 1.1rem; accent-color: var(--teal); }
button, input[type="submit"] { min-height: 2.75rem; border: 1px solid var(--teal-deep); border-radius: .6rem; padding: .65rem 1.1rem; background: var(--teal); color: #fff; font-weight: 800; cursor: pointer; box-shadow: 0 3px 8px rgb(8 127 112 / 12%); }
button:hover, input[type="submit"]:hover { background: var(--teal-deep); }
button:disabled { opacity: .65; cursor: not-allowed; }
form[action="/revoke"] button { background: #fff; color: #974117; border-color: #d6a189; box-shadow: none; }
form[action="/revoke"] button:hover { background: #fff2eb; }
ol, ul { padding-left: 1.3rem; }
main li { padding: .55rem .45rem; border-bottom: 1px solid #e6edf0; overflow-wrap: anywhere; }
main li:last-child { border-bottom: 0; }
main ol { border: 1px solid var(--line); border-radius: .8rem; background: #fbfdfe; padding: .6rem 1rem .6rem 2.5rem; }
main ol li { padding: .7rem .25rem; }
code, pre { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
pre { max-width: 100%; overflow: auto; padding: 1rem; background: #eaf1f4; border-radius: .65rem; }
table { width: 100%; border-collapse: collapse; display: block; max-width: 100%; overflow-x: auto; }
th, td { padding: .65rem; text-align: left; border-bottom: 1px solid var(--line); }
th { background: #ecf3f5; }
video { display: block; width: 100%; max-width: 760px; height: auto; border-radius: .8rem; background: #091421; }
.state-badge { display: inline-flex; align-items: center; padding: .3rem .85rem; border: 1px solid transparent; border-radius: 100px; font-size: .9rem; font-weight: 800; text-transform: capitalize; line-height: 1.6; }
.state-badge::before { content: ""; width: .55rem; height: .55rem; border-radius: 50%; background: currentColor; margin-right: .5rem; }
.state-succeeded { background: #e1f6ec; color: #116041; border-color: #9acdb4; }
.state-queued, .state-running { background: #e8f1ff; color: #164e88; border-color: #b6cbe8; }
.state-failed { background: #fff0eb; color: #a3371e; border-color: #e2b2a6; }
.state-unknown { background: #edf0f3; color: #334155; border-color: #cbd5e1; }
/* Coarse job stages: never suggest numeric completion or unverified accuracy. */
ol.job-steps { list-style: none; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .85rem; margin: 1.25rem 0 1.6rem; padding: 0; border: 0; background: transparent; }
ol.job-steps .job-step { min-width: 0; display: flex; gap: .7rem; align-items: center; padding: 1rem; border: 1px solid var(--line); border-radius: .85rem; background: #f7fafc; color: #485c70; font-weight: 700; }
.job-steps .step-index { flex-shrink: 0; display: grid; place-items: center; height: 2.2rem; width: 2.2rem; border-radius: 50%; border: 2px solid currentColor; font-size: .79rem; font-weight: 800; }
.job-steps .step-label { overflow-wrap: anywhere; }
ol.job-steps .is-complete { color: #185b42; background: #e5f6ec; border-color: #a4d8ba; }
ol.job-steps .is-current { color: #075e55; background: #e3f7f2; border: 2px solid #087f70; padding: calc(1rem - 1px); box-shadow: 0 3px 10px rgb(8 127 112 / 9%); }
ol.job-steps .is-failed { color: #962d1b; background: #fff0eb; border-color: #e2b2a6; }
/* Guided native upload: no fake drop handler or external resources. */
.import-panel {
  margin: 2.2rem 0;
  padding: clamp(1rem, 2.4vw, 1.7rem);
  background: linear-gradient(145deg, #e8f6f2 0%, #f7fbfc 64%, #f4f8ff 100%);
  border: 1px solid #b9d9d1;
  border-radius: 1.25rem;
  box-shadow: 0 12px 36px rgb(12 65 72 / 8%);
}
.import-heading { display: flex; align-items: center; justify-content: space-between; gap: 1.1rem; flex-wrap: wrap; margin-bottom: 1.35rem; }
.import-eyebrow { margin: 0; color: var(--teal-deep); text-transform: uppercase; font-size: .75rem; font-weight: 850; letter-spacing: .13em; }
.import-panel h2 { border: 0; margin: .25rem 0 .3rem; padding: 0; font-size: clamp(1.45rem, 3vw, 1.85rem); }
.import-intro { margin: 0; color: #40576a; }
.import-private { display: inline-flex; align-items: center; gap: .55rem; padding: .45rem .8rem; border-radius: 99px; background: #fff; border: 1px solid #b2d6cc; font-size: .85rem; font-weight: 750; color: #185d50; white-space: nowrap; }
.import-private::before { content: ""; width: .5rem; height: .5rem; background: #087f70; border-radius: 50%; }
form[action="/upload"] { border: 0; margin: 0; padding: 0; background: transparent; display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr); gap: 1rem; align-items: stretch; }
.import-stage { min-width: 0; margin: 0; padding: 1.1rem; border: 1px solid #c9dddf; border-radius: .95rem; background: #fff; box-shadow: 0 3px 10px rgb(28 72 84 / 4%); }
.import-stage legend { padding: 0 .4rem; font-size: 1.02rem; font-weight: 850; color: var(--night); }
.import-stage legend span { display: inline-grid; place-items: center; margin-right: .4rem; width: 1.75rem; height: 1.75rem; color: #fff; background: var(--teal-deep); border-radius: .5rem; font-size: .78rem; }
.import-stage label { display: block; min-width: 0; width: 100%; color: #32465b; font-weight: 700; }
.import-file input[type="file"] { min-width: 0; max-width: 100%; min-height: 8rem; padding: 1.3rem .8rem; background: #eff8f6; border: 2px dashed #4c988b; border-radius: .8rem; }
.import-file input[type="file"]:hover { background: #e2f4ee; border-color: var(--teal-deep); }
.import-file input[type="file"]::file-selector-button { background: var(--teal-deep); }
.import-help { max-width: 58ch; margin: .8rem 0 0; color: #52677a; font-size: .84rem; line-height: 1.45; }
form[action="/upload"] .import-consent { display: flex; align-items: flex-start; gap: .55rem; padding: .75rem; background: #edf8f4; border: 1px solid #c8e5db; border-radius: .65rem; font-size: .89rem; line-height: 1.4; }
.import-consent input { flex: 0 0 auto; margin-top: .15rem; }
.import-fields { display: grid; grid-template-columns: minmax(0, 1fr); gap: .8rem; margin-top: 1rem; }
.import-actions { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-rows: auto auto; align-items: center; column-gap: 1rem; row-gap: .2rem; padding: 1.15rem .1rem .2rem; border-top: 1px solid #c6ddd7; }
form[action="/upload"] .import-actions label { grid-column: 1; grid-row: 1; display: flex; align-items: center; gap: .55rem; flex: 0 1 auto; font-size: .96rem; font-weight: 750; }
.import-actions label input { margin: 0; flex: 0 0 auto; }
.import-actions p { grid-column: 1; grid-row: 2; margin: 0 0 0 1.65rem; color: #52677a; font-size: .83rem; }
form[action="/upload"] .import-actions button { grid-column: 2; grid-row: 1 / span 2; justify-self: end; min-width: 11rem; background: var(--night); border-color: var(--night); box-shadow: 0 6px 14px rgb(16 28 47 / 13%); }
form[action="/upload"] .import-actions button:hover { background: var(--night-light); border-color: var(--night-light); }
footer { padding: 1.2rem .25rem; font-size: .87rem; color: var(--muted); }
footer strong { color: var(--night); }
@media (max-width: 720px) {
  .topbar-inner { gap: .6rem; padding: .85rem 1rem; }
  .topbar nav { order: 3; width: 100%; margin: .15rem 0 0; }
  .topbar nav a { flex: 1; justify-content: center; }
  .local-pill { margin-left: auto; }
  .workspace { padding: 0 .85rem 2rem; }
  .hero { padding: 1.8rem .25rem 1.1rem; }
  .content-surface { border-radius: .85rem; padding: 1.1rem; }
  form, form[action="/upload"] { display: flex; flex-direction: column; align-items: stretch; }
  form label { flex: 1 1 auto; width: 100%; }
  button { width: 100%; }
  input[type="file"] { padding: .8rem; }
  .import-panel { margin: 1.35rem 0; padding: 1rem; border-radius: 1rem; }
  .import-heading { align-items: flex-start; gap: .75rem; }
  form[action="/upload"] { display: grid; grid-template-columns: minmax(0, 1fr); gap: .85rem; }
  .import-stage { padding: .9rem; }
  .import-file input[type="file"] { padding: 1rem .6rem; }
  .import-actions { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto; gap: .65rem; }
  form[action="/upload"] .import-actions label, .import-actions p, form[action="/upload"] .import-actions button { grid-column: 1; grid-row: auto; }
  .import-actions p { margin: 0; }
  form[action="/upload"] .import-actions button { justify-self: stretch; width: 100%; }
  ol.job-steps { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}
"""
