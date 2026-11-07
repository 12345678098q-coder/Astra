"""Learn edit parameters from real pairs; the renderer cannot synthesize pixels.

A small RBF ridge regressor is appropriate for an initial small image-level
dataset. Its 27 outputs are bounded editing controls, never an image/residual.
"""
if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import json
import numpy as np
from scipy.ndimage import gaussian_filter
try:
    from .colour_controls import identity_recipe, validate, fit_recipe, apply_recipe
except ImportError:
    from colour_controls import identity_recipe, validate, fit_recipe, apply_recipe

FEATURES = 40
LOWER = np.r_[np.full(20, -1.2), [-.3] * 2, [-np.log(2)] * 3, [0.] * 2]
UPPER = np.r_[np.full(20, 1.2), [.3] * 2, [np.log(2)] * 3, [.4] * 2]
KIND = 'colour_control_predictor_v1'


def descriptor(image):
    a = np.asarray(image)
    if a.ndim != 3 or a.shape[-1] != 3 or not np.isfinite(a).all() or a.min() < 0 or a.max() > 1.00001:
        raise ValueError(localize('Нужен уже растянутый RGB-кадр в диапазоне 0…1.'))
    step = max(1, int(np.ceil(max(a.shape[:2]) / 128)))
    a = a[::step, ::step].reshape(-1, 3).astype(np.float64)
    lum = a @ np.array([.2126, .7152, .0722])
    saturation = (a.max(axis=1) - a.min(axis=1)) / np.maximum(a.max(axis=1), .005)
    q = [.01, .1, .3, .5, .7, .9, .99]
    result = np.r_[a.mean(axis=0), a.std(axis=0), np.quantile(a, q, axis=0).ravel(),
                   np.quantile(lum, q), saturation.mean(), saturation.std(),
                   (a / np.maximum(a.sum(axis=1, keepdims=True), .005)).mean(axis=0),
                   np.mean(lum < .05)]
    assert result.shape == (FEATURES,)
    return result


def kernel(a, b, bandwidth):
    distance = np.mean((a[:, None, :] - b[None, :, :]) ** 2, axis=-1)
    return np.exp(-distance / (2 * bandwidth ** 2))


def build(examples, regularization, bandwidth, mode,predictor='rbf',neighbors=3,shrinkage=1.):
    x = np.stack([e['features'] if 'features' in e else descriptor(e['before']) for e in examples])
    targets = np.stack([validate(e['recipe']) for e in examples])
    mean = x.mean(axis=0)
    scale = np.maximum(x.std(axis=0), .025)
    x = (x - mean) / scale
    average = targets.mean(axis=0)
    similarity=x@x.T/FEATURES if predictor=='linear' else kernel(x,x,bandwidth)
    coefficients = np.linalg.solve(similarity + regularization * np.eye(len(x)), targets - average)
    return {'feature_mean': mean, 'feature_scale': scale, 'training_features': x,
            'average_parameters': average, 'coefficients': coefficients,'training_parameters':targets,
            'bandwidth': np.array(bandwidth), 'regularization': np.array(regularization),
            'meta': json.dumps({'version': 2, 'kind': KIND, 'mode': mode,
                                'renderer':examples[0]['recipe']['renderer'],'predictor':predictor,'neighbors':int(neighbors),
                                'parameter_shrinkage':float(shrinkage)})}


def predict_recipe(source, model, mode=None):
    meta = json.loads(str(model['meta']))
    chosen_mode = meta['mode'] if mode is None else mode
    recipe = identity_recipe(chosen_mode)
    recipe['renderer']=meta.get('renderer','monotone_curves_balance_saturation_v1')
    x = (descriptor(source) - model['feature_mean']) / model['feature_scale']
    predictor=meta.get('predictor','rbf')
    if predictor=='mean':p=model['average_parameters'].copy()
    elif predictor in ('knn','rbf_average'):
        distance=np.mean((x-model['training_features'])**2,axis=1)
        if predictor=='knn':
            order=np.argsort(distance)[:max(1,min(int(meta.get('neighbors',3)),len(distance)))]
            weights=1/(distance[order]+.05)
            p=weights@model['training_parameters'][order]/weights.sum()
        else:
            weights=np.exp(-(distance-distance.min())/(2*float(model['bandwidth'])**2))
            p=weights@model['training_parameters']/weights.sum()
    else:
        weights=(x@model['training_features'].T/FEATURES) if predictor=='linear' else kernel(x[None], model['training_features'], float(model['bandwidth']))[0]
        p=model['average_parameters']+weights@model['coefficients']
    p=np.clip(p,LOWER,UPPER)*float(meta.get('parameter_shrinkage',1.))
    if chosen_mode == 'natural':
        p[25:] = 0
    recipe['parameters'] = p.tolist()
    validate(recipe)
    recipe['predictor'] = {'kind': KIND,
                           'nearest_feature_distance': float(np.sqrt(np.min(np.mean((x - model['training_features']) ** 2, axis=1))))}
    return recipe


def apply(source, model, strength=1., preserve=True, cancel=lambda: False,
          progress=lambda message: None, device='auto'):
    if cancel():
        raise InterruptedError(localize('Отменено.'))
    recipe = predict_recipe(source, model)
    progress(localize('Подобраны кривые, баланс и насыщенность; обработка исходных пикселей на CPU.'))
    return apply_recipe(source, recipe, strength, preserve, cancel, progress)


def score(model, examples):
    rows = []
    for e in examples:
        target = gaussian_filter(e['after'], (1.2, 1.2, 0))
        before = gaussian_filter(e['before'], (1.2, 1.2, 0))
        output = gaussian_filter(apply(e['before'], model, preserve=False), (1.2, 1.2, 0))
        rows.append({'group': e['group'], 'input_mse': float(np.mean((before - target) ** 2)),
                     'predicted_edit_mse': float(np.mean((output - target) ** 2))})
    return {'mean_input_mse': float(np.mean([r['input_mse'] for r in rows])),
            'mean_predicted_edit_mse': float(np.mean([r['predicted_edit_mse'] for r in rows])), 'per_pair': rows}


def train_from_recipes(training, validation, mode='natural', progress=lambda message: None,
                       cancel=lambda: False):
    train_groups = {e['group'] for e in training}
    validation_groups = {e['group'] for e in validation}
    if len(train_groups) < 3 or not validation_groups:
        raise ValueError(localize('Для подбора настроек нужны минимум три обучающих объекта и один отдельный проверочный объект.'))
    if train_groups & validation_groups:
        raise ValueError(localize('Один объект попал и в обучение, и в проверку.'))
    candidates = []
    best = None
    for regularization in [.1, 1., 10.]:
        for bandwidth in [.5, 1., 2.]:
            if cancel():
                raise InterruptedError(localize('Обучение отменено.'))
            model = build(training, regularization, bandwidth, mode)
            metrics = score(model, validation)
            candidates.append({'regularization': regularization, 'bandwidth': bandwidth, 'validation': metrics})
            progress(localize('Проверка регрессии: regularization={0:g}, bandwidth={1:g}, MSE={2:.6f}').format(regularization, bandwidth, metrics['mean_predicted_edit_mse']))
            if best is None or metrics['mean_predicted_edit_mse'] < best[0]:
                best = (metrics['mean_predicted_edit_mse'], model, metrics)
    model = best[1]
    renderer=training[0]['recipe']['renderer']
    if any(e['recipe']['renderer']!=renderer for e in training+validation):raise ValueError(localize('Нельзя смешивать разные версии обработки.'))
    model['meta'] = json.dumps({'version': 2, 'kind': KIND, 'mode': mode,'renderer':renderer,
                               'algorithm': 'RBF ridge regression of bounded edit parameters',
                               'features': FEATURES, 'outputs': 27, 'backend': 'CPU', 'scale': 1.,
                               'pairs': len(training) + len(validation), 'epochs': 0,
                               'training_groups': sorted(train_groups), 'validation_groups': sorted(validation_groups),
                               'training_pair_count': len(training), 'validation': best[0],
                               'validation_scores': best[2], 'candidates': candidates,
                               'synthetic_degradation': False, 'experimental': True,
                               'limitation': 'Small real-pair dataset. Predicts global colour controls only; no denoise, deconvolution, star removal or measured OIII recovery.'}, ensure_ascii=False)
    return model


def train(pairs, epochs=80, cancel=lambda: False, progress=lambda message: None,
          scale=1., device='auto', auto_align=True, mode='natural', groups=None):
    try:
        from . import engine
        from .alignment import align_pair
    except ImportError:
        import engine
        from alignment import align_pair
    if groups is None:
        groups = [str(pair[0]) for pair in pairs]
    if len(groups) != len(pairs) or len(set(groups)) < 4:
        raise ValueError(localize('Нужны минимум четыре независимых объекта: три для обучения, один для проверки. Все версии одного объекта укажите одной группой.'))
    examples = []
    progress(localize('Подбор ограниченных кривых и регрессия выполняются на CPU; модель не генерирует изображения.'))
    for index, (pair, group) in enumerate(zip(pairs, groups)):
        if cancel():
            raise InterruptedError(localize('Обучение отменено.'))
        before, after = [engine.read(path, scale) for path in pair]
        if auto_align:
            before, after, _ = align_pair(before, after, cancel, progress, max_control_points=250)
        recipe = fit_recipe(before, after, mode, cancel, progress, max_evaluations=epochs)
        examples.append({'before': before, 'after': after, 'recipe': recipe, 'group': str(group)})
        progress(localize('Подобраны настройки пары {0}/{1}').format(index + 1, len(pairs)))
    validation_group = str(groups[-1])
    model = train_from_recipes([e for e in examples if e['group'] != validation_group],
                               [e for e in examples if e['group'] == validation_group], mode, progress, cancel)
    meta = json.loads(model['meta'])
    meta.update(scale=float(scale), epochs=int(epochs))
    model['meta'] = json.dumps(meta, ensure_ascii=False)
    return model


def validate_model(model):
    shapes = {'feature_mean': (FEATURES,), 'feature_scale': (FEATURES,),
              'average_parameters': (27,), 'bandwidth': (), 'regularization': ()}
    for key, shape in shapes.items():
        value = np.asarray(model.get(key))
        if value.shape != shape or value.dtype.kind not in 'fi' or not np.isfinite(value).all():
            raise ValueError(localize('Некорректная модель настроек: ') + key)
    n = model.get('training_features', np.empty((0,))).shape
    if len(n) != 2 or n[1] != FEATURES or not 3 <= n[0] <= 200:
        raise ValueError(localize('Некорректные обучающие признаки.'))
    if model.get('coefficients', np.empty((0,))).shape != (n[0], 27):
        raise ValueError(localize('Некорректные коэффициенты.'))
    if not all(np.isfinite(model[key]).all() for key in ('training_features', 'coefficients')):
        raise ValueError(localize('Неконечные веса.'))
    if np.any(model['feature_scale'] <= 0) or float(model['bandwidth']) <= 0 or float(model['regularization']) <= 0:
        raise ValueError(localize('Некорректный масштаб модели.'))
    meta = json.loads(str(model['meta']))
    if meta.get('version') != 2 or meta.get('kind') != KIND or meta.get('mode') not in ('natural', 'hoo'):
        raise ValueError(localize('Неподдерживаемая версия модели настроек.'))
    if 'automatic_mask_policy' in meta:
        from processes.palettes.ai_masks import coefficients
        coefficients(model)
    if meta.get('predictor','rbf') not in ('rbf','linear','knn','rbf_average','mean'):
        raise ValueError(localize('Неизвестный способ подбора настроек.'))
    if meta.get('renderer','monotone_curves_balance_saturation_v1') not in (
            'monotone_curves_balance_saturation_v1','monotone_curves_balance_saturation_v2'):
        raise ValueError(localize('Неизвестная версия обработки.'))
    if not 0<=float(meta.get('parameter_shrinkage',1.))<=1:raise ValueError(localize('Некорректная сила подбора настроек.'))
    if meta.get('predictor') in ('knn','rbf_average'):
        values=model.get('training_parameters',np.empty((0,)))
        if values.shape!=(n[0],27) or not np.isfinite(values).all():raise ValueError(localize('Некорректные обучающие настройки.'))
    return model
