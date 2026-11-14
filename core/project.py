"""Portable project archive: JSON workspace and lossless NumPy history states."""
from core.i18n import localize
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
import numpy as np
from .history import ImageHistory
from .resources import require_memory

FORMAT='astra-project'
VERSION=1

def validate_workspace(manifest):
    nmb=manifest.get('nebula_mask_builder')
    if nmb is not None:
        if not isinstance(nmb,dict) or not isinstance(nmb.get('visible'),bool) or not isinstance(nmb.get('geometry'),str) or type(nmb.get('class')) is not int or not 0<=nmb['class']<=4 or (nmb.get('target') is not None and (type(nmb['target']) is not int or not 0<=nmb['target']<len(manifest['documents']))):raise ValueError(localize('Некорректное состояние Nebula Mask Builder.'))
    import base64
    from astropy.io import fits
    for key in ('main_geometry','main_state','module_geometry'):base64.b64decode(manifest[key],validate=True)
    for key in ('tools','toolbar'):
        if not isinstance(manifest[key],list) or not all(isinstance(v,str) for v in manifest[key]):raise ValueError(localize('Некорректный список инструментов.'))
    if not isinstance(manifest['settings'],dict) or not isinstance(manifest['stack_options'],dict) or not isinstance(manifest['stack'],dict):raise ValueError(localize('Некорректные настройки проекта.'))
    for name,group in manifest['stack'].items():
        if not isinstance(group,list):raise ValueError(localize('Некорректный список кадров.'))
        for item in group:
            if not isinstance(item['path'],str) or not isinstance(item['checked'],bool) or not isinstance(item['master'],bool):raise ValueError(localize('Некорректный кадр сложения.'))
            weight=item.get('weight',1)
            if not isinstance(weight,(int,float)) or not np.isfinite(weight) or not 0<weight<=1e6:raise ValueError(localize('Некорректный вес кадра.'))
    settings=manifest['settings']
    for key,value in settings.items():
        if not isinstance(key,str) or not isinstance(value,(str,bool,int,float)):raise ValueError(localize('Некорректная настройка.'))
        if key.startswith('astrometry/') and key!='astrometry/executable':
            if not np.isfinite(float(value)):raise ValueError(localize('Некорректная настройка астрометрии.'))
    for key in ('file_presets','tools/pinned'):
        if key in settings:json.loads(settings[key])
    if 'preview_target' in settings and not .05<=float(settings['preview_target'])<=.5:raise ValueError(localize('Некорректная яркость фона.'))
    if 'crop/portrait' in settings and int(settings['crop/portrait']) not in (0,1):raise ValueError(localize('Некорректная ориентация.'))
    for document in manifest['documents']:
        ranges=document.get('preview_ranges',{})
        if not isinstance(ranges,dict):raise ValueError(localize('Некорректные границы отображения.'))
        for token,limits in ranges.items():
            if not isinstance(token,str) or not isinstance(limits,(list,tuple)) or len(limits) not in (2,3) or not all(isinstance(v,(int,float)) for v in limits) or not np.isfinite(limits).all() or limits[1]<=limits[0] or (len(limits)==3 and not 0<=limits[2]<=1000):raise ValueError(localize('Некорректные границы отображения.'))
        points=document.get('graxpert_points',[])
        if not isinstance(points,list) or len(points)>500:raise ValueError(localize('Некорректные точки GraXpert.'))
        for point in points:
            if not isinstance(point,list) or len(point)!=2 or not all(isinstance(v,(int,float)) for v in point) or not np.isfinite(point).all() or min(point)<0:raise ValueError(localize('Некорректная точка GraXpert.'))
        point_shape=document.get('graxpert_points_shape')
        if point_shape is not None and (not isinstance(point_shape,list) or len(point_shape)!=2 or not all(type(v) is int and v>0 for v in point_shape)):raise ValueError(localize('Некорректная геометрия точек GraXpert.'))
        regions=document.get('reference_background_regions',{})
        region_shape=document.get('reference_background_shape')
        if region_shape is not None and (not isinstance(region_shape,list) or len(region_shape)!=2 or not all(type(v) is int and v>0 for v in region_shape)):raise ValueError(localize('Некорректная геометрия сверки HiPS.'))
        if not isinstance(regions,dict):raise ValueError(localize('Некорректные области сверки HiPS.'))
        for kind,rects in regions.items():
            if kind not in ('protect','background') or not isinstance(rects,list) or len(rects)>100:raise ValueError(localize('Некорректные области сверки HiPS.'))
            for rect in rects:
                if not isinstance(rect,list) or len(rect)!=4 or not all(isinstance(v,(int,float)) for v in rect) or not np.isfinite(rect).all() or min(rect[:2])<0 or min(rect[2:])<=0:raise ValueError(localize('Некорректная область сверки HiPS.'))
        group=document.get('view_group')
        if group is not None and (not isinstance(group,str) or len(group)>128):raise ValueError(localize('Некорректная группа окон.'))
        samples=document.get('nebula_samples',[[],[],[],[]])
        if not isinstance(samples,list) or len(samples) not in (4,5):raise ValueError(localize('Некорректные образцы Nebula Mask Builder.'))
        for group in samples:
            if not isinstance(group,list) or len(group)>500:raise ValueError(localize('Слишком много образцов Nebula Mask Builder.'))
            for mark in group:
                if not isinstance(mark,dict) or not all(isinstance(mark.get(k),(int,float)) for k in ('x','y','r')) or not np.isfinite([mark['x'],mark['y'],mark['r']]).all() or not 1<=mark['r']<=200:raise ValueError(localize('Некорректный образец Nebula Mask Builder.'))
        annotations=document.get('annotations',[])
        if not isinstance(annotations,list) or len(annotations)>1000:raise ValueError(localize('Некорректная разметка объектов.'))
        for item in annotations:
            if not isinstance(item['name'],str) or len(item['name'])>1024 or not np.isfinite([item['x'],item['y']]).all():raise ValueError(localize('Некорректная подпись объекта.'))
            points=item['points']
            if points and (len(points)>128 or np.asarray(points).shape!=(len(points),2) or not np.isfinite(points).all()):raise ValueError(localize('Некорректный контур объекта.'))
        options=document.get('annotation_options',{})
        if not isinstance(options,dict) or not 8<=options.get('font',14)<=40 or not isinstance(options.get('color',''),str):raise ValueError(localize('Некорректные настройки подписей.'))
        if not isinstance(document['title'],str):raise ValueError(localize('Некорректное название фото.'))
        for key in ('stretch','auto_stretch','visible','fitted'):
            if not isinstance(document[key],bool):raise ValueError(localize('Некорректные настройки окна.'))
        if document.get('wcs'):fits.Header.fromstring(document['wcs'])
        if document.get('crop') and (len(document['crop'])!=4 or not all(isinstance(v,int) for v in document['crop'])):raise ValueError(localize('Некорректная область кропа.'))

def save_archive(path,manifest,documents,progress=lambda text:None):
    path=Path(path);temporary=None
    try:
        fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.partial',dir=path.parent);os.close(fd);temporary=Path(name)
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for number,document in enumerate(documents):
                history=document['history'];states=[]
                for index,entry in enumerate(history.entries):
                    progress(localize('Изображение {0}/{1}, снимок {2}/{3}').format(number + 1, len(documents), index + 1, len(history.entries)))
                    state={'label':entry['label']}
                    for field in ('token','link_id'):
                        if entry.get(field):state[field]=entry[field]
                    if entry.get('link_number'):state['link_number']=entry['link_number']
                    if entry.get('wcs'):state['wcs']=entry['wcs']
                    for key,array in [('path',document['data']),('count_path',document['count'])]:
                        source=entry[key];member=f'images/{number}/{index}/{key}.npy'
                        if source is not None:archive.write(source,member);state[key]=member
                        elif index==history.index and array is not None:
                            with archive.open(member,'w',force_zip64=True) as output:np.save(output,array,allow_pickle=False)
                            state[key]=member
                        else:state[key]=None
                    if state['path'] is None:raise ValueError(localize('Отсутствует снимок истории.'))
                    states.append(state)
                manifest['documents'][number]['states']=states
                mask=document.get('mask')
                if mask is not None:
                    member=f'images/{number}/mask.npy'
                    with archive.open(member,'w',force_zip64=True) as output:np.save(output,mask,allow_pickle=False)
                    manifest['documents'][number]['mask_member']=member
                    manifest['documents'][number]['mask_enabled']=bool(document.get('mask_enabled',False))
            archive.writestr('project.json',json.dumps({'format':FORMAT,'version':VERSION,**manifest},ensure_ascii=False,allow_nan=False))
        with temporary.open('r+b') as stream:os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def load_archive(path,progress=lambda text:None):
    histories=[]
    try:
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('project.json')
            if info.file_size>16*1024**2:raise ValueError(localize('Слишком большой манифест проекта.'))
            manifest=json.loads(archive.read(info))
            if manifest.get('format')!=FORMAT or manifest.get('version')!=VERSION:raise ValueError(localize('Неподдерживаемый формат проекта.'))
            validate_workspace(manifest)
            documents=manifest['documents']
            if not isinstance(documents,list) or len(documents)>1000:raise ValueError(localize('Некорректный список изображений.'))
            required=sum(archive.getinfo(state[key]).file_size for document in documents for state in document['states'] for key in ('path','count_path') if state.get(key))
            required+=sum(archive.getinfo(document['mask_member']).file_size for document in documents if document.get('mask_member'))
            if required+128*1024**2>shutil.disk_usage(tempfile.gettempdir()).free:raise OSError(localize('Недостаточно места для распаковки истории проекта.'))
            total_memory=0
            for number,document in enumerate(documents):
                progress(localize('Проверка изображения {0}/{1}').format(number + 1, len(documents)))
                states=document['states'];index=document['index']
                if not states or not isinstance(index,int) or not 0<=index<len(states):raise ValueError(localize('Некорректная история.'))
                history=ImageHistory(document['title']);history.directory=tempfile.TemporaryDirectory(prefix='astra-project-history-');history.entries=[];history.index=index;histories.append(history)
                for i,state in enumerate(states):
                    entry={'label':str(state['label'])}
                    for field in ('token','link_id'):
                        if state.get(field) is not None:
                            if not isinstance(state[field],str) or not 1<=len(state[field])<=128:raise ValueError(localize('Некорректная связь снимков истории.'))
                            entry[field]=state[field]
                    if state.get('link_number') is not None:
                        number=state['link_number']
                        if type(number) is not int or not 1<=number<=1000000:raise ValueError(localize('Некорректный номер связи.'))
                        entry['link_number']=number
                    if state.get('wcs') is not None:
                        if not isinstance(state['wcs'],str):raise ValueError(localize('Некорректный заголовок WCS.'))
                        entry['wcs']=state['wcs']
                    for key in ('path','count_path'):
                        member=state[key];entry[key]=None
                        if member is None:
                            if key=='path':raise ValueError(localize('Нет данных изображения.'))
                            continue
                        target=Path(history.directory.name)/f'{i}-{key}.npy'
                        with archive.open(member) as source,target.open('wb') as output:shutil.copyfileobj(source,output,1024*1024)
                        data=np.load(target,allow_pickle=False,mmap_mode='r')
                        if data.dtype.kind not in 'uif' or data.ndim not in (2,3) or min(data.shape)<=0:raise ValueError(localize('Некорректный массив изображения.'))
                        if key=='path' and data.ndim==3 and data.shape[-1] not in (1,3,4):raise ValueError(localize('Некорректное число каналов.'))
                        if i==index:total_memory+=data.nbytes
                        del data;entry[key]=target
                    history.entries.append(entry)
                for key in ('geometry','split'):
                    if not isinstance(document[key],list) or not all(isinstance(v,int) for v in document[key]):raise ValueError(localize('Некорректное расположение окна.'))
                if len(document['geometry'])!=4 or len(document['split'])!=2:raise ValueError(localize('Некорректная геометрия.'))
                if not isinstance(document['strength'],(int,float)) or not 0<=document['strength']<=1000:raise ValueError(localize('Некорректная предрастяжка.'))
                if len(document['offset'])!=2 or not np.isfinite([*document['offset'],document['scale']]).all() or document['scale']<=0:raise ValueError(localize('Некорректный масштаб.'))
                if document.get('mask_member'):
                    target=Path(history.directory.name)/'mask.npy'
                    with archive.open(document['mask_member']) as source,target.open('wb') as output:shutil.copyfileobj(source,output,1024*1024)
                    mask=np.load(target,mmap_mode='r',allow_pickle=False);current=np.load(history.entries[index]['path'],mmap_mode='r',allow_pickle=False)
                    if mask.dtype.kind not in 'fu' or mask.shape!=current.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):raise ValueError(localize('Некорректная маска проекта.'))
                    total_memory+=mask.nbytes;del mask,current;document['_mask_path']=target
            require_memory(total_memory*2,localize('Открытие проекта'))
            loaded=[]
            for document,history in zip(documents,histories):
                data,count=history.restore(history.index);loaded.append({**document,'history':history,'data':data,'count':count,'mask':np.load(document['_mask_path'],allow_pickle=False) if document.get('_mask_path') else None})
        return manifest,loaded
    except Exception:
        for history in histories:history.close()
        raise
