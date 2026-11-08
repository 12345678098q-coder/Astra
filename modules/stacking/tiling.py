"""Bounded tile scheduling shared by calibration and integration."""
from core.i18n import localize
from concurrent.futures import ThreadPoolExecutor
from core.resources import plan_resources,MIB


def tile_rows(shape,frames,workers=1,gpu_free=None):
    plan=plan_resources()
    # Input plus masks, deviations, medians, result and reduction temporaries.
    workspace=8
    budget=min(256*MIB,plan.budget//workspace)
    if gpu_free is not None:budget=min(budget,max(0,int(gpu_free)-256*MIB)//workspace)
    row_bytes=shape[1]*(shape[2] if len(shape)==3 else 1)*max(1,frames)*4
    if row_bytes*workers>budget:
        raise MemoryError(localize('Недостаточно памяти даже для одной строки сложения. Закройте лишние изображения и повторите запуск.'))
    return max(1,min(shape[0],512,budget//(row_bytes*workers)))


def process_tiles(shape,frames,operation,progress,log,phase,gpu=None,gpu_provider=None):
    channels=shape[2] if len(shape)==3 else 1
    plan=plan_resources()
    workers=min(4,plan.threads) if gpu is None and shape[0]*shape[1]*channels*frames>=2_000_000 else 1
    while workers>1:
        try:tile_rows(shape,frames,workers);break
        except MemoryError:workers-=1
    y=0; reported=False
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='astra-tile') as executor:
        while y<shape[0]:
            current_gpu=gpu_provider() if gpu_provider is not None else gpu
            free=current_gpu.cuda.runtime.memGetInfo()[0] if current_gpu is not None else None
            rows=tile_rows(shape,frames,workers,free)
            if not reported:
                log(localize('{0}: автоматический блок {1} строк, параллельных блоков {2}.').format(phase, rows, workers));reported=True
            ends=[]; tasks=[]
            for _ in range(workers):
                if y>=shape[0]:break
                end=min(y+rows,shape[0])
                if workers==1:operation(y,end)
                else:tasks.append(executor.submit(operation,y,end))
                ends.append(end);y=end
            for task in tasks:task.result()
            progress(ends[-1],shape[0],phase)
