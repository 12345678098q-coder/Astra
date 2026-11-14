"""Stacking defaults shared by the interface and the processing engine."""

DEFAULT_STACK_OPTIONS = {
    'auto_resources':True, 'hot':True, 'cold':True, 'device':'cpu', 'drizzle':False, 'drizzle_cfa':False, 'drizzle_scale':2, 'pixfrac':0.8, 'method':'mad', 'sigma_low':3., 'sigma_high':3., 'iterations':2,
    'selection_enabled':False, 'selection_percent':100, 'auto_crop':False, 'auto_crop_rotate':False,
    'neutralize_rgb':False, 'neutralize_strength':1.0, 'save_masters':True, 'master_dir':'', 'master_method':'median', 'normalize':True, 'align':True,
    'detection_sigma':5.0, 'control_points':50, 'min_area':5,
    'skip_failed':False, 'cosmetic_sigma':6.0, 'cache_dir':'',
    'motion_enabled':False, 'motion_estimate':True, 'motion_auto':True, 'motion_length':3.0,
    'motion_angle':0.0, 'motion_regularization':.03, 'motion_strength':.7
}
