// ----------------------------------------------------------------------------
// NebulaMaskBuilder.js
// PixInsight JavaScript Runtime (PJSR) script.
//
// Sample Background, H-alpha, OIII and optional SII disks on an open
// RGB image. Every pixel is then classified by regularized Mahalanobis
// distance in a color feature space and written as a grayscale mask in [0,1].
//
// Run from PixInsight: Script > Execute Script File...
// ----------------------------------------------------------------------------

#engine v8

#feature-id NebulaMaskBuilder : Toolbox > NebulaMaskBuilder

#feature-info Samples Background, H-alpha and OIII on an RGB view and builds competing grayscale masks from color, not brightness.

// ----------------------------------------------------------------------------
// Pure color model. No PixInsight objects in this section, so the math can be
// checked outside the runtime.
// ----------------------------------------------------------------------------

var NMB_VERSION = "1.2";
var NMB_NDIM = 6;
var NMB_CLASS_NAME = [ "Background", "H-alpha", "OIII", "SII (manual / SHO)" ];
var NMB_MASK_ID = [ "Background_mask", "Ha_mask", "OIII_mask", "SII_mask" ];
var NMB_CLASS_COLOR = [ 0xffe8e8e8, 0xffff3b30, 0xff2ec7ff, 0xffffcc33 ];
var NMB_CLASS_FILL = [ 0x55e8e8e8, 0x66ff3b30, 0x662ec7ff, 0x66ffcc33 ];

// Applied after per-feature z-scoring. Chromaticity, saturation and channel
// ratios dominate. Luminance is only a weak cue, so a faint OIII patch is not
// swallowed by the background just because it is dim.
var NMB_WEIGHTS = [ 3.0, 3.0, 2.0, 1.8, 1.8, 0.45 ];
var NMB_PREVIEW_MAX = 1600;
var NMB_MAX_PIXELS = 100000000;
var NMB_MAX_TRAIN = 16000;
var NMB_MAX_MARKS = 500;

function nmbWriteFeatures( r, g, b, dst, o )
{
   var eps = 1.0e-8;
   if ( r < 0 ) r = 0;
   if ( g < 0 ) g = 0;
   if ( b < 0 ) b = 0;
   var sum = r + g + b;
   var invSum = 1 / (sum + eps);
   var rn = r * invSum;
   var bn = b * invSum;
   var mx = r > g ? r : g;
   if ( b > mx ) mx = b;
   var mn = r < g ? r : g;
   if ( b < mn ) mn = b;
   dst[o]     = rn;
   dst[o + 1] = bn;
   dst[o + 2] = (mx - mn) / (mx + eps);
   dst[o + 3] = Math.log( (r + eps) / (g + eps) );
   dst[o + 4] = Math.log( (b + eps) / (g + eps) );
   dst[o + 5] = sum / 3;
}

function nmbInvert6( src )
{
   var n = NMB_NDIM;
   var cols = n * 2;
   var a = new Float64Array( n * cols );
   var r, c, col, pivot, best, v, tmp, diag, f;
   for ( r = 0; r < n; ++r )
   {
      for ( c = 0; c < n; ++c )
         a[r * cols + c] = src[r * n + c];
      a[r * cols + n + r] = 1;
   }
   for ( col = 0; col < n; ++col )
   {
      pivot = col;
      best = Math.abs( a[col * cols + col] );
      for ( r = col + 1; r < n; ++r )
      {
         v = Math.abs( a[r * cols + col] );
         if ( v > best )
         {
            best = v;
            pivot = r;
         }
      }
      if ( !(best > 1.0e-12) )
         return null;
      if ( pivot !== col )
      {
         for ( c = 0; c < cols; ++c )
         {
            tmp = a[col * cols + c];
            a[col * cols + c] = a[pivot * cols + c];
            a[pivot * cols + c] = tmp;
         }
      }
      diag = a[col * cols + col];
      for ( c = 0; c < cols; ++c )
         a[col * cols + c] /= diag;
      for ( r = 0; r < n; ++r )
      {
         if ( r === col )
            continue;
         f = a[r * cols + col];
         if ( f === 0 )
            continue;
         for ( c = 0; c < cols; ++c )
            a[r * cols + c] -= f * a[col * cols + c];
      }
   }
   var inv = new Float64Array( n * n );
   for ( r = 0; r < n; ++r )
      for ( c = 0; c < n; ++c )
         inv[r * n + c] = a[r * cols + n + c];
   return inv;
}

function nmbInvertOrIdentity( cov )
{
   var lambda = 0;
   var attempt, i, a, inv;
   for ( attempt = 0; attempt < 8; ++attempt )
   {
      a = new Float64Array( cov );
      if ( lambda > 0 )
         for ( i = 0; i < NMB_NDIM; ++i )
            a[i * NMB_NDIM + i] += lambda;
      inv = nmbInvert6( a );
      if ( inv )
         return inv;
      lambda = (lambda === 0) ? 1.0e-4 : lambda * 10;
   }
   inv = new Float64Array( NMB_NDIM * NMB_NDIM );
   for ( i = 0; i < NMB_NDIM; ++i )
      inv[i * NMB_NDIM + i] = 1;
   return inv;
}

function nmbPooledStats( rawByClass )
{
   var total = 0;
   var c, n, i, k, o, d;
   for ( c = 0; c < rawByClass.length; ++c )
      total += (rawByClass[c].length / NMB_NDIM) | 0;
   if ( total < 1 )
      return null;

   var mean = new Float64Array( NMB_NDIM );
   for ( c = 0; c < rawByClass.length; ++c )
   {
      var raw = rawByClass[c];
      n = (raw.length / NMB_NDIM) | 0;
      for ( i = 0; i < n; ++i )
      {
         o = i * NMB_NDIM;
         for ( k = 0; k < NMB_NDIM; ++k )
            mean[k] += raw[o + k];
      }
   }
   for ( k = 0; k < NMB_NDIM; ++k )
      mean[k] /= total;

   var m2 = new Float64Array( NMB_NDIM );
   for ( c = 0; c < rawByClass.length; ++c )
   {
      raw = rawByClass[c];
      n = (raw.length / NMB_NDIM) | 0;
      for ( i = 0; i < n; ++i )
      {
         o = i * NMB_NDIM;
         for ( k = 0; k < NMB_NDIM; ++k )
         {
            d = raw[o + k] - mean[k];
            m2[k] += d * d;
         }
      }
   }
   var std = new Float64Array( NMB_NDIM );
   var denom = total > 1 ? (total - 1) : 1;
   for ( k = 0; k < NMB_NDIM; ++k )
   {
      std[k] = Math.sqrt( m2[k] / denom );
      if ( !(std[k] > 1.0e-4) )
         std[k] = 1.0e-4;
   }
   return { mean: mean, std: std, total: total };
}

function nmbScaleRaw( raw, n, featMean, featStd, weights )
{
   var z = new Float64Array( n * NMB_NDIM );
   var i, k, o;
   for ( i = 0; i < n; ++i )
   {
      o = i * NMB_NDIM;
      for ( k = 0; k < NMB_NDIM; ++k )
         z[o + k] = ((raw[o + k] - featMean[k]) / featStd[k]) * weights[k];
   }
   return z;
}

// Regularized Mahalanobis. Shrinkage toward the identity makes a nearly flat
// sample set behave like weighted Euclidean distance, which keeps the softmax
// distances of every class on the same scale.
function nmbFitClass( z, n )
{
   var mean = new Float64Array( NMB_NDIM );
   var i, k, j, o, y, trace, meanVar, lambda;
   for ( i = 0; i < n; ++i )
   {
      o = i * NMB_NDIM;
      for ( k = 0; k < NMB_NDIM; ++k )
         mean[k] += z[o + k];
   }
   for ( k = 0; k < NMB_NDIM; ++k )
      mean[k] /= n;

   var cov = new Float64Array( NMB_NDIM * NMB_NDIM );
   if ( n >= 2 )
   {
      var invN = 1 / (n - 1);
      var diff = new Float64Array( NMB_NDIM );
      for ( i = 0; i < n; ++i )
      {
         o = i * NMB_NDIM;
         for ( k = 0; k < NMB_NDIM; ++k )
            diff[k] = z[o + k] - mean[k];
         for ( k = 0; k < NMB_NDIM; ++k )
            for ( j = 0; j < NMB_NDIM; ++j )
               cov[k * NMB_NDIM + j] += diff[k] * diff[j];
      }
      for ( k = 0; k < NMB_NDIM * NMB_NDIM; ++k )
         cov[k] *= invN;
   }

   lambda = (n < 2) ? 1 : Math.min( 0.9, Math.max( 0.05, NMB_NDIM / n ) );
   trace = 0;
   for ( k = 0; k < NMB_NDIM; ++k )
      trace += cov[k * NMB_NDIM + k];
   meanVar = trace / NMB_NDIM;
   if ( meanVar > 4 )
      lambda = Math.max( lambda, 1 - 4 / meanVar );
   if ( lambda > 0.98 )
      lambda = 0.98;

   for ( k = 0; k < NMB_NDIM; ++k )
      for ( j = 0; j < NMB_NDIM; ++j )
         cov[k * NMB_NDIM + j] *= (1 - lambda);
   for ( k = 0; k < NMB_NDIM; ++k )
      cov[k * NMB_NDIM + k] += lambda;

   return {
      mean: mean,
      inv: nmbInvertOrIdentity( cov ),
      lambda: lambda,
      count: n
   };
}

function nmbFitModel( rawByClass )
{
   var stats = nmbPooledStats( rawByClass );
   if ( !stats )
      return null;

   var weights = new Float64Array( NMB_WEIGHTS );
   var ids = [];
   var means = [];
   var invs = [];
   var counts = [];
   var lambdas = [];
   var c, n, z, fitted;

   for ( c = 0; c < rawByClass.length; ++c )
   {
      n = (rawByClass[c].length / NMB_NDIM) | 0;
      if ( n < 1 )
         continue;
      z = nmbScaleRaw( rawByClass[c], n, stats.mean, stats.std, weights );
      fitted = nmbFitClass( z, n );
      ids.push( c );
      means.push( fitted.mean );
      invs.push( fitted.inv );
      counts.push( n );
      lambdas.push( fitted.lambda );
   }
   if ( ids.length < 2 )
      return null;

   var packed = new Float64Array( ids.length * NMB_NDIM );
   for ( c = 0; c < ids.length; ++c )
      for ( var k = 0; k < NMB_NDIM; ++k )
         packed[c * NMB_NDIM + k] = means[c][k];

   var bgSlot = 0;
   for ( c = 0; c < ids.length; ++c )
      if ( ids[c] === 0 )
         bgSlot = c;

   return {
      ids: ids,
      count: ids.length,
      means: packed,
      inv: invs,
      counts: counts,
      lambdas: lambdas,
      featMean: stats.mean,
      featStd: stats.std,
      weights: weights,
      bgSlot: bgSlot,
      logs: new Float64Array( ids.length )
   };
}

function nmbSquaredDistance( z, mean, meanBase, inv )
{
   var y0 = z[0] - mean[meanBase];
   var y1 = z[1] - mean[meanBase + 1];
   var y2 = z[2] - mean[meanBase + 2];
   var y3 = z[3] - mean[meanBase + 3];
   var y4 = z[4] - mean[meanBase + 4];
   var y5 = z[5] - mean[meanBase + 5];
   var d =
      y0 * (inv[ 0] * y0 + inv[ 1] * y1 + inv[ 2] * y2 + inv[ 3] * y3 + inv[ 4] * y4 + inv[ 5] * y5) +
      y1 * (inv[ 6] * y0 + inv[ 7] * y1 + inv[ 8] * y2 + inv[ 9] * y3 + inv[10] * y4 + inv[11] * y5) +
      y2 * (inv[12] * y0 + inv[13] * y1 + inv[14] * y2 + inv[15] * y3 + inv[16] * y4 + inv[17] * y5) +
      y3 * (inv[18] * y0 + inv[19] * y1 + inv[20] * y2 + inv[21] * y3 + inv[22] * y4 + inv[23] * y5) +
      y4 * (inv[24] * y0 + inv[25] * y1 + inv[26] * y2 + inv[27] * y3 + inv[28] * y4 + inv[29] * y5) +
      y5 * (inv[30] * y0 + inv[31] * y1 + inv[32] * y2 + inv[33] * y3 + inv[34] * y4 + inv[35] * y5);
   return d > 0 ? d : 0;
}

function nmbProbabilities( r, g, b, model, sensitivity, scratch, out )
{
   if(model.unmix)
   {
      nmbUnmixProbabilities(r,g,b,model.unmix,out);
      return;
   }
   nmbWriteFeatures( r, g, b, scratch, 0 );
   var mean = model.featMean;
   var std = model.featStd;
   var w = model.weights;
   var k, c, d2, logit, sum, inv;
   for ( k = 0; k < NMB_NDIM; ++k )
      scratch[k] = ((scratch[k] - mean[k]) / std[k]) * w[k];

   var nc = model.count;
   var logs = model.logs;
   var maxLog = -1.0e300;
   for ( c = 0; c < nc; ++c )
   {
      d2 = nmbSquaredDistance( scratch, model.means, c * NMB_NDIM, model.inv[c] );
      logit = -sensitivity * Math.sqrt( d2 );
      logs[c] = logit;
      if ( logit > maxLog )
         maxLog = logit;
   }
   sum = 0;
   for ( c = 0; c < nc; ++c )
   {
      out[c] = Math.exp( logs[c] - maxLog );
      sum += out[c];
   }
   inv = sum > 0 ? 1 / sum : 0;
   for ( c = 0; c < nc; ++c )
      out[c] *= inv;

}

function nmbMarkIndices( width, height, marks )
{
   var seen = new Set();
   var list = [];
   var m, cx, cy, rad, r2, x0, x1, y0, y1, y, x, dy, dx, idx, row;
   for ( m = 0; m < marks.length; ++m )
   {
      if ( !isFinite( marks[m].x ) || !isFinite( marks[m].y ) )
         continue;
      cx = Math.round( marks[m].x );
      cy = Math.round( marks[m].y );
      rad = Math.round( marks[m].r );
      if ( rad < 1 )
         rad = 1;
      r2 = rad * rad;
      x0 = cx - rad;
      if ( x0 < 0 ) x0 = 0;
      x1 = cx + rad;
      if ( x1 >= width ) x1 = width - 1;
      y0 = cy - rad;
      if ( y0 < 0 ) y0 = 0;
      y1 = cy + rad;
      if ( y1 >= height ) y1 = height - 1;
      for ( y = y0; y <= y1; ++y )
      {
         dy = y - cy;
         row = y * width;
         for ( x = x0; x <= x1; ++x )
         {
            dx = x - cx;
            if ( dx * dx + dy * dy > r2 )
               continue;
            idx = row + x;
            if ( seen.has( idx ) )
               continue;
            seen.add( idx );
            list.push( idx );
         }
      }
   }

   if ( list.length > NMB_MAX_TRAIN )
   {
      for ( var i = NMB_MAX_TRAIN; i < list.length; ++i )
      {
         var j = Math.floor( Math.random() * (i + 1) );
         if ( j < NMB_MAX_TRAIN )
            list[j] = list[i];
      }
      list.length = NMB_MAX_TRAIN;
   }
   return list;
}

function nmbFeaturesFromIndices( list, width, readPixel )
{
   var kept = [];
   var tmp = new Float64Array( NMB_NDIM );
   var i, idx, x, y, rgb;
   for ( i = 0; i < list.length; ++i )
   {
      idx = list[i];
      x = idx % width;
      y = (idx / width) | 0;
      rgb = readPixel( x, y );
      if ( !rgb || !isFinite( rgb.r ) || !isFinite( rgb.g ) || !isFinite( rgb.b ) )
         continue;
      nmbWriteFeatures( rgb.r, rgb.g, rgb.b, tmp, 0 );
      kept.push( tmp[0], tmp[1], tmp[2], tmp[3], tmp[4], tmp[5] );
   }
   var raw = new Float64Array( kept.length );
   for ( i = 0; i < kept.length; ++i )
      raw[i] = kept[i];
   return raw;
}

function nmbCollectClassFeatures( R, G, B, width, height, marks )
{
   return nmbFeaturesFromIndices( nmbMarkIndices( width, height, marks ), width, function( x, y )
   {
      var idx = y * width + x;
      return { r: R[idx], g: G[idx], b: B[idx] };
   } );
}

function nmbClassifyImage( R, G, B, width, height, model, sensitivity, onProgress )
{
   var n = width * height;
   var nc = model.count;
   var masks = [];
   var c, y, x, row, p, r, g, b;
   for ( c = 0; c < nc; ++c )
      masks.push( new Float32Array( n ) );

   var scratch = new Float64Array( NMB_NDIM );
   var probs = new Float64Array( nc );
   var bg = model.bgSlot;

   for ( y = 0; y < height; ++y )
   {
      row = y * width;
      for ( x = 0; x < width; ++x )
      {
         p = row + x;
         r = R[p];
         g = G[p];
         b = B[p];
         if ( !isFinite( r ) || !isFinite( g ) || !isFinite( b ) )
         {
            masks[bg][p] = 1;
            continue;
         }
         nmbProbabilities( r, g, b, model, sensitivity, scratch, probs );
         for ( c = 0; c < nc; ++c )
            masks[c][p] = probs[c];
      }
      if ( onProgress && ((y & 63) === 0 || y === height - 1) )
         if ( onProgress( y, height ) === false )
            return null;
   }
   return masks;
}

function nmbSegment( R, G, B, width, height, marksByClass, sensitivity, onProgress )
{
   var rawByClass = [];
   var c;
   for ( c = 0; c < marksByClass.length; ++c )
   {
      if ( !marksByClass[c] || marksByClass[c].length === 0 )
         rawByClass.push( new Float64Array( 0 ) );
      else
         rawByClass.push( nmbCollectClassFeatures( R, G, B, width, height, marksByClass[c] ) );
   }
   var missing = [];
   for ( c = 0; c < 3; ++c )
      if ( rawByClass[c].length < NMB_NDIM )
         missing.push( NMB_CLASS_NAME[c] );
   if ( missing.length )
      return { error: "Mark at least one sample region for: " + missing.join( ", " ) + "." };

   var model = nmbFitModel( rawByClass );
   if ( !model )
      return { error: "The samples are not enough to separate the classes." };

   var masks = nmbClassifyImage( R, G, B, width, height, model, sensitivity, onProgress );
   if ( !masks )
      return { aborted: true };
   return { model: model, masks: masks, rawByClass: rawByClass };
}

// Deterministic, bounded grid sampling. Neighborhood averages suppress hot
// pixels; percentile tails supply anchors without trusting one extreme pixel.
function nmbAutoModel( image, palette )
{
   var step = Math.max( 1, Math.ceil( Math.sqrt(image.width*image.height/40000) ) );
   var points = [], x, y, dx, dy, r, g, b, n, sum, mx, mn;
   for ( y = 0; y < image.height; y += step )
   {
      for ( x = 0; x < image.width; x += step )
      {
         r = g = b = n = 0;
         for ( dy = -1; dy <= 1; ++dy )
            for ( dx = -1; dx <= 1; ++dx )
            {
               var xx = Math.max(0, Math.min(image.width-1,x+dx));
               var yy = Math.max(0, Math.min(image.height-1,y+dy));
               var rr=image.sample(xx,yy,0), gg=image.sample(xx,yy,1), bb=image.sample(xx,yy,2);
               if ( !isFinite(rr) || !isFinite(gg) || !isFinite(bb) ) continue;
               r+=Math.max(0,rr); g+=Math.max(0,gg); b+=Math.max(0,bb); ++n;
            }
         if ( !n ) continue;
         r/=n; g/=n; b/=n; sum=r+g+b;
         if ( !(sum>1e-8) )
         {
            points.push({r:0,g:0,b:0,l:0,sat:0,h:0,o:0,sulfur:0});
            continue;
         }
         mx=Math.max(r,g,b); mn=Math.min(r,g,b);
         points.push({r:r,g:g,b:b,l:sum/3,sat:(mx-mn)/mx,
            h:palette===1 ? (g-Math.max(r,b))/sum : (r+g-2*b)/sum,
            o:palette===1 ? (b-Math.max(r,g))/sum : (2*b-r-g)/sum,
            sulfur:(r-Math.max(g,b))/sum});
      }
      if ( (y/step)%32===0 )
      {
         CoreApplication.processEvents();
         if ( console.abortRequested ) throw new Error("NMB_ABORT");
      }
   }
   if ( points.length<32 ) return {error:"Not enough finite, nonzero pixels for AUTO."};
   points.sort(function(a,b){return a.l-b.l;});
   var floor=points[Math.floor(points.length*0.15)].l;
   var ceiling=points[Math.floor(points.length*0.98)].l;
   var raw=[[],[],[],[]], tmp=new Float64Array(NMB_NDIM);
   function add(c,p)
   {
      nmbWriteFeatures(p.r,p.g,p.b,tmp,0);
      for(var k=0;k<NMB_NDIM;++k) raw[c].push(tmp[k]);
   }
   var take=Math.min(512,Math.max(8,Math.floor(points.length*0.02)));
   for(var i=0;i<take;++i) add(0,points[i]);
   // HOO: rank relative warm/cool balance, including desaturated emission.
   // No absolute cyan or saturation requirement: white can be the cool end
   // of a gold/white image. Do not call every neutral pixel oxygen.
   var eligible=points.filter(function(p){return p.l>floor && p.l<=ceiling;});
   if(eligible.length<16) return {error:"AUTO needs brightness variation above the background."};
   var keys=palette===1 ? ["h","o","sulfur"] : ["h","o"];
   if(palette!==1)
   {
      eligible.sort(function(a,b){return a.h-b.h;});
      var lo=eligible[Math.floor(eligible.length*0.1)].h;
      var hi=eligible[Math.floor(eligible.length*0.9)].h;
      if(hi-lo<0.015)
         return {error:"AUTO cannot separate warm and cool regions: insufficient relative color contrast. Use manual anchors."};
      var lowEnd=lo+0.2*(hi-lo), highEnd=hi-0.2*(hi-lo);
      var warm=eligible.filter(function(p){return p.h>=highEnd;});
      var cool=eligible.filter(function(p){return p.h<=lowEnd;});
      // Spread samples across the entire tail instead of just the most extreme
      // colors. This includes bright white OIII alongside blue OIII anchors.
      for(var c=1;c<=2;++c)
      {
         var group=c===1?warm:cool;
         if(group.length<8) return {error:"AUTO needs more spatial samples for each color region."};
         group.sort(function(a,b){return a.l-b.l;});
         var count=Math.min(take,group.length);
         for(i=0;i<count;++i) add(c,group[Math.floor((i+0.5)*group.length/count)]);
      }
   }
   else for(var c=0;c<keys.length;++c)
   {
      var key=keys[c];
      eligible.sort(function(a,b){return b[key]-a[key];});
      var selected=eligible.filter(function(p){return p[key]>0.035;});
      if(selected.length<8)
         return {error:"AUTO cannot find distinct "+NMB_CLASS_NAME[c+1]+" anchors. Check palette or use manual samples."};
      for(i=0;i<Math.min(take,selected.length);++i) add(c+1,selected[i]);
   }
   var model=nmbFitModel(raw);
   if(!model) return {error:"AUTO could not fit the color anchors."};
   if(palette!==1)
   {
      // Estimate the sky pedestal and its scatter from a broad dark sample,
      // not just the darkest 2% (which underestimates the sky).
      points.sort(function(a,b){return a.l-b.l;});
      var skyPoints=points.slice(0,Math.max(8,Math.floor(points.length*0.3)));
      function median(values)
      {
         values.sort(function(a,b){return a-b;});
         return values[Math.floor(values.length/2)];
      }
      var sky=[], noise2=0;
      var channels=["r","g","b"];
      for(var k=0;k<3;++k)
      {
         var values=skyPoints.map(function(p){return p[channels[k]];});
         sky[k]=median(values);
         var deviations=values.map(function(v){return Math.abs(v-sky[k]);});
         var sigma=1.4826*median(deviations);
         noise2+=sigma*sigma;
      }
      function anchor(group)
      {
         group.sort(function(a,b){return a.l-b.l;});
         var bright=group.slice(Math.floor(group.length/2)), v=[];
         for(var k=0;k<3;++k)
            v[k]=Math.max(0,median(bright.map(function(p){return p[channels[k]];}))-sky[k]);
         var norm=Math.sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]);
         if(norm<1e-8) return null;
         for(k=0;k<3;++k) v[k]/=norm;
         return v;
      }
      // Include white emission only as a bright endpoint. Neutral background
      // never supplies an oxygen endpoint merely because it is less warm.
      var neutral=eligible.filter(function(p){return p.sat<0.12 && p.h<(lo+hi)/2;});
      var oxygenGroup=cool;
      if(neutral.length>=8)
      {
         neutral.sort(function(a,b){return a.l-b.l;});
         var brightNeutral=neutral.slice(Math.floor(neutral.length*0.75));
         if(brightNeutral[0].l>floor) oxygenGroup=brightNeutral;
      }
      var hAnchor=anchor(warm), oAnchor=anchor(oxygenGroup);
      if(!hAnchor || !oAnchor) return {error:"AUTO cannot measure emission above the background."};
      var dot=hAnchor[0]*oAnchor[0]+hAnchor[1]*oAnchor[1]+hAnchor[2]*oAnchor[2];
      if(1-dot*dot<0.0001) return {error:"AUTO color endpoints are too similar. Use manual anchors."};
      model.unmix={sky:sky,h:hAnchor,o:oAnchor,dot:dot,
         // Anchors were measured with a 3x3 mean; restore pixel-noise variance.
         noise2:Math.max(9*noise2,1e-12)};
   }
   return {model:model,rawByClass:raw};
}

// Nonnegative two-endmember least squares after sky subtraction.
// The residual is allowed to remain unexplained: oxygen is not 1 - hydrogen.
function nmbUnmixProbabilities(r,g,b,u,out)
{
   var v=[r-u.sky[0],g-u.sky[1],b-u.sky[2]];
   var ph=0,po=0,norm2=0;
   for(var k=0;k<3;++k){ph+=v[k]*u.h[k];po+=v[k]*u.o[k];norm2+=v[k]*v[k];}
   var det=1-u.dot*u.dot;
   var h=(ph-u.dot*po)/det, o=(po-u.dot*ph)/det;
   if(h<0){h=0;o=Math.max(0,po);}
   if(o<0){o=0;h=Math.max(0,ph);}
   var residual=0;
   for(k=0;k<3;++k){var d=v[k]-h*u.h[k]-o*u.o[k];residual+=d*d;}
   var power=h*h+o*o;
   // Smooth SNR gate has no brightness cut at the faint-emission boundary.
   var evidence=Math.max(0,power-3*u.noise2);
   var signal=evidence/(evidence+3*u.noise2);
   var fit=Math.max(0,1-residual/(norm2+u.noise2));
   var total=h+o;
   out[1]=total>0 ? signal*fit*h/total : 0;
   out[2]=total>0 ? signal*fit*o/total : 0;
   out[0]=Math.max(0,1-out[1]-out[2]);
}

// Local probability consensus for ambiguous pixels. Confident anchors remain
// unchanged; two synchronous passes avoid directional, scan-order artifacts.
function nmbSpatialConsensus( masks, width, height, progress )
{
   var n=width*height, nc=masks.length;
   for(var pass=0;pass<2;++pass)
   {
      var next=[];
      for(var c=0;c<nc;++c) next.push(new Float32Array(n));
      for(var y=0;y<height;++y)
      {
         for(var x=0;x<width;++x)
         {
            var p=y*width+x, first=0, second=0;
            for(c=0;c<nc;++c)
            {
               var v=masks[c][p];
               if(v>first){second=first;first=v;} else if(v>second) second=v;
            }
            var strength=0.65*Math.max(0,1-(first-second)/0.7);
            for(c=0;c<nc;++c)
            {
               var sum=0, weight=0;
               for(var dy=-1;dy<=1;++dy)
                  for(var dx=-1;dx<=1;++dx)
                  {
                     var xx=x+dx, yy=y+dy;
                     if(xx<0 || xx>=width || yy<0 || yy>=height || (!dx && !dy)) continue;
                     var w=dx && dy ? 0.70710678 : 1;
                     sum+=w*masks[c][yy*width+xx]; weight+=w;
                  }
               next[c][p]=weight ? (1-strength)*masks[c][p]+strength*sum/weight : masks[c][p];
            }
         }
         if((y&63)===0 && progress && !progress()) return false;
      }
      for(c=0;c<nc;++c) masks[c]=next[c];
   }
   return true;
}

// Connected components of the maximum-probability label, with 4-connectivity.
// Only small components are reassigned. Large regions and mixed boundaries keep
// their soft probabilities. Blur is applied afterwards by the publisher.
function nmbCleanRegions( masks, width, height, minArea, progress )
{
   if ( minArea<=1 ) return true;
   var n=width*height, nc=masks.length, labels=new Uint8Array(n);
   var seen=new Uint8Array(n), queue=new Int32Array(n), p,c,j;
   for(p=0;p<n;++p)
   {
      var best=0;
      for(c=1;c<nc;++c) if(masks[c][p]>masks[best][p]) best=c;
      labels[p]=best;
   }
   for(p=0;p<n;++p)
   {
      if((p&65535)===0 && progress && !progress()) return false;
      if(seen[p]) continue;
      var label=labels[p], head=0, tail=1, votes=new Float64Array(nc);
      queue[0]=p; seen[p]=1;
      while(head<tail)
      {
         var q=queue[head++], x=q%width;
         // No row wrapping at the left and right borders.
         for(var d=0;d<4;++d)
         {
            j=d===0 ? (x>0?q-1:-1) : d===1 ? (x+1<width?q+1:-1) : d===2 ? q-width : q+width;
            if(j<0 || j>=n) continue;
            if(labels[j]===label)
            {
               if(!seen[j]) {seen[j]=1;queue[tail++]=j;}
            }
            else votes[labels[j]]+=masks[labels[j]][j];
         }
         if((head&65535)===0 && progress && !progress()) return false;
      }
      if(tail>=minArea) continue;
      var target=-1;
      for(c=0;c<nc;++c) if(c!==label && votes[c]>0 && (target<0 || votes[c]>votes[target])) target=c;
      if(target<0) continue;
      for(var k=0;k<tail;++k)
      {
         q=queue[k];
         // Collapse the rejected island's distribution onto its surrounding class.
         for(c=0;c<nc;++c) masks[c][q]=c===target?1:0;
      }
   }
   return true;
}

function nmbGaussianKernel( sigma )
{
   var radius = Math.ceil( sigma * 3 );
   if ( radius < 1 )
      radius = 1;
   if ( radius > 128 )
      radius = 128;
   var twoSigma2 = 2 * sigma * sigma;
   var n = radius * 2 + 1;
   var k = new Float64Array( n );
   var sum = 0;
   var i, x;
   for ( i = 0; i < n; ++i )
   {
      x = i - radius;
      k[i] = Math.exp( -(x * x) / twoSigma2 );
      sum += k[i];
   }
   if ( sum <= 0 )
      sum = 1;
   for ( i = 0; i < n; ++i )
      k[i] /= sum;
   return k;
}

function nmbMeanFeature( raw, feature )
{
   var n = (raw.length / NMB_NDIM) | 0;
   if ( n < 1 )
      return 0;
   var s = 0;
   for ( var i = 0; i < n; ++i )
      s += raw[i * NMB_NDIM + feature];
   return s / n;
}

// ----------------------------------------------------------------------------
// PixInsight view / image helpers.
// ----------------------------------------------------------------------------

function nmbHtml( text )
{
   return String( text ).replace( /&/g, "&amp;" ).replace( /</g, "&lt;" ).replace( />/g, "&gt;" );
}

function nmbErrorText( error )
{
   if ( !error )
      return "Unknown error.";
   if ( error.message )
      return String( error.message );
   return String( error );
}

function nmbAlert( message, isError )
{
   var icon = isError ? StdIcon.Error : StdIcon.Warning;
   (new MessageBox( "<p>" + nmbHtml( message ) + "</p>",
                    "Nebula Mask Builder",
                    icon,
                    StdButton.Ok )).execute();
}

function nmbIsRgbView( view )
{
   if ( !view || view.isNull )
      return false;
   var image = view.image;
   return image.isColor
       && image.colorSpace == ColorSpace.RGB
       && image.numberOfChannels >= 3
       && image.width > 0
       && image.height > 0;
}

function nmbAutoStretch( image )
{
   var shadowsClipping = -2.8;
   var targetBackground = 0.25;
   var ht = new HistogramTransformation;
   var h = [
      [ 0, 0.5, 1, 0, 1 ],
      [ 0, 0.5, 1, 0, 1 ],
      [ 0, 0.5, 1, 0, 1 ],
      [ 0, 0.5, 1, 0, 1 ],
      [ 0, 0.5, 1, 0, 1 ]
   ];
   // Linked stretch: one midtones balance for the whole RGB image, so the
   // preview does not invent a color cast while the user is sampling.
   image.resetSelections();
   var median = image.median();
   var mad = image.MAD( median ) * 1.4826;
   var c0 = Math.range( median + shadowsClipping * mad, 0, 1 );
   var x = median - c0;
   if ( !(x > 0) )
      x = 1.0e-6;
   var m = Math.mtf( targetBackground, x );
   if ( !isFinite( m ) || m <= 0 || m >= 1 )
      m = 0.5;
   h[3] = [ c0, m, 1, 0, 1 ];
   ht.H = h;
   ht.executeOn( image );
}

function nmbMakePreviewBitmap( view, autoStf )
{
   var work = new Image( view.image );
   var stretched = false;
   try
   {
      var longSide = work.width > work.height ? work.width : work.height;
      if ( longSide > NMB_PREVIEW_MAX )
         work.resample( NMB_PREVIEW_MAX / longSide );
      if ( autoStf )
      {
         try
         {
            nmbAutoStretch( work );
            stretched = true;
         }
         catch ( stretchError )
         {
            stretched = false;
         }
      }
      var bmp = work.render();
      if ( !stretched && view.window )
         view.window.applyColorTransformation( bmp );
      return bmp;
   }
   finally
   {
      work.free();
   }
}

function nmbCollectFromImage( image, marks )
{
   return nmbFeaturesFromIndices( nmbMarkIndices( image.width, image.height, marks ), image.width,
      function( x, y )
      {
         return {
            r: image.sample( x, y, 0 ),
            g: image.sample( x, y, 1 ),
            b: image.sample( x, y, 2 )
         };
      } );
}

function nmbClassifyView( image, model, sensitivity, onProgress )
{
   var width = image.width;
   var height = image.height;
   var nc = model.count;
   var masks = [];
   var c;
   for ( c = 0; c < nc; ++c )
      masks.push( new Float32Array( width * height ) );

   // About a million pixels per tile keeps the temporary RGB buffers small
   // while getSamples() still runs in native code.
   var tileRows = Math.max( 1, Math.min( height, Math.floor( 1000000 / width ) ) );
   var scratch = new Float64Array( NMB_NDIM );
   var probs = new Float64Array( nc );
   var bg = model.bgSlot;
   var y0, rows, n, R, G, B, rect, i, r, g, b, p;

   for ( y0 = 0; y0 < height; y0 += tileRows )
   {
      rows = Math.min( tileRows, height - y0 );
      n = width * rows;
      R = new Float64Array( n );
      G = new Float64Array( n );
      B = new Float64Array( n );
      rect = new Rect( 0, y0, width, y0 + rows );
      image.getSamples( R, rect, 0 );
      image.getSamples( G, rect, 1 );
      image.getSamples( B, rect, 2 );
      for ( i = 0; i < n; ++i )
      {
         r = R[i];
         g = G[i];
         b = B[i];
         p = y0 * width + i;
         if ( !isFinite( r ) || !isFinite( g ) || !isFinite( b ) )
         {
            masks[bg][p] = 1;
            continue;
         }
         nmbProbabilities( r, g, b, model, sensitivity, scratch, probs );
         for ( c = 0; c < nc; ++c )
            masks[c][p] = probs[c];
      }
      if ( onProgress && onProgress( Math.min( height, y0 + rows ) - 1, height ) === false )
         return null;
   }
   return masks;
}

function nmbRunOnView( image, marksByClass, sensitivity, onProgress )
{
   var rawByClass = [];
   var c;
   for ( c = 0; c < marksByClass.length; ++c )
   {
      if ( !marksByClass[c] || marksByClass[c].length === 0 )
         rawByClass.push( new Float64Array( 0 ) );
      else
         rawByClass.push( nmbCollectFromImage( image, marksByClass[c] ) );
   }
   var missing = [];
   for ( c = 0; c < 3; ++c )
      if ( rawByClass[c].length < NMB_NDIM )
         missing.push( NMB_CLASS_NAME[c] );
   if ( missing.length )
      return { error: "Mark at least one sample region for: " + missing.join( ", " ) + "." };

   var model = nmbFitModel( rawByClass );
   if ( !model )
      return { error: "The samples are not enough to separate the classes." };

   var masks = nmbClassifyView( image, model, sensitivity, onProgress );
   if ( !masks )
      return { aborted: true };
   return { model: model, masks: masks, rawByClass: rawByClass };
}

// Never close or overwrite an existing image, including previous output masks.
function nmbCloseForeignView( id, protectedView )
{
   var base = id, suffix = 1;
   while ( true )
   {
      var existing = View.viewById( id );
      if ( existing === null || existing.isNull ) return id;
      id = base + "_" + suffix++;
   }
}

function nmbPublishMask( id, samples, width, height, sigma, protectedView )
{
   var maskImage = new Image( samples, width, height, 1, ColorSpace.Gray );
   var win = null;
   var shown = false;
   try
   {
      if ( sigma > 0.05 )
      {
         var kernel = nmbGaussianKernel( sigma );
         maskImage.convolveSeparable( kernel, kernel );
      }
      maskImage.truncate( 0, 1 );
      id = nmbCloseForeignView( id, protectedView );
      win = new ImageWindow( width, height, 1, 32, true, false, id );
      var view = win.mainView;
      view.beginProcess( UndoFlag.NoSwapFile );
      try
      {
         view.image.assign( maskImage );
      }
      finally
      {
         view.endProcess();
      }
      win.show();
      shown = true;
      win.zoomToFit();
      return win;
   }
   catch ( error )
   {
      if ( !shown && win && !win.isNull )
         win.forceClose();
      throw error;
   }
   finally
   {
      maskImage.free();
   }
}

function nmbLogModel( result )
{
   var model = result.model;
   var c, id, raw, n;
   if(model.unmix)
      console.writeln( "HOO AUTO: sky-subtracted nonnegative H/O separation with noise rejection; brightness is not assigned to OIII by itself." );
   console.writeln( "Color model (chromaticity rn/bn, saturation, log channel ratios, luminance):" );
   for ( c = 0; c < model.count; ++c )
   {
      id = model.ids[c];
      raw = result.rawByClass[id];
      n = model.counts[c];
      console.writeln( NMB_CLASS_NAME[id] + format(
         ": %u px, rn=%.3f bn=%.3f sat=%.3f L=%.4g, shrinkage=%.2f",
         n,
         nmbMeanFeature( raw, 0 ),
         nmbMeanFeature( raw, 1 ),
         nmbMeanFeature( raw, 2 ),
         nmbMeanFeature( raw, 5 ),
         model.lambdas[c] ) );
   }
   if ( model.ids.indexOf( 3 ) < 0 )
      console.writeln( "No SII anchors: only Background, H-alpha and OIII masks are created." );
}

// ----------------------------------------------------------------------------
// Preview. Left click samples a disk. Right click deletes the nearest mark.
// Wheel zooms. Middle button, or Ctrl/Alt + left button, pans.
// ----------------------------------------------------------------------------

var NmbPreview = class extends Frame
{
   constructor( parent, owner )
   {
      super( parent );
      this.owner = owner;
      this.bitmap = null;
      this.scale = 1;
      this.minScale = 0.01;
      this.maxScale = 16;
      this.panning = false;
      this._fittedOnce = false;
      this.backBrush = new Brush( 0xff202020 );

      this.scrollbox = new ScrollBox( this );
      this.scrollbox.autoScroll = true;
      this.scrollbox.tracking = true;
      this.scrollbox.cursor = new Cursor( StdCursor.Cross );
      this.scrollbox.viewport.cursor = new Cursor( StdCursor.Cross );

      this.btnZoomIn = new ToolButton( this );
      this.btnZoomIn.icon = this.scaledResource( ":/icons/zoom-in.png" );
      this.btnZoomIn.setScaledFixedSize( 24, 24 );
      this.btnZoomIn.toolTip = "Zoom in";
      this.btnZoomIn.onMousePress = () => { this.updateZoom( this.scale * 1.25 ); };

      this.btnZoomOut = new ToolButton( this );
      this.btnZoomOut.icon = this.scaledResource( ":/icons/zoom-out.png" );
      this.btnZoomOut.setScaledFixedSize( 24, 24 );
      this.btnZoomOut.toolTip = "Zoom out";
      this.btnZoomOut.onMousePress = () => { this.updateZoom( this.scale / 1.25 ); };

      this.btnZoom11 = new ToolButton( this );
      this.btnZoom11.icon = this.scaledResource( ":/icons/zoom-1-1.png" );
      this.btnZoom11.setScaledFixedSize( 24, 24 );
      this.btnZoom11.toolTip = "Zoom 1:1";
      this.btnZoom11.onMousePress = () => { this.updateZoom( 1 ); };

      this.btnFit = new ToolButton( this );
      this.btnFit.icon = this.scaledResource( ":/toolbar/view-zoom-fit.png" );
      this.btnFit.setScaledFixedSize( 24, 24 );
      this.btnFit.toolTip = "Zoom to fit";
      this.btnFit.onMousePress = () => { this.zoomToFit(); };

      this.coordLabel = new Label( this );
      this.coordLabel.text = "";

      this.buttons = new HorizontalSizer;
      this.buttons.margin = 4;
      this.buttons.spacing = 4;
      this.buttons.add( this.btnZoomIn );
      this.buttons.add( this.btnZoomOut );
      this.buttons.add( this.btnZoom11 );
      this.buttons.add( this.btnFit );
      this.buttons.addSpacing( 12 );
      this.buttons.add( this.coordLabel );
      this.buttons.addStretch();

      var self = this;

      this.scrollbox.onHorizontalScrollPosUpdated = function()
      {
         self.scrollbox.viewport.update();
      };
      this.scrollbox.onVerticalScrollPosUpdated = function()
      {
         self.scrollbox.viewport.update();
      };

      this.scrollbox.viewport.onPaint = ( x0, y0, x1, y1 ) =>
      {
         var g = new Graphics( self.scrollbox.viewport );
         try
         {
            g.fillRect( x0, y0, x1, y1, self.backBrush );
            if ( !self.bitmap || !(self.scale > 0) )
               return;
            var vw = self.scrollbox.viewport.width;
            var vh = self.scrollbox.viewport.height;
            var iw = self.bitmap.width * self.scale;
            var ih = self.bitmap.height * self.scale;
            var ox = (vw - iw) / 2;
            var oy = (vh - ih) / 2;
            if ( self.scrollbox.maxHorizontalScrollPosition > 0 )
               ox = -self.scrollbox.horizontalScrollPosition;
            if ( self.scrollbox.maxVerticalScrollPosition > 0 )
               oy = -self.scrollbox.verticalScrollPosition;
            g.translateTransformation( ox, oy );
            g.scaleTransformation( self.scale, self.scale );
            g.drawBitmap( 0, 0, self.bitmap );
            g.antialiasing = true;
            if ( self.owner )
               self.owner.paintOverlay( g );
         }
         finally
         {
            g.end();
         }
      };

      this.scrollbox.viewport.onResize = () =>
      {
         if ( !self._fittedOnce && self.bitmap && self.scrollbox.viewport.width > 20 )
         {
            self._fittedOnce = true;
            self.zoomToFit();
         }
      };

      this.scrollbox.viewport.onMousePress = ( x, y, button, buttons, modifiers ) =>
      {
         if ( !self.owner || self.owner.busy )
            return;
         var pan = (button == MouseButton.Middle)
                || (button == MouseButton.Left && (modifiers & (KeyModifier.Control | KeyModifier.Alt)));
         if ( pan )
         {
            if ( self.owner )
               self.owner.setHover( null );
            self.panning = true;
            self.panCursor = new Point( x, y );
            self.panScroll = new Point( self.scrollbox.horizontalScrollPosition,
                                        self.scrollbox.verticalScrollPosition );
            self.scrollbox.viewport.cursor = new Cursor( StdCursor.ClosedHand );
            return;
         }
         var pt = self.viewportToImage( x, y );
         if ( !pt )
            return;
         if ( button == MouseButton.Right )
            self.owner.removeNearest( pt.x, pt.y );
         else if ( button == MouseButton.Left )
            self.owner.addMark( pt.x, pt.y );
      };

      this.scrollbox.viewport.onMouseMove = ( x, y, buttons, modifiers ) =>
      {
         if ( self.panning )
         {
            self.scrollbox.horizontalScrollPosition = self.panScroll.x - (x - self.panCursor.x);
            self.scrollbox.verticalScrollPosition = self.panScroll.y - (y - self.panCursor.y);
            self.scrollbox.viewport.update();
            return;
         }
         var pt = self.viewportToImage( x, y );
         if ( self.owner )
            self.owner.setHover( pt );
         self.coordLabel.text = pt ? format( "x = %.0f    y = %.0f", pt.x, pt.y ) : "";
      };

      this.scrollbox.viewport.onMouseRelease = ( x, y, button, buttons, modifiers ) =>
      {
         if ( !self.panning )
            return;
         self.panning = false;
         self.scrollbox.viewport.cursor = new Cursor( StdCursor.Cross );
         self.scrollbox.viewport.update();
      };

      this.scrollbox.viewport.onMouseWheel = ( x, y, delta, buttons, modifiers ) =>
      {
         var notches = delta;
         if ( Math.abs( delta ) >= 40 )
            notches = delta / 120;
         var speed = (modifiers & KeyModifier.Control) ? 1.35 : 1.15;
         self.updateZoom( self.scale * Math.pow( speed, notches ), new Point( x, y ) );
      };

      this.scrollbox.viewport.onLeave = () =>
      {
         if ( self.owner )
            self.owner.setHover( null );
         self.coordLabel.text = "";
         return false;
      };

      this.sizer = new VerticalSizer;
      this.sizer.margin = 0;
      this.sizer.spacing = 0;
      this.sizer.add( this.buttons );
      this.sizer.add( this.scrollbox );
      this.setScaledMinSize( 760, 560 );
   }

   setImage( bitmap )
   {
      this.bitmap = bitmap;
      this._fittedOnce = false;
      if ( this.scrollbox.viewport.width > 20 && this.scrollbox.viewport.height > 20 )
      {
         this._fittedOnce = true;
         this.zoomToFit();
      }
      else
         this.scrollbox.viewport.update();
   }

   forceRedraw()
   {
      this.scrollbox.viewport.update();
   }

   _computeMinScale()
   {
      if ( !this.bitmap )
         return 0.01;
      var vw = this.scrollbox.viewport.width;
      var vh = this.scrollbox.viewport.height;
      if ( vw <= 1 || vh <= 1 )
         return 0.01;
      var fit = Math.min( vw / this.bitmap.width, vh / this.bitmap.height );
      return fit > 0.0001 ? fit : 0.0001;
   }

   _updateScrollBounds()
   {
      if ( !this.bitmap )
         return;
      this.minScale = this._computeMinScale();
      var w = this.bitmap.width * this.scale;
      var h = this.bitmap.height * this.scale;
      this.scrollbox.maxHorizontalScrollPosition = Math.max( 0, w - this.scrollbox.viewport.width );
      this.scrollbox.maxVerticalScrollPosition = Math.max( 0, h - this.scrollbox.viewport.height );
   }

   updateZoom( newScale, anchor )
   {
      if ( !this.bitmap )
         return;
      var oldScale = this.scale > 0 ? this.scale : 1;
      this.minScale = this._computeMinScale();
      var scale = newScale;
      if ( scale < this.minScale )
         scale = this.minScale;
      if ( scale > this.maxScale )
         scale = this.maxScale;
      var ax = this.scrollbox.viewport.width / 2;
      var ay = this.scrollbox.viewport.height / 2;
      if ( anchor )
      {
         ax = anchor.x;
         ay = anchor.y;
      }
      var sx = (ax + this.scrollbox.horizontalScrollPosition) / oldScale;
      var sy = (ay + this.scrollbox.verticalScrollPosition) / oldScale;
      this.scale = scale;
      this._updateScrollBounds();
      this.scrollbox.horizontalScrollPosition = sx * this.scale - ax;
      this.scrollbox.verticalScrollPosition = sy * this.scale - ay;
      this.scrollbox.viewport.update();
   }

   zoomToFit()
   {
      if ( !this.bitmap )
         return;
      var vw = this.scrollbox.viewport.width;
      var vh = this.scrollbox.viewport.height;
      if ( vw <= 1 || vh <= 1 )
         return;
      this.scale = Math.min( vw / this.bitmap.width, vh / this.bitmap.height );
      if ( !(this.scale > 0) )
         this.scale = 1;
      this._updateScrollBounds();
      this.scrollbox.horizontalScrollPosition = 0;
      this.scrollbox.verticalScrollPosition = 0;
      this.scrollbox.viewport.update();
   }

   viewportToImage( x, y )
   {
      if ( !this.bitmap || !this.owner || !(this.owner.fullWidth > 0) || !(this.scale > 0) )
         return null;
      var vw = this.scrollbox.viewport.width;
      var vh = this.scrollbox.viewport.height;
      var iw = this.bitmap.width * this.scale;
      var ih = this.bitmap.height * this.scale;
      var ox = (vw - iw) / 2;
      var oy = (vh - ih) / 2;
      if ( this.scrollbox.maxHorizontalScrollPosition > 0 )
         ox = -this.scrollbox.horizontalScrollPosition;
      if ( this.scrollbox.maxVerticalScrollPosition > 0 )
         oy = -this.scrollbox.verticalScrollPosition;
      var bx = (x - ox) / this.scale;
      var by = (y - oy) / this.scale;
      if ( bx < 0 || by < 0 || bx >= this.bitmap.width || by >= this.bitmap.height )
         return null;
      return {
         x: bx * this.owner.fullWidth / this.bitmap.width,
         y: by * this.owner.fullHeight / this.bitmap.height
      };
   }
};

// ----------------------------------------------------------------------------
// Dialog.
// ----------------------------------------------------------------------------

var NmbDialog = class extends Dialog
{
   constructor()
   {
      super();
      this.windowTitle = "Nebula Mask Builder " + NMB_VERSION;
      this.userResizable = true;
      this.busy = false;
      this.fullWidth = 0;
      this.fullHeight = 0;
      this.targetView = null;
      this.currentClass = 0;
      this.hover = null;
      this._shown = false;
      this.marks = [ [], [], [], [] ];

      this.markPens = [];
      this.markBrushes = [];
      for ( var c = 0; c < 4; ++c )
      {
         this.markPens.push( new Pen( NMB_CLASS_COLOR[c], 0 ) );
         this.markBrushes.push( new Brush( NMB_CLASS_FILL[c] ) );
      }

      this.preview = new NmbPreview( this, this );

      this.info = new Label( this );
      this.info.useRichText = true;
      this.info.wordWrapping = true;
      this.info.scaledMinWidth = 320;
      this.info.scaledMaxWidth = 420;
      this.info.text =
         "<b>Nebula Mask Builder</b><br/>" +
         "Left-click samples a disk. Right-click removes the nearest sample of the current class. " +
         "Wheel zooms. Ctrl+drag or the middle button pans.<br/><br/>" +
         "Classification uses normalized RGB, saturation and channel ratios. " +
         "Luminance is only a weak cue, so faint OIII stays OIII. " +
         "AUTO finds color anchors using the selected HOO or SHO palette. " +
         "SII requires SHO or manual samples. Min region removes small islands before mask blur.";

      this.viewLabel = new Label( this );
      this.viewLabel.text = "Target:";
      this.viewLabel.textAlignment = TextAlignment.Right | TextAlignment.VertCenter;

      this.viewList = new ViewList( this );
      this.viewList.toolTip = "Open RGB image to classify.";
      this.viewList.onViewSelected = ( view ) =>
      {
         if ( this._loading )
            return;
         this.loadTarget( view, true );
      };

      this.viewRow = new HorizontalSizer;
      this.viewRow.spacing = 6;
      this.viewRow.add( this.viewLabel );
      this.viewRow.add( this.viewList, 100 );

      this.autoStfCheck = new CheckBox( this );
      this.autoStfCheck.text = "Auto STF preview";
      this.autoStfCheck.checked = true;
      this.autoStfCheck.toolTip = "Linked screen stretch for the preview only. Masks are computed from the original pixels. Uncheck to use the target window's own STF.";
      this.autoStfCheck.onClick = () => { this.rebuildPreview( true ); };

      this.classGroup = new GroupBox( this );
      this.classGroup.title = "Sample class";
      this.classGroup.sizer = new VerticalSizer;
      this.classGroup.sizer.margin = 6;
      this.classGroup.sizer.spacing = 4;

      this.classRadios = [];
      this.countLabels = [];
      for ( var i = 0; i < 4; ++i )
      {
         let classId = i;
         let radio = new RadioButton( this.classGroup );
         radio.text = NMB_CLASS_NAME[i];
         radio.checked = (i === 0);
         radio.onClick = () =>
         {
            this.currentClass = classId;
            this.preview.forceRedraw();
         };
         let count = new Label( this.classGroup );
         count.text = "0";
         count.toolTip = "Number of sample disks in this class.";
         let clearButton = new PushButton( this.classGroup );
         clearButton.text = "Clear";
         clearButton.toolTip = "Remove every sample of this class.";
         clearButton.onClick = () =>
         {
            this.marks[classId] = [];
            this.updateCounts();
            this.preview.forceRedraw();
         };
         let row = new HorizontalSizer;
         row.spacing = 6;
         row.add( radio );
         row.addStretch();
         row.add( count );
         row.add( clearButton );
         this.classGroup.sizer.add( row );
         this.classRadios.push( radio );
         this.countLabels.push( count );
      }

      this.palette = new ComboBox( this );
      this.palette.addItem( "HOO / warm H-alpha, cool-white OIII" );
      this.palette.addItem( "SHO / R=SII, G=H-alpha, B=OIII" );
      this.palette.toolTip = "Select the actual channel mapping. AUTO estimates color regions, not chemical abundances.";

      this.integrityControl = new NumericControl( this );
      this.configureNumeric( this.integrityControl, "Min region (px):", false, 0, 0, 10000, 16,
         "Reassign connected winner regions smaller than this area to their strongest boundary class. 0 disables cleanup; small real structures can also be removed." );

      this.autoButton = new PushButton( this );
      this.autoButton.text = "AUTO";
      this.autoButton.toolTip = "Find robust color anchors for the selected palette and create all supported masks. Manual marks are kept.";
      this.autoButton.onClick = () => { this.onGetMasks( true ); };

      this.radiusControl = new NumericControl( this );
      this.configureNumeric( this.radiusControl, "Sample radius:", false, 0, 1, 200, 12,
         "Radius, in source pixels, of each sample disk. The click is the center." );

      this.sensitivityControl = new NumericControl( this );
      this.configureNumeric( this.sensitivityControl, "Sensitivity:", true, 2, 0.1, 12, 1.5,
         "Manual/SHO classifier temperature. HOO AUTO uses nonnegative signal separation and estimated noise instead." );

      this.smoothControl = new NumericControl( this );
      this.configureNumeric( this.smoothControl, "Mask blur (sigma):", true, 1, 0, 64, 2,
         "Gaussian sigma in pixels applied to each mask after classification. 0 leaves the masks unsmoothed." );

      this.getMasksButton = new PushButton( this );
      this.getMasksButton.text = "Get Masks";
      this.getMasksButton.toolTip = "Classify the whole target and create Ha_mask, OIII_mask and Background_mask.";
      this.getMasksButton.onClick = () => { this.onGetMasks(); };

      this.closeButton = new PushButton( this );
      this.closeButton.text = "Close";
      this.closeButton.onClick = () => { this.cancel(); };

      this.buttonRow = new HorizontalSizer;
      this.buttonRow.spacing = 6;
      this.buttonRow.add( this.autoButton );
      this.buttonRow.add( this.getMasksButton );
      this.buttonRow.addStretch();
      this.buttonRow.add( this.closeButton );

      this.status = new Label( this );
      this.status.wordWrapping = true;
      this.status.scaledMinWidth = 320;
      this.status.scaledMaxWidth = 420;
      this.status.text = "Open an RGB image, then select it as the target.";

      this.right = new Control( this );
      this.right.sizer = new VerticalSizer;
      this.right.sizer.margin = 8;
      this.right.sizer.spacing = 8;
      this.right.setScaledMinWidth( 380 );
      this.right.sizer.add( this.info );
      this.right.sizer.add( this.viewRow );
      this.right.sizer.add( this.autoStfCheck );
      this.right.sizer.add( this.classGroup );
      this.right.sizer.add( this.palette );
      this.right.sizer.add( this.integrityControl );
      this.right.sizer.add( this.radiusControl );
      this.right.sizer.add( this.sensitivityControl );
      this.right.sizer.add( this.smoothControl );
      this.right.sizer.add( this.buttonRow );
      this.right.sizer.add( this.status );
      this.right.sizer.addStretch();

      this.sizer = new HorizontalSizer;
      this.sizer.margin = 6;
      this.sizer.spacing = 6;
      this.sizer.add( this.preview, 100 );
      this.sizer.add( this.right );

      this.onShow = () =>
      {
         if ( this._shown )
            return;
         this._shown = true;
         this.loadInitialView();
      };
   }

   configureNumeric( control, label, real, precision, lo, hi, value, tip )
   {
      control.label.text = label;
      control.toolTip = tip;
      control.label.toolTip = tip;
      control.setReal( real );
      if ( real )
         control.setPrecision( precision );
      control.setRange( lo, hi );
      control.setValue( value );
      control.label.setScaledMinWidth( 130 );
   }

   loadInitialView()
   {
      var initial = null;
      if ( Parameters.isViewTarget && Parameters.targetView && !Parameters.targetView.isNull )
         initial = Parameters.targetView;
      else if ( !ImageWindow.activeWindow.isNull )
         initial = ImageWindow.activeWindow.currentView;

      this._loading = true;
      this.viewList.getMainViews();
      if ( initial && !initial.isNull )
         this.viewList.currentView = initial;
      this._loading = false;

      var selected = this.viewList.currentView;
      if ( selected && !selected.isNull )
         this.loadTarget( selected, false );
   }

   loadTarget( view, interactive )
   {
      if ( !view || view.isNull )
      {
         this.clearTarget();
         return;
      }
      if ( !nmbIsRgbView( view ) )
      {
         this.status.text = "The target must be an RGB color image.";
         if ( interactive )
            nmbAlert( "Select an RGB image. Grayscale and non-RGB color spaces cannot be sampled.", false );
         return;
      }

      var same = this.targetView
              && !this.targetView.isNull
              && view.id === this.targetView.id
              && this.fullWidth === view.image.width
              && this.fullHeight === view.image.height;
      if ( !same )
      {
         this.marks = [ [], [], [], [] ];
         this.updateCounts();
      }
      this.targetView = view;
      this.fullWidth = view.image.width;
      this.fullHeight = view.image.height;
      this.rebuildPreview( interactive );
   }

   clearTarget()
   {
      this.targetView = null;
      this.fullWidth = 0;
      this.fullHeight = 0;
      this.hover = null;
      this.preview.setImage( null );
      this.status.text = "Open an RGB image, then select it as the target.";
   }

   rebuildPreview( interactive )
   {
      if ( !this.targetView || this.targetView.isNull || !nmbIsRgbView( this.targetView ) )
         return;
      this.status.text = "Building preview...";
      CoreApplication.processEvents();
      try
      {
         var bmp = nmbMakePreviewBitmap( this.targetView, this.autoStfCheck.checked );
         this.preview.setImage( bmp );
         this.status.text = this.targetView.id + format( "  %u x %u. Click the preview to sample the selected class.",
                                                         this.fullWidth, this.fullHeight );
         this.updateCounts();
      }
      catch ( error )
      {
         this.status.text = nmbErrorText( error );
         if ( interactive )
            nmbAlert( nmbErrorText( error ), true );
      }
   }

   updateCounts()
   {
      for ( var c = 0; c < 4; ++c )
         this.countLabels[c].text = String( this.marks[c].length );
   }

   addMark( x, y )
   {
      if ( this.busy || !(this.fullWidth > 0) )
         return;
      var classId = this.currentClass;
      if ( this.marks[classId].length >= NMB_MAX_MARKS )
      {
         this.status.text = NMB_CLASS_NAME[classId] + " already has " + NMB_MAX_MARKS + " samples.";
         return;
      }
      var radius = this.radiusControl.value;
      if ( !(radius >= 1) )
         radius = 1;
      this.marks[classId].push( { x: x, y: y, r: radius } );
      this.updateCounts();
      this.status.text = NMB_CLASS_NAME[classId] + format( " sample at (%.0f, %.0f), radius %.0f.", x, y, radius );
      this.preview.forceRedraw();
   }

   removeNearest( x, y )
   {
      if ( this.busy )
         return;
      var classId = this.currentClass;
      var list = this.marks[classId];
      var best = -1;
      var bestD = 1.0e300;
      for ( var i = 0; i < list.length; ++i )
      {
         var dx = list[i].x - x;
         var dy = list[i].y - y;
         var d = dx * dx + dy * dy;
         if ( d < bestD )
         {
            bestD = d;
            best = i;
         }
      }
      if ( best < 0 )
         return;
      var limit = Math.max( 24, list[best].r * 2 );
      if ( bestD > limit * limit )
         return;
      list.splice( best, 1 );
      this.updateCounts();
      this.preview.forceRedraw();
   }

   setHover( pt )
   {
      var changed = false;
      if ( !pt && this.hover )
         changed = true;
      else if ( pt && !this.hover )
         changed = true;
      else if ( pt && this.hover && (Math.abs( pt.x - this.hover.x ) > 0.5 || Math.abs( pt.y - this.hover.y ) > 0.5) )
         changed = true;
      this.hover = pt;
      if ( changed )
         this.preview.forceRedraw();
   }

   paintOverlay( g )
   {
      if ( !this.preview.bitmap || !(this.fullWidth > 0) || !(this.fullHeight > 0) )
         return;
      var sx = this.preview.bitmap.width / this.fullWidth;
      var sy = this.preview.bitmap.height / this.fullHeight;
      var c, i, marks, x, y, rx, ry;
      for ( c = 0; c < 4; ++c )
      {
         marks = this.marks[c];
         g.pen = this.markPens[c];
         for ( i = 0; i < marks.length; ++i )
         {
            x = marks[i].x * sx;
            y = marks[i].y * sy;
            rx = marks[i].r * sx;
            ry = marks[i].r * sy;
            if ( rx < 0.75 ) rx = 0.75;
            if ( ry < 0.75 ) ry = 0.75;
            g.fillEllipse( x - rx, y - ry, x + rx, y + ry, this.markBrushes[c] );
            g.drawEllipse( x - rx, y - ry, x + rx, y + ry );
         }
      }
      if ( !this.hover )
         return;
      c = this.currentClass;
      var hr = this.radiusControl.value;
      if ( !(hr >= 1) )
         hr = 1;
      x = this.hover.x * sx;
      y = this.hover.y * sy;
      rx = hr * sx;
      ry = hr * sy;
      if ( rx < 0.75 ) rx = 0.75;
      if ( ry < 0.75 ) ry = 0.75;
      g.pen = this.markPens[c];
      g.drawEllipse( x - rx, y - ry, x + rx, y + ry );
   }

   onGetMasks( automatic )
   {
      if ( this.busy )
         return;
      if ( !this.targetView || this.targetView.isNull || !nmbIsRgbView( this.targetView ) )
      {
         nmbAlert( "Select an open RGB image first.", false );
         return;
      }
      var image = this.targetView.image;
      var width = image.width;
      var height = image.height;
      var n = width * height;
      if ( n > NMB_MAX_PIXELS )
      {
         nmbAlert( "This image has more than 100 megapixels. Crop or bin it, then run the script again.", false );
         return;
      }

      var marks = [];
      for ( var c = 0; c < 4; ++c )
         marks.push( this.marks[c].slice() );

      var sensitivity = this.sensitivityControl.value;
      if ( !(sensitivity > 0) )
         sensitivity = 1.5;
      var sigma = this.smoothControl.value;
      if ( !(sigma >= 0) )
         sigma = 0;

      this.busy = true;
      this.getMasksButton.enabled = false;
      this.autoButton.enabled = false;
      this.status.text = "Reading sample disks...";
      console.show();
      console.abortEnabled = true;
      var t0 = Date.now();
      try
      {
         console.writeln( "<end><cbr><br><b>Nebula Mask Builder " + NMB_VERSION + "</b>" );
         console.writeln( "Target: " + this.targetView.id + format( " (%u x %u)", width, height ) );
         console.writeln( format( "Sensitivity = %.3f, smoothness = %.2f px", sensitivity, sigma ) );
         console.writeln( "Reading sample disks..." );
         CoreApplication.processEvents();

         var result = automatic
            ? nmbAutoModel( image, this.palette.currentItem )
            : null;
         if ( !automatic ) result = nmbRunOnView( image, marks, sensitivity,
            ( y, rows ) =>
            {
               if ( console.abortRequested )
                  return false;
               this.status.text = format( "Classifying... %d%%", Math.round( 100 * (y + 1) / rows ) );
               CoreApplication.processEvents();
               return true;
            } );
         if ( automatic && !result.error )
         {
            result.masks = nmbClassifyView( image, result.model, sensitivity, ( y, rows ) =>
            {
               this.status.text = format( "AUTO classifying... %d%%", Math.round(100*(y+1)/rows) );
               CoreApplication.processEvents();
               return !console.abortRequested;
            } );
            if ( !result.masks ) result.aborted = true;
         }
         if ( !result )
            throw new Error( "Classification failed." );
         if ( result.aborted )
            throw new Error( "NMB_ABORT" );
         if ( result.error )
         {
            this.status.text = result.error;
            nmbAlert( result.error, false );
            return;
         }

         if ( automatic && !nmbSpatialConsensus( result.masks, width, height,
              () => { CoreApplication.processEvents(); return !console.abortRequested; } ) )
            throw new Error( "NMB_ABORT" );
         this.status.text = "Cleaning connected regions...";
         CoreApplication.processEvents();
         if ( !nmbCleanRegions( result.masks, width, height, this.integrityControl.value,
              () => { CoreApplication.processEvents(); return !console.abortRequested; } ) )
            throw new Error( "NMB_ABORT" );
         nmbLogModel( result );
         console.writeln( "Writing masks..." );
         CoreApplication.processEvents();

         var model = result.model;
         var written = [];
         for ( var slot = 0; slot < model.count; ++slot )
         {
            var classId = model.ids[slot];
            if ( console.abortRequested )
               throw new Error( "NMB_ABORT" );
            nmbPublishMask( NMB_MASK_ID[classId], result.masks[slot], width, height, sigma, this.targetView );
            written.push( NMB_MASK_ID[classId] );
         }

         var seconds = (Date.now() - t0) / 1000;
         console.writeln( format( "Created %d mask(s) in %.1f s.", written.length, seconds ) );
         this.status.text = "Created " + written.join( ", " ) + format( " in %.1f s.", seconds );
         if ( this.targetView && this.targetView.window )
            this.targetView.window.bringToFront();
      }
      catch ( error )
      {
         if ( nmbErrorText( error ) === "NMB_ABORT" )
         {
            console.writeln( "Cancelled." );
            this.status.text = "Cancelled.";
         }
         else
         {
            console.criticalln( nmbErrorText( error ) );
            this.status.text = nmbErrorText( error );
            nmbAlert( nmbErrorText( error ), true );
         }
      }
      finally
      {
         console.abortEnabled = false;
         this.busy = false;
         this.getMasksButton.enabled = true;
         this.autoButton.enabled = true;
      }
   }
};

function main()
{
   var dialog = new NmbDialog();
   dialog.execute();
}

main();
