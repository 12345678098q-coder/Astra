#define AppVersion "1.1.5"
#define StageDir "..\release\Astra-1.1.5"

[Setup]
AppId={{F7D3715E-B994-4AA9-8BB7-778402D0D947}
AppName=Astra
AppVersion={#AppVersion}
DefaultDirName={autopf}\Astra
UsePreviousAppDir=yes
DefaultGroupName=Astra
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=Setup-{#AppVersion}
SetupIconFile=..\assets\astra.ico
UninstallDisplayIcon={app}\Astra.exe
Compression=lzma2/ultra64
SolidCompression=yes
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
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "tools,tools\*,optional,optional\*,__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Astra"; Filename: "{app}\Astra.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\astra.ico"; AppUserModelID: "Astra.Astrophotography"
Name: "{autodesktop}\Astra"; Filename: "{app}\Astra.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\astra.ico"; Tasks: desktopicon; AppUserModelID: "Astra.Astrophotography"

[Registry]
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\shell\open\command"; ValueType: string; ValueData: """{app}\Astra.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\DefaultIcon"; ValueType: string; ValueData: "{app}\assets\astra.ico"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".fit"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".fits"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".fts"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".xisf"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".tif"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Applications\Astra.exe\SupportedTypes"; ValueType: string; ValueName: ".tiff"; ValueData: ""; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Astra"; ValueData: "Software\Astra\Capabilities"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Astra\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Astra"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Astra\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Открытие астрономических изображений"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".fit"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".fits"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".fts"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xisf"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tif"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Astra\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tiff"; ValueData: "Astra.Image"
Root: HKLM; Subkey: "Software\Classes\Astra.Image"; ValueType: string; ValueData: "Астрономическое изображение Astra"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Astra.Image\DefaultIcon"; ValueType: string; ValueData: "{app}\assets\astra.ico"
Root: HKLM; Subkey: "Software\Classes\Astra.Image\shell\open\command"; ValueType: string; ValueData: """{app}\Astra.exe"" ""%1"""

[Run]
Filename: "{app}\Astra.exe"; WorkingDir: "{app}"; Description: "Запустить Astra"; Flags: nowait postinstall skipifsilent
