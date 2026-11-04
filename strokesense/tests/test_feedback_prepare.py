import unittest,sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strokesense.feedback_prepare import summarize_metrics

class FeedbackPrepareTests(unittest.TestCase):
 def test_failure_never_becomes_clean_technique_or_fake_rate(self):
  r=summarize_metrics(None,start=2,end=14)
  self.assertEqual(r['aspects']['rate']['status'],'unavailable')
  self.assertNotIn('SPM',r['aspects']['rate']['summary'])
 def test_revision_binds_changed_metrics_and_explanation(self):
  a=summarize_metrics(None);b=summarize_metrics(None,note='Changed assessment')
  self.assertNotEqual(a['version'],b['version'])
 def test_partial_metrics_are_exposed_without_crew_cadence_invention(self):
  r=summarize_metrics({'rowers':[{'seat':'A','summary':{'n_strokes':1,'rate':23.,'trunk_catch':9.,'trunk_finish':-13.,'issues':[]}}]})
  self.assertIn('withheld',r['aspects']['rate']['summary'])
  self.assertEqual(len(r['aspects']['rate']['details']),1)
  self.assertEqual(r['aspects']['timing']['status'],'unavailable')
 def test_shared_boat_rate_is_the_only_reviewable_rate_and_raw_inputs_stay_unchanged(self):
  metrics={'rowers':[{'seat':str(i),'summary':{'n_strokes':4,'rate':rate,'issues':[]}}
                     for i,rate in enumerate([21.,34.,34.,34.,34.,34.,34.,45.])],
           'crew_cadence':{'rate_spm':34.2,'supporting_rowers':6,'total_rowers':8,
                           'support_duration_seconds':8.5,'rate_range_spm':[33.,35.]},
           'evidence':{'status':'candidate'}}
  original=deepcopy(metrics);result=summarize_metrics(metrics);rate=result['aspects']['rate']
  self.assertEqual(rate['status'],'available')
  self.assertIn('34.2 SPM',rate['summary'])
  self.assertIn('whole selected boat',rate['details'][1]['value'])
  self.assertNotIn('21.0',str(rate));self.assertNotIn('45.0',str(rate))
  self.assertEqual(metrics,original)
  self.assertIn('evidence',result['aspects'])
  # Different raw evidence still binds a new analysis revision even if the shared display agrees.
  metrics['rowers'][-1]['summary']['rate']=46.
  changed=summarize_metrics(metrics)
  self.assertEqual(changed['aspects']['rate'],rate)
  self.assertNotEqual(changed['version'],result['version'])
 def test_withheld_shared_estimate_cannot_fall_back_to_raw_rower_rates(self):
  metrics={'crew_cadence':{'rate_spm':None},'rowers':[
      {'seat':str(i),'summary':{'n_strokes':1,'rate':34.,'issues':[]}} for i in range(8)]}
  result=summarize_metrics(metrics)
  self.assertEqual(result['aspects']['rate']['status'],'unavailable')
  self.assertNotIn('34.0',str(result['aspects']['rate']))
if __name__=='__main__':unittest.main()
