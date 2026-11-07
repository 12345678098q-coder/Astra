/*
 * Palette Mixer for PixInsight 1.8.5
 *
 * Скрипт: сборка палитры через PixelMath.
 * Предпросмотр — в диалоге и на Preview исходного кадра.
 *
 * Script > Utilities > Palette Mixer
 */

#feature-id    Utilities > Palette Mixer
#feature-info  Палитры SHO/HOO и свои коэффициенты через PixelMath. \
               Предпросмотр на Preview и в окне скрипта.

#include <pjsr/Sizer.jsh>
#include <pjsr/FrameStyle.jsh>
#include <pjsr/TextAlign.jsh>
#include <pjsr/StdButton.jsh>
#include <pjsr/StdIcon.jsh>
#include <pjsr/UndoFlag.jsh>
#include <pjsr/DataType.jsh>
#include <pjsr/ColorSpace.jsh>
#include <pjsr/SampleType.jsh>
#include "NonModal.jsh"

#ifndef DataType_Int32
#define DataType_Int32 4
#endif
#ifndef DataType_Float
#define DataType_Float 10
#endif
#ifndef DataType_Boolean
#define DataType_Boolean 1
#endif
#ifndef DataType_String
#define DataType_String 15
#endif
#ifndef ColorSpace_Gray
#define ColorSpace_Gray 0
#endif
#ifndef ColorSpace_RGB
#define ColorSpace_RGB 1
#endif
#ifndef SampleType_Real
#define SampleType_Real 1
#endif

#define VERSION "1.1.0"
#define SETTINGS_KEY "PaletteMixer"
#define PREVIEW_ID "Palette"
#define PREVIEW_MAX_W 420
#define PREVIEW_MAX_H 280

function formatFloat(value, precision)
{
   var p = Math.pow(10, precision);
   return format("%.*f", precision, Math.round(value * p) / p);
}

function parseCoeff(edit)
{
   var x = parseFloat(edit.text);
   if (isNaN(x))
      x = 0;
   return x;
}

function uniqueId(base)
{
   var id = base;
   var n = 1;
   while (true)
   {
      try
      {
         var v = View.viewById(id);
         if (!v || v.isNull)
            return id;
      }
      catch (e)
      {
         return id;
      }
      ++n;
      id = base + format("_%d", n);
      if (n > 50)
         return base + "_x";
   }
}

function sameSize(a, b)
{
   return a.width == b.width && a.height == b.height;
}

function coeffExpr(k, name)
{
   if (Math.abs(k) < 0.00001)
      return "";
   return formatFloat(k, 4) + "*" + name;
}

function joinTerms(parts)
{
   var out = "";
   var i;
   for (i = 0; i < parts.length; ++i)
   {
      if (!parts[i].length)
         continue;
      if (!out.length)
         out = parts[i];
      else
         out += "+" + parts[i];
   }
   if (!out.length)
      out = "0";
   return out;
}

function mtf(m, x)
{
   if (x <= 0)
      return 0;
   if (x >= 1)
      return 1;
   try
   {
      return Math.mtf(m, x);
   }
   catch (e)
   {
      if (Math.abs(m - 0.5) < 1.0e-6)
         return x;
      return ((m - 1) * x) / (((2 * m - 1) * x) - m);
   }
}

function findMidtonesBalance(v0, v1)
{
   if (v1 <= 0)
      return 0;
   if (v1 >= 1)
      return 1;
   if (v0 < 0)
      v0 = 0;
   if (v0 > 1)
      v0 = 1;
   var m0, m1, m, v, n;
   if (v1 < v0)
   {
      m0 = 0;
      m1 = 0.5;
   }
   else
   {
      m0 = 0.5;
      m1 = 1;
   }
   for (n = 0; n < 40; ++n)
   {
      m = (m0 + m1) / 2;
      v = mtf(m, v1);
      if (Math.abs(v - v0) < 5.0e-5)
         return m;
      if (v < v0)
         m1 = m;
      else
         m0 = m;
   }
   return (m0 + m1) / 2;
}

function viewOk(v)
{
   return v && !v.isNull;
}

function mainViewOf(view)
{
   return view.window.mainView;
}

function centerRect(image)
{
   var w = image.width;
   var h = image.height;
   var pw = Math.round(w * 0.4);
   var ph = Math.round(h * 0.4);
   if (pw < 160)
      pw = Math.min(160, w);
   if (ph < 160)
      ph = Math.min(160, h);
   if (pw > w)
      pw = w;
   if (ph > h)
      ph = h;
   var x0 = Math.round((w - pw) / 2);
   var y0 = Math.round((h - ph) / 2);
   return new Rect(x0, y0, x0 + pw, y0 + ph);
}

function previewRectOf(view)
{
   var win = view.window;
   if (view.isPreview)
   {
      try { return win.previewRect(view); }
      catch (e) {}
   }
   try
   {
      if (viewOk(win.selectedPreview))
         return win.previewRect(win.selectedPreview);
   }
   catch (e2) {}
   try
   {
      var pal = win.previewById(PREVIEW_ID);
      if (viewOk(pal))
         return win.previewRect(pal);
   }
   catch (e3) {}
   try
   {
      if (win.previews && win.previews.length > 0)
         return win.previewRect(win.previews[0]);
   }
   catch (e4) {}
   return centerRect(win.mainView.image);
}

function extractPlane(image, channel, rect)
{
   image.resetSelections();
   if (rect)
      image.selectedRect = rect;
   if (image.numberOfChannels > 1 && channel >= 0)
      image.selectedChannel = channel;
   var out = new Image;
   out.assign(image);
   image.resetSelections();
   return out;
}

function fitImage(img, maxW, maxH)
{
   if (img.width <= maxW && img.height <= maxH)
      return;
   var sx = maxW / img.width;
   var sy = maxH / img.height;
   var s = sx < sy ? sx : sy;
   if (s < 0.999)
      img.resample(s);
}

function mixRGB(imgA, imgB, imgC, matrix, doRescale)
{
   var w = imgA.width;
   var h = imgA.height;
   var rgb = new Image(w, h, 3, ColorSpace_RGB, 32, SampleType_Real);
   var x, y, a, b, c, r, g, bl;
   for (y = 0; y < h; ++y)
   {
      for (x = 0; x < w; ++x)
      {
         a = imgA.sample(x, y, 0);
         b = imgB.sample(x, y, 0);
         c = imgC.sample(x, y, 0);
         r  = matrix[0][0] * a + matrix[0][1] * b + matrix[0][2] * c;
         g  = matrix[1][0] * a + matrix[1][1] * b + matrix[1][2] * c;
         bl = matrix[2][0] * a + matrix[2][1] * b + matrix[2][2] * c;
         rgb.setSample(r,  x, y, 0);
         rgb.setSample(g,  x, y, 1);
         rgb.setSample(bl, x, y, 2);
      }
   }
   if (doRescale)
   {
      try { rgb.rescale(); }
      catch (e) {}
   }
   else
   {
      try { rgb.truncate(); }
      catch (e2) {}
   }
   return rgb;
}

function autoStretchImage(img)
{
   img.resetSelections();
   var median = img.median();
   var avgDev = img.avgDev();
   if (!(avgDev > 0))
      return;
   var c0 = median - 1.25 * avgDev;
   if (c0 < 0)
      c0 = 0;
   if (c0 > 0.95)
      c0 = 0.95;
   var m = findMidtonesBalance(0.25, median - c0);
   var w = img.width;
   var h = img.height;
   var n = img.numberOfChannels;
   var x, y, ch, v, d;
   d = 1 - c0;
   if (d < 1.0e-6)
      d = 1.0e-6;
   for (ch = 0; ch < n; ++ch)
   {
      for (y = 0; y < h; ++y)
      {
         for (x = 0; x < w; ++x)
         {
            v = (img.sample(x, y, ch) - c0) / d;
            if (v < 0)
               v = 0;
            if (v > 1)
               v = 1;
            img.setSample(mtf(m, v), x, y, ch);
         }
      }
   }
}

function makeGraphics(control)
{
   try { return new Graphics(control); }
   catch (e) { return new VectorGraphics(control); }
}

function PreviewFrame(parent)
{
   this.__base__ = Frame;
   this.__base__(parent);
   this.bitmap = null;
   this.frameStyle = FrameStyle_Box;
   this.setMinWidth(320);
   this.setMinHeight(240);

   this.setBitmap = function(bmp)
   {
      this.bitmap = bmp;
      this.update();
   };

   this.onPaint = function()
   {
      var g = makeGraphics(this);
      g.fillRect(this.boundsRect, new Brush(0xff202020));
      if (this.bitmap && this.bitmap.width > 0)
      {
         var x = Math.round((this.width - this.bitmap.width) / 2);
         var y = Math.round((this.height - this.bitmap.height) / 2);
         g.drawBitmap(x, y, this.bitmap);
      }
      g.end();
   };
}

PreviewFrame.prototype = new Frame;

function PaletteDialog()
{
   this.__base__ = Dialog;
   this.__base__();
   var self = this;
   this.windowTitle = "Palette Mixer  " + VERSION;
   this.userResizable = true;

   this.help = new Label(this);
   this.help.wordWrapping = true;
   this.help.useRichText = true;
   this.help.text =
      "<b>Скрипт палитр через PixelMath.</b> " +
      "Предпросмотр считает смесь на Preview кадра (если превью нет — создаст Palette по центру). " +
      "Окно не блокирует PixInsight: кадры можно двигать и править, не закрывая скрипт. " +
      "Коэффициенты можно крутить и сразу смотреть. Собрать — полный кадр.";

   this.modeLabel = new Label(this);
   this.modeLabel.text = "Источник:";
   this.modeLabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.modeCombo = new ComboBox(this);
   this.modeCombo.addItem("Три моно канала (Ha / OIII / SII)");
   this.modeCombo.addItem("Один RGB (разобрать на каналы)");
   this.modeCombo.onItemSelected = function()
   {
      self.updateMode();
      self.refreshDialogPreview();
   };
   this.modeSizer = new HorizontalSizer;
   this.modeSizer.spacing = 8;
   this.modeSizer.add(this.modeLabel);
   this.modeSizer.add(this.modeCombo, 100);

   this.viewALabel = new Label(this);
   this.viewALabel.text = "A = Ha / R:";
   this.viewALabel.minWidth = 90;
   this.viewALabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.viewA = new ViewList(this);
   try { this.viewA.getAll(); } catch (e) { this.viewA.getMainViews(); }

   this.viewBLabel = new Label(this);
   this.viewBLabel.text = "B = OIII / G:";
   this.viewBLabel.minWidth = 90;
   this.viewBLabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.viewB = new ViewList(this);
   try { this.viewB.getAll(); } catch (e) { this.viewB.getMainViews(); }

   this.viewCLabel = new Label(this);
   this.viewCLabel.text = "C = SII / B:";
   this.viewCLabel.minWidth = 90;
   this.viewCLabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.viewC = new ViewList(this);
   try { this.viewC.getAll(); } catch (e) { this.viewC.getAll(); }

   this.rgbLabel = new Label(this);
   this.rgbLabel.text = "RGB кадр:";
   this.rgbLabel.minWidth = 90;
   this.rgbLabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.rgbView = new ViewList(this);
   try { this.rgbView.getAll(); } catch (e) { this.rgbView.getMainViews(); }
   if (!ImageWindow.activeWindow.isNull)
      this.rgbView.currentView = ImageWindow.activeWindow.currentView;

   function hookView(list)
   {
      try
      {
         list.onViewSelected = function() { self.refreshDialogPreview(); };
      }
      catch (e) {}
   }
   hookView(this.viewA);
   hookView(this.viewB);
   hookView(this.viewC);
   hookView(this.rgbView);

   this.rowA = new HorizontalSizer;
   this.rowA.spacing = 8;
   this.rowA.add(this.viewALabel);
   this.rowA.add(this.viewA, 100);
   this.rowB = new HorizontalSizer;
   this.rowB.spacing = 8;
   this.rowB.add(this.viewBLabel);
   this.rowB.add(this.viewB, 100);
   this.rowC = new HorizontalSizer;
   this.rowC.spacing = 8;
   this.rowC.add(this.viewCLabel);
   this.rowC.add(this.viewC, 100);
   this.rowRGB = new HorizontalSizer;
   this.rowRGB.spacing = 8;
   this.rowRGB.add(this.rgbLabel);
   this.rowRGB.add(this.rgbView, 100);

   this.presetLabel = new Label(this);
   this.presetLabel.text = "Палитра:";
   this.presetLabel.textAlignment = TextAlign_Right | TextAlign_VertCenter;
   this.presetCombo = new ComboBox(this);
   this.presetNames = [
      "RGB / как есть",
      "HOO",
      "SHO Hubble",
      "HOS",
      "HSO",
      "OSH",
      "Forte",
      "CFHT",
      "Dynamic SHO"
   ];
   var p;
   for (p = 0; p < this.presetNames.length; ++p)
      this.presetCombo.addItem(this.presetNames[p]);
   this.presetCombo.onItemSelected = function()
   {
      self.applyPreset(self.presetCombo.currentItem);
      self.refreshDialogPreview();
   };
   this.presetSizer = new HorizontalSizer;
   this.presetSizer.spacing = 8;
   this.presetSizer.add(this.presetLabel);
   this.presetSizer.add(this.presetCombo, 100);

   this.matrixGroup = new GroupBox(this);
   this.matrixGroup.title = "Коэффициенты  (выход = A*k + B*k + C*k)";
   this.matrixGroup.sizer = new VerticalSizer;
   this.matrixGroup.sizer.margin = 8;
   this.matrixGroup.sizer.spacing = 4;

   this.head = new HorizontalSizer;
   this.head.spacing = 8;
   this.head.addSpacing(40);
   this.labA = new Label(this.matrixGroup);
   this.labA.text = "A";
   this.labA.minWidth = 60;
   this.labA.textAlignment = TextAlign_HorzCenter;
   this.labB = new Label(this.matrixGroup);
   this.labB.text = "B";
   this.labB.minWidth = 60;
   this.labB.textAlignment = TextAlign_HorzCenter;
   this.labC = new Label(this.matrixGroup);
   this.labC.text = "C";
   this.labC.minWidth = 60;
   this.labC.textAlignment = TextAlign_HorzCenter;
   this.head.add(this.labA);
   this.head.add(this.labB);
   this.head.add(this.labC);
   this.head.addStretch();
   this.matrixGroup.sizer.add(this.head);

   this.edits = [];
   var row, col, hs, lab, ed;
   var rowNames = ["R", "G", "B"];
   for (row = 0; row < 3; ++row)
   {
      hs = new HorizontalSizer;
      hs.spacing = 8;
      lab = new Label(this.matrixGroup);
      lab.text = rowNames[row];
      lab.minWidth = 24;
      lab.textAlignment = TextAlign_Right | TextAlign_VertCenter;
      hs.add(lab);
      this.edits[row] = [];
      for (col = 0; col < 3; ++col)
      {
         ed = new Edit(this.matrixGroup);
         ed.setFixedWidth(60);
         ed.text = (row == col) ? "1.00" : "0.00";
         ed.onEditCompleted = function() { self.refreshDialogPreview(); };
         this.edits[row][col] = ed;
         hs.add(ed);
      }
      hs.addStretch();
      this.matrixGroup.sizer.add(hs);
   }

   this.rescaleBox = new CheckBox(this);
   this.rescaleBox.text = "Rescale результат в 0..1";
   this.rescaleBox.checked = true;
   this.rescaleBox.onClick = function() { self.refreshDialogPreview(); };

   this.newImageBox = new CheckBox(this);
   this.newImageBox.text = "Собрать в новое изображение";
   this.newImageBox.checked = true;

   this.stfBox = new CheckBox(this);
   this.stfBox.text = "AutoSTF в окне предпросмотра";
   this.stfBox.checked = true;
   this.stfBox.onClick = function() { self.refreshDialogPreview(); };

   this.optSizer = new HorizontalSizer;
   this.optSizer.spacing = 12;
   this.optSizer.add(this.rescaleBox);
   this.optSizer.add(this.newImageBox);
   this.optSizer.add(this.stfBox);
   this.optSizer.addStretch();

   this.previewGroup = new GroupBox(this);
   this.previewGroup.title = "Предпросмотр";
   this.previewGroup.sizer = new VerticalSizer;
   this.previewGroup.sizer.margin = 6;
   this.previewGroup.sizer.spacing = 4;
   this.previewFrame = new PreviewFrame(this.previewGroup);
   this.previewStatus = new Label(this.previewGroup);
   this.previewStatus.wordWrapping = true;
   this.previewStatus.text = "Выберите каналы — предпросмотр обновится сам.";
   this.previewGroup.sizer.add(this.previewFrame, 100);
   this.previewGroup.sizer.add(this.previewStatus);

   this.exprLabel = new Label(this);
   this.exprLabel.wordWrapping = true;
   this.exprLabel.text = "";

   this.previewButton = new PushButton(this);
   this.previewButton.text = "Предпросмотр";
   this.previewButton.toolTip = "Показать смесь в окне скрипта и на Preview исходного кадра.";
   this.previewButton.onClick = function()
   {
      try { self.runPreview(); }
      catch (e)
      {
         console.criticalln(String(e));
         (new MessageBox(String(e), "Palette Mixer", StdIcon_Error, StdButton_Ok)).execute();
      }
   };
   this.runButton = new PushButton(this);
   this.runButton.text = "Собрать";
   this.runButton.onClick = function()
   {
      try { self.runMix(); }
      catch (e)
      {
         console.criticalln(String(e));
         (new MessageBox(String(e), "Palette Mixer", StdIcon_Error, StdButton_Ok)).execute();
      }
   };
   this.closeButton = new PushButton(this);
   this.closeButton.text = "Закрыть";
   this.closeButton.onClick = function() { closeScriptDialog(self); };
   this.btns = new HorizontalSizer;
   this.btns.spacing = 8;
   this.btns.addStretch();
   this.btns.add(this.previewButton);
   this.btns.add(this.runButton);
   this.btns.add(this.closeButton);

   this.sizer = new VerticalSizer;
   this.sizer.margin = 8;
   this.sizer.spacing = 8;
   this.sizer.add(this.help);
   this.sizer.add(this.modeSizer);
   this.sizer.add(this.rowRGB);
   this.sizer.add(this.rowA);
   this.sizer.add(this.rowB);
   this.sizer.add(this.rowC);
   this.sizer.add(this.presetSizer);
   this.sizer.add(this.matrixGroup);
   this.sizer.add(this.optSizer);
   this.sizer.add(this.previewGroup, 100);
   this.sizer.add(this.exprLabel);
   this.sizer.add(this.btns);

   this.applyPreset(2);
   this.presetCombo.currentItem = 2;
   this.modeCombo.currentItem = 0;
   this.updateMode();
   this.adjustToContents();
   this.setMinWidth(520);
   this.refreshDialogPreview();
}

PaletteDialog.prototype = new Dialog;

PaletteDialog.prototype.updateMode = function()
{
   var rgb = (this.modeCombo.currentItem === 1);
   this.rowRGB.visible = rgb;
   this.rowA.visible = !rgb;
   this.rowB.visible = !rgb;
   this.rowC.visible = !rgb;
   this.labA.text = rgb ? "R" : "Ha";
   this.labB.text = rgb ? "G" : "OIII";
   this.labC.text = rgb ? "B" : "SII";
   this.adjustToContents();
};

PaletteDialog.prototype.applyPreset = function(index)
{
   var m = [
      [[1,0,0],[0,1,0],[0,0,1]],
      [[1,0,0],[0,1,0],[0,1,0]],
      [[0,0,1],[1,0,0],[0,1,0]],
      [[1,0,0],[0,1,0],[0,0,1]],
      [[1,0,0],[0,0,1],[0,1,0]],
      [[0,1,0],[0,0,1],[1,0,0]],
      [[0.25,0,0.80],[1,0,0],[0,1,0]],
      [[1,0,0],[0.30,0.70,0],[0,1,0]],
      [[0.15,0,0.90],[0.80,0.20,0],[0,1,0]]
   ];
   if (index < 0 || index >= m.length)
      index = 0;
   var r, c;
   for (r = 0; r < 3; ++r)
      for (c = 0; c < 3; ++c)
         this.edits[r][c].text = formatFloat(m[index][r][c], 2);
};

PaletteDialog.prototype.matrix = function()
{
   var m = [];
   var r, c;
   for (r = 0; r < 3; ++r)
   {
      m[r] = [];
      for (c = 0; c < 3; ++c)
         m[r][c] = parseCoeff(this.edits[r][c]);
   }
   return m;
};

PaletteDialog.prototype.buildExpressions = function(nameA, nameB, nameC)
{
   var m = this.matrix();
   var expr = [];
   var r;
   for (r = 0; r < 3; ++r)
   {
      expr[r] = joinTerms([
         coeffExpr(m[r][0], nameA),
         coeffExpr(m[r][1], nameB),
         coeffExpr(m[r][2], nameC)
      ]);
   }
   return expr;
};

PaletteDialog.prototype.resolveSources = function()
{
   var rgbMode = (this.modeCombo.currentItem === 1);
   var target;
   var nameA, nameB, nameC;

   if (rgbMode)
   {
      target = this.rgbView.currentView;
      if (!viewOk(target))
         throw new Error("Выберите RGB-кадр.");
      if (!mainViewOf(target).image.isColor)
         throw new Error("Этот кадр не RGB. Переключитесь на режим трёх моно каналов.");
      nameA = mainViewOf(target).id + "[0]";
      nameB = mainViewOf(target).id + "[1]";
      nameC = mainViewOf(target).id + "[2]";
      return {
         rgbMode: true,
         target: target,
         nameA: nameA,
         nameB: nameB,
         nameC: nameC,
         imgA: mainViewOf(target).image,
         imgB: mainViewOf(target).image,
         imgC: mainViewOf(target).image,
         chA: 0,
         chB: 1,
         chC: 2
      };
   }

   var vA = this.viewA.currentView;
   var vB = this.viewB.currentView;
   var vC = this.viewC.currentView;
   if (!viewOk(vA) || !viewOk(vB) || !viewOk(vC))
      throw new Error("Укажите три моно канала: Ha, OIII и SII.");
   var iA = mainViewOf(vA).image;
   var iB = mainViewOf(vB).image;
   var iC = mainViewOf(vC).image;
   if (!sameSize(iA, iB) || !sameSize(iA, iC))
      throw new Error("Размеры каналов не совпадают. Сначала StarAlignment.");
   return {
      rgbMode: false,
      target: vA,
      nameA: mainViewOf(vA).id,
      nameB: mainViewOf(vB).id,
      nameC: mainViewOf(vC).id,
      imgA: iA,
      imgB: iB,
      imgC: iC,
      chA: 0,
      chB: 0,
      chC: 0
   };
};

PaletteDialog.prototype.makePixelMath = function(expr, createNew, newId)
{
   var PM = new PixelMath;
   PM.expression = expr[0];
   PM.expression1 = expr[1];
   PM.expression2 = expr[2];
   PM.expression3 = "";
   PM.useSingleExpression = false;
   PM.symbols = "";
   PM.generateOutput = true;
   PM.singleThreaded = false;
   PM.use64BitWorkingImage = false;
   PM.rescale = this.rescaleBox.checked;
   PM.rescaleLower = 0;
   PM.rescaleUpper = 1;
   PM.truncate = true;
   PM.truncateLower = 0;
   PM.truncateUpper = 1;
   PM.createNewImage = createNew;
   PM.showNewImage = createNew;
   PM.newImageId = newId ? newId : "";
   PM.newImageWidth = 0;
   PM.newImageHeight = 0;
   PM.newImageAlpha = false;
   try { PM.newImageColorSpace = PixelMath.prototype.RGB; }
   catch (e2) {}
   try { PM.newImageSampleFormat = PixelMath.prototype.f32; }
   catch (e3) {}
   return PM;
};

PaletteDialog.prototype.ensurePreview = function(view)
{
   var win = view.window;
   if (view.isPreview)
      return view;
   try
   {
      if (viewOk(win.selectedPreview))
         return win.selectedPreview;
   }
   catch (e) {}
   try
   {
      var pal = win.previewById(PREVIEW_ID);
      if (viewOk(pal))
         return pal;
   }
   catch (e2) {}
   try
   {
      if (win.previews && win.previews.length > 0)
         return win.previews[0];
   }
   catch (e3) {}

   var img = win.mainView.image;
   var rect = centerRect(img);
   try { win.createPreview(rect, PREVIEW_ID); }
   catch (e4) {}
   try
   {
      var created = win.previewById(PREVIEW_ID);
      if (viewOk(created))
         return created;
   }
   catch (e5) {}
   if (win.previews && win.previews.length > 0)
      return win.previews[0];
   throw new Error("Не удалось создать Preview. Сделайте превью на кадре вручную (Alt+N).");
};

PaletteDialog.prototype.refreshDialogPreview = function()
{
   try
   {
      var ctx = this.resolveSources();
      var expr = this.buildExpressions(ctx.nameA, ctx.nameB, ctx.nameC);
      this.exprLabel.text = "R: " + expr[0] + "\nG: " + expr[1] + "\nB: " + expr[2];

      var rect = previewRectOf(ctx.target);
      var planeA = extractPlane(ctx.imgA, ctx.chA, rect);
      var planeB = extractPlane(ctx.imgB, ctx.chB, rect);
      var planeC = extractPlane(ctx.imgC, ctx.chC, rect);
      fitImage(planeA, PREVIEW_MAX_W, PREVIEW_MAX_H);
      fitImage(planeB, PREVIEW_MAX_W, PREVIEW_MAX_H);
      fitImage(planeC, PREVIEW_MAX_W, PREVIEW_MAX_H);
      if (planeA.width != planeB.width || planeA.width != planeC.width)
      {
         fitImage(planeA, 256, 180);
         fitImage(planeB, 256, 180);
         fitImage(planeC, 256, 180);
      }

      var mixed = mixRGB(planeA, planeB, planeC, this.matrix(), this.rescaleBox.checked);
      if (this.stfBox.checked)
         autoStretchImage(mixed);
      this.previewFrame.setBitmap(mixed.render());
      this.previewStatus.text = format("Превью %dx%d  (область исходника %dx%d)",
         mixed.width, mixed.height, rect.width, rect.height);
   }
   catch (e)
   {
      this.previewFrame.setBitmap(null);
      this.previewStatus.text = String(e);
   }
};

PaletteDialog.prototype.runPreview = function()
{
   var ctx = this.resolveSources();
   var expr = this.buildExpressions(ctx.nameA, ctx.nameB, ctx.nameC);
   this.exprLabel.text = "R: " + expr[0] + "\nG: " + expr[1] + "\nB: " + expr[2];

   var preview = this.ensurePreview(ctx.target);
   var PM = this.makePixelMath(expr, false, "");
   console.show();
   console.writeln("<b>Palette Mixer — предпросмотр</b> на " + preview.fullId);
   console.writeln("R = " + expr[0]);
   console.writeln("G = " + expr[1]);
   console.writeln("B = " + expr[2]);
   PM.executeOn(preview, false);
   try { preview.window.currentView = preview; }
   catch (e) {}
   try { preview.window.bringToFront(); }
   catch (e2) {}
   this.refreshDialogPreview();
   this.previewStatus.text = "Предпросмотр на " + preview.fullId +
      ". Сброс превью в окне кадра, если нужно вернуться к оригиналу.";
};

PaletteDialog.prototype.runMix = function()
{
   var ctx = this.resolveSources();
   var expr = this.buildExpressions(ctx.nameA, ctx.nameB, ctx.nameC);
   this.exprLabel.text = "R: " + expr[0] + "\nG: " + expr[1] + "\nB: " + expr[2];

   var idBase = "palette";
   try { idBase = this.presetNames[this.presetCombo.currentItem]; } catch (e) {}
   idBase = String(idBase).split(" ").join("_");
   idBase = idBase.split("/").join("_");
   var newId = uniqueId(idBase);
   var createNew = this.newImageBox.checked;
   var target = createNew ? mainViewOf(ctx.target) : ctx.target;

   var PM = this.makePixelMath(expr, createNew, newId);
   console.show();
   console.writeln("<b>Palette Mixer</b>");
   console.writeln("R = " + expr[0]);
   console.writeln("G = " + expr[1]);
   console.writeln("B = " + expr[2]);
   PM.executeOn(target, false);
   if (createNew)
      console.writeln("Готово: " + newId);
   else
      console.writeln("Готово: " + target.fullId);
   this.refreshDialogPreview();
};

function main()
{
   if (ImageWindow.openWindows.length < 1)
   {
      (new MessageBox("Откройте каналы или RGB и запустите скрипт снова.",
                      "Palette Mixer", StdIcon_Warning, StdButton_Ok)).execute();
      return;
   }
   var d = new PaletteDialog;
   runScriptDialog(d);
}

main();
