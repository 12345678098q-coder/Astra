#define AppVersion "1.0.0"
; Base installers must exclude optional GPU dependencies, even when staging
; was copied from a development environment. See package-policy.json.
#define OptionalGpuExcludes "runtime\Lib\site-packages\cupy*,runtime\Lib\site-packages\cuda*,runtime\Lib\site-packages\nvidia*"
[Setup]
AppId={{F7D3715E-B994-4AA9-8BB7-778402D0D947}
AppName=Astra
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Astra
DefaultGroupName=Astra
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=Astra-Setup-{#AppVersion}-win64
SetupIconFile=..\assets\astra.ico
UninstallDisplayIcon={app}\assets\astra.ico
Compression=zip/5
SolidCompression=no
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=Astra {#AppVersion}
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: checkedonce
[Files]
Source: "..\release\Astra-1.0.0\*"; DestDir: "{app}"; Excludes: "{#OptionalGpuExcludes},optional\cuda,optional\cuda\*,__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\requirements-cuda.txt"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Astra"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\astra.ico"; AppUserModelID: "Astra.Astrophotography"
Name: "{autodesktop}\Astra"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\astra.ico"; Tasks: desktopicon; AppUserModelID: "Astra.Astrophotography"
[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; Description: "Запустить Astra"; Flags: nowait postinstall skipifsilent
