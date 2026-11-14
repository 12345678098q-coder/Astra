"""Detect a consistent moving source after registration on field stars."""
from core.i18n import localize
import warnings
import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, shift
from scipy.spatial import cKDTree
from skimage.transform import warp
from .engine import check, image


def align_comet(arrays, times=None, cancel=lambda: False, note=lambda value: None, *, alignment='comet'):
    import astroalign
    from processes.native.processing import luminance
    from core.resources import require_memory
    if len(arrays) < 3:
        raise ValueError(localize('Для автоматического поиска нужны минимум три кадра.'))
    frames = [image(a) for a in arrays]
    if any(a.shape != frames[0].shape for a in frames):
        raise ValueError(localize('Размеры и число каналов кадров должны совпадать.'))
    if alignment not in ('comet', 'stars'):
        raise ValueError(localize('Неизвестный режим совмещения.'))
    t = np.arange(len(frames), dtype=float) if times is None or alignment == 'stars' else np.asarray(times, float)
    if len(t) != len(frames) or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError(localize('Время съёмки кадров должно строго возрастать.'))
    t = (t-t[0])/(t[-1]-t[0])
    require_memory(sum(a.nbytes for a in frames)*5, localize('Совмещение по комете'))
    ref = luminance(frames[0])
    registered = [frames[0]]
    for i, frame in enumerate(frames[1:], 2):
        check(cancel)
        note(localize('Совмещение по звёздам {0}/{1}', 'Aligning on stars {0}/{1}').format(i, len(frames)))
        transform, _ = astroalign.find_transform(luminance(frame), ref)
        registered.append(warp(frame, transform.inverse, output_shape=ref.shape,
                               order=1, mode='constant', cval=np.nan, preserve_range=True))
    positions = (find_track(registered, t, cancel, note) if alignment == 'comet'
                 else np.zeros((len(frames), 2)))
    total = np.zeros_like(frames[0])
    count = np.zeros(ref.shape)
    for frame, position in zip(registered, positions):
        check(cancel)
        moved = frame
        if alignment == 'comet':
            delta = positions[0]-position
            moved = shift(frame, tuple(delta[::-1])+((0,) if frame.ndim == 3 else ()),
                          order=1, cval=np.nan, prefilter=False)
        covered = np.isfinite(moved).all(axis=-1) if moved.ndim == 3 else np.isfinite(moved)
        total += np.where(covered[...,None] if frame.ndim == 3 else covered, moved, 0)
        count += covered
    result = total/np.maximum(count[...,None] if total.ndim == 3 else count, 1)
    result[count == 0] = np.nan
    return result, count, positions


def find_track(registered, t, cancel, note):
    from processes.native.processing import luminance
    planes = np.array([luminance(a) for a in registered])
    valid = np.isfinite(planes).all(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        background = np.nanmedian(planes, axis=0)
    candidates = []
    for plane in planes:
        check(cancel)
        residual = np.where(valid, plane-background, 0.)
        residual -= np.median(residual[valid]) if valid.any() else 0.
        smooth = gaussian_filter(residual, 1.)
        noise = 1.4826*np.median(np.abs(smooth[valid]-np.median(smooth[valid]))) if valid.any() else 0.
        threshold = max(5*noise, np.max(np.abs(plane[np.isfinite(plane)]))*1e-7)
        peaks = (smooth == maximum_filter(smooth, 7)) & (smooth > threshold) & valid
        peaks[:8] = False; peaks[-8:] = False; peaks[:,:8] = False; peaks[:,-8:] = False
        y, x = np.where(peaks)
        top = np.argsort(smooth[y,x])[-40:]
        candidates.append((np.column_stack((x[top],y[top])), smooth[y[top],x[top]]/threshold))
    if any(len(points) == 0 for points, _ in candidates):
        raise ValueError(localize('Движущийся объект не найден во всех кадрах. Нужна серия с заметным движением относительно звёзд.'))
    trees = [cKDTree(points) for points, _ in candidates]
    tracks = []
    for start in candidates[0][0]:
        check(cancel)
        for end in candidates[-1][0]:
            if np.linalg.norm(end-start) < 3:
                continue
            predicted = start+(end-start)*t[:,None]
            hits = [tree.query(position) for tree, position in zip(trees, predicted)]
            distances, indices = np.asarray(hits).T
            if np.max(distances) > 2.5:
                continue
            points = np.array([entry[0][int(index)] for entry,index in zip(candidates,indices)])
            design = np.column_stack((np.ones(len(t)), t))
            fitted = design@np.linalg.lstsq(design, points, rcond=None)[0]
            error = np.sqrt(np.mean((fitted-points)**2))
            significance = np.median([entry[1][int(index)] for entry,index in zip(candidates,indices)])
            tracks.append((significance/(1+error), fitted))
    if not tracks:
        raise ValueError(localize('Не удалось подтвердить траекторию. Проверьте последовательность и наличие движущегося объекта.'))
    tracks.sort(key=lambda entry: entry[0], reverse=True)
    best_score, positions = tracks[0]
    for score, track in tracks[1:]:
        if score > best_score*.85 and np.linalg.norm(track[0]-positions[0]) > 5:
            raise ValueError(localize('Найдено несколько сопоставимых траекторий. Выберите серию с одним основным движущимся объектом.'))
    distance = np.linalg.norm(positions[-1]-positions[0])
    note(localize('Объект найден в {0} кадрах. Перемещение {1:.1f} пикс.',
                  'Object detected across {0} frames. Displacement: {1:.1f} px.').format(len(registered), distance))
    return positions
