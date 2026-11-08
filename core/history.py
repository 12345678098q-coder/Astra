"""Per-document history of image states, stored on disk between operations."""
from core.i18n import localize
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
import uuid

class ImageHistory:
    def __init__(self,label):
        self.directory=None; self.entries=[{'label':label,'path':None,'count_path':None}]; self.index=0
    def _write(self,data):
        if data is None:return None
        if self.directory is None:self.directory=TemporaryDirectory(prefix='astra-history-')
        path=Path(self.directory.name)/(uuid.uuid4().hex+'.npy')
        try:
            with path.open('xb') as f:np.save(f,data,allow_pickle=False)
        except Exception:
            path.unlink(missing_ok=True);raise
        return path
    def commit(self,current,current_count,data,count,label):
        original=self.entries[self.index]; created=[]
        try:
            old_path=original['path']
            if old_path is None:
                old_path=self._write(current); created.append(old_path)
                old_count=self._write(current_count)
                if old_count:created.append(old_count)
            else:old_count=original['count_path']
            new_path=self._write(data);created.append(new_path)
            new_count=self._write(count)
            if new_count:created.append(new_count)
        except Exception:
            for path in created:path.unlink(missing_ok=True)
            raise
        original.update(path=old_path,count_path=old_count)
        for entry in self.entries[self.index+1:]:
            for key in ('path','count_path'):
                if entry[key]:entry[key].unlink(missing_ok=True)
        self.entries=self.entries[:self.index+1]+[{'label':label,'path':new_path,'count_path':new_count}]; self.index+=1
    def snapshot(self,index,current=None,current_count=None):
        entry=self.entries[index]
        if entry['path'] is None:
            if index!=self.index or current is None:raise ValueError('Snapshot unavailable')
            return current.copy(),current_count.copy() if current_count is not None else None
        return np.load(entry['path'],allow_pickle=False),np.load(entry['count_path'],allow_pickle=False) if entry['count_path'] else None

    def truncate(self,last):
        if not 0<=last<len(self.entries) or self.index>last:raise ValueError('Restore retained snapshot first')
        removed=self.entries[last+1:]
        self.entries=self.entries[:last+1]
        for entry in removed:
            for key in ('path','count_path'):
                if entry[key]:
                    try:entry[key].unlink(missing_ok=True)
                    except OSError:pass  # Windows may still hold a mapped snapshot; the history directory owns cleanup.

    def restore(self,index):
        entry=self.entries[index]
        if entry['path'] is None:raise ValueError(localize('Состояние ещё не сохранено.'))
        data=np.load(entry['path'],allow_pickle=False)
        count=np.load(entry['count_path'],allow_pickle=False) if entry['count_path'] else None
        self.index=index;return data,count
    def close(self):
        if self.directory:self.directory.cleanup();self.directory=None
