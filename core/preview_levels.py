"""Stable display limits for noise-only processing, independent of UI."""
import numpy as np


def checkpoint_limits(record):
    history=record.get('history')
    if history is None:return None
    token=history.entries[history.index].get('token')
    saved=record.get('preview_ranges',{}).get(token)
    return saved[:2] if saved is not None else None


def checkpoint_strength(record):
    history=record.get('history')
    if history is None:return None
    saved=record.get('preview_ranges',{}).get(history.entries[history.index].get('token'))
    return saved[2] if saved is not None and len(saved)==3 else None


def checkpoint_transfer(record):
    limits=checkpoint_limits(record)
    if limits is None:return None
    strength=checkpoint_strength(record)
    return (*limits,record.get('strength',20) if strength is None else strength)


def reset_checkpoint_display(record):
    history=record.get('history')
    if history is not None:
        record.get('preview_ranges',{}).pop(history.entries[history.index].get('token'),None)


def denoise_limits(record):
    """Keep the previous pedestal/white point when the noise floor changes."""
    existing=checkpoint_limits(record)
    if existing is not None:return existing
    data=record['data'];step=max(1,int(np.ceil(max(data.shape[:2])/1600)))
    sample=data[::step,::step];finite=sample[np.isfinite(sample)]
    if not finite.size:return None
    lo,hi=np.percentile(finite,[.2,99.8])
    return (float(lo),float(hi)) if hi>lo else None
