from core.i18n import localize
import json
DEFAULTS={'scnr':dict(channel=1,protection='average',amount=1,lightness=True),'lhe':dict(size=64,limit=2,amount=.5,auto=False),'hdr':dict(scale=8,layers=4,amount=.5),'curves':dict(curves={})}
OPERATIONS={**{k:set(v) for k,v in DEFAULTS.items() if k!='linearfit'},'histogram':{'channels'},'color':{'neutral','x','y','width','height','red','green','blue'},'motion':{'length','angle','regularization','strength','auto'},'defects':{'hot','cold','sigma','radius','iterations','bayer','algorithm_version','sample_halo_fraction','sample_auto'}}
def validate(document):
 if not isinstance(document,dict) or document.get('version')!=1 or not isinstance(document.get('steps'),list):raise ValueError(localize('Неподдерживаемая версия последовательности.'))
 if len(document['steps'])>100:raise ValueError(localize('Максимум 100 шагов.'))
 for step in document['steps']:
  if not isinstance(step,dict) or step.get('operation') not in OPERATIONS or not isinstance(step.get('settings'),dict):raise ValueError(localize('Неподдерживаемая операция.'))
  if set(step['settings'])-OPERATIONS[step['operation']]:raise ValueError(localize('Неподдерживаемые параметры.'))
  if type(step.get('enabled',True)) is not bool:raise ValueError(localize('Некорректный флаг включения.'))
 return document
