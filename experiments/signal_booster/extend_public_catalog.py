"""Index additional Moana RGB archives, retaining attribution and calibration URLs."""
from concurrent.futures import ThreadPoolExecutor
import html
import re
import urllib.request

from prepare_selection5000 import OUT, COLORS, RemoteZip, read, write_json, zipfile

PAGES = {
    'Baby Eagle': 'https://erellaz.com/moana/open-datasets/baby-eagle/',
    'Horse Head': 'https://erellaz.com/moana/horse-head-nebula/',
    'M8': 'https://erellaz.com/moana/open-datasets/lagoon-nebula/',
    'M16': 'https://erellaz.com/moana/open-datasets/m16/',
    'Rosette': 'https://erellaz.com/moana/open-datasets/rosette-nebula/',
    'Cocoon': 'https://erellaz.com/moana/open-datasets/cocoon/',
    'Tulip': 'https://erellaz.com/moana/open-datasets/tulip-nebula/',
    'Helix': 'https://erellaz.com/moana/open-datasets/helix/',
    'M1': 'https://erellaz.com/moana/open-datasets/m1/',
    'M57': 'https://erellaz.com/moana/open-datasets/m57/',
    'IC443': 'https://erellaz.com/moana/open-datasets/ic-443/',
    'M15': 'https://erellaz.com/moana/open-datasets/m15/',
    'NGC6888': 'https://erellaz.com/moana/open-datasets/crescent-nebula/',
    'M2': 'https://erellaz.com/moana/open-datasets/m2-2/',
    'Clusters': 'https://erellaz.com/moana/open-datasets/cluster-galore/',
}


def page_jobs(item):
    field,page = item
    try:
        with urllib.request.urlopen(page,timeout=45) as response:
            markup=response.read().decode('utf-8')
        urls=list(dict.fromkeys(html.unescape(url) for url in re.findall(r'https://[^\s"<>]+\.zip',markup,re.I)))
        calibration='calibration_new' if any('2023-10-01' in url for url in urls) else 'calibration'
        jobs=[]
        for url in urls:
            name=url.rsplit('/',1)[-1].lower()
            if any(part in name for part in ('calibration','_nb','_sho','_ha','_sii','_oiii')):
                continue
            tile=('_tile2' if '_t2' in name else '_tile1') if field=='M8' else ''
            name_field = field
            if field=='Clusters':
                name_field=next(cluster for cluster in ('M5','M13','M92') if re.search(cluster.lower()+r'[_\.]',name))
            jobs.append(dict(field=name_field+tile,page=page,url=url,calibration=calibration))
        return jobs
    except Exception as error:
        print('PAGE ERROR',field,str(error),flush=True)
        return []


def index(job):
    try:
        with zipfile.ZipFile(RemoteZip(job['url'])) as archive:
            names=[name for name in archive.namelist() if name.lower().endswith(('.fit','.fits'))]
        colors={color:[name for name in names if re.search('_('+color+'|'+color[0]+')_',name,re.I)] for color in COLORS}
        if not sum(map(len,colors.values())):
            return None
        print('INDEXED',job['field'],sum(map(len,colors.values())),flush=True)
        return dict(job,colors=colors,credit='Moana Project',license='CC BY 4.0')
    except Exception as error:
        print('ARCHIVE ERROR',job['url'],str(error),flush=True)
        return None


if __name__=='__main__':
    current=read(OUT/'catalog.json')
    known={row['url'] for row in current}
    with ThreadPoolExecutor(4) as pool:
        jobs=[job for batch in pool.map(page_jobs,PAGES.items()) for job in batch if job['url'] not in known]
    with ThreadPoolExecutor(5) as pool:
        extra=[row for row in pool.map(index,jobs) if row]
    write_json(OUT/'extended_sources.json',extra)
    write_json(OUT/'catalog.json',current+extra)
    print('EXTRA FRAMES',sum(sum(map(len,row['colors'].values())) for row in extra),flush=True)
