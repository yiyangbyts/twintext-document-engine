import unittest
from types import SimpleNamespace
import pymupdf
from page_geometry import normalize,reference_response,restore_content,content_rotation

class GeometryTests(unittest.TestCase):
 def test_sideways_body_without_rotate_is_parsed_upright_and_restored(self):
  with pymupdf.open() as pdf:
   for angle in (90,180,270):
    p=pdf.new_page(width=600,height=800)
    for n in range(8):p.insert_text((180 if angle==90 else 450 if angle==270 else 480,650 if angle==90 else 160 if angle==270 else 600-n*22),'Body prose describing the study and its measurements.',rotate=angle,fontsize=9)
    p.insert_text((60,760),'Horizontal footer')
   data=pdf.tobytes()
  config=SimpleNamespace(should_translate_page=lambda n:True);canonical,_=normalize(data,config)
  self.assertEqual(config.twintext_content_rotations,{0:90,1:180,2:270})
  restored=restore_content(canonical,config.twintext_content_rotations)
  with pymupdf.open(stream=data,filetype='pdf') as source,pymupdf.open(stream=canonical,filetype='pdf') as upright,pymupdf.open(stream=restored,filetype='pdf') as output:
   for n in range(3):
    self.assertEqual(content_rotation(upright[n]),0);self.assertEqual(source[n].rect,output[n].rect)
    a=source[n].get_pixmap().samples;b=output[n].get_pixmap().samples
    self.assertLess(sum(abs(x-y) for x,y in zip(a,b))/len(a),.2)
 def test_sideways_margin_labels_do_not_rotate_horizontal_body(self):
  with pymupdf.open() as pdf:
   p=pdf.new_page();p.insert_text((70,110),'An ordinary horizontal scientific paragraph with enough words to be recognized.')
   for y in (100,300,500):p.insert_text((22,y),'Author Manuscript',rotate=270)
   self.assertEqual(content_rotation(p),0)
 def source(self):
  with pymupdf.open() as d:
   for rotation in (0,90,180,270):
    p=d.new_page(width=400,height=600);p.insert_text((90,110),'Original table 71.3 67.8 72.0');p.draw_line((70,140),(310,140));p.set_cropbox(pymupdf.Rect(40,60,360,550));p.set_rotation(rotation)
   p=d.new_page(width=600,height=400);p.insert_text((90,110),'Direct landscape table')
   return d.tobytes()
 def test_vector_normalization_preserves_visible_crop_and_rotated_table(self):
  data=self.source();canonical,rotations=normalize(data,SimpleNamespace(should_translate_page=lambda n:True))
  self.assertEqual(rotations,{1:90,2:180,3:270})
  with pymupdf.open(stream=data,filetype='pdf') as old,pymupdf.open(stream=canonical,filetype='pdf') as new:
   for index in range(5):
    self.assertEqual(new[index].rotation,0)
    self.assertEqual(new[index].rect,old[index].rect)
    self.assertEqual(new[index].get_text(),old[index].get_text())
    self.assertEqual(len(new[index].get_drawings()),len(old[index].get_drawings()))
    # Rotation resampling can shift edge antialiasing by one pixel. Content
    # coverage must nevertheless match exactly to within a small edge budget.
    a=old[index].get_pixmap();b=new[index].get_pixmap()
    self.assertEqual((a.width,a.height),(b.width,b.height))
    self.assertLess(sum(abs(x-y) for x,y in zip(a.samples,b.samples))/len(a.samples),.2)
 def test_unselected_rotated_page_remains_in_its_original_frame(self):
  data=self.source();canonical,rotations=normalize(data,SimpleNamespace(should_translate_page=lambda n:n==2))
  self.assertEqual(rotations,{1:90})
  with pymupdf.open(stream=data,filetype='pdf') as old,pymupdf.open(stream=canonical,filetype='pdf') as new:
   for index in (0,2,3,4):
    self.assertEqual(new[index].rotation,old[index].rotation)
    self.assertEqual(new[index].get_pixmap().samples,old[index].get_pixmap().samples)
 def test_upright_document_returns_original_bytes_without_resaving(self):
  data=self.source();canonical,rotations=normalize(data,SimpleNamespace(should_translate_page=lambda n:n in (1,5)))
  self.assertIs(canonical,data);self.assertEqual(rotations,{})
 def test_reference_region_rotation_is_local_and_non_mutating(self):
  r=dict(left=.1,top=.2,width=.3,height=.05)
  response={'entries':[{'pageIndex':3,'rect':r,'lines':[{'rect':r}],'bodyLeft':.12}], 'exclusions':[{'pageIndex':0,'rect':r}]}
  converted=reference_response(response,{3:270})
  for k,v in dict(left=.2,top=.6,width=.05,height=.3).items():self.assertAlmostEqual(converted['entries'][0]['rect'][k],v)
  self.assertEqual(converted['exclusions'],response['exclusions'])
  self.assertIsNone(converted['entries'][0]['bodyLeft']);self.assertEqual(response['entries'][0]['rect'],r)
 def test_already_oriented_standard_regions_are_not_rotated_twice(self):
  r=dict(left=.1,top=.2,width=.3,height=.05)
  response={'entries':[{'pageIndex':3,'rect':r,'coordinateRotation':270,'bodyLeft':.12}]}
  self.assertEqual(reference_response(response,{3:270}),response)
 def test_nonzero_media_origin_and_crop_preserve_visible_content(self):
  with pymupdf.open() as pdf:
   p=pdf.new_page(width=400,height=600);p.set_mediabox(pymupdf.Rect(25,40,425,640));p.insert_text((90,110),'Offset landscape table 71.3');p.draw_line((70,140),(310,140));p.set_cropbox(pymupdf.Rect(65,60,385,550));p.set_rotation(270);data=pdf.tobytes()
  canonical,rotations=normalize(data,SimpleNamespace(should_translate_page=lambda n:True))
  self.assertEqual(rotations,{0:270})
  with pymupdf.open(stream=data,filetype='pdf') as old,pymupdf.open(stream=canonical,filetype='pdf') as new:
   self.assertEqual(old[0].rect,new[0].rect)
   self.assertEqual(old[0].get_text(),new[0].get_text())
   a=old[0].get_pixmap().samples;b=new[0].get_pixmap().samples
   self.assertLess(sum(abs(x-y) for x,y in zip(a,b))/len(a),.2)
if __name__=='__main__':unittest.main()
