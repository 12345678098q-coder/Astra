"""Tool messages compatible with log windows created before a code reload."""
import json


def image_info(log,data,label,tr):
    if data is None or not hasattr(data,'shape'):return
    height,width=data.shape[:2]
    channels=data.shape[2] if data.ndim==3 else 1
    log.append(f'{label}: {width} × {height} · '+tr('каналов: ','channels: ')+f'{channels} · {data.dtype}')


def parameters(log,options,tr):
    if not options:return
    log.append(tr('Параметры инструмента','Tool parameters'))
    for key,value in options.items():
        if key.startswith('_'):continue
        text=json.dumps(value,ensure_ascii=False,default=str)
        if len(text)>240:text=text[:237]+'…'
        log.append(f'  {key} = {text}')
