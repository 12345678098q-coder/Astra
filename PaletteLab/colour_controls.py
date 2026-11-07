"""Interpretable colour editing: curves and saturation, never image synthesis.

An estimator may predict these few controls. Rendering is always a deterministic
pointwise transform of the original RGB values, independent of pixel coordinates.
Reference images are only used by fit_recipe, never by apply_recipe.
"""
if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.optimize import least_squares

X = np.array([0., .03, .1, .3, .65, 1.], dtype=np.float64)
LUMA = np.array([.2126, .7152, .0722], dtype=np.float64)
PARAMETERS = 27


def identity_recipe(mode='natural'):
    if mode not in ('natural', 'hoo'):
        raise ValueError(localize('Режим должен быть natural или hoo.'))
    return {'version': 1, 'mode': mode, 'parameters': [0.] * PARAMETERS,
            'renderer': 'monotone_curves_balance_saturation_v2'}


def validate(recipe):
    if recipe.get('version') != 1 or recipe.get('mode') not in ('natural', 'hoo'):
        raise ValueError(localize('Неподдерживаемый рецепт.'))
    if recipe.get('renderer') not in ('monotone_curves_balance_saturation_v1','monotone_curves_balance_saturation_v2'):
        raise ValueError(localize('Неподдерживаемый способ обработки.'))
    p = np.asarray(recipe.get('parameters'), dtype=np.float64)
    if p.shape != (PARAMETERS,) or not np.isfinite(p).all():
        raise ValueError(localize('Некорректные параметры.'))
    if np.any(np.abs(p[:20]) > 1.2) or np.any(np.abs(p[20:22]) > .3):
        raise ValueError(localize('Слишком сильные кривые или баланс.'))
    if np.any(np.abs(p[22:25]) > np.log(2) + 1e-9):
        raise ValueError(localize('Насыщенность должна быть в пределах 0.5…2.'))
    if np.any(p[25:] < 0) or np.any(p[25:] > .4):
        raise ValueError(localize('Слишком сильное выделение HOO.'))
    if recipe['mode'] == 'natural' and np.any(p[25:] != 0):
        raise ValueError(localize('Настройки HOO не применяются в режиме текущей палитры.'))
    return p


def knots(parameters):
    """Positive slopes guarantee a monotone curve, fixed black and white endpoints."""
    increments = np.diff(X) * np.exp(parameters)
    return np.r_[0., np.cumsum(increments) / increments.sum()]


def _compress_gamut(values,lum=None):
    if lum is None:lum=values@LUMA
    chroma=values-lum[...,None]
    positive=np.where(chroma>0,(1-lum[...,None])/np.maximum(chroma,1e-12),np.inf)
    negative=np.where(chroma<0,lum[...,None]/np.maximum(-chroma,1e-12),np.inf)
    scale=np.minimum(1.,np.minimum(positive.min(axis=-1),negative.min(axis=-1)))
    return np.clip(lum[...,None]+np.maximum(scale,0)[...,None]*chroma,0,1)


def _render(rgb, p, mode, renderer='monotone_curves_balance_saturation_v2'):
    gain=np.exp([p[20], -(p[20] + p[21]) / 2, p[21]])
    if renderer.endswith('_v2'):
        # Endpoint-preserving gain curve protects bright star cores from clipping.
        balanced=rgb*gain/(1+(gain-1)*rgb)
    else:balanced=rgb*gain
    values = np.empty_like(balanced, dtype=np.float64)
    for channel in range(3):
        values[..., channel] = np.interp(balanced[..., channel], X, knots(p[channel * 5:channel * 5 + 5]))
    # A shared master RGB curve, then tonal saturation, all on the same pixel.
    values = np.interp(values, X, knots(p[15:20]))
    lum = values @ LUMA
    shadow = (1 - np.clip(lum, 0, 1)) ** 2
    highlight = np.clip(lum, 0, 1) ** 2
    mid = 1 - shadow - highlight
    saturation = np.exp(p[22] * shadow + p[23] * mid + p[24] * highlight)
    values = lum[..., None] + saturation[..., None] * (values - lum[..., None])
    if mode == 'hoo':
        # HOO emphasis is gated by existing red/cyan chroma; grey cannot become a nebula.
        red = np.maximum(rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2]), 0)
        cyan = np.maximum(np.minimum(rgb[..., 1], rgb[..., 2]) - rgb[..., 0], 0)
        brightness = np.maximum(rgb.max(axis=-1), .02)
        factor = 1 + p[25] * red / brightness + p[26] * cyan / brightness
        values = lum[..., None] + factor[..., None] * (values - lum[..., None])
    return _compress_gamut(values) if renderer.endswith('_v2') else values


def apply_recipe(source, recipe, strength=1., preserve_luminance=False,
                 cancel=lambda: False, progress=lambda message: None):
    p = validate(recipe)
    a = np.asarray(source)
    if a.ndim != 3 or a.shape[-1] != 3 or not np.isfinite(a).all():
        raise ValueError(localize('Нужны конечные RGB-данные.'))
    if a.min() < 0 or a.max() > 1.00001:
        raise ValueError(localize('Нужен диапазон 0…1; линейный стек сначала растяните отдельно.'))
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError(localize('Сила должна быть в диапазоне 0…1.'))
    if strength == 0 or not np.any(p):
        return a.copy()
    output = np.empty(a.shape, np.float32)
    for top in range(0, len(a), 128):
        if cancel():
            raise InterruptedError(localize('Цветокоррекция отменена.'))
        original = a[top:top + 128].astype(np.float64)
        edited = _render(original, p, recipe['mode'],recipe['renderer'])
        if preserve_luminance:
            edited += ((original @ LUMA) - (edited @ LUMA))[..., None]
            if recipe['renderer'].endswith('_v2'):edited=_compress_gamut(edited,original@LUMA)
        output[top:top + 128] = original + strength * (edited - original)
        progress(localize('Кривые и насыщенность: {0}/{1}').format(min(top + 128, len(a)), len(a)))
    return output


def describe_recipe(recipe):
    p = validate(recipe)
    return {'mode': recipe['mode'],
            'curves': {name: {'x': X.tolist(), 'y': knots(p[i * 5:i * 5 + 5]).tolist()}
                       for i, name in enumerate(['red', 'green', 'blue', 'master'])},
            'balance_rgb': np.exp([p[20], -(p[20] + p[21]) / 2, p[21]]).tolist(),
            'saturation_shadows_midtones_highlights': np.exp(p[22:25]).tolist(),
            'hoo_red_cyan_emphasis': p[25:].tolist(),
            'operations': ['colour_balance', 'monotone_RGB_curves', 'monotone_master_curve',
                           'tonal_saturation'] + (['existing_red_cyan_emphasis'] if recipe['mode'] == 'hoo' else [])}


def fit_recipe(before, after, mode='natural', cancel=lambda: False,
               progress=lambda message: None, max_evaluations=80, family='full', colour_weight=0.):
    """Find an editing recipe for an already registered real before/after pair.

    This fits one pair. It is not a general model for predicting edits on new images.
    A separate learned parameter estimator needs multiple independent real pairs.
    Low-frequency loss avoids trying to imitate the reference's sharpening/denoise.
    """
    recipe = identity_recipe(mode)
    if before.shape != after.shape or before.ndim != 3 or before.shape[-1] != 3:
        raise ValueError(localize('Сначала совместите настоящую пару одного исходного снимка.'))
    if any(not np.isfinite(a).all() or a.min() < 0 or a.max() > 1.00001 for a in (before, after)):
        raise ValueError(localize('Оба изображения должны быть конечными RGB в диапазоне 0…1.'))
    # Stratified spatial sampling; exclude borders containing source labels/watermarks.
    rng = np.random.default_rng(20261104)
    h, w = before.shape[:2]
    if min(h, w) < 32:
        raise ValueError(localize('Общая область пары должна быть не меньше 32×32.'))
    yy = rng.integers(max(1, h // 20), max(2, h * 9 // 10), size=8000)
    xx = rng.integers(max(1, w // 20), max(2, w * 19 // 20), size=8000)
    # The loss uses low-frequency colours; full-resolution rendering is checked
    # separately because smoothing and nonlinear curves do not commute exactly.
    target = gaussian_filter(after.astype(np.float64), (1.2, 1.2, 0))[yy, xx]
    patch = gaussian_filter(before.astype(np.float64), (1.2, 1.2, 0))[yy, xx]
    if family == 'full':indices = np.arange(25)
    elif family == 'rgb':indices = np.r_[np.arange(15), np.arange(22,25)]
    elif family == 'global':indices = np.arange(15,25)
    else:raise ValueError(localize('Неизвестное семейство настроек.'))
    if mode == 'hoo':indices=np.r_[indices,[25,26]]
    count=len(indices)
    lower = np.r_[np.full(20, -1.2), [-.3] * 2, [-np.log(2)] * 3, [0.] * 2][indices]
    upper = np.r_[np.full(20, 1.2), [.3] * 2, [np.log(2)] * 3, [.4] * 2][indices]
    target_colour=target/np.maximum(target.sum(axis=-1,keepdims=True),.03)
    colour_mask=np.clip((target@LUMA)/.08,0,1)[:,None]
    calls = 0
    def residual(active):
        nonlocal calls
        if cancel():
            raise InterruptedError(localize('Подбор кривых отменён.'))
        p = np.zeros(PARAMETERS)
        p[indices] = active
        calls += 1
        if calls % 300 == 0:
            progress(localize('Подбор кривых по реальной паре…'))
        # Both versions are smooth, so fine PSF/noise differences do not dominate.
        output=_render(patch,p,mode)
        colour_error = (output - target).ravel() / np.sqrt(target.size)
        if colour_weight:
            output_colour=output/np.maximum(output.sum(axis=-1,keepdims=True),.03)
            chroma=(colour_weight*colour_mask*(output_colour-target_colour)).ravel()/np.sqrt(target.size)
            return np.r_[colour_error,chroma,active*.0015]
        return np.r_[colour_error, active * .0015]
    fitted = least_squares(residual, np.zeros(count), bounds=(lower, upper),
                           max_nfev=max_evaluations, diff_step=.001)
    p = np.zeros(PARAMETERS)
    p[indices] = fitted.x
    recipe['parameters'] = p.tolist()
    validate(recipe)
    recipe['fit'] = {'sampled_pixels': len(yy), 'function_evaluations': int(fitted.nfev),
                     'family':family,'colour_weight':float(colour_weight),
                     'converged':bool(fitted.success),'optimality':float(fitted.optimality),
                     'input_low_frequency_mse': float(np.mean((patch - target) ** 2)),
                     'edited_low_frequency_mse': float(np.mean((_render(patch, p, mode) - target) ** 2)),
                     'status': 'one_pair_recipe_fit_not_a_general_trained_model'}
    return recipe
