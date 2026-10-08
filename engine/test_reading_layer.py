"""Bounds of the read-only structured reader API; no model/network is needed."""
import tempfile,threading,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from reading_layer import run,character_obstacles

class ReadingLayerTests(unittest.TestCase):
 def test_display_formula_glyphs_are_obstacles_without_joining_columns(self):
  characters=[SimpleNamespace(box=dict(left=x,top=100,width=8,height=12)) for x in (20,30,40,260,270)]
  result=character_obstacles(characters,lambda box:box)
  self.assertEqual(len(result),2);self.assertEqual(result[0]['width'],28);self.assertEqual(result[1]['left'],260)
 def test_page_index_is_validated_before_loading_a_checkpoint(self):
  for value in (-1,True,'1',None):
   with self.assertRaisesRegex(ValueError,'Invalid reading page'):run({'currentPage':value},Path('.'),threading.Event())
 def test_expired_handle_does_not_trigger_translation(self):
  with self.assertRaisesRegex(ValueError,'native_artifact_expired'):run({'currentPage':0},Path('.'),threading.Event())
 def test_only_requested_page_is_loaded_from_its_part(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);part={'first':16,'last':31,'sha256':'a'*64}
   with patch('native_reflow.load_manifest',return_value=(root,{'pages':[19,20],'parts':[part]})),patch('native_reflow.load_part',return_value={'local':True}) as load,patch('reading_layer.page_data',return_value={'profile':'native-reading-2.0.12-v1','pageIndex':3}) as render:
    value=run({'currentPage':19,'artifactFile':'manifest'},root,threading.Event());self.assertEqual(value['pageIndex'],19)
    self.assertEqual(render.call_args.args[1],3);self.assertEqual(load.call_count,1)
    again=run({'currentPage':19,'artifactFile':'manifest'},root,threading.Event());self.assertEqual(again,value);self.assertEqual(render.call_count,1)
    with self.assertRaisesRegex(ValueError,'outside translated range'):run({'currentPage':1,'artifactFile':'manifest'},root,threading.Event())

if __name__=='__main__':unittest.main()
