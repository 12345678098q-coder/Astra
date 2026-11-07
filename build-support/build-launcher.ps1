$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$icon = Join-Path $project 'assets\astra.ico'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework compiler not found.' }
if (-not (Test-Path -LiteralPath $icon)) { throw 'Astra icon not found.' }
& $compiler /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/win32icon:$icon" "/out:$project\Astra.exe" (Join-Path $PSScriptRoot 'AstraLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Failed to build Astra.exe.' }
Write-Output (Join-Path $project 'Astra.exe')
