"""Fetch pinned upstream source distributions, independently of client software.
Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Archives are not extracted or executed. Runtime/native-library scope is recorded
separately in the license inventory; these three archives are not that full scope.
"""
import argparse,hashlib,json,time,urllib.request
from pathlib import Path

def verified(path,record):
 if not path.is_file() or path.stat().st_size!=record['bytes']:return False
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==record['sha256']

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path(__file__).with_name('upstream-source'));args=parser.parse_args()
 args.output.mkdir(parents=True,exist_ok=True)
 for record in json.loads(Path(__file__).with_name('upstream-sources.json').read_text()):
  if Path(record['file']).name!=record['file']:raise ValueError('Invalid source filename')
  destination=args.output/record['file']
  if verified(destination,record):print('Verified '+record['file'],flush=True);continue
  for attempt in range(3):
   temporary=destination.with_suffix('.tmp')
   try:
    size=0
    with urllib.request.urlopen(record['url'],timeout=60) as incoming,temporary.open('wb') as outgoing:
     while chunk:=incoming.read(1024*1024):
      size+=len(chunk)
      if size>record['bytes']:raise ValueError('Unexpected upstream source size')
      outgoing.write(chunk)
    if not verified(temporary,record):raise ValueError('Upstream source checksum mismatch')
    temporary.replace(destination);print('Downloaded '+record['file'],flush=True);break
   except Exception:
    temporary.unlink(missing_ok=True)
    if attempt==2:raise
    time.sleep(attempt+1)
if __name__=='__main__':main()
