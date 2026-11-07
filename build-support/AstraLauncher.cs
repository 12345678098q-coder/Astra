using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyTitle("Astra")]
[assembly: AssemblyVersion("1.1.4.0")]
[assembly: AssemblyFileVersion("1.1.4.0")]
class Launcher {
 [STAThread] static int Main() {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  try {
   string python=Path.Combine(root,"runtime","pythonw.exe");
   string script=Path.Combine(root,"app.py");
   if(!File.Exists(python)||!File.Exists(script)) throw new FileNotFoundException("Extract the entire Astra folder before launching Astra.exe.");
   var start=new ProcessStartInfo(python,"-B -E \""+script+"\"");
   start.WorkingDirectory=root;start.UseShellExecute=false;start.CreateNoWindow=true;
   Process.Start(start);return 0;
  } catch(Exception error) {MessageBox.Show(error.Message,"Astra",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
 }
}
