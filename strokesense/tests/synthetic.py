"""Synthetic side-on rower generator used to unit-test the analysis with known faults."""
from __future__ import annotations

import numpy as np


def _ss(x, a, b):
    """smoothstep from 0 at a to 1 at b."""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _knee(hip, ankle, L1, L2):
    """Knee position (above the hip-ankle line) by circle intersection."""
    d = np.linalg.norm(hip - ankle)
    d = min(d, L1 + L2 - 1e-6)
    a = (L1 ** 2 - L2 ** 2 + d ** 2) / (2 * d)
    hgt = np.sqrt(max(L1 ** 2 - a ** 2, 0))
    u = (ankle - hip) / d
    p = hip + a * u
    n = np.array([u[1], -u[0]])          # perpendicular; pick the one pointing up (negative y)
    if n[1] > 0:
        n = -n
    return p + hgt * n


def make_rower(n_strokes=8, rate=22, fps=30, faults=(), facing=1, noise=1.5, seed=0,
               layback=-22, catch_angle=28, hide_ankles=False):
    rng = np.random.default_rng(seed)
    period = 60 / rate
    drive = 0.75 if rate < 26 else 0.65
    if "rushed_recovery" in faults:
        drive = period / 2.05
    T = n_strokes * period + 0.5
    t = np.arange(0, T, 1 / fps)
    ph = (t % period)
    in_drive = ph < drive
    pd = np.where(in_drive, ph / drive, 1.0)                 # drive progress
    pr = np.where(in_drive, 0.0, (ph - drive) / (period - drive))  # recovery progress

    early_arms = "early_arms" in faults
    legs = np.where(in_drive, _ss(pd, 0, 0.7), 1 - _ss(pr, 0.35, 1.0))
    body = np.where(in_drive, _ss(pd, 0.3, 0.85), 1 - _ss(pr, 0.15, 0.45))
    arms = np.where(in_drive, _ss(pd, 0.05 if early_arms else 0.6, 0.45 if early_arms else 1.0),
                    1 - _ss(pr, 0.0, 0.25))
    if "late_body_prep" in faults:
        body = np.where(in_drive, body, 1 - _ss(pr, 0.55, 0.95))
        legs = np.where(in_drive, legs, 1 - _ss(pr, 0.15, 1.0))

    L1, L2, TR, UA, FA = 45.0, 45.0, 55.0, 30.0, 28.0      # thigh, shank, torso, upper arm, forearm
    ankle = np.array([400.0, 300.0])
    seat_y = ankle[1] + 5
    hip_x = ankle[0] - (40 + legs * (L1 + L2 - 42))         # catch: hips close to feet
    theta = catch_angle + body * (layback - catch_angle)
    if "shooting_slide" in faults:
        theta = theta + np.where(in_drive, 10 * np.sin(np.pi * np.clip(pd / 0.4, 0, 1)), 0)
    elbow_ang = 175 - arms * 95

    kp = np.zeros((len(t), 17, 3))
    for i in range(len(t)):
        hip = np.array([hip_x[i], seat_y])
        knee = _knee(hip, ankle, L1, L2)
        th = np.radians(theta[i])
        sh = hip + TR * np.array([np.sin(th), -np.cos(th)])
        reach = np.sqrt(UA ** 2 + FA ** 2 - 2 * UA * FA * np.cos(np.radians(elbow_ang[i])))
        hand_y = sh[1] + 0.55 * TR
        dy = hand_y - sh[1]
        dx = np.sqrt(max(reach ** 2 - dy ** 2, 1.0))
        wr = sh + np.array([dx, dy])
        # elbow: circle intersection below the shoulder-wrist line
        d = np.linalg.norm(wr - sh); a = (UA ** 2 - FA ** 2 + d ** 2) / (2 * d)
        hh = np.sqrt(max(UA ** 2 - a ** 2, 0)); u = (wr - sh) / d; nrm = np.array([-u[1], u[0]])
        if nrm[1] < 0:
            nrm = -nrm
        el = sh + a * u + hh * nrm
        head = sh + np.array([4, -18])
        pts = {0: head, 5: sh, 6: sh, 7: el, 8: el, 9: wr, 10: wr, 11: hip, 12: hip,
               13: knee, 14: knee, 15: ankle, 16: ankle}
        for j, p in pts.items():
            x = p[0] if facing == 1 else 2 * ankle[0] - p[0] - 300
            kp[i, j, :2] = [x, p[1]] + rng.normal(0, noise, 2)
            kp[i, j, 2] = 0.9 if j % 2 == 0 else 0.6          # right side "near" the camera
        if hide_ankles:
            kp[i, 15:17, 2] = 0.05
    return kp, fps
