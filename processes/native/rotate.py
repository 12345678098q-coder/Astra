"""Rotate an open image and its optional coverage map together."""
import numpy as np
from scipy.ndimage import rotate as nd_rotate,map_coordinates
import math
from modules.stacking.autocrop import crop_bounds,_rotate_mask


def rotate_image(data,coverage,angle,crop=True):
    if not np.isfinite(data).all():raise ValueError('Поворот требует изображение без NaN и бесконечностей.')
    if not np.isfinite(angle) or not -180<=angle<=180:raise ValueError('Угол должен быть от −180° до 180°.')
    quarters=angle/90
    if np.isclose(quarters,round(quarters)):
        turns=int(round(quarters))%4
        output=np.rot90(data,turns).copy()
        covered=np.rot90(coverage,turns).copy() if coverage is not None else None
        return output,covered
    output=nd_rotate(data,angle,axes=(1,0),reshape=True,order=1,prefilter=False,cval=np.nan)
    covered=nd_rotate(coverage,angle,axes=(1,0),reshape=True,order=0,prefilter=False,cval=0) if coverage is not None else None
    if crop:
        footprint=_rotate_mask(np.ones(data.shape[:2],dtype=bool),angle)
        left,top,right,bottom=crop_bounds(footprint)
        output=output[top:bottom,left:right].copy()
        if covered is not None:covered=covered[top:bottom,left:right].copy()
    return output,covered


def crop_rotated(data,coverage,rect,angle):
    """Resample the selected rotated rectangle directly into its output pixels."""
    x,y,width,height=rect
    if width<1 or height<1:raise ValueError('Нарисуйте область кадрирования.')
    if not angle:
        crop=data[y:y+height,x:x+width].copy()
        count=coverage[y:y+height,x:x+width].copy() if coverage is not None else None
        return crop,count
    yy,xx=np.indices((height,width),dtype=np.float64)
    dx=xx-(width-1)/2;dy=yy-(height-1)/2
    center_x=x+(width-1)/2;center_y=y+(height-1)/2
    rad=math.radians(angle);c=math.cos(rad);s=math.sin(rad)
    source_x=center_x+c*dx-s*dy;source_y=center_y+s*dx+c*dy
    inside=(source_x>=0)&(source_y>=0)&(source_x<=data.shape[1]-1)&(source_y<=data.shape[0]-1)
    if data.ndim==2:result=map_coordinates(data,[source_y,source_x],order=1,mode='constant',cval=np.nan)
    else:result=np.stack([map_coordinates(data[...,channel],[source_y,source_x],order=1,mode='constant',cval=np.nan) for channel in range(data.shape[-1])],axis=-1)
    count=None
    if coverage is not None:
        if coverage.ndim==2:count=map_coordinates(coverage,[source_y,source_x],order=0,mode='constant',cval=0)
        else:count=np.stack([map_coordinates(coverage[...,channel],[source_y,source_x],order=0,mode='constant',cval=0) for channel in range(coverage.shape[-1])],axis=-1)
    if not inside.all():
        left,top,right,bottom=crop_bounds(inside)
        result=result[top:bottom,left:right].copy()
        if count is not None:count=count[top:bottom,left:right].copy()
    return result,count
