import importlib.util,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import comic
class Formats(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);comic.init(self.r/'work',False)
 def tearDown(self):self.tmp.cleanup()
 def test_epub_uses_spine_order_and_preserves_archive(self):
  f=self.r/'original.epub'
  with zipfile.ZipFile(f,'w') as z:
   z.writestr('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
   z.writestr('OPS/book.opf','<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
   z.writestr('OPS/a.xhtml','<html><p>Chapter A original fixture.</p></html>');z.writestr('OPS/b.xhtml','<html><p>Chapter B original fixture.</p></html>')
  d=comic.ingest(self.r/'work',f);self.assertEqual([u['locator'] for u in d['units']],['OPS/b.xhtml','OPS/a.xhtml']);self.assertEqual(comic.sha(f),d['source_sha256'])
 @unittest.skipUnless(importlib.util.find_spec('pypdf') and importlib.util.find_spec('reportlab'),'optional PDF dependencies not present')
 def test_selectable_text_pdf_and_scan_failure(self):
  from reportlab.pdfgen.canvas import Canvas
  f=self.r/'story.pdf';c=Canvas(str(f));c.drawString(80,700,'Original sample chapter one.');c.showPage();c.drawString(80,700,'Original sample chapter two.');c.save()
  d=comic.ingest(self.r/'work',f);self.assertEqual(len(d['units']),2)
  blank=self.r/'scan.pdf';c=Canvas(str(blank));c.showPage();c.save()
  with self.assertRaisesRegex(ValueError,'NO_READABLE_TEXT'):comic.ingest(self.r/'work',blank)
if __name__=='__main__':unittest.main()
