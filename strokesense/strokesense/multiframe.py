"""Bounded later-frame review and heuristic boat-focused person proposals.

Boat groups are geometric proposals, not verified boat segmentation. No remote
model request or weight download is made by this module.
"""
from __future__ import annotations
import base64
import importlib.util
import math
import threading
import cv2
import numpy as np
from .pose import PoseDetector, DEFAULT_MODEL
from .pose_merge import merge_refined_detections

_LOCK = threading.Lock()
_detector = None
_key = None


def boat_regions(boxes, points, width, height):
    """Find disjoint approximately aligned crews; operator must confirm membership."""
    boxes = np.asarray(boxes, float)
    if not len(boxes) or len(boxes) > 64:
        return []
    centres = (boxes[:, :2] + boxes[:, 2:]) / 2
    sizes = boxes[:, 2:] - boxes[:, :2]
    remaining = set(range(len(boxes))); groups = []
    while len(remaining) >= 3 and len(groups) < 4:
        best = []
        for i in sorted(remaining):
            for j in sorted(remaining):
                dx = centres[j, 0] - centres[i, 0]
                if dx <= max(2, sizes[i, 0]):
                    continue
                slope = (centres[j, 1] - centres[i, 1]) / dx
                if abs(slope) > .5:
                    continue
                ids = np.array(sorted(remaining))
                residual = abs(centres[ids, 1] - centres[i, 1] - slope*(centres[ids, 0]-centres[i, 0]))
                members = ids[(residual < np.maximum(2, sizes[ids, 1]*.28))
                              & (sizes[ids, 1] / sizes[i, 1] > .5)
                              & (sizes[ids, 1] / sizes[i, 1] < 2)]
                # Collinearity alone can merge two different boats. Split the
                # line at gaps large relative to person size before proposing it.
                members = members[np.argsort(centres[members, 0])]
                if len(members):
                    limit = max(3.5 * float(np.median(sizes[members, 0])),
                                1.5 * float(np.median(sizes[members, 1])))
                    cuts = np.flatnonzero(np.diff(centres[members, 0]) > limit) + 1
                    for group in np.split(members, cuts):
                        if len(group) > len(best):
                            best = group.tolist()
        if len(best) < 3: break
        b = boxes[best]
        pad = float(np.median(b[:, 3]-b[:, 1])) * .5
        region = [max(0, b[:,0].min()-pad), max(0, b[:,1].min()-pad),
                  min(width, b[:,2].max()+pad), min(height, b[:,3].max()+pad)]
        groups.append({'id': len(groups)+1, 'members': best,
                       'box': (np.array(region)/[width,height,width,height]).tolist(),
                       'kind': 'rower_alignment_proposal'})
        remaining.difference_update(best)
    return groups


def refined_detections(frame, detector):
    """Full-image tiles, then higher effective resolution over up to two crews."""
    h,w = frame.shape[:2]
    boxes,scores,kpts = detector(frame, tiles=PoseDetector.tile_grid(w,h))
    boxes,scores,kpts = np.asarray(boxes,float),np.asarray(scores,float),np.asarray(kpts,float)
    if boxes.shape != (len(scores),4) or kpts.shape != (len(scores),17,3):
        raise ValueError('invalid_detections')
    valid = (np.isfinite(boxes).all(1) & np.isfinite(scores) & np.isfinite(kpts).all((1,2))
             & (boxes[:,2:]>boxes[:,:2]).all(1))
    boxes,scores,kpts = boxes[valid],scores[valid],kpts[valid]
    groups = boat_regions(boxes,kpts,w,h)
    all_b,all_s,all_k = [boxes],[scores],[kpts]
    for g in groups[:2]:
        x0,y0,x1,y1 = np.round(np.array(g['box'])*[w,h,w,h]).astype(int)
        crop=frame[y0:y1,x0:x1]
        if min(crop.shape[:2]) < 32: continue
        b,s,k=detector(crop, tiles=PoseDetector.tile_grid(x1-x0,y1-y0,tile=320))
        b,k=np.asarray(b,float).copy(),np.asarray(k,float).copy()
        b[:,[0,2]]+=x0;b[:,[1,3]]+=y0;k[:,:,0]+=x0;k[:,:,1]+=0+y0
        all_b.append(b);all_s.append(np.asarray(s,float));all_k.append(k)
    boxes,scores,kpts=np.concatenate(all_b),np.concatenate(all_s),np.concatenate(all_k)
    if not len(boxes): return boxes,scores,kpts
    valid = (np.isfinite(boxes).all(1) & np.isfinite(scores) & np.isfinite(kpts).all((1,2))
             & (boxes[:,2:]>boxes[:,:2]).all(1))
    boxes,scores,kpts=boxes[valid],scores[valid],kpts[valid]
    return merge_refined_detections(boxes, scores, kpts)


def propose(frame):
    global _detector,_key
    if not _LOCK.acquire(blocking=False): return {'state':'busy','candidates':[]}
    try:
        if not DEFAULT_MODEL.is_file() or importlib.util.find_spec('onnxruntime') is None:
            return {'state':'model_unavailable','candidates':[]}
        stat=DEFAULT_MODEL.stat(); key=(stat.st_size,stat.st_mtime_ns)
        if _detector is None or _key!=key:
            _detector=PoseDetector(DEFAULT_MODEL);_key=key
        from .auto_selection import detect_candidates
        result=detect_candidates(frame,lambda image,tiles=None:refined_detections(image,_detector))
        c=result['candidates']
        result['boats']=boat_regions(np.array([p['box'] for p in c]),None,1,1) if c else []
        # Pixel-sized minimum tolerances above must be applied before normalizing.
        if c:
            h,w=frame.shape[:2]
            result['boats']=boat_regions(np.array([p['box'] for p in c])*[w,h,w,h],None,w,h)
        return result
    except Exception:
        return {'state':'failed','candidates':[]}
    finally:
        _LOCK.release()


def scan_clip(path, *, suggest_fn=None):
    """Sample at most five aligned frames across the first 20s, not just frame 0."""
    suggest_fn=suggest_fn or propose
    cap=cv2.VideoCapture(str(path))
    try:
        fps=cap.get(cv2.CAP_PROP_FPS); count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(fps) or not 0<fps<=240 or not math.isfinite(count) or not 1<=count<=144000:
            raise ValueError('preview_unavailable')
        stride=max(1,round(fps/15))
        final=min(int(count)-1,int(fps*20)); final=(final//stride)*stride
        indices=sorted(set(int(round(i/stride))*stride for i in np.linspace(0,final,5)))
        frames=[]; state='ready'
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES,index); ok,image=cap.read()
            if not ok or image is None: continue
            h,w=image.shape[:2]
            if min(h,w)<64 or h*w>3840*2160: raise ValueError('preview_unavailable')
            proposals=suggest_fn(image)
            if w>1280: image=cv2.resize(image,(1280,round(h*1280/w)))
            ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not ok or len(jpeg)>2*1024*1024: raise ValueError('preview_unavailable')
            frames.append({'seconds':index/fps,'source_frame':index,
                           'image':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode(),
                           'candidates':proposals.get('candidates',[]),'boats':proposals.get('boats',[]),
                           'state':proposals['state']})
            if proposals['state'] in ('model_unavailable','busy','failed'):
                state=proposals['state'];break
        if not frames: raise ValueError('preview_unavailable')
        return {'state':state,'frames':frames,'selected':[],'method':'boat-focused-multiframe-v1'}
    finally:
        cap.release()
