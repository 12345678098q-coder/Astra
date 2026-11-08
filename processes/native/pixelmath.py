"""Restricted AST interpreter; no eval, exec, attribute traversal or imports."""
from core.i18n import localize
import ast
import numpy as np
from .processing import image,luminance

FUNCTIONS={'min':2,'max':2,'clip':3,'abs':1,'sqrt':1}

def compile_formula(formula,images):
    if len(formula)>2000:raise ValueError(localize('Слишком длинная формула.'))
    try:tree=ast.parse(formula,mode='eval')
    except SyntaxError as error:raise ValueError(localize('Синтаксис формулы: ')+str(error))
    if len(list(ast.walk(tree)))>128:raise ValueError(localize('Формула слишком сложная.'))
    used=set()
    def check(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            try:
                if np.isfinite(float(node.value)):return
            except (OverflowError,ValueError):pass
            raise ValueError(localize('Число вне допустимого диапазона.'))
        if isinstance(node,ast.Name) and node.id in images:used.add(node.id);return
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id in images and node.attr in ('R','G','B','L'):
            used.add(node.value.id)
            if node.attr!='L' and images[node.value.id].ndim!=3:raise ValueError(localize('Канал RGB требует цветного фото.'))
            return
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            check(node.left);check(node.right);return
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):check(node.operand);return
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS and len(node.args)==FUNCTIONS[node.func.id] and not node.keywords:
            for arg in node.args:check(arg)
            return
        raise ValueError(localize('Недопустимое выражение или имя.'))
    check(tree.body)
    shapes={image(images[key]).shape[:2] for key in used}
    if len(shapes)>1:raise ValueError(localize('Размеры изображений различаются.'))
    return tree.body,used

def calculate(formula,images,default_shape=None,channel=None):
    tree,used=compile_formula(formula,images)
    def pair(a,b):
        if np.ndim(a)==2 and np.ndim(b)==3:a=a[...,None]
        if np.ndim(b)==2 and np.ndim(a)==3:b=b[...,None]
        return a,b
    def run(node):
        if isinstance(node,ast.Constant):return float(node.value)
        if isinstance(node,ast.Name):
            value=images[node.id].astype(np.float64,copy=False)
            return (luminance(value) if channel=='L' else value[...,channel]) if channel is not None and value.ndim==3 else value
        if isinstance(node,ast.Attribute):
            a=images[node.value.id];return luminance(a) if node.attr=='L' else a[...,'RGB'.index(node.attr)].astype(np.float64,copy=False)
        if isinstance(node,ast.UnaryOp):return -run(node.operand) if isinstance(node.op,ast.USub) else run(node.operand)
        if isinstance(node,ast.BinOp):
            a,b=pair(run(node.left),run(node.right))
            if isinstance(node.op,ast.Div):
                if np.any(np.asarray(b)==0):raise ValueError(localize('Деление на ноль.'))
                return a/b
            return a+b if isinstance(node.op,ast.Add) else a-b if isinstance(node.op,ast.Sub) else a*b
        args=[run(arg) for arg in node.args];name=node.func.id
        if name=='abs':return np.abs(args[0])
        if name=='sqrt':
            if np.any(np.asarray(args[0])<0):raise ValueError(localize('Корень из отрицательного значения.'))
            return np.sqrt(args[0])
        a,b=pair(args[0],args[1])
        if name=='min':return np.minimum(a,b)
        if name=='max':return np.maximum(a,b)
        a,c=pair(a,args[2]);b,c=pair(b,c)
        if np.any(b>c):raise ValueError(localize('Нижняя граница выше верхней.'))
        return np.minimum(np.maximum(a,b),c)
    with np.errstate(over='raise',invalid='ignore',divide='raise'):
        try:result=np.asarray(run(tree),dtype=np.float64)
        except FloatingPointError:raise ValueError(localize('Переполнение чисел.'))
    if result.ndim==0:
        shape=images[next(iter(used))].shape if used else default_shape
        if shape is None:raise ValueError(localize('Откройте фото для размера результата.'))
        result=np.full(shape,result,dtype=np.float64)
    return image(result).copy()


def _evaluate_full(images,settings,target_shape=None):
    """All expressions read the same immutable input images."""
    single=settings.get('single',True);space=settings.get('space','same')
    if space not in ('same','rgb','mono'):raise ValueError(localize('Некорректное пространство.'))
    formulas=[settings.get('formula','T')] if single else [settings.get('formula','T'),settings.get('green','T'),settings.get('blue','T')]
    alpha=settings.get('alpha','').strip();used=set()
    for text in formulas+([alpha] if alpha else []):
        _,names=compile_formula(text,images);used.update(names)
    sizes={images[name].shape[:2] for name in used}
    if len(sizes)>1:raise ValueError(localize('Размеры изображений различаются.'))
    shape=target_shape or (images[next(iter(used))].shape if used else None)
    if shape is None:raise ValueError(localize('Откройте целевое изображение.'))
    spatial=next(iter(sizes),shape[:2]);channels=3 if not single or space=='rgb' else 1 if space=='mono' else (shape[-1] if len(shape)==3 else 1)
    if single:
        result=calculate(formulas[0],images,spatial if channels==1 else (*spatial,3))
        if space=='mono' and result.ndim==3:result=luminance(result)
        elif space=='rgb' and result.ndim==2:result=np.repeat(result[...,None],3,axis=2)
    else:
        if space=='mono':raise ValueError(localize('Раздельные формулы требуют пространства RGB.'))
        result=np.stack([calculate(text,images,spatial,channel=c) for c,text in enumerate(formulas)],axis=-1)
    mask=None
    if alpha:
        mask=calculate(alpha,images,spatial,channel='L')
        if mask.ndim!=2 or mask.shape!=result.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):raise ValueError(localize('A должна быть конечной моно-маской в диапазоне 0…1.'))
    return result,mask


def evaluate_expressions(images,settings,target_shape=None,cancel=lambda:False,progress=lambda n,t:None):
    from .processing import block_rows,output_image
    from core.disk_image import disk_array
    used=set()
    for text in ([settings.get('formula','T')] if settings.get('single',True) else [settings.get('formula','T'),settings.get('green','T'),settings.get('blue','T')])+([settings['alpha']] if settings.get('alpha','').strip() else []):
        _,names=compile_formula(text,images);used.update(names)
    selected={key:images[key] for key in used}
    sizes={a.shape[:2] for a in selected.values()}
    if len(sizes)>1:raise ValueError(localize('Размеры изображений различаются.'))
    shape=target_shape or (next(iter(selected.values())).shape if selected else None)
    if shape is None:raise ValueError(localize('Откройте целевое изображение.'))
    height=next(iter(sizes),shape[:2])[0]
    rows=block_rows(next(iter(selected.values()))) if selected else 64
    result=mask=None
    for top in range(0,height,rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        end=min(top+rows,height);stripe={k:a[top:end] for k,a in selected.items()}
        value,weight=_evaluate_full(stripe,settings,(end-top,*shape[1:]))
        if result is None:
            result=disk_array((height,*value.shape[1:]))
            if weight is not None:mask=disk_array((height,*weight.shape[1:]))
        result[top:end]=value
        if weight is not None:mask[top:end]=weight
        progress(end,height)
    return result,mask


def image_names(titles):
    """Readable, unique Python identifiers for displayed document titles."""
    import re,keyword,unicodedata
    from pathlib import Path
    result=[];used=set(FUNCTIONS)
    for title in titles:
        text=unicodedata.normalize('NFKC',str(title))
        if Path(text).suffix.lower() in ('.fits','.fit','.fts','.tif','.tiff','.xisf','.png','.jpg','.jpeg'):text=Path(text).stem
        base=re.sub(r'\W','_',text,flags=re.UNICODE) or 'image'
        if not base.isidentifier() or keyword.iskeyword(base):base='img_'+base
        name=base;number=2
        while name in used:name=base+'_'+str(number);number+=1
        used.add(name);result.append(name)
    return result
