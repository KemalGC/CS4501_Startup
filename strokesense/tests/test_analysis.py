import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from strokesense import kinematics, strokes  # noqa: E402
from synthetic import make_rower  # noqa: E402


def run(faults=(), **kw):
    kp, fps = make_rower(faults=faults, **kw)
    k = kinematics.build(kp, fps)
    st, _ = strokes.analyse(k)
    return k, st, strokes.summarise(st)


def test_clean_rower():
    k, st, summ = run()
    assert len(st) >= 6, len(st)
    assert abs(summ["rate"] - 22) < 1.5, summ["rate"]
    assert summ["issues"] == [], summ["issues"]
    assert summ["score"] >= 85, summ


def test_facing_left_and_hidden_ankles():
    k, st, summ = run(facing=-1, hide_ankles=True)
    assert k.facing == -1
    assert len(st) >= 6
    assert summ["issues"] == [], summ["issues"]


def test_fault_detection():
    for f in ["shooting_slide", "early_arms", "rushed_recovery", "late_body_prep"]:
        _, st, summ = run(faults=(f,))
        codes = [i["code"] for i in summ["issues"]]
        assert f in codes, (f, codes, [s.to_dict() for s in st[:2]])


def test_angle_faults():
    _, _, summ = run(layback=-40)
    assert "excess_layback" in [i["code"] for i in summ["issues"]]
    _, _, summ = run(catch_angle=5)
    assert "short_catch" in [i["code"] for i in summ["issues"]]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
