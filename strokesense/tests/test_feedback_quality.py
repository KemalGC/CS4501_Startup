"""Four-question quality review; all feedback here is explicitly synthetic."""
from copy import deepcopy
import csv,io,json,unittest
from test_feedback import FeedbackTests

KEYS=('clarity','specificity','completeness','actionability')
class FeedbackQualityTests(unittest.TestCase):
 def setUp(self):
  self.base=FeedbackTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
 def payload(self,**changes):
  return dict(clip_id='clip-one',analysis_version='revision1',questionnaire_version='quality-v2',
              answers={k:4 for k in KEYS},comment='Synthetic quality check',**changes)
 def save(self,p=None):return self.base.request('POST','/api/quality',p or self.payload())
 def get(self):
  s,h,b=self.base.request('GET','/api/quality?clip=clip-one');self.assertEqual(s,200);return json.loads(b)['responses']
 def owner(self,fmt='json'):
  return self.base.request('GET','/api/owner/quality.'+fmt,headers={'Authorization':'Bearer '+self.base.server.owner_key})
 def test_bootstrap_has_four_quality_questions_and_five_review_aspects(self):
  _,_,b=self.base.request('GET','/api/bootstrap');d=json.loads(b)
  self.assertIn('quality_questions',d,'quality questions are missing')
  self.assertEqual([q['id'] for q in d['quality_questions']],list(KEYS));self.assertEqual(len(d['aspects']),5)
 def test_quality_is_once_per_clip_revision_and_upserts_without_duplication(self):
  self.base.enroll();self.assertEqual(self.save()[0],200)
  p=self.payload();p['answers']['clarity']=2;self.assertEqual(self.save(p)[0],200)
  rows=self.get();self.assertEqual(len(rows),4);self.assertEqual(next(x for x in rows if x['question_id']=='clarity')['score'],2)
  self.assertEqual(self.base.server.store.rows(),[])
 def test_cannot_judge_and_not_applicable_stay_null_not_low_scores(self):
  self.base.enroll();p=self.payload();p['answers'].update(clarity='cannot_judge',completeness='not_applicable')
  self.assertEqual(self.save(p)[0],200);rows={r['question_id']:r for r in self.get()}
  self.assertIsNone(rows['clarity']['score']);self.assertEqual(rows['clarity']['reason'],'cannot_judge')
  self.assertIsNone(rows['completeness']['score']);self.assertEqual(rows['completeness']['reason'],'not_applicable')
 def test_missing_or_fabricated_question_and_invalid_values_are_rejected(self):
  self.base.enroll()
  for value in [True,1.5,0,6,None,float('nan'),'4','hidden']:
   p=self.payload();p['answers']['clarity']=value
   with self.subTest(value=value):self.assertEqual(self.save(p)[0],422)
  for change in ['missing','extra']:
   p=self.payload()
   if change=='missing':p['answers'].pop('actionability')
   else:p['answers']['injected']=5
   self.assertEqual(self.save(p)[0],422)
 def test_stale_revision_and_invalid_comment_rejected(self):
  self.base.enroll()
  for key,value in [('analysis_version','stale'),('questionnaire_version','quality-v999'),('clip_id','foreign'),('comment','a'*2001),('comment',False)]:
   p=self.payload();p[key]=value
   with self.subTest(key=key):self.assertEqual(self.save(p)[0],422)
 def test_requires_session_origin_csrf_and_owner_auth(self):
  self.assertEqual(self.save()[0],401);self.base.enroll()
  self.assertEqual(self.base.request('POST','/api/quality',self.payload(),{'Origin':'https://foreign.example'})[0],403)
  self.assertEqual(self.base.request('POST','/api/quality',self.payload(),{'X-CSRF-Token':'bad'})[0],403)
  self.assertEqual(self.base.request('GET','/api/owner/quality.json')[0],403)
 def test_other_reviewer_cannot_read_saved_quality(self):
  self.base.enroll();self.assertEqual(self.save()[0],200);self.base.cookie=None;self.base.enroll();self.assertEqual(self.get(),[])
 def test_withdraw_cascades_both_quality_and_existing_feedback(self):
  self.base.enroll();self.assertEqual(self.save()[0],200)
  self.base.request('POST','/api/reviews',self.base.review());self.base.request('POST','/api/withdraw',{})
  s,_,b=self.owner();self.assertEqual(s,200);self.assertEqual(json.loads(b)['responses'],[])
  self.assertEqual(self.base.server.store.rows(),[])
 def test_owner_exports_are_versioned_and_formula_safe(self):
  self.base.enroll();p=self.payload();p['comment']='=2+2';self.assertEqual(self.save(p)[0],200)
  s,_,raw=self.owner('csv');self.assertEqual(s,200)
  rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));self.assertEqual(len(rows),4)
  self.assertEqual(rows[0]['questionnaire_version'],'quality-v2');self.assertEqual(rows[0]['comment'],"'=2+2")
 def test_quality_install_preserves_legacy_rows_and_reopening(self):
  self.base.enroll();self.base.request('POST','/api/reviews',self.base.review())
  old=self.base.server.store.rows();self.assertEqual(self.save()[0],200)
  from strokesense.feedback_quality import QualityStore
  q=QualityStore(self.base.server.store)
  self.assertEqual(self.base.server.store.rows(),old);self.assertEqual(len(q.rows()),4)
 def test_previous_quality_questionnaire_and_evidence_answer_are_retained(self):
  session=self.base.enroll()
  from strokesense.feedback_quality import QualityStore
  q=QualityStore(self.base.server.store)
  old={'clip_id':'clip-one','analysis_version':'revision1','questionnaire_version':'quality-v1',
       'question_id':'evidence_support','score':None,'reason':'cannot_judge','comment':'Synthetic historical answer'}
  q.save(session['reviewer_id'],[old])
  self.assertEqual(self.save()[0],200)
  rows=QualityStore(self.base.server.store).rows()
  self.assertEqual(len(rows),5)
  evidence=next(r for r in rows if r['question_id']=='evidence_support')
  self.assertEqual(evidence['questionnaire_version'],'quality-v1')
  self.assertIsNone(evidence['score'])
  stale=self.payload();stale['questionnaire_version']='quality-v1'
  self.assertEqual(self.save(stale)[0],422)
  extra=self.payload();extra['answers']['evidence_support']=4
  self.assertEqual(self.save(extra)[0],422)

if __name__=='__main__':unittest.main()
