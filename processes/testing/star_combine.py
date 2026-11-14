"""Combine aligned starless and stellar layers without detecting new stars."""
import numpy as np
from core.i18n import localize
from .engine import image, check


def combine(background, stars, automatic=True, background_gain=1., stars_gain=1., mode='add', cancel=lambda: False):
    check(cancel)
    background, stars = image(background), image(stars)
    if background.shape != stars.shape:
        raise ValueError(localize('Фон и звёзды должны иметь одинаковые размеры и каналы. Совместите слои перед объединением.'))
    if mode not in ('add', 'screen') or not np.isfinite([background_gain, stars_gain]).all() or min(background_gain, stars_gain) < 0:
        raise ValueError(localize('Некорректные настройки объединения.'))
    if automatic:
        background_gain = stars_gain = 1.
    check(cancel)
    a, b = background * background_gain, stars * stars_gain
    if mode == 'screen':
        if min(a.min(), b.min()) < 0 or max(a.max(), b.max()) > 1:
            raise ValueError(localize('Режим «Экран» требует слои в диапазоне 0…1. Выберите сложение или уменьшите яркость слоёв.'))
        result = a + b - a*b
    else:
        result = a + b
    scale = 1.
    # Preserve one shared colour scale; never silently clip individual channels.
    if automatic and min(background.min(), stars.min()) >= 0 and max(background.max(), stars.max()) <= 1:
        scale = max(1., float(result.max()))
        result /= scale
    check(cancel)
    return result, scale
