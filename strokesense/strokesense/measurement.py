"""Shared, versioned measurement-quality policy. Thresholds are not coach validation."""
from __future__ import annotations
import numpy as np

VERSION = 'observed-motion-v1'
JOINTS = {'handle': ('hip', 'wrist'), 'trunk': ('hip', 'shoulder'),
          'thigh': ('hip', 'knee'), 'elbow': ('shoulder', 'elbow', 'wrist'),
          'shin': ('ankle', 'knee'), 'knee': ('hip', 'knee', 'ankle')}
AMPLITUDE = {'handle': .12, 'trunk': 5., 'thigh': 5., 'elbow': 8., 'shin': 5., 'knee': 8.}


def observed_mask(k, signal):
    """Use the same joint observation masks in measurements and visualizations."""
    joints = JOINTS[signal]
    masks = getattr(k, 'observed', {})
    if all(j in masks for j in joints):
        return np.logical_and.reduce([masks[j] for j in joints])
    result = np.array(k.visible, dtype=bool, copy=True)
    for joint in joints:
        if not k.reliable.get(joint, True):
            result[:] = False
        confidence = getattr(k, 'conf', {}).get(joint)
        if confidence is not None:
            result &= np.isfinite(confidence) & (confidence >= .35)
    return result


def supported(k, name, values, *, minimum_fraction=0., minimum_amplitude=None):
    """Absolute motion and robust jitter checks precede any normalization.

    Difference MAD is an engineering noise proxy, not calibrated uncertainty.
    A missing joint never becomes support simply because another signal cycles.
    """
    values = np.asarray(values, float)
    observed = observed_mask(k, name) & np.isfinite(values)
    if observed.sum() < 5 or observed.mean() < minimum_fraction:
        return False
    good = values[observed]
    amplitude = float(np.percentile(good, 95)-np.percentile(good, 5))
    pairs = observed[1:] & observed[:-1]
    differences = np.diff(values)[pairs]
    noise = (1.4826 * float(np.median(np.abs(differences - np.median(differences))))
             if len(differences) else float('inf'))
    floor = AMPLITUDE[name] if minimum_amplitude is None else minimum_amplitude
    return amplitude >= floor and amplitude >= 3.0 * noise


def segment_supported(k, name, start, stop, *, motion=True):
    values = k.handle if name == 'handle' else k.angles[name]
    observed = observed_mask(k, name)[start:stop]
    segment = values[start:stop]
    if not len(segment) or not np.isfinite(segment).all() or observed.mean() < .9:
        return False
    if not observed[0] or not observed[-1]:
        return False
    if not motion:
        return True
    from types import SimpleNamespace
    view = SimpleNamespace(visible=observed, reliable=k.reliable, observed={}, conf={})
    return supported(view, name, segment, minimum_fraction=.9)
