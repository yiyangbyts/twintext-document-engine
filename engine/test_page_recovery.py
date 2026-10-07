import base64,unittest
import pymupdf
from service import Jobs

def pdf(texts):
    doc=pymupdf.open()
    for text in texts:doc.new_page().insert_text((30,50),text)
    if len(texts)>1:doc.set_toc([[1,'Bookmark',2]])
    data=doc.tobytes();doc.close();return base64.b64encode(data).decode()

class RecoveryTests(unittest.TestCase):
    def test_replace_only_successful_page_keep_count_order_and_bookmark(self):
        jobs=Jobs('babeldoc','.')
        try:
            r=jobs.assemble({'pdf':pdf(['Original 1','Original 2','Original 3']),'parts':[{'pageIndex':0,'pdf':pdf(['Translated 1'])},{'pageIndex':2,'pdf':pdf(['Translated 3'])}]})
            with pymupdf.open(stream=base64.b64decode(r['pdf']),filetype='pdf') as d:
                self.assertEqual(d.page_count,3);self.assertEqual([p.get_text().strip() for p in d],['Translated 1','Original 2','Translated 3']);self.assertEqual(d.get_toc()[0][2],2)
        finally:jobs.pool.shutdown()
    def test_reject_duplicate_or_misaligned_pages(self):
        jobs=Jobs('babeldoc','.')
        try:
            with self.assertRaises(ValueError):jobs.assemble({'pdf':pdf(['1','2']),'parts':[{'pageIndex':0,'pdf':pdf(['A','B'])}]})
            with self.assertRaises(ValueError):jobs.assemble({'pdf':pdf(['1','2']),'parts':[{'pageIndex':0,'pdf':pdf(['A'])},{'pageIndex':0,'pdf':pdf(['B'])}]})
        finally:jobs.pool.shutdown()


class PreserveTests(unittest.TestCase):
    def test_source_vector_clip_keeps_literal_link_and_does_not_duplicate_body_text(self):
        from preserved_regions import restore
        original=pymupdf.open();p=original.new_page(width=300,height=300);p.insert_text((20,30),'https://doi.org/10.1000/original');p.insert_text((20,200),'Unrelated body')
        translated=pymupdf.open();translated.new_page(width=300,height=300)
        data=restore(original.tobytes(),translated.tobytes(),[{'pageIndex':0,'rect':{'left':0,'top':0,'width':1,'height':.2}}])
        with pymupdf.open(stream=data,filetype='pdf') as out:
            self.assertIn('https://doi.org/10.1000/original',out[0].get_text());self.assertNotIn('Unrelated body',out[0].get_text())
            clip=pymupdf.Rect(0,0,300,60);self.assertEqual(out[0].get_pixmap(clip=clip).samples,original[0].get_pixmap(clip=clip).samples)
        original.close();translated.close()

if __name__=='__main__':unittest.main()
