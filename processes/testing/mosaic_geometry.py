"""Validated projective registration and distortion-aware celestial mappings."""
import numpy as np
from skimage.transform import ProjectiveTransform
from core.i18n import localize


def estimate_projective(source, target):
    if hasattr(ProjectiveTransform, 'from_estimate'):
        return ProjectiveTransform.from_estimate(source, target)
    fit = ProjectiveTransform()
    return fit if fit.estimate(source, target) else None


def refine(similarity, points, shape):
    """Only accept extra degrees of freedom when held-out stars improve."""
    source, target = map(np.asarray, points)
    if len(source) < 18:
        return similarity
    # Deterministic spatially interleaved validation, independent of brightness.
    order = np.lexsort((source[:, 0], source[:, 1]))
    validation = order[::4]
    training = np.setdiff1d(order, validation)
    fit = estimate_projective(source[training], target[training])
    if not fit:
        return similarity
    error = np.linalg.norm(fit(source[validation])-target[validation], axis=1)
    baseline = np.linalg.norm(similarity(source[validation])-target[validation], axis=1)
    if np.median(error) + .05 >= .8*np.median(baseline) or np.max(error) > 2.:
        return similarity
    residual = np.linalg.norm(fit(source)-target, axis=1)
    good = residual < max(.5, 3*np.median(residual))
    if good.sum() < 14:
        return similarity
    fit = estimate_projective(source[good], target[good])
    if not fit:return similarity
    h,w = shape[:2]
    corners = np.array([[0,0],[w-1,0],[0,h-1],[w-1,h-1]])
    denominator = corners @ fit.params[2,:2] + fit.params[2,2]
    # Reject poles, orientation flips and unconstrained extrapolation.
    if np.min(denominator)*np.max(denominator) <= 0:
        return similarity
    if not np.isfinite(fit(corners)).all() or np.max(np.linalg.norm(fit(corners)-similarity(corners),axis=1)) > .15*max(h,w):
        return similarity
    return fit


class SkyMapping:
    def __init__(self, source, reference):
        self.source, self.reference = source, reference

    def __call__(self, xy):
        world = self.source.all_pix2world(xy, 0)
        return self.reference.all_world2pix(world, 0, quiet=True)

    def inverse(self, xy):
        world = self.reference.all_pix2world(xy, 0)
        return self.source.all_world2pix(world, 0, quiet=True)


def celestial_mappings(headers):
    from astropy.wcs import WCS
    systems = []
    for header in headers:
        metadata = {key:value for key,value in dict(header).items() if key not in ('COMMENT','HISTORY','')}
        wcs = WCS(metadata).celestial
        if not wcs.has_celestial or wcs.pixel_n_dim != 2:
            raise ValueError(localize('Отсутствует небесная система координат WCS.', 'Missing celestial WCS'))
        systems.append(wcs)
    return [SkyMapping(wcs, systems[0]) for wcs in systems]
