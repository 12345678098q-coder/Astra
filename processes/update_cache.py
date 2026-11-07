"""Persist GitHub API cache and rate-limit cooldown across application restarts."""
from core.i18n import localize
import hashlib,json,os,time,tempfile,urllib.request,urllib.error
from pathlib import Path

def github_json(url,root=None):
    root=Path(root) if root is not None else Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'Astra'/'update-cache'
    path=root/(hashlib.sha256(url.encode()).hexdigest()+'.json');now=time.time();state={}
    try:state=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    if not isinstance(state,dict):state={}
    if state.get('data') is not None and now-state.get('saved',0)<86400:return state['data']
    if state.get('retry_after',0)>now:
        if state.get('data') is not None:return state['data']
        raise RuntimeError(localize('GitHub временно ограничил запросы. Повторная проверка отложена; скачать GraXpert можно по ссылке в настройках.'))
    def save():
        temporary=None
        try:
            root.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(dir=root,suffix='.partial');temporary=Path(name)
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(state,f)
            temporary.replace(path)
        except OSError:pass
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'Astra','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(request,timeout=40) as response:data=json.load(response)
    except urllib.error.HTTPError as error:
        if error.code not in (403,429):raise
        # Preserve a successful previous response. Do not repeatedly hit a limited API.
        retry=now+3600
        try:retry=max(retry,float(error.headers.get('X-RateLimit-Reset',0)),now+float(error.headers.get('Retry-After',0)))
        except (ValueError,TypeError,AttributeError):pass
        state['retry_after']=min(retry,now+86400);save()
        if state.get('data') is not None:return state['data']
        raise RuntimeError(localize('GitHub ограничил запросы (403/429). Проверка отложена; ссылка для ручной установки GraXpert находится в настройках.')) from error
    state={'data':data,'saved':now};save();return data
