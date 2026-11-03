"""Optional dominant-crew study runs, with explicit geometric selection limits.

Groups are pose detections of similarly sized aligned people, NOT a trained hull
segmenter. A chosen group is never replaced just because a different boat stays
visible. Camera cuts/long losses stay gaps; identity accuracy needs human review.
"""
from __future__ import annotations
import math
import cv2
import numpy as np

VERSION = 'dominant-aligned-crew-v1'


def groups(boxes, keypoints):
    boxes=np.asarray(boxes,float); keypoints=np.asarray(keypoints,float)
    if boxes.shape!=(len(boxes),4) or keypoints.shape!=(len(boxes),17,3):
        raise ValueError('invalid_detections')
    if not len(boxes):return []
    sizes=boxes[:,2:]-boxes[:,:2];centres=(boxes[:,:2]+boxes[:,2:])/2
    valid=np.isfinite(boxes).all(1)&np.isfinite(keypoints).all((1,2))&(sizes>0).all(1)
    valid &= keypoints[:,5:13,2].mean(1)>=.25
    ids=list(np.flatnonzero(valid));remaining=set(ids);answer=[]
    while remaining:
        first=min(remaining);remaining.remove(first);component=[first];frontier=[first]
        while frontier:
            i=frontier.pop()
            for j in sorted(remaining):
                dx,dy=np.abs(centres[i]-centres[j]);hi,hj=sizes[i,1],sizes[j,1]
                if (.6<=hi/hj<=1/.6 and dx<=max(3.5*max(sizes[i,0],sizes[j,0]),2.8*max(hi,hj))
                        and dy<=.45*min(hi,hj)+.10*dx):
                    remaining.remove(j);component.append(j);frontier.append(j)
        if len(component)<3:continue
        b=boxes[component];h=float(np.median(sizes[component,1]));w=float(np.median(sizes[component,0]))
        envelope=np.r_[b[:,:2].min(0),b[:,2:].max(0)]
        score=min(8,len(component))*h*w*float(keypoints[component,5:13,2].mean())
        answer.append({'members':component,'box':envelope.tolist(),'height':h,'width':w,'score':score})
    return answer


def choose_group(candidates):
    if not candidates:raise ValueError('dominant_crew_unavailable')
    return max(candidates,key=lambda g:(g['score'],len(g['members'])))


class CrewLock:
    def __init__(self, group, fps):
        self.previous=group;self.missed=0;self.limit=max(1,round(float(fps)*2));self.retired=False
    def select(self,boxes,keypoints):
        if self.retired:return []
        old=np.asarray(self.previous['box']);centre=(old[:2]+old[2:])/2;h=self.previous['height']
        matches=[]
        for g in groups(boxes,keypoints):
            b=np.asarray(g['box']);c=(b[:2]+b[2:])/2;dx,dy=np.abs(c-centre)
            if (.60<=g['height']/h<=1.65 and dy<=1.25*h
                    and dx<=max(2*h,.45*(old[2]-old[0]))):
                matches.append((float(np.linalg.norm((c-centre)/[max(old[2]-old[0],h),h])),g))
        matches.sort(key=lambda x:x[0])
        if matches and (len(matches)==1 or matches[1][0]-matches[0][0]>.15):
            self.previous=matches[0][1];self.missed=0;return list(self.previous['members'])
        self.missed+=1
        if self.missed>self.limit:self.retired=True
        return []


def isolate(detections,fps,reference=0):
    if not 0<=reference<len(detections):raise ValueError('invalid_reference')
    initial=choose_group(groups(*detections[reference]));indices={reference:initial['members']}
    for sequence in (range(reference+1,len(detections)),range(reference-1,-1,-1)):
        lock=CrewLock(initial,fps)
        for i in sequence:indices[i]=lock.select(*detections[i])
    selected=[];excluded=0
    for i,(b,k) in enumerate(detections):
        ids=indices[i];selected.append((b[ids],k[ids]));excluded+=len(b)-len(ids)
    audit={'version':VERSION,'method':'largest_clear_aligned_pose_group_then_continuity_lock',
      'reference_sample':int(reference),'reference_seconds':reference/float(fps),
      'reference_box':initial['box'],'reference_people':len(initial['members']),
      'total_sampled_frames':len(detections),'frames_with_group':sum(bool(indices[i]) for i in indices),
      'excluded_detections':int(excluded),'max_reacquisition_gap_seconds':2.,
      'independent_identity_validation':False,'hull_segmentation':False,
      'note':'Automatic visual grouping; other crews excluded geometrically. Camera cuts/long loss remain gaps.'}
    return selected,audit


def run_video(video, detector, *, target_fps=10., start=0., duration=None, progress=None):
    from .pose import PoseDetector,run_video as extract
    cap=cv2.VideoCapture(str(video));srcfps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if not cap.isOpened() or not math.isfinite(srcfps) or srcfps<=0:
        cap.release();raise ValueError('invalid_media')
    length=min(float(duration),count/srcfps-start) if duration else count/srcfps-start
    candidates=[];W=H=0
    try:
        for t in np.linspace(start,min(start+length-.1,count/srcfps-.1),5):
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,image=cap.read()
            if not ok:continue
            if image.shape[1]>1920:image=cv2.resize(image,(1920,round(image.shape[0]*1920/image.shape[1])))
            H,W=image.shape[:2]
            b,_,k=detector(image,tiles=PoseDetector.tile_grid(W,H,tile=480))
            found=groups(b,k)
            if not found:
                b,_,k=detector(image,tiles=PoseDetector.tile_grid(W,H,tile=240));found=groups(b,k)
            if found:candidates.append((float(t),choose_group(found)))
    finally:cap.release()
    if not candidates:raise ValueError('dominant_crew_unavailable')
    when,anchor=max(candidates,key=lambda c:c[1]['score']);height=anchor['height']
    # Follow the chosen crew's vertical band, retaining broad whole-frame detection.
    # Full-image context is still inferred; smaller tiles improve small-person input scale.
    related=[g for _,g in candidates if .6<=g['height']/height<=1.65]
    low=max(0,min(g['box'][1] for g in related)-height)
    high=min(H,max(g['box'][3] for g in related)+height)
    tile=int(np.clip(6*height,320,640))
    tiles=PoseDetector.tile_grid(W,H,(low,high),tile=tile)
    left=max(0,min(g['box'][0] for g in related)-2*height)
    right=min(W,max(g['box'][2] for g in related)+2*height)
    tiles=[t for t in tiles if t[2]>=left and t[0]<=right]
    dets,meta=extract(video,detector,tiles=tiles,start=start,duration=duration,target_fps=target_fps,progress=progress)
    reference=min(len(dets)-1,max(0,round((when-start)*meta['fps'])))
    eligible=[i for i in range(max(0,reference-round(meta['fps'])),min(len(dets),reference+round(meta['fps'])+1)) if groups(*dets[i])]
    if not eligible:raise ValueError('dominant_crew_unavailable')
    reference=min(eligible,key=lambda i:abs(i-reference))
    clean,audit=isolate(dets,meta['fps'],reference)
    audit.update(source_reference_seconds=start+reference/meta['fps'],tile_size=tile,tile_count=len(tiles),pilot_frames=5)
    return clean,meta,audit


def validate_metrics(metrics, *, n_frames):
    """Structural/measurement consistency, NOT proof of correct visual inference."""
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('nonfinite_metric')
        if isinstance(value,dict):
            for v in value.values():finite(v)
        elif isinstance(value,(list,tuple)):
            for v in value:finite(v)
    finite(metrics);rowers=metrics.get('rowers',[]);seen=set();cycles=0
    for rower in rowers:
        tid=rower.get('track',rower.get('tid'))
        if tid in seen:raise ValueError('duplicate_track')
        seen.add(tid);strokes=rower.get('strokes',[])
        if rower.get('summary',{}).get('n_strokes',0)!=len(strokes):raise ValueError('stroke_count_mismatch')
        for stroke in strokes:
            c,f,n=(stroke[k] for k in ('catch','finish','next_catch'))
            if not 0<=c<f<n<n_frames:raise ValueError('invalid_stroke_bounds')
            cycles+=1
        for counts in rower.get('joint_observation_counts',{}).values():
            if any(type(v) is not int or v<0 for v in counts.values()) or sum(counts.values())!=n_frames:
                raise ValueError('invalid_joint_denominator')
    return {'state':'checks_passed','checked_rowers':len(rowers),'checked_cycles':cycles,
      'sampled_frames':int(n_frames),'checks':['finite_values','unique_tracks','stroke_order_and_bounds','cycle_counts','joint_denominators'],
      'visual_accuracy':'not_independently_validated','coach_review':'pending'}


def decorate_report(path, metrics, validation):
    """Expose scope and omissions beside the actual, still-provisional estimates."""
    import html
    from pathlib import Path
    p=Path(path);scope=metrics.get('sync',{}).get('crew_selection',{})
    rows=[]
    for rower in metrics.get('rowers',[]):
        s=rower.get('summary',{});tracking=s.get('tracking',{});cycles=s.get('n_strokes',0)
        status='Five-cycle target met' if cycles>=5 else ('Short sample' if cycles else 'No usable continuous cycle')
        rows.append('<tr><td>'+html.escape(str(rower.get('seat','?')))+'</td><td>'
            +str(tracking.get('observed_frames',0))+' / '+str(validation['sampled_frames'])+'</td><td>'
            +str(cycles)+'</td><td>'+status+'</td></tr>')
    block=('<section style="max-width:1160px;margin:20px auto;padding:24px;border:1px solid #b4c9c2;background:#f2faf7;border-radius:14px">'
        '<h2>Analyzed crew and validation</h2><p>The largest, clearest aligned group of pose-model detections was selected automatically. '
        'A continuity gate excludes other crews; losses and camera changes remain gaps instead of recruiting replacement people. '
        'This is not a trained boat detector or independently verified identity tracking.</p>'
        f'<p>Selected crew visible in {scope.get("frames_with_group",0)} / {validation["sampled_frames"]} sampled frames. '
        f'{scope.get("excluded_detections",0)} other or ambiguous person detections were excluded.</p>'
        '<p><strong>Automated consistency checks passed:</strong> finite values, unique track IDs, stroke order/time bounds, cycle counts and joint-observation denominators. '
        '<strong>This does not validate the truth of every prediction.</strong> Technical accuracy and technique findings still require human review.</p>'
        '<table style="width:100%;text-align:left"><thead><tr><th>Model ID</th><th>Observed / sampled</th><th>Usable cycles</th><th>Evidence status</th></tr></thead>'
        '<tbody>'+''.join(rows)+'</tbody></table><p>IDs indicate model tracks, not verified seat numbers. '
        'Rates and phases below are body-motion estimates, not verified blade-entry measurements. '
        'Unobserved joints, unsupported rates and missing timing values remain unavailable. No measurements were inserted to fill the form.</p></section>')
    page=p.read_text(encoding='utf-8')
    if '<body>' not in page:raise ValueError('invalid_report_html')
    p.write_text(page.replace('<body>','<body>'+block,1),encoding='utf-8')


def track_visible_window(detections, fps):
    """Estimate slots only within the observed crew span; preserve source indices.

    Leading/trailing absence is not evidence of a zero-seat boat. Internal gaps
    remain present and downstream strict observed-cycle rules still apply.
    """
    from .pose import crew_tracks
    active=[i for i,(b,_) in enumerate(detections) if len(b)]
    if not active:return {},1,0
    first,last=active[0],active[-1]
    tracks,direction,seats=crew_tracks(detections[first:last+1],fps)
    for track in tracks.values():track['frames']=track['frames']+first
    return tracks,direction,seats
