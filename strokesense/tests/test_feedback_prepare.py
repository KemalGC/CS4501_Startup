import unittest,sys
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
if __name__=='__main__':unittest.main()
