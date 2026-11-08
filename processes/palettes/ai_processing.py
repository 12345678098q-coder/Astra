"""Input preparation for palette inference, independent of Qt."""
from core.i18n import localize
import numpy as np


def prepare_input(data, scale, linear=False, cancel=lambda: False, progress=lambda text: None):
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError(localize('Некорректный диапазон'))
    a = np.asarray(data, dtype=np.float64) / scale
    if a.ndim != 3 or a.shape[-1] != 3 or not np.isfinite(a).all():
        raise ValueError(localize('Требуется RGB без NaN/Inf'))
    if cancel():
        raise InterruptedError(localize('Отменено'))
    if linear:
        from PaletteLab.display_stretch import auto_stretch
        # Linear calibrated stacks can contain negative background samples.
        return auto_stretch(a, cancel=cancel, progress=progress)[0]
    if a.min() < 0 or a.max() > 1.00001:
        raise ValueError(localize('Проверьте диапазон. ИИ требует уже растянутый RGB-кадр'))
    return a.astype(np.float32)
