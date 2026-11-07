param([string]$Target)
$ErrorActionPreference = 'Stop'
if (-not $Target) { $Target = Read-Host 'Path to the installed Astra folder' }
$targetRoot = [IO.Path]::GetFullPath($Target.Trim('"')).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'app.py'))) { throw 'app.py not found. Select the existing Astra installation folder.' }
if (-not ((Test-Path -LiteralPath (Join-Path $targetRoot 'runtime\python.exe')) -or (Test-Path -LiteralPath (Join-Path $targetRoot '.venv\Scripts\python.exe')))) { throw 'Existing Python runtime not found.' }
$running = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and $_.CommandLine.IndexOf($targetRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
if ($running) { throw 'Close Astra before installing this update.' }
$payloadRoot = Join-Path $PSScriptRoot 'payload'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
function Within([string]$root, [string]$relative) {
    $absolute = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $absolute.StartsWith($root.TrimEnd('\')+'\', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe path: $relative" }
    return $absolute
}
# Validate the complete payload before touching the installation.
foreach ($entry in $manifest.files) {
    $source = Within $payloadRoot $entry.path
    $destination = Within $targetRoot $entry.path
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($source)
    try { $hash = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
    if ($hash -ne $entry.sha256) { throw "Damaged file: $($entry.path)" }
}
$backupRoot = Join-Path $targetRoot ('compatibility-backup-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
foreach ($entry in $manifest.files) {
    $destination = Within $targetRoot $entry.path
    if (Test-Path -LiteralPath $destination) {
        $backup = Within $backupRoot $entry.path
        New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $destination -Destination $backup
    }
}
# Only source code, app assets, launchers and the profile flag are replaced.
# No runtime libraries, CUDA files, third-party programs or user images.
foreach ($entry in $manifest.files) {
    $source = Within $payloadRoot $entry.path
    $destination = Within $targetRoot $entry.path
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}
Write-Host "Installed. Backup: $backupRoot"
Write-Host "Run: $targetRoot\diagnose_cpu.bat"
Write-Host "Then run: $targetRoot\start_cpu.bat"
