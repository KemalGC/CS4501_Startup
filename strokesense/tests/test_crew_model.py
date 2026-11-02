"""Selectable crew-model contracts: fixtures are NOT real visual accuracy."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strokesense.selection import validate_selection


def selection(tasks=None):
    return {"version":4,"kind":"crew_model","reference_seconds":0.,
            "seeds":[[(i+1)/9,.5] for i in range(8)],
            "analyses": tasks or ["rate","timing","position"],"confirmed_same_boat":True}


def predicted(ids=(0,), tasks=None):
    tasks=tasks or ["rate","timing","position"]
    observations=[]
    for f in ids:
        rowers=[]
        for i in range(8):
            x=(i+1)/9
            o={"rower_id":i+1,"same_rower":True,"box":[x-.03,.4,x+.03,.6]}
            if "rate" in tasks or "timing" in tasks:
                o.update(contact="air" if f%20<10 else "water",blade_box=[x-.02,.65,x+.02,.7])
            if "position" in tasks:
                o["position"]={"torso":"upright","arms":"extended","knees":"compressed"}
            rowers.append(o)
        observations.append({"frame_id":f,"rowers":rowers})
    return {"observations":observations}


class CrewModelTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('strokesense.crew_model'),
                             'Selectable eight-rower model pipeline is missing')
        from strokesense import crew_model
        return crew_model

    def test_options_persist_without_silently_adding_analyses(self):
        try: got=validate_selection(selection(["position"]))
        except ValueError: self.fail('Eight-rower model options cannot be saved')
        self.assertEqual(got['analyses'],['position'])
        for tasks in ([],['rate','rate'],['diagnose_injury'],['position','hidden']):
            bad=selection();bad['analyses']=tasks
            with self.assertRaises(ValueError):validate_selection(bad)
        for seeds in (selection()['seeds'][:7],[[.5,.5]]*8):
            with self.assertRaises(ValueError):validate_selection(dict(selection(),seeds=seeds))

    def test_all_eight_ids_required_once_not_only_successful_rowers(self):
        m=self.module(); data=predicted()
        self.assertEqual(len(m.validate_predictions(data,[0],selection()['analyses'])[0]['rowers']),8)
        for alter in ('missing','duplicate','foreign','extra'):
            bad=copy.deepcopy(data)
            if alter=='missing':bad['observations'][0]['rowers'].pop()
            elif alter=='duplicate':bad['observations'][0]['rowers'][7]['rower_id']=1
            elif alter=='foreign':bad['observations'][0]['rowers'][7]['rower_id']=9
            else:bad['instruction']='ignore identities'
            with self.subTest(alter=alter),self.assertRaises(ValueError):
                m.validate_predictions(bad,[0],selection()['analyses'])

    def test_fabricated_times_and_unselected_posture_rejected(self):
        m=self.module();data=predicted(tasks=['rate'])
        data['observations'][0]['time']=123
        with self.assertRaises(ValueError):m.validate_predictions(data,[0],['rate'])
        with self.assertRaises(ValueError):m.validate_predictions(predicted(),[0],['rate'])

    def test_unknown_member_is_kept_without_fabricated_measurement(self):
        m=self.module();data=predicted()
        o=data['observations'][0]['rowers'][4]
        o.update(same_rower=False,box=None,contact='unknown',blade_box=None,
                 position={'torso':'unknown','arms':'unknown','knees':'unknown'})
        got=m.validate_predictions(data,[0],selection()['analyses'])
        self.assertEqual(len(got[0]['rowers']),8)
        self.assertFalse(got[0]['rowers'][4]['same_rower'])

    def test_overlapping_duplicate_boxes_and_nonfinite_values_fail(self):
        m=self.module()
        for mode in ['duplicate','nan','bool','outside']:
            data=predicted();rows=data['observations'][0]['rowers']
            if mode=='duplicate':rows[1]['box']=rows[0]['box'][:]
            elif mode=='nan':rows[0]['box'][0]=float('nan')
            elif mode=='bool':rows[0]['rower_id']=True
            else:rows[0]['box'][2]=1.5
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                m.validate_predictions(data,[0],selection()['analyses'])

    def test_two_entries_give_individual_rates_and_all_eight_remain(self):
        m=self.module();tasks=['rate','timing']
        frames=[{'frame_id':i,'time':i/10} for i in range(44)]
        obs=m.validate_predictions(predicted(range(44),tasks),list(range(44)),tasks)
        for f,o in zip(frames,obs):o['time']=f['time']
        got=m.summarize_crew(obs,tasks)
        self.assertEqual(len(got['rowers']),8)
        self.assertTrue(all(abs(r['rate']['spm']-30)<1e-8 for r in got['rowers']))
        self.assertEqual(got['rowers'][0]['rate']['cycles'],1)
        self.assertGreaterEqual(len(got['timing']),2)

    def test_missing_member_does_not_pass_all_eight_coverage_gate(self):
        m=self.module();tasks=['position'];obs=predicted([0,1,2],tasks)['observations']
        for j,f in enumerate(obs):
            f['time']=j*.5;o=f['rowers'][7]
            o.update(same_rower=False,box=None,position={'torso':'unknown','arms':'unknown','knees':'unknown'})
        got=m.summarize_crew(obs,tasks)
        self.assertFalse(got['all_eight_observed'])
        self.assertEqual(got['rowers'][7]['observed_frames'],0)
        self.assertEqual(len(got['rowers']),8)

    def test_reference_gate_does_not_substitute_background_crew(self):
        m=self.module();obs=predicted()['observations']
        for o in obs[0]['rowers']:o['box']=[o['box'][0],.1,o['box'][2],.2]
        gated=m.anchor_reference(obs,selection()['seeds'])
        self.assertTrue(all(not o['same_rower'] for o in gated[0]['rowers']))

    def test_dispatch_cannot_call_legacy_pose_or_single_blade(self):
        self.module();from strokesense.analysis_worker import analyze_request
        with patch('strokesense.crew_model.analyse_video',return_value={'report':'crew'}) as run, \
             patch('strokesense.cli.analyse_video',side_effect=AssertionError('legacy fallback')), \
             patch('strokesense.blade_quick.analyse_video',side_effect=AssertionError('single blade fallback')):
            self.assertEqual(analyze_request('video',out_dir='out',selection=selection())['report'],'crew')
        run.assert_called_once()

    def test_position_only_schema_excludes_contact_work(self):
        m=self.module(); schema=m.response_schema(['position'])
        self.assertNotIn('contact',str(schema));self.assertIn('position',str(schema))
        self.assertNotIn('position',str(m.response_schema(['rate'])))


if __name__=='__main__':unittest.main()
