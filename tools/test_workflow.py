import base64,copy,json,shutil,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import comic
from compile_comic_prompt import compile_prompt,CompileError
class WorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'work';comic.init(self.root,True);comic.plan(self.root,'sample/episode.json')
 def tearDown(self):self.tmp.cleanup()
 def authorize(self):comic.write(self.root/'control.json',{'hold':False,'generation_authorized':True,'episode':'sample-e001','max_attempts':2})
 def test_init_preserves_existing(self):
  with self.assertRaisesRegex(ValueError,'WORKSPACE_EXISTS'):comic.init(self.root,True)
 def test_hold_scope_and_unknown_result_prevent_duplicate(self):
  with self.assertRaisesRegex(ValueError,'HOLD'):comic.prepare(self.root,'sample-e001','p001')
  self.authorize();comic.prepare(self.root,'sample-e001','p001')
  with self.assertRaisesRegex(ValueError,'UNKNOWN_RESULT'):comic.prepare(self.root,'sample-e001','p001')
  self.assertEqual(len(comic.attempts(self.root/'episodes/sample-e001/p001')),1)
 def test_same_page_lock_blocks_concurrent_writer(self):
  self.authorize();p=self.root/'episodes/sample-e001/p001'
  with comic.lock(p):
   with self.assertRaises(FileExistsError):comic.prepare(self.root,'sample-e001','p001')
 def test_source_and_reference_drift_fail_before_call(self):
  self.authorize();(self.root/'sample/source.json').write_text('{}',encoding='utf-8')
  with self.assertRaisesRegex(CompileError,'stale source'):comic.prepare(self.root,'sample-e001','p001')
 def test_wrong_speaker_is_rejected(self):
  spec=comic.read(self.root/'sample/page-p001.json');spec['texts'][0]['speaker']='銅豆'
  with self.assertRaisesRegex(CompileError,'speaker mismatch'):compile_prompt(spec,comic.read(self.root/'sample/references.json'),comic.read(self.root/'sample/source-map.json'),self.root)
 def save_fixture(self):
  self.authorize();comic.prepare(self.root,'sample-e001','p001')
  # Test-only native-format carrier; never claimed as a generated comic.
  p=self.root/'fixture.png';p.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aKe8AAAAASUVORK5CYII='))
  r=self.root/'fixture-result.json';comic.write(r,{'image_url':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),'output_hint':'TEST FIXTURE ONLY'})
  c=comic.read(self.root/'control.json');c['hold']=True;comic.write(self.root/'control.json',c)
  comic.save(self.root,'sample-e001','p001',p,r);self.authorize();return p
 def observations(self,status='PASS'):
  a=self.root/'episodes/sample-e001/p001/attempt-01/native.png';r={'image_sha256':comic.sha(a),'observer':'test fixture, not human QA'}
  for k in comic.CRITERIA:r[k]={'status':status,'observation':'test-only lifecycle invariant'}
  f=self.root/'observations.json';comic.write(f,r);return f
 def test_save_during_hold_and_pass_never_regenerates(self):
  self.save_fixture();comic.review(self.root,'sample-e001','p001',self.observations())
  with self.assertRaisesRegex(ValueError,'ALREADY_SAVED_OR_PASS'):comic.prepare(self.root,'sample-e001','p001')
  out=comic.export(self.root,'sample-e001');self.assertEqual(out['pages'],1)
  with self.assertRaisesRegex(ValueError,'EXPORT_EXISTS'):comic.export(self.root,'sample-e001')
 def test_review_is_bound_to_actual_png(self):
  self.save_fixture();f=self.observations();r=comic.read(f);r['image_sha256']='0'*64;comic.write(f,r)
  with self.assertRaisesRegex(ValueError,'WRONG_IMAGE'):comic.review(self.root,'sample-e001','p001',f)
 def test_repair_preserves_attempt_and_requires_fail(self):
  self.save_fixture();comic.review(self.root,'sample-e001','p001',self.observations('FAIL'))
  s=comic.read(self.root/'sample/page-p001.json');s['panels'][0]['positions']='阿澄在右側，銅豆在左側'
  comic.write(self.root/'sample/page-p001-r02.json',s);comic.revise(self.root,'sample-e001','p001','sample/page-p001-r02.json')
  comic.prepare(self.root,'sample-e001','p001');self.assertEqual(len(comic.attempts(self.root/'episodes/sample-e001/p001')),2)
 def test_import_txt_is_idempotent_and_keeps_original(self):
  p=self.root/'original.txt';p.write_text('章一\n\n這是原創測試。',encoding='utf-8');one=comic.ingest(self.root,p);two=comic.ingest(self.root,p);self.assertEqual(one,two);self.assertEqual(one['units'][0]['paragraphs'],2)
 def test_paths_cannot_escape_workspace(self):
  with self.assertRaises(ValueError):comic.inside(self.root,'../outside')
if __name__=='__main__':unittest.main()
