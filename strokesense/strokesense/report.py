"""Self-contained HTML coaching report."""
from __future__ import annotations

import base64
import html
import io
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import cadence, measurement
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


def sequencing_summary(rower, n=50):
    """Supported per-stroke curves with robust centre/spread and explicit counts."""
    k = rower.k
    result = {}
    for key, signal in (('legs', 'thigh'), ('body', 'trunk'), ('arms', 'elbow')):
        curves = []
        for stroke in rower.strokes:
            c, f = stroke.catch, stroke.finish
            if f-c < 3 or not measurement.segment_supported(k, signal, c, f+1):
                continue
            segment = k.angles[signal][c:f+1]
            delta = float(segment[-1]-segment[0])
            if abs(delta) < measurement.AMPLITUDE[signal]:
                continue
            # Do not clip excursions into an idealized 0..100% template.
            curves.append(np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(segment)),
                                    (segment-segment[0])/delta))
        result[key] = {'count': len(curves), 'curves': curves,
                       'median': np.median(curves, axis=0) if curves else None,
                       'lower': np.percentile(curves, 25, axis=0) if curves else None,
                       'upper': np.percentile(curves, 75, axis=0) if curves else None}
    return result


def sequencing_curves(rower, n=50):
    return {key: value['median'] for key, value in sequencing_summary(rower, n).items()}


def chart_sequencing(rower):
    summary = sequencing_summary(rower)
    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    x = np.linspace(0, 100, 50)
    for key, col, label in (('legs', C_LEGS, 'Legs'), ('body', C_BODY, 'Body swing'), ('arms', C_ARMS, 'Arms')):
        item = summary[key]
        if item['count']:
            for curve in item['curves']:
                ax.plot(x, curve*100, color=col, alpha=.12, lw=.7)
            ax.fill_between(x, item['lower']*100, item['upper']*100, color=col, alpha=.15)
            ax.plot(x, item['median']*100, color=col, lw=2,
                    label=f"{label}: {item['count']} cycles")
    missing = [key for key, item in summary.items() if not item['count']]
    if missing:
        ax.text(.02, .98, 'Unavailable: '+', '.join(missing), transform=ax.transAxes,
                va='top', fontsize=8, color=MUTED)
    ax.set_xlabel('% of drive (catch → finish)')
    ax.set_ylabel('Measured progress (%)')
    ax.set_xlim(0, 100)
    ax.grid(axis='y', color=GRID, lw=.8)
    if any(item['count'] for item in summary.values()):
        ax.legend(frameon=False, loc='lower right', fontsize=8)
    ax.set_title('Supported drives: median and middle 50%', fontsize=10, color=INK, loc='left')
    return _png(fig)


def chart_trunk(rower, start_seconds=0.0):
    k = rower.k
    t = start_seconds + np.arange(k.n)/k.fps
    tr = k.angles['trunk']
    observed = measurement.observed_mask(k, 'trunk') & np.isfinite(tr)
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    ax.plot(t, np.where(observed, tr, np.nan), color=INK, lw=1.3, label='Observed chain')
    estimated = ~observed & np.isfinite(tr)
    if estimated.any():
        ax.scatter(t[estimated], tr[estimated], color=MUTED, marker='x', s=14,
                   label='Short-gap estimate')
    for i, stroke in enumerate(rower.strokes):
        ax.plot(start_seconds+stroke.catch/k.fps, tr[stroke.catch], 'o', color=C_LEGS, ms=5,
                label='Catch' if i == 0 else '_nolegend_')
        ax.plot(start_seconds+stroke.finish/k.fps, tr[stroke.finish], 's', color=C_BODY, ms=5,
                label='Finish' if i == 0 else '_nolegend_')
    ax.legend(frameon=False, loc='upper right', fontsize=8)
    ax.axhline(0, color=GRID, lw=1)
    ax.set_xlabel('Source video time (s)'); ax.set_ylabel('Projected body angle (°)')
    ax.set_title('Canonical 2D angle — no assumed camera detrending', fontsize=9, color=INK, loc='left')
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


def _rate_text(value):
    return f"{value:.1f} spm" if type(value) in (int, float) and math.isfinite(value) and value > 0 else "Unavailable"


def _boat_cadence_html(result, rowers, start_seconds):
    """One boat result, with raw track estimates kept as inspectable diagnostics."""
    block = ('<section class="card wide" aria-label="Crew cadence"><h2>One stroke rate for the boat</h2><p>'
             + html.escape(cadence.description(result))
             + '</p><p>Every rower card uses this shared boat estimate. Catch timing is assessed separately: '
             'a rower can be early or late while following the same rhythm.</p>')
    trend = result.get('trend', [])
    rate_range = result.get('rate_range_spm')
    if result.get('rate_spm') is not None and trend:
        if rate_range:
            block += (f"<p>Supported rhythm range: {rate_range[0]:.1f}–{rate_range[1]:.1f} spm "
                      f"over {result.get('support_duration_seconds', 0.):.1f} seconds of overlapping evidence. "
                      'The main number summarizes that trend.</p>')
        rows = ''.join(
            f"<tr><td>{start_seconds+t['start_seconds']:.2f}–{start_seconds+t['end_seconds']:.2f}</td>"
            f"<td>{t['rate_spm']:.1f}</td><td>{len(t['rowers'])}</td></tr>" for t in trend)
        block += ('<details><summary>Boat rhythm over the analyzed window</summary>'
                  '<p>Source-video seconds. These windows combine overlapping detected stroke periods; '
                  'their boundaries are not additional catch events.</p>'
                  '<div style="overflow-x:auto"><table><thead><tr><th>Window (s)</th>'
                  '<th>Shared SPM</th><th>Supporting rowers</th></tr></thead><tbody>'
                  + rows + '</tbody></table></div></details>')
    diagnostics = []
    for rower in rowers:
        raw = result.get('per_rower', {}).get(rower.seat, {})
        note = cadence.qualification(result, rower.seat) if raw else 'No usable rate evidence'
        diagnostics.append(
            f"<tr><td>{html.escape(rower.seat)}</td><td>{_rate_text(raw.get('raw_spm'))}</td>"
            f"<td>{raw.get('cycles', 0)}</td><td>{html.escape(note)}</td></tr>")
    block += ('<details class="rate-diagnostics"><summary>Raw motion-rate diagnostics</summary>'
              '<p>These intermediate body-motion detections explain support for the shared estimate. '
              'Missed or extra detections can produce outliers; the values below are not separate rowing rates '
              'assigned to individual crew members.</p>'
              '<div style="overflow-x:auto"><table><thead><tr><th>Track</th><th>Raw interval estimate</th>'
              '<th>Detected intervals</th><th>Contribution</th></tr></thead><tbody>'
              + ''.join(diagnostics) + '</tbody></table></div></details></section>')
    return block


def build_html(video_name, pose, rowers, sync, snaps, out_path, *, start_seconds=None):
    if start_seconds is None:
        start_seconds = getattr(pose, "start", 0.0)
    crew = len(rowers) > 1
    rates = [r.summary.get("rate") for r in rowers if r.summary.get("rate")]
    cadence_result = cadence.estimate(rowers)
    estimate = cadence_result['rate_spm'] if crew else (rates[0] if rates else None)
    rate = _rate_text(estimate)
    rate_label = 'Shared boat stroke rate' if crew else 'Stroke rate'
    cadence_block = _boat_cadence_html(cadence_result, rowers, start_seconds) if crew else ''
    shared = cadence_result.get('shared_cycles', [])
    if shared:
        rows = ''.join(
            f"<tr><td>{i+1}</td><td>{start_seconds+c['catch_seconds']:.2f}</td>"
            f"<td>{start_seconds+c['next_catch_seconds']:.2f}</td>"
            f"<td>{c['rate_spm']:.1f}</td><td>{len(c['rowers'])}</td></tr>"
            for i, c in enumerate(shared))
        cadence_block += ('<section class="card wide"><details><summary>Aligned catch-event evidence</summary>'
            '<p>Body-motion catch proxies in source-video seconds; not verified blade entry. '
            'This stricter timing evidence is separate from the boat rhythm estimate. '
            'No peaks or missing cycles were inserted to force agreement.</p>'
            '<div style="overflow-x:auto"><table><thead><tr><th>Cycle</th><th>Catch (s)</th>'
            '<th>Next catch (s)</th><th>SPM</th><th>Supporting rowers</th></tr></thead>'
            '<tbody>'+rows+'</tbody></table></div></details></section>')
    media_block = ('<section class="card wide" role="status"><h2>Annotated video unavailable</h2>'
                   '<p>Browser video encoding was unavailable. The report and measurements are still saved. '
                   'Install a local FFmpeg build with H.264 encoding and retry to generate browser video.</p></section>') \
                   if sync.get('media', {}).get('state') == 'unavailable' else ''
    n_strokes = max((r.summary.get("n_strokes", 0) for r in rowers), default=0)

    from .dynamic_crew import coverage_html
    tracking_block = coverage_html(rowers)
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
        fault_photos = []
        from .strokes import FAULTS
        for code, photo in sn.get('faults', {}).items():
            if code not in FAULTS:
                continue
            src = _img(photo['path'])
            if src is None:
                continue
            caption = (f"{r.seat} · {FAULTS[code]['title']} · stroke {photo['stroke'] + 1} · "
                       f"{photo['seconds']:.2f} s (source video)")
            fault_photos.append(
                '<figure class="fault-photo"><img src="' + src + '" alt="'
                + html.escape(caption, quote=True) + '"><figcaption>'
                + html.escape(caption) + '<br>Flagged-stroke context frame; candidate finding, '
                'not coach-verified. Motion faults require the surrounding video.</figcaption></figure>')
        unavailable = ''.join('<p>Image unavailable for ' + html.escape(issue['title']) + '</p>'
                              for issue in s['issues'][:3]
                              if issue['code'] not in sn.get('faults', {})
                              or _img(sn['faults'][issue['code']]['path']) is None)
        fault_gallery = ('<h3>Pictures of flagged technique</h3><div class="fault-gallery">'
                         + ''.join(fault_photos) + '</div>') if fault_photos else ''
        fault_gallery += unavailable
        count = s['n_strokes']
        readiness = ('Short assessment ready' if count >= 5 else
                     f'Preliminary: {count} of 5 usable strokes')
        consistency = (f"{s['consistency']}/100" if s.get('consistency') is not None
                       else 'Not enough cycles')
        window_rows = ''.join(
            f"<tr><td>{st.idx+1}</td><td>{start_seconds+st.catch/pose.fps:.2f}</td>"
            f"<td>{start_seconds+st.finish/pose.fps:.2f}</td>"
            f"<td>{start_seconds+st.next_catch/pose.fps:.2f}</td>"
            f"<td>{getattr(st,'observed_frames',0)}</td><td>{getattr(st,'gap_frames',0)}</td></tr>"
            for st in r.strokes)
        stroke_table = ('<details><summary>Stroke-by-stroke windows</summary>'
            '<p>Source-video seconds. Missing frames were estimated only inside short '
            'accepted gaps; they are not observations. Each row is measured independently.</p>'
            '<div style="overflow-x:auto"><table><thead><tr><th>Stroke</th><th>Catch (s)</th>'
            '<th>Finish (s)</th><th>Next catch (s)</th><th>Observed frames</th>'
            '<th>Estimated gap frames</th></tr></thead><tbody>' + window_rows
            + '</tbody></table></div></details>')
        cards.append(f"""
<section class="card">
  <header><h2>{html.escape(r.seat)}</h2>
    <div class="score" style="border-color:{_score_color(s['score'])};color:{_score_color(s['score'])}">{s['score']}</div></header>
  <p role="status"><strong>{readiness}</strong> · Five usable strokes suffice for a short assessment, not coach validation.</p>
  <p>Technique score is a provisional heuristic, not measured accuracy.</p>
  <div class="metrics">
    <div class="m"><span>Strokes analysed</span><b>{s['n_strokes']}</b></div>
    <div class="m"><span>{rate_label}</span><b>{rate}</b></div>
    <div class="m"><span>Recovery : drive</span><b>{s['ratio']:.1f} : 1</b></div>
    <div class="m"><span>Body angle at catch</span><b>{s['trunk_catch']:+.0f}°</b></div>
    <div class="m"><span>Body angle at finish</span><b>{s['trunk_finish']:+.0f}°</b></div>
    <div class="m"><span>Consistency</span><b>{consistency}</b></div>
    {sync_line}
  </div>
  <h3>Top things to work on</h3><ul class="issues">{issues}</ul>
  <div class="shots">{shots}</div>
  {fault_gallery}
  {stroke_table}
  <div class="charts"><img src="{chart_sequencing(r)}"><img src="{chart_trunk(r, start_seconds)}"></div>
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
.fault-gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px}}
.fault-photo{{margin:0;border:1px solid var(--line);border-radius:8px;padding:8px}}
.fault-photo img{{width:100%;height:auto;display:block}}
.rate-diagnostics{{margin-top:16px}} .card details summary{{cursor:pointer;font-weight:600}} .card table{{border-collapse:collapse;width:100%;font-size:14px}} .card th,.card td{{padding:8px;text-align:left;border-bottom:1px solid var(--line)}}
.charts img{{width:100%;margin-top:10px}} .sync{{width:100%;max-width:720px;display:block;margin:10px auto 0}} .lede{{color:#3d4b5c;margin:6px 0 0}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:20px}}
</style></head><body>
<div class="top"><h1>StrokeSense technique report</h1><p>{html.escape(video_name)} · generated {datetime.now(ZoneInfo('America/New_York')):%b %d, %Y %H:%M %Z}</p>
<div class="kpis"><div><span>Rowers tracked</span><b>{len(rowers)}</b></div><div><span>Strokes</span><b>{n_strokes}</b></div>
<div><span>{rate_label}</span><b>{rate}</b></div><div><span>Clip analysed</span><b>{pose.n_frames / pose.fps:.0f} s</b></div></div></div>
<main>{media_block}{cadence_block}{tracking_block}{sync_block}{''.join(cards)}</main>
<footer>Angles are measured in 2D from a single camera; they are most accurate when the camera is level with and
perpendicular to the boat. Body angle: + = leaning toward the stern (body over), − = layback.</footer>
</body></html>"""
    Path(out_path).write_text(page, encoding="utf-8")
    return out_path


def build_json(rowers, sync, out_path, *, analysis_key=None, fps=None, start_seconds=0.0):
    data = {"measurement_policy": {
        "version": measurement.VERSION, "confidence_threshold": .35,
        "max_internal_gap_seconds": .2, "minimum_cycle_observed_fraction": .9,
        "absolute_motion_floors": measurement.AMPLITUDE,
        "coordinates": "hip-relative displacement and projected 2D angles; not boat-relative travel",
        "camera_detrending": False, "thresholds_coach_validated": False,
    }, "crew_cadence": cadence.estimate(rowers), "sync": sync, "rowers": [
        {"seat": r.seat, "track": r.tid, "summary": r.summary, "sync_ms": r.sync_ms,
         "strokes": [s.to_dict() for s in r.strokes]} for r in rowers]}
    for item, rower in zip(data['rowers'], rowers):
        k = getattr(rower, 'k', None)
        if k is not None and getattr(k, 'observed', None):
            item['joint_observation_counts'] = {
                joint: {'observed': int(mask.sum()), 'estimated': int(k.estimated[joint].sum()),
                        'unavailable': int(len(mask)-mask.sum()-k.estimated[joint].sum())}
                for joint, mask in k.observed.items()}
            item['sequencing'] = {
                name: {key: value.tolist() if isinstance(value, np.ndarray) else value
                       for key, value in stats.items() if key != 'curves'}
                for name, stats in sequencing_summary(rower).items()}
    if fps is not None:
        from .stroke_windows import manifest
        data['stroke_windows'] = manifest(rowers, fps, start_seconds)
    if analysis_key is not None:
        from . import evidence
        data["evidence"] = evidence.build_evidence_snapshot(
            data, analysis_key=analysis_key, fps=fps, start_seconds=start_seconds
        )
    Path(out_path).write_text(json.dumps(data, indent=2, default=float, allow_nan=False))
    return out_path
