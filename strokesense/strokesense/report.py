"""Self-contained HTML coaching report."""
from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .kinematics import smooth  # noqa: E402

INK, MUTED, GRID = "#1f2933", "#6b7785", "#e3e7ec"
C_LEGS, C_BODY, C_ARMS = "#2f6fdf", "#e0802a", "#2aa876"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "font.family": "DejaVu Sans"})


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _img(path) -> str | None:
    if path is None or not Path(path).exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def sequencing_curves(rower, n=50):
    """Average 0->1 progress of legs, body and arms across the drive (catch -> finish)."""
    k = rower.k
    A = {name: smooth(v, k.fps, 0.2) for name, v in k.angles.items()}
    out = {"legs": [], "body": [], "arms": []}
    for s in rower.strokes:
        c, f = s.catch, s.finish
        if f - c < 3:
            continue
        x = np.linspace(0, 1, f - c + 1)
        xi = np.linspace(0, 1, n)
        for key, sig in (("legs", A["thigh"]), ("body", A["trunk"]), ("arms", A["elbow"])):
            seg = sig[c:f + 1]
            d = seg[-1] - seg[0]
            prog = (seg - seg[0]) / d if abs(d) > 1e-6 else np.zeros_like(seg)
            out[key].append(np.interp(xi, x, np.clip(prog, -0.3, 1.3)))
    return {k_: np.mean(v, 0) if v else None for k_, v in out.items()}


def chart_sequencing(rower):
    cur = sequencing_curves(rower)
    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    x = np.linspace(0, 100, 50)
    for key, col, lab in (("legs", C_LEGS, "Legs"), ("body", C_BODY, "Body swing"), ("arms", C_ARMS, "Arms")):
        if cur[key] is not None:
            ax.plot(x, cur[key] * 100, color=col, lw=2.4, label=lab)
    ax.set_xlabel("% of drive (catch → finish)")
    ax.set_ylabel("% complete")
    ax.set_ylim(-15, 115); ax.set_xlim(0, 100)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.set_title("Drive sequencing — ideal order is legs, then body, then arms", fontsize=10, color=INK, loc="left")
    return _png(fig)


def chart_trunk(rower):
    k = rower.k
    t = np.arange(k.n) / k.fps
    tr = smooth(k.angles["trunk"], k.fps, 0.2)
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    ax.axhspan(15, 35, color=C_LEGS, alpha=0.07, lw=0)
    ax.axhspan(-30, -10, color=C_BODY, alpha=0.07, lw=0)
    ax.plot(t, np.where(k.visible, tr, np.nan), color=INK, lw=1.6)
    for s in rower.strokes:
        ax.plot(s.catch / k.fps, tr[s.catch], "o", color=C_LEGS, ms=5)
        ax.plot(s.finish / k.fps, tr[s.finish], "o", color=C_BODY, ms=5)
    ax.axhline(0, color=GRID, lw=1)
    ax.set_xlabel("time (s)"); ax.set_ylabel("body angle (°)")
    ax.set_title("Body angle — ● catch  ● finish  (shaded = target zones)", fontsize=10, color=INK, loc="left")
    return _png(fig)


def chart_sync(sync, rowers):
    per = sync.get("per_seat", {})
    seats = [r.seat for r in rowers if r.seat in per]
    if not seats:
        return None
    vals = [per[s]["mean_ms"] for s in seats]
    sds = [per[s]["sd_ms"] for s in seats]
    fig, ax = plt.subplots(figsize=(7, 0.32 * len(seats) + 1.0))
    cols = ["#d64545" if abs(v) > 60 else ("#e0a52a" if abs(v) > 30 else "#2aa876") for v in vals]
    y = np.arange(len(seats))
    ax.barh(y, vals, xerr=sds, color=cols, height=0.6, error_kw=dict(ecolor=MUTED, lw=1, capsize=3))
    ax.set_yticks(y, seats)
    ax.invert_yaxis()
    ax.axvline(0, color=INK, lw=1)
    lim = max(80, max(abs(v) + s for v, s in zip(vals, sds)) * 1.15)
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("catch timing vs crew (ms)   ← early | late →")
    ax.grid(axis="x", color=GRID, lw=0.8)
    return _png(fig)


def _score_color(sc):
    if sc is None:
        return MUTED
    return "#2aa876" if sc >= 80 else ("#e0a52a" if sc >= 65 else "#d64545")


def build_html(video_name, pose, rowers, sync, snaps, out_path):
    crew = len(rowers) > 1
    rates = [r.summary.get("rate") for r in rowers if r.summary.get("rate")]
    rate = f"{np.median(rates):.0f}" if rates else "–"
    n_strokes = max((r.summary.get("n_strokes", 0) for r in rowers), default=0)

    cards = []
    for r in rowers:
        s = r.summary
        if not s.get("n_strokes"):
            continue
        issues = "".join(
            f"<li><b>{html.escape(i['title'])}</b> <span class='pct'>{i['frac']*100:.0f}% of strokes</span>"
            f"<div class='cue'>{html.escape(i['cue'])}</div></li>" for i in s["issues"][:3]
        ) or "<li class='ok'>No consistent faults detected — keep it up.</li>"
        sync_line = ""
        if r.sync_ms is not None:
            word = "late" if r.sync_ms > 0 else "early"
            sync_line = f"<div class='m'><span>Catch timing</span><b>{abs(r.sync_ms):.0f} ms {word}</b></div>"
        sn = snaps.get(r.tid, {})
        shots = "".join(f"<figure><img src='{_img(p)}'><figcaption>{cap}</figcaption></figure>"
                        for cap, p in (("Catch", sn.get("catch")), ("Finish", sn.get("finish"))) if _img(p))
        cards.append(f"""
<section class="card">
  <header><h2>{html.escape(r.seat)}</h2>
    <div class="score" style="border-color:{_score_color(s['score'])};color:{_score_color(s['score'])}">{s['score']}</div></header>
  <div class="metrics">
    <div class="m"><span>Strokes analysed</span><b>{s['n_strokes']}</b></div>
    <div class="m"><span>Stroke rate</span><b>{s['rate']:.1f} spm</b></div>
    <div class="m"><span>Recovery : drive</span><b>{s['ratio']:.1f} : 1</b></div>
    <div class="m"><span>Body angle at catch</span><b>{s['trunk_catch']:+.0f}°</b></div>
    <div class="m"><span>Body angle at finish</span><b>{s['trunk_finish']:+.0f}°</b></div>
    <div class="m"><span>Consistency</span><b>{s['consistency']}/100</b></div>
    {sync_line}
  </div>
  <h3>Top things to work on</h3><ul class="issues">{issues}</ul>
  <div class="shots">{shots}</div>
  <div class="charts"><img src="{chart_sequencing(r)}"><img src="{chart_trunk(r)}"></div>
</section>""")

    sync_block = ""
    if crew:
        img = chart_sync(sync, rowers)
        if img:
            spread = sync.get("crew_spread_ms")
            sync_block = f"""<section class="card wide"><header><h2>Crew timing at the catch</h2></header>
<p class="lede">How far each seat's catch lands from the crew's median catch, averaged over the piece
(bars = mean, whiskers = stroke-to-stroke spread). Average absolute offset: <b>{spread:.0f} ms</b>.</p>
<img class="sync" src="{img}"></section>"""

    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StrokeSense Report</title>
<style>
:root{{--ink:#1f2933;--muted:#6b7785;--bg:#f6f7f9;--card:#fff;--line:#e3e7ec;--accent:#2f6fdf}}
*{{box-sizing:border-box}} body{{margin:0;font:15px/1.5 -apple-system,Segoe UI,Inter,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.top{{background:#0f2747;color:#fff;padding:28px 24px}} .top h1{{margin:0;font-size:26px;letter-spacing:-.01em}}
.top p{{margin:4px 0 0;color:#b9c6d8}} .kpis{{display:flex;gap:28px;margin-top:16px;flex-wrap:wrap}}
.kpis div span{{display:block;font-size:12px;color:#9fb0c6;text-transform:uppercase;letter-spacing:.06em}} .kpis b{{font-size:22px}}
main{{max-width:1100px;margin:0 auto;padding:20px 16px;display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}} .wide{{grid-column:1/-1}}
.card header{{display:flex;justify-content:space-between;align-items:center}} h2{{margin:0;font-size:20px}} h3{{font-size:14px;margin:16px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
.score{{width:54px;height:54px;border-radius:50%;border:3px solid;display:grid;place-items:center;font-weight:700;font-size:18px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:12px}}
.m{{background:var(--bg);border-radius:8px;padding:8px 10px}} .m span{{display:block;font-size:12px;color:var(--muted)}} .m b{{font-size:16px}}
.issues{{margin:0;padding-left:18px}} .issues li{{margin:6px 0}} .pct{{color:var(--muted);font-size:12px;margin-left:6px}} .cue{{color:#3d4b5c;font-size:14px}} .ok{{color:#2aa876}}
.shots{{display:flex;gap:10px;margin-top:12px}} .shots figure{{margin:0;flex:1}} .shots img{{width:100%;border-radius:8px;display:block}} figcaption{{font-size:12px;color:var(--muted);text-align:center}}
.charts img{{width:100%;margin-top:10px}} .sync{{width:100%;max-width:720px;display:block;margin:10px auto 0}} .lede{{color:#3d4b5c;margin:6px 0 0}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:20px}}
</style></head><body>
<div class="top"><h1>StrokeSense technique report</h1><p>{html.escape(video_name)} · generated {datetime.now():%b %d, %Y %H:%M}</p>
<div class="kpis"><div><span>Rowers tracked</span><b>{len(rowers)}</b></div><div><span>Strokes</span><b>{n_strokes}</b></div>
<div><span>Stroke rate</span><b>{rate} spm</b></div><div><span>Clip analysed</span><b>{pose.n_frames / pose.fps:.0f} s</b></div></div></div>
<main>{sync_block}{''.join(cards)}</main>
<footer>Angles are measured in 2D from a single camera; they are most accurate when the camera is level with and
perpendicular to the boat. Body angle: + = leaning toward the stern (body over), − = layback.</footer>
</body></html>"""
    Path(out_path).write_text(page, encoding="utf-8")
    return out_path


def build_json(rowers, sync, out_path, *, analysis_key=None, fps=None, start_seconds=0.0):
    data = {"sync": sync, "rowers": [
        {"seat": r.seat, "track": r.tid, "summary": r.summary, "sync_ms": r.sync_ms,
         "strokes": [s.to_dict() for s in r.strokes]} for r in rowers]}
    if analysis_key is not None:
        from . import evidence
        data["evidence"] = evidence.build_evidence_snapshot(
            data, analysis_key=analysis_key, fps=fps, start_seconds=start_seconds
        )
    Path(out_path).write_text(json.dumps(data, indent=2, default=float))
    return out_path
