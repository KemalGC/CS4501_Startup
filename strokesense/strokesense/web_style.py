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
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}
"""
