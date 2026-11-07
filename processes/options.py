"""User-facing processing options and validation, shared by forms and CLI adapters."""
from core.i18n import localize
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class Option:
    name:str
    ru:str
    en:str
    default:object
    minimum:float=0
    maximum:float=1
    step:float=.05
    choices:tuple=()

DEVICE=Option('device','Вычисления','Device','auto',choices=(('Авто','auto'),('CPU','cpu'),('GPU','gpu')))
RC_COMMON=[DEVICE,Option('overlap','Перекрытие блоков','Tile overlap',.2,0,.5,.01),Option('ml_version','Версия ИИ (0 = последняя)','AI version (0 = latest)',0.,0,99,.1)]
SCHEMAS={
 'local:background':[
    Option('strength','Сила коррекции','Correction strength',1.),
    Option('percentile','Доля тёмных участков, %','Dark region fraction, %',40,10,80,5),
    Option('grid','Участков по стороне','Regions per side',8,4,32,1),
    Option('sigma','Исключение звёзд, σ','Star rejection, sigma',2.5,1.,5.,.1)],
 'rcastro:bxt':[
    Option('auto_settings','Автонастройка по изображению','Automatic image-based settings',False),
    Option('sharpen_stars','Резкость звёзд','Sharpen stars',.5,0,.7),
    Option('halos','Ореолы звёзд','Adjust star halos',0.,-.5,.5),
    Option('auto_psf','Авто PSF','Automatic PSF',True),
    Option('psf','Диаметр PSF, пикс.','PSF diameter, pixels',0.,0,8,.1),
    Option('sharpen_nonstellar','Резкость туманности','Sharpen nonstellar',.5),
    Option('correct_only','Только коррекция аберраций','Correct only',False),
    Option('lunar','Луна / планеты','Lunar / planetary',False),*RC_COMMON],
 'rcastro:nxt':[Option('strength','Сила шумоподавления','Denoising strength',90,0,100,1)],
 'rcastro:sxt':[
    Option('stars','Создать слой звёзд','Generate star image',False)],
 'graxpert:background-extraction':[
    Option('method','Метод','Method','AI',choices=(('ИИ','AI'),('RBF · по точкам','RBF'))),
    Option('sample_size','Радиус образца, пикс.','Sample radius, pixels',25,2,100,1),
    Option('kernel','Ядро RBF','RBF kernel','thin_plate',choices=(('Тонкая пластина','thin_plate'),('Линейное','linear'),('Кубическое','cubic'),('Пятой степени','quintic'),('Мультиквадратичное','multiquadric'),('Гауссово','gaussian'),('Обратное','inverse'))),
    Option('smoothing','Сглаживание фона','Smoothing',0.),
    Option('correction','Коррекция','Correction','Subtraction',choices=(('Вычитание','Subtraction'),('Деление','Division'))),
    Option('background','Открыть модель фона','Open background model',False)],
 'graxpert:denoising':[Option('strength','Шумоподавление','Denoising strength',.5)],
 'graxpert:deconv-obj':[Option('strength','Сила деконволюции','Deconvolution strength',.5),Option('psf','Размер PSF','PSF size',5.,.1,20,.1)],
 'graxpert:deconv-stellar':[Option('strength','Сила деконволюции','Deconvolution strength',.5),Option('psf','Размер PSF','PSF size',5.,.1,20,.1)],
 'starnet':[
    Option('mode','Состояние изображения','Image state',0,choices=(('Линейное',0),('Применить предрастяжку',1),('Уже растянуто',2))),
    Option('stars','Создать слой звёзд','Generate star image',True),
    Option('unscreen','Звёзды для режима «Экран»','Unscreen stars',False),
    Option('stride','Шаг обработки, пикс.','Tile stride, pixels',256,2,512,2),
    Option('upsample','Обрабатывать в масштабе 2×','Process at 2× scale',False),
    Option('shadows','Порог теней (MAD)','Shadows clipping (MAD)',-2.8,-20,-.01,.1),
    Option('target','Целевой фон','Target background',.25,.01,.99,.01),
    Option('protect','Защита светов','Protect highlights',True)]}
for key in tuple(SCHEMAS):
    if key.startswith('graxpert:'):
        SCHEMAS[key]+=[Option('gpu','Ускорение GPU','GPU acceleration',True)]
        if not key.endswith('background-extraction'):
            SCHEMAS[key]+=[Option('batch','Параллельных блоков ИИ','AI batch size',4,1,32,1)]
        SCHEMAS[key]+=[Option('model','Версия ИИ (пусто = авто)','AI version (empty = auto)','')]

def values_for(key,values=None):
    if key not in SCHEMAS:raise ValueError(localize('Неизвестный инструмент: ')+key)
    result={o.name:o.default for o in SCHEMAS[key]}
    for option in SCHEMAS[key]:
        value=(values or {}).get(option.name,option.default)
        if option.choices:
            if value not in [v for _,v in option.choices]:raise ValueError(localize(option.ru,option.en)+localize(': недопустимое значение.'))
        elif isinstance(option.default,bool):
            if not isinstance(value,bool):raise ValueError(localize(option.ru,option.en)+localize(': ожидается переключатель.'))
        elif isinstance(option.default,(int,float)):
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not option.minimum<=value<=option.maximum:raise ValueError(localize(option.ru,option.en)+localize(': вне диапазона.'))
            if isinstance(option.default,int) and int(value)!=value:raise ValueError(localize(option.ru,option.en)+localize(': ожидается целое число.'))
        elif not isinstance(value,str):raise ValueError(localize(option.ru,option.en)+localize(': ожидается строка.'))
        result[option.name]=value
    if key=='starnet' and result['stride']%2:raise ValueError(localize('Шаг StarNet должен быть чётным.'))
    if key=='starnet' and not result['stars']:result['unscreen']=False
    if key=='rcastro:bxt' and result['auto_psf']:result['psf']=0.
    return result
