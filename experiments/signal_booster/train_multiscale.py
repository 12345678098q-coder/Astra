"""Train the multiscale model from prepared stack records; does not install it in Astra."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from functools import lru_cache
from filelock import FileLock
from structure_guard import teacher_fine_loss,retention_penalty
from detail_recovery import fine_detail_loss,fine_shape_loss,response_tensor
from contrast_response import star_mask
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from scipy.ndimage import gaussian_filter
from multiscale import HALO, SignalBoosterRGB, enhance, load_checkpoint, statistics, write_checkpoint,colour_preserving_correction
from noise_compat import compatibility_loss,VERSION as COMPATIBILITY_VERSION


@lru_cache(maxsize=None)
def image(path, checksum):
    file = Path(path)
    if hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
        raise ValueError(f'Stack checksum changed: {file}')
    with np.load(file, allow_pickle=False) as data:
        pixels = data['image']
    if pixels.ndim==2:
        pixels=np.repeat(pixels[...,None],3,axis=2)
    if pixels.ndim != 3 or pixels.shape[2] != 3 or not np.isfinite(pixels).all():
        raise ValueError(f'Invalid linear RGB stack: {file}')
    return pixels


def pixels(level):
    return image(level['path'], level['file_sha256'])


@lru_cache(maxsize=None)
def median(path, checksum):
    return np.median(image(path, checksum), axis=(0,1))


@lru_cache(maxsize=None)
def background_plane(first_path,first_checksum,last_path,last_checksum):
    """Fit only a smooth additive sky change; keep local image structures intact."""
    first=image(first_path,first_checksum)
    difference=image(last_path,last_checksum)-first
    height,width=first.shape[:2]
    samples=[]
    values=[]
    for rows in np.array_split(np.arange(height),12):
        for columns in np.array_split(np.arange(width),12):
            y,x=float(np.mean(rows)),float(np.mean(columns))
            samples.append((1,x/(width-1)*2-1,y/(height-1)*2-1))
            values.append(np.median(difference[rows[0]:rows[-1]+1,columns[0]:columns[-1]+1],axis=(0,1)))
    design=np.asarray(samples,dtype='f8')
    values=np.asarray(values,dtype='f8')
    coefficients=[]
    for channel in range(3):
        keep=np.ones(len(values),dtype=bool)
        for _ in range(4):
            fit=np.linalg.lstsq(design[keep],values[keep,channel],rcond=None)[0]
            residual=values[:,channel]-design@fit
            center=np.median(residual)
            scatter=1.4826*np.median(abs(residual-center))
            if scatter<=np.finfo(float).eps:
                break
            proposed=abs(residual-center)<=3*scatter
            if proposed.sum()<len(values)//2:
                break
            keep=proposed
        coefficients.append(fit)
    return np.asarray(coefficients,dtype='f4')


@lru_cache(maxsize=None)
def structure_positions(path, checksum, core=32):
    data=image(path,checksum)
    offset,scale=statistics(data)
    luminance=((data-offset)/scale).mean(axis=2)
    diffuse=gaussian_filter(luminance,4)-gaussian_filter(luminance,16)
    side=2*HALO+core
    candidates=[]
    scores=[]
    for y in range(0,data.shape[0]-side+1,32):
        for x in range(0,data.shape[1]-side+1,32):
            tile=diffuse[y+HALO:y+HALO+core,x+HALO:x+HALO+core]
            candidates.append((y,x))
            scores.append(float(np.mean(tile**2)))
    # Sample useful spatial contrast while retaining uniform patches separately.
    scores=np.asarray(scores)
    lower,upper=np.percentile(scores,[50,95])
    return np.asarray(candidates)[(scores>=lower)&(scores<=upper)]


def objective(output,target,input_tensor,fraction,spatial=False,detail=False,weak_focus=False,coarse_identity=False,
              retain_structure=False,diffuse_weight=.5,retention_one_sided=False):
    active=(fraction>0).expand_as(output)[...,HALO:-HALO,HALO:-HALO]
    stars=None
    if weak_focus:
        luminance=input_tensor.mean(dim=1,keepdim=True)
        contrast=luminance-F.avg_pool2d(luminance,17,stride=1,padding=8)
        stars=F.max_pool2d((contrast>8).float(),7,stride=1,padding=3)>0
        stars=stars.expand_as(output)[...,HALO:-HALO,HALO:-HALO]
    def distance(a,b):
        errors=F.huber_loss(a[...,HALO:-HALO,HALO:-HALO],
                            b[...,HALO:-HALO,HALO:-HALO],delta=3,reduction='none')
        selected=active if stars is None else active & ~stars
        return errors[selected].mean() if selected.any() else errors.sum()*0
    loss=distance(output,target)
    if stars is not None and (active & stars).any():
        identity=F.huber_loss(output[...,HALO:-HALO,HALO:-HALO],
            input_tensor[...,HALO:-HALO,HALO:-HALO],delta=3,reduction='none')
        loss=loss+.1*identity[active & stars].mean()
    if spatial:
        output5=F.avg_pool2d(output,5,stride=1,padding=2)
        target5=F.avg_pool2d(target,5,stride=1,padding=2)
        output17=F.avg_pool2d(output,17,stride=1,padding=8)
        target17=F.avg_pool2d(target,17,stride=1,padding=8)
        loss=loss+.5*distance(output-output5,target-target5)
        loss=loss+diffuse_weight*distance(output5-output17,target5-target17)
    if detail:
        correction=(output-input_tensor)[...,HALO:-HALO,HALO:-HALO]
        loss=loss+(.1 if spatial else 1.)*correction.mean(dim=(-2,-1)).square().mean()
    if coarse_identity:
        smooth=F.avg_pool2d(output-input_tensor,17,stride=1,padding=8)
        loss=loss+3*smooth[...,HALO:-HALO,HALO:-HALO].square().mean()
    if retain_structure:
        # R is independent of A when --independent-loss is active. Matching
        # covariance with R protects real contrast; reducing variance alone
        # cannot satisfy this constraint. Ignore unsupported/noisy covariance.
        def core(t):return t[...,HALO:-HALO,HALO:-HALO]
        keep=active if stars is None else active & ~stars
        weights=keep.float()
        count=weights.sum(dim=(0,2,3)).clamp_min(1)
        def centered(t):
            t=core(t)
            return t-(t*weights).sum(dim=(0,2,3))[None,:,None,None]/count[None,:,None,None]
        def pool(t,n):return F.avg_pool2d(t,n,stride=1,padding=n//2)
        in5,in17=pool(input_tensor,5),pool(input_tensor,17)
        out5,out17=pool(output,5),pool(output,17)
        ref5,ref17=pool(target,5),pool(target,17)
        for source,predicted,reference in ((input_tensor-in5,output-out5,target-ref5),
                                            (in5-in17,out5-out17,ref5-ref17)):
            source,predicted,reference=map(centered,(source,predicted,reference))
            signal=(source*reference*weights).sum(dim=(0,2,3))/count
            power=(source.square()*weights).sum(dim=(0,2,3))/count
            floor=(.02*power).clamp_min(1e-6)
            supported=signal>floor
            change=((predicted-source)*reference*weights).sum(dim=(0,2,3))/count
            relative=change/signal.detach().clamp_min(floor.detach())
            penalty=F.relu((-relative if retention_one_sided else relative.abs())-(.002 if retention_one_sided else .01)).square()
            if supported.any():loss=loss+20*penalty[supported].mean()
    return loss


def groups(path, split,deep_pairs=False,minimum_ratio=1.):
    records = json.loads(path.read_text(encoding='utf-8'))
    fields = []
    for record in records:
        if record['split'] != split:
            continue
        pairs = []
        level_pairs=list(zip(record['levels'],record['levels'][1:]))
        if deep_pairs and len(record['levels'])>2:
            level_pairs.extend((short,record['levels'][-1]) for short in record['levels'][:-2])
        for short, deep in level_pairs:
            times = short['actual_seconds']
            for channel in times:
                first=short['frames'][channel]
                last=deep['frames'][channel]
                if [row['sha256'] for row in first] != [row['sha256'] for row in last[:len(first)]]:
                    raise ValueError('Expected cumulative stacks with nested source exposures')
                for level,rows in ((short,first),(deep,last)):
                    if sum(row['seconds'] for row in rows)!=level['actual_seconds'][channel]:
                        raise ValueError('Stack exposure time differs from source ledger')
            ratio = np.array([deep['actual_seconds'][c]/times[c] for c in ('Red','Green','Blue')],dtype='f4') if 'Red' in times else np.repeat(np.float32(deep['actual_seconds']['image']/times['image']),3)
            if np.min(ratio[ratio>1],initial=float('inf'))<minimum_ratio:continue
            a,b = pixels(short),pixels(deep)
            if a.shape!=b.shape or (ratio<1).any() or np.all(ratio==1):
                raise ValueError('Inconsistent cumulative pair')
            if min(a.shape[:2]) < 2*HALO+32:
                raise ValueError('Insufficient common area for training')
            pairs.append((short,deep,ratio,statistics(a)))
        if pairs:
            fields.append(pairs)
    if not fields:
        raise ValueError(f'No {split} objects in {path}')
    return fields


def validate(model, fields, detail_objective=False, spatial=False,noise_compat=False,compat_weight=1.,teacher=None,structure_priority=0.,fine_validation=False,shape_validation=False):
    scores=[]
    for field in fields:
        field_scores=[]
        for short, deep, ratio, (offset,scale) in field:
            a,b=pixels(short),pixels(deep)
            predicted=enhance(a,model,exposure_ratio=ratio)
            active=ratio>1
            fraction=1/ratio[active]
            ref=(b[...,active]-a[...,active]*fraction)/(1-fraction)
            if detail_objective:
                ref = ref - np.median(ref,axis=(0,1)) + np.median(a[...,active],axis=(0,1))
            initial=np.mean((a[...,active]-ref).astype('f8')**2)
            if initial<=0:
                raise ValueError('Degenerate validation pair')
            if fine_validation:
                def fine(data):
                    return (gaussian_filter(data,(1,1,0))-gaussian_filter(data,(4,4,0)))[32:-32,32:-32]/scale[active]
                expected=fine(ref)
                keep=star_mask(a,scale)[32:-32,32:-32]<.5
                before=np.mean((fine(a[...,active])-expected)[keep].astype('f8')**2)
                after=np.mean((fine(predicted[...,active])-expected)[keep].astype('f8')**2)
                if shape_validation:
                    original_band=fine(a[...,active])[keep].astype('f8')
                    predicted_band=fine(predicted[...,active])[keep].astype('f8')
                    reference_band=expected[keep].astype('f8')
                    for v in (original_band,predicted_band,reference_band):v-=v.mean(axis=0)
                    signal=float((original_band*reference_band).mean())
                    cross=float((predicted_band*reference_band).mean())
                    power=float(np.mean(predicted_band**2)*np.mean(reference_band**2))
                    correlation=cross/np.sqrt(max(power,1e-30))
                    input_correlation=signal/np.sqrt(max(float(np.mean(original_band**2)*np.mean(reference_band**2)),1e-30))
                    retention=max(.99-cross/signal,0.)**2 if input_correlation>.01 else 0.
                    field_scores.append(float(1-correlation+retention))
                else:field_scores.append(float(after/before))
            elif spatial:
                band_scores=[]
                for low,high in ((1,4),(4,16)):
                    def band(data):
                        return (gaussian_filter(data,(low,low,0))-gaussian_filter(data,(high,high,0)))[32:-32,32:-32]
                    expected=band(ref)
                    baseline=np.mean((band(a[...,active])-expected).astype('f8')**2)
                    band_scores.append(float(np.mean((band(predicted[...,active])-expected).astype('f8')**2)/baseline))
                field_scores.append(float(np.mean(band_scores)))
            else:
                field_scores.append(float(np.mean((predicted[...,active]-ref).astype('f8')**2)/initial))
            if noise_compat:
                size=2*HALO+128
                patches=[[],[],[]]
                # Frozen spatial grid, never rescale the source images.
                for y in np.linspace(0,a.shape[0]-size,3,dtype=int):
                    for x in np.linspace(0,a.shape[1]-size,3,dtype=int):
                        for items,data in zip(patches,(predicted,a,ref)):
                            items.append(((data[y:y+size,x:x+size]-offset)/scale).transpose(2,0,1).copy())
                device=next(model.parameters()).device
                with torch.no_grad():
                    tensors=[torch.from_numpy(np.stack(items)).to(device) for items in patches]
                    off=torch.as_tensor(offset,device=device)[None,:,None,None]
                    sc=torch.as_tensor(scale,device=device)[None,:,None,None]
                    penalty,_=compatibility_loss(*tensors,off,sc)
                    field_scores[-1]+=compat_weight*float(penalty.cpu())
            if teacher is not None and structure_priority:
                teacher_output=enhance(a,teacher,exposure_ratio=ratio)
                penalty,_=retention_penalty(a,predicted,teacher_output,ref,scale)
                field_scores[-1]+=structure_priority*penalty
        scores.append(float(np.mean(field_scores)))
    if spatial:
        return max(scores)
    return float(np.mean(scores))


@torch.inference_mode()
def diagnose(model, fields, device):
    """Exercise real inputs and conditioning without gradients or an optimizer."""
    size=2*HALO+32
    examples=[]
    model.eval()
    for field in fields:
        short,deep,ratio,(offset,scale)=field[0]
        data=pixels(short)
        y,x=[(length-size)//2 for length in data.shape[:2]]
        patch=((data[y:y+size,x:x+size]-offset)/scale).transpose(2,0,1).copy()
        tensor=torch.from_numpy(patch)[None].to(device)
        fraction=torch.from_numpy(1-1/ratio)[None,:,None,None].to(device)
        delta=.5*model(tensor,fraction)
        zero=model(tensor,torch.zeros_like(fraction))
        if not torch.isfinite(delta).all() or torch.count_nonzero(zero).item():
            raise ValueError('Invalid forward pass or zero-boost conditioning')
        center=delta[0,:,HALO:-HALO,HALO:-HALO].cpu().numpy()
        examples.append(dict(short=short['path'],ratio=ratio.tolist(),
            correction_std_noise_units=center.std(axis=(1,2)).tolist(),
            correction_max_noise_units=np.max(abs(center),axis=(1,2)).tolist()))
    return examples


def train(args):
    global HALO
    HALO=args.training_halo
    if args.train_through_response and HALO<160:
        raise ValueError('Training through the 16px spatial response requires a 160px context halo')
    frozen_training_sha=hashlib.sha256(args.records.read_bytes()).hexdigest()
    frozen_validation_sha=hashlib.sha256(args.validation.read_bytes()).hexdigest()
    if args.compat_weight<=0:raise ValueError('Positive compatibility weight required')
    if args.retain_structure and not args.independent_loss:
        raise ValueError('Structure retention requires an independent remainder target')
    if args.noise_compat and not args.independent_loss:
        raise ValueError('Noise compatibility requires an independent remainder target')
    if args.steps<1 or args.batch<1 or args.check_every<1:
        raise ValueError('Positive training settings required')
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.diagnose_only and args.output.suffix!='.json':
        raise ValueError('Diagnostic output must be a JSON report')
    torch.manual_seed(args.seed)
    torch.set_num_threads(4)
    rng=np.random.default_rng(args.seed)
    training=groups(args.records,'train_candidate',args.deep_pairs,args.minimum_reference_ratio)
    validation=groups(args.validation,'validation')
    manifest_records=json.loads(args.records.read_text(encoding='utf-8'))
    long_paths={r['levels'][0]['path'] for r in manifest_records if r.get('object_available_hours',0)>=args.long_threshold_hours}
    field_weights=np.asarray([args.long_weight if field[0][0]['path'] in long_paths else 1. for field in training],dtype='f8')
    field_weights/=field_weights.sum()
    def identities(fields, key):
        return {f[key] for field in fields for _,deep,_,_ in field for channel in deep['frames'].values() for f in channel}
    for key in ('sha256','object'):
        if identities(training,key) & identities(validation,key):
            raise ValueError(f'Train/validation overlap: {key}')
    declared_new={f['sha256'] for field in training for _,deep,_,_ in field
                  for frames in deep['frames'].values() for f in frames if f.get('new_to_model')}
    device=torch.device(args.device)
    model=load_checkpoint(args.initial, device)[0] if args.initial else SignalBoosterRGB().to(device)
    if (model.structure_response_enabled or any(model.structure_gains)) and not args.train_through_response:
        raise ValueError('Train from the raw neural checkpoint, then refit the spatial contrast response. Its coefficients are not part of the differentiable training forward pass.')
    if args.train_through_response and not model.structure_response_enabled:
        raise ValueError('Training through the response requires a calibrated initial model')
    if args.fine_detail_weight<0 or args.fine_shape_weight<0:raise ValueError('Nonnegative fine-detail weights required')
    if args.shape_validation and not args.fine_validation:raise ValueError('Shape validation requires fine-validation')
    teacher=None
    if args.teacher_fine_weight:
        if not args.initial:raise ValueError('Fine preservation requires a retained teacher checkpoint')
        teacher=load_checkpoint(args.teacher_checkpoint or args.initial,device)[0].eval()
        for parameter in teacher.parameters():parameter.requires_grad_(False)
    if args.preserve_colour:model.preserve_colour=True
    if args.residual_limit is not None:
        if not 0<args.residual_limit<=12:raise ValueError('Residual limit must be in (0,12]')
        model.residual_limit=args.residual_limit
    if args.diagnose_only:
        examples=diagnose(model,training,device)
        args.output.write_text(json.dumps(dict(mode='forward_only',optimizer_steps=0,
            training_frames=len(identities(training,'sha256')),training_fields=len(training),
            validation_fields=len(validation),parameters=sum(p.numel() for p in model.parameters()),
            examples=examples),indent=2),encoding='utf-8')
        print('FORWARD ONLY',len(examples),'fields, 0 optimizer steps',flush=True)
        return
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr)
    if args.precision!='fp32' and device.type!='cuda':
        raise ValueError('Mixed precision training requires CUDA')
    scaler=torch.amp.GradScaler('cuda',enabled=args.precision=='fp16',init_scale=1024.)
    initial_validation=validate(model.eval(),validation,args.detail_objective,
                                args.structure_objective or args.validation_spatial,args.noise_compat,args.compat_weight,teacher,args.structure_priority,args.fine_validation,args.shape_validation)
    print('INITIAL VALIDATION',initial_validation,flush=True)
    size=2*HALO+args.patch_core
    history=[]
    best=float('inf')
    seen_pairs=set()
    optimizer_steps=0
    used_frames=set()
    coverage=[pair for field in training for pair in field]
    coverage=[coverage[index] for index in rng.permutation(len(coverage))]
    coverage_index=0
    for step in range(1,args.steps+1):
        model.train()
        inputs,targets,fractions=[],[],[]
        offsets,scales=[],[]
        batch_pairs={}
        for _ in range(args.batch):
            field=training[rng.choice(len(training),p=field_weights)]
            if coverage_index<len(coverage):
                pair=coverage[coverage_index]
                coverage_index+=1
            else:
                pair=field[rng.integers(len(field))]
            short,deep,ratio,(offset,scale)=pair
            pair_key=(short['path'],deep['path'])
            batch_pairs[pair_key]={row['sha256'] for rows in deep['frames'].values() for row in rows}
            a,b=pixels(short),pixels(deep)
            y,x=[int(rng.integers(n-size+1)) for n in a.shape[:2]]
            if args.structure_objective and rng.random()<.5:
                positions=structure_positions(short['path'],short['file_sha256'],args.patch_core)
                if len(positions):
                    y,x=positions[rng.integers(len(positions))]
            def patch(arr):
                return ((arr[y:y+size,x:x+size]-offset)/scale).transpose(2,0,1)
            input_patch=patch(a)
            target_patch=patch(b)
            if args.background_plane:
                coefficients=background_plane(short['path'],short['file_sha256'],deep['path'],deep['file_sha256'])
                yy=np.arange(y,y+size,dtype='f4')/(a.shape[0]-1)*2-1
                xx=np.arange(x,x+size,dtype='f4')/(a.shape[1]-1)*2-1
                plane=(coefficients[:,0,None,None]+coefficients[:,1,None,None]*xx[None,None,:]
                       +coefficients[:,2,None,None]*yy[None,:,None])
                target_patch-=plane/scale[:,None,None]
            elif args.detail_objective:
                target_patch -= ((median(deep['path'],deep['file_sha256'])-median(short['path'],short['file_sha256']))/scale)[:,None,None]
            if args.structure_objective:
                turns=int(rng.integers(4))
                input_patch=np.rot90(input_patch,turns,axes=(1,2))
                target_patch=np.rot90(target_patch,turns,axes=(1,2))
                if rng.random()<.5:
                    input_patch=input_patch[:,:,::-1]
                    target_patch=target_patch[:,:,::-1]
            inputs.append(input_patch.copy())
            targets.append(target_patch)
            fractions.append(1-1/ratio)
            offsets.append(offset)
            scales.append(scale)
        x,target,frac=[torch.from_numpy(np.stack(z)).to(device) for z in (inputs,targets,fractions)]
        context=(torch.autocast('cuda',dtype=torch.float16 if args.precision=='fp16' else torch.bfloat16)
                 if args.precision!='fp32' else nullcontext())
        with context:
            correction=model(x,frac[:,:,None,None])
        if model.preserve_colour:
            off=torch.from_numpy(np.stack(offsets)).to(device)[:,:,None,None]
            sc=torch.from_numpy(np.stack(scales)).to(device)[:,:,None,None]
            correction=colour_preserving_correction(x,correction.float(),off,sc)
        output=x+.5*correction.float()
        stars_tensor=None
        if args.train_through_response or args.fine_detail_weight or args.fine_shape_weight:
            masks=[star_mask(p.transpose(1,2,0)*s+o,s)[None] for p,s,o in zip(inputs,scales,offsets)]
            stars_tensor=torch.from_numpy(np.stack(masks)).to(device)
        if args.train_through_response:
            off=torch.from_numpy(np.stack(offsets)).to(device)[:,:,None,None]
            sc=torch.from_numpy(np.stack(scales)).to(device)[:,:,None,None]
            physical=response_tensor(output*sc+off,x*sc+off,sc,model.structure_gains,stars_tensor,
                                     (frac.mean(dim=1,keepdim=True)[:,:,None,None]/.5).clamp(0,1))
            output=(physical-off)/sc
        delivered=output
        fine_teacher_penalty=None
        if teacher is not None:
            with torch.no_grad(),(torch.autocast('cuda',dtype=torch.bfloat16) if args.precision!='fp32' else nullcontext()):
                teacher_delta=teacher(x,frac[:,:,None,None])
            if teacher.preserve_colour:
                teacher_delta=colour_preserving_correction(x,teacher_delta.float(),off,sc)
            teacher_output=x if args.teacher_input else x+.5*teacher_delta.float()
            fine_teacher_penalty=teacher_fine_loss(delivered,teacher_output,HALO,args.teacher_envelope)
        fraction=frac[:,:,None,None]
        if args.independent_loss:
            # B=(1-f)A+fR for nested weighted means. Train the clean correction
            # against disjoint remainder R; inference still returns A+f*correction.
            safe_fraction=fraction.clamp_min(1e-6)
            output=x+(output-x)/safe_fraction
            target=x+(target-x)/safe_fraction
        loss=objective(output,target,x,fraction,
                       spatial=args.structure_objective,detail=args.detail_objective,
                       weak_focus=args.weak_focus,coarse_identity=args.coarse_identity,
                       retain_structure=args.retain_structure,diffuse_weight=args.diffuse_weight,retention_one_sided=args.retention_one_sided)
        if args.fine_detail_weight:
            loss=loss+args.fine_detail_weight*fine_detail_loss(output,target,fraction>0,stars_tensor,HALO)
        if args.fine_shape_weight:
            loss=loss+args.fine_shape_weight*fine_shape_loss(output,target,fraction>0,stars_tensor,HALO)
        compatibility_parts={}
        if fine_teacher_penalty is not None:loss=loss+args.teacher_fine_weight*fine_teacher_penalty
        if args.noise_compat:
            off=torch.from_numpy(np.stack(offsets)).to(device)[:,:,None,None]
            sc=torch.from_numpy(np.stack(scales)).to(device)[:,:,None,None]
            compat,compatibility_parts=compatibility_loss(delivered,x,target,off,sc)
            loss=loss+args.compat_weight*compat
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite training loss')
        optimizer.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=args.precision!='fp16')
        previous_scale=scaler.get_scale()
        scaler.step(optimizer)
        scaler.update()
        stepped=scaler.get_scale()>=previous_scale
        optimizer_steps+=int(stepped)
        if stepped:
            for pair_key,identities_in_pair in batch_pairs.items():
                seen_pairs.add(pair_key)
                used_frames.update(identities_in_pair)
        if step%args.check_every==0 or step==args.steps:
            if (hashlib.sha256(args.records.read_bytes()).hexdigest()!=frozen_training_sha or
                hashlib.sha256(args.validation.read_bytes()).hexdigest()!=frozen_validation_sha):
                raise RuntimeError('Training or validation manifest changed during this run; candidate must not be deployed')
            score=validate(model.eval(),validation,args.detail_objective,args.structure_objective or args.validation_spatial,args.noise_compat,args.compat_weight,teacher,args.structure_priority,args.fine_validation,args.shape_validation)
            loss_value=float(loss.detach().cpu())
            history.append(dict(step=step,validation_mse_ratio=score,training_loss=loss_value,
                compatibility_components={k:float(v.detach().cpu()) for k,v in compatibility_parts.items()}))
            eligible=len(used_frames & declared_new)>=args.minimum_new_frames
            if score<best and eligible:
                best=score
                write_checkpoint(args.output,model,dict(step=step,seed=args.seed,history=history,
                    optimizer_steps=optimizer_steps,
                    coverage_counts_successful_optimizer_steps_only=True,
                    training_manifest=str(args.records.resolve()),validation_manifest=str(args.validation.resolve()),
                    training_frames=len(used_frames),available_training_frames=len(identities(training,'sha256')),
                    new_training_frames=len(used_frames & declared_new),available_new_training_frames=len(declared_new),
                    minimum_new_training_frames=args.minimum_new_frames,
                    teacher_fine_preservation_weight=args.teacher_fine_weight,structure_retention_selection_weight=args.structure_priority,
                    teacher_allows_amplification=args.teacher_envelope,retention_one_sided=args.retention_one_sided,
                    teacher_fine_reference='input' if args.teacher_input else str(args.teacher_checkpoint or args.initial),
                    sampled_pairs=len(seen_pairs),parent=str(args.initial) if args.initial else None,
                    detail_objective=args.detail_objective,learning_rate=args.lr,batch_size=args.batch,
                    patch_core=args.patch_core,
                    training_context_halo=HALO,
                    fine_detail_loss_weight=args.fine_detail_weight,
                    fine_shape_correlation_loss_weight=args.fine_shape_weight,
                    train_through_frozen_contrast_response=args.train_through_response,
                    structure_objective=args.structure_objective,
                    geometric_augmentation=args.structure_objective,
                    longest_reference_pairs=args.deep_pairs,
                    minimum_reference_ratio=args.minimum_reference_ratio,
                    long_integration_field_weight=args.long_weight,
                    diffuse_structure_loss_weight=args.diffuse_weight,
                    independent_remainder_loss=args.independent_loss,
                    background_plane_matching=args.background_plane,
                    weak_signal_focus=args.weak_focus,
                    reference_covariance_retention=args.retain_structure,
                    noise_colour_compatibility=args.noise_compat,
                    compatibility_version=COMPATIBILITY_VERSION if args.noise_compat else None,
                    compatibility_weight=args.compat_weight if args.noise_compat else None,
                    coarse_identity_penalty=args.coarse_identity,
                    validation_metric='nonstellar_fine_shape_correlation_plus_retention' if args.shape_validation else ('nonstellar_1_4px_independent_reference_error' if args.fine_validation else ('spatial_error_plus_noise_colour' if args.noise_compat else ('worst_field_spatial_band_error' if args.structure_objective or args.validation_spatial else 'independent_reference_mse'))),
                    parent_validation_score=initial_validation,
                    training_manifest_sha256=frozen_training_sha,
                    torch_version=str(torch.__version__),device=str(device),precision=args.precision,
                    training_objects=sorted(identities(training,'object')),status='experimental'))
            args.output.with_suffix('.history.json').write_text(json.dumps(dict(
                steps_completed=step,best_validation_mse_ratio=best,history=history),indent=2),encoding='utf-8')
            print(step,score,'training_loss',loss_value,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',required=True,type=Path)
    parser.add_argument('--validation',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--precision',choices=('fp32','fp16','bf16'),default='fp32')
    parser.add_argument('--patch-core',type=int,choices=(32,64,128,256),default=32)
    parser.add_argument('--initial',type=Path)
    parser.add_argument('--residual-limit',type=float,help='Optional experimentally increased correction bound')
    parser.add_argument('--detail-objective',action='store_true')
    parser.add_argument('--structure-objective',action='store_true',help='Add spatial-band losses and input-based structure sampling')
    parser.add_argument('--validation-spatial',action='store_true',help='Select weights by worst-field spatial error with either loss')
    parser.add_argument('--independent-loss',action='store_true',help='Train noise correction against the disjoint remainder of cumulative stacks')
    parser.add_argument('--background-plane',action='store_true',help='Match additive sky gradients between training stack levels')
    parser.add_argument('--weak-focus',action='store_true',help='Fit faint pixels while preserving bright stellar cores selected from the input')
    parser.add_argument('--coarse-identity',action='store_true',help='Penalize changes to existing broad structures')
    parser.add_argument('--retain-structure',action='store_true',help='Penalize loss of contrast supported by independent-reference covariance')
    parser.add_argument('--noise-compat',action='store_true',help='Preserve coloured-noise correlations and smooth physical RGB chromaticity')
    parser.add_argument('--compat-weight',type=float,default=1.,help='Relative weight of the noise/colour constraint')
    parser.add_argument('--preserve-colour',action='store_true',help='Train and infer only a common physical RGB gain')
    parser.add_argument('--deep-pairs',action='store_true',help='Add each short rung paired with the longest available integration')
    parser.add_argument('--minimum-reference-ratio',type=float,default=1.,help='Skip training pairs with tiny independent remainder integrations')
    parser.add_argument('--long-weight',type=float,default=1.,help='Sampling weight for records verified to contain >=20h per object')
    parser.add_argument('--long-threshold-hours',type=float,default=20.,help='Minimum verified field integration qualifying for long-weight')
    parser.add_argument('--diffuse-weight',type=float,default=.5,help='Loss weight for confirmed 5-17px spatial structure')
    parser.add_argument('--diagnose-only',action='store_true',help='Write a forward-only JSON report without training')
    parser.add_argument('--lr',type=float,default=.0001)
    parser.add_argument('--steps',type=int,default=2000)
    parser.add_argument('--batch',type=int,default=4)
    parser.add_argument('--check-every',type=int,default=100)
    parser.add_argument('--seed',type=int,default=5000)
    parser.add_argument('--minimum-new-frames',type=int,default=0,help='Save selectable checkpoints only after this many new exposure hashes participated in successful optimizer steps')
    parser.add_argument('--teacher-fine-weight',type=float,default=0.,help='Preserve the retained model fine component, including weak low-SNR structure')
    parser.add_argument('--structure-priority',type=float,default=0.,help='Penalize independently supported structure attenuation in validation selection')
    parser.add_argument('--retention-one-sided',action='store_true',help='Protect independently supported contrast without penalizing contrast increases')
    parser.add_argument('--teacher-envelope',action='store_true',help='Penalize weakening and sign reversals of teacher fine coefficients, but permit amplification')
    parser.add_argument('--teacher-checkpoint',type=Path,help='Retained structural baseline independent of the initialization')
    parser.add_argument('--teacher-input',action='store_true',help='Protect the original input fine coefficients while permitting removal of finer pixel noise')
    parser.add_argument('--fine-detail-weight',type=float,default=0.,help='Independent-reference Gaussian 1-4px shape error weight')
    parser.add_argument('--fine-shape-weight',type=float,default=0.,help='Independent-reference fine shape correlation loss weight')
    parser.add_argument('--fine-validation',action='store_true',help='Select on nonstellar Gaussian 1-4px error')
    parser.add_argument('--shape-validation',action='store_true',help='With fine-validation, select by shape correlation and supported contrast retention')
    parser.add_argument('--train-through-response',action='store_true',help='Differentiate through the frozen calibrated spatial response')
    parser.add_argument('--training-halo',type=int,choices=(72,160),default=72,help='Native context around the loss core; use 160 for response-aware training')
    args=parser.parse_args()
    with FileLock(str(args.output)+'.training.lock',timeout=0):
        train(args)
