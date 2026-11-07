/*
 * Немодальный диалог для PixInsight 1.8.5.
 * execute() блокирует редактирование кадров — show() + processEvents нет.
 */

#ifndef __NonModal_jsh
#define __NonModal_jsh

function closeScriptDialog(dialog)
{
   try { dialog._scriptClosed = true; } catch (e) {}
   try { dialog.hide(); } catch (e2) {}
   try { dialog.visible = false; } catch (e3) {}
   try { dialog.cancel(); } catch (e4) {}
}

function runScriptDialog(dialog)
{
   dialog._scriptClosed = false;
   try
   {
      dialog.onClose = function()
      {
         this._scriptClosed = true;
         return true;
      };
   }
   catch (e) {}
   try
   {
      dialog.onHide = function()
      {
         this._scriptClosed = true;
      };
   }
   catch (e2) {}

   var shown = false;
   try
   {
      if (typeof dialog.show === "function")
      {
         dialog.show();
         shown = true;
      }
   }
   catch (e3) {}

   if (!shown)
   {
      try
      {
         dialog.visible = true;
         shown = !!dialog.visible;
      }
      catch (e4) {}
   }

   if (!shown)
   {
      dialog.execute();
      return;
   }

   try { dialog.activateWindow(); } catch (e5) {}
   console.abortEnabled = true;
   while (!dialog._scriptClosed)
   {
      processEvents();
      try
      {
         if (dialog.visible === false)
            break;
      }
      catch (e6)
      {
         break;
      }
      try { msleep(30); } catch (e7) {}
      try
      {
         if (console.abortRequested)
         {
            closeScriptDialog(dialog);
            break;
         }
      }
      catch (e8) {}
   }
}

#endif
