"""Explicit local real-model identity/localization check against supplied labels.

No downloads or training. Exit 2 means blocked, 1 means failed supplied labels,
0 means passed these declared development labels, NOT general model accuracy.
"""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import time
from .blade_model import BladeModelError
from .blade_video import reference_frame
from .crew_model import CrewVision,validate_options,validate_predictions,mark_frame,_iou,_box
from .registry import _stream_sha256


def evaluate(video,labels,model,*,provider=None):
    selection=validate_options(labels['selection'])
    if selection['analyses']!=['position']:raise ValueError('evaluation_is_localization_only')
    if _stream_sha256(video)!=labels['source_sha256']:raise ValueError('wrong_labeled_recording')
    examples=labels.get('frames')
    if not isinstance(examples,list) or not 1<=len(examples)<=6:raise ValueError('bounded_labels_required')
    for f in examples:
        if (set(f)!={'seconds','boxes'} or len(f['boxes'])!=8
                or type(f['seconds']) not in (float,int) or not 0<=f['seconds']<=600):raise ValueError('invalid_labels')
        for b in f['boxes']:_box(b)
    actual_provider=provider or CrewVision(model)
    start=time.perf_counter();provenance=actual_provider.check()
    ref,actual=reference_frame(video,selection['reference_seconds'])
    reference=mark_frame({'image':base64.b64encode(ref).decode()},seeds=selection['seeds'])
    frames=[]
    for i,label in enumerate(examples):
        image,when=reference_frame(video,label['seconds'])
        frames.append({'frame_id':i,'time':when,'image':base64.b64encode(image).decode()})
    response=actual_provider.predict_crew(reference,frames,selection['seeds'],['position'])
    predicted=validate_predictions({'observations':response},list(range(len(frames))),['position'])
    actual_provider.check();records=[]
    for frame,truth in zip(predicted,examples):
        for i,(person,box) in enumerate(zip(frame['rowers'],truth['boxes']),1):
            visible=box is not None;found=person['same_rower'] and person['box'] is not None
            overlap=_iou(person['box'],box) if found and visible else None
            passed=(found and overlap>=.5) if visible else not found
            records.append({'frame_id':frame['frame_id'],'rower_id':i,'expected_visible':visible,
                            'model_visible':found,'iou':overlap,'passed_supplied_label':bool(passed)})
    return {'state':'passed_supplied_labels' if all(r['passed_supplied_label'] for r in records) else 'failed_supplied_labels',
       'label_provenance':labels.get('label_provenance','unspecified'),
       'model':provenance,'real_inference':provider is None,'seconds':time.perf_counter()-start,
       'tested_rower_frames':len(records),'passed_rower_frames':sum(r['passed_supplied_label'] for r in records),
       'per_rower':{str(i):{'passed':sum(r['passed_supplied_label'] for r in records if r['rower_id']==i),
           'total':len(frames)} for i in range(1,9)},'records':records,
       'limits':'Localization and identity against supplied labels only. Not blade-contact, SPM, posture correctness or coach validation.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--labels',type=Path,required=True)
    p.add_argument('--model',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--permission-confirmed',action='store_true',required=True)
    a=p.parse_args(argv)
    try:
        if a.labels.stat().st_size>65536:raise ValueError('label_file_too_large')
        labels=json.loads(a.labels.read_text(encoding='utf-8'))
        result=evaluate(a.video,labels,a.model)
    except Exception as exc:
        reason=str(exc) if type(exc) is BladeModelError else type(exc).__name__
        result={'state':'blocked','real_inference':False,'reason':reason,'passed_rower_frames':None}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 2 if result['state']=='blocked' else int(result['state']!='passed_supplied_labels')


if __name__=='__main__':raise SystemExit(main())
