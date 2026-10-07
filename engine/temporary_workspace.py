"""Clean only engine-created temporary files without discarding valid output."""
from contextlib import contextmanager
from pathlib import Path
import gc,logging,shutil,tempfile,threading

def cleanup(path):
    for attempt in range(2):
        try:shutil.rmtree(path);return True
        except FileNotFoundError:return True
        except OSError:
            if attempt==0:gc.collect()
    return False

def retry_cleanup(path,attempt=0):
    if cleanup(path):return
    if attempt>=3:
        logging.getLogger(__name__).warning('Temporary workspace still occupied: %s',Path(path).name)
        return
    timer=threading.Timer((2,10,60)[attempt],retry_cleanup,args=(path,attempt+1))
    timer.daemon=True;timer.start()

@contextmanager
def temporary_workspace(prefix):
    # mkdtemp records the exact directory created by this operation. Never
    # scan or delete arbitrary folders in the user's system temporary tree.
    path=tempfile.mkdtemp(prefix=prefix)
    try:yield path
    finally:retry_cleanup(path)
