param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$BuildId,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$RunNumber = "1"
)

$ErrorActionPreference = "Stop"
$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location $Root

function Require-Path([string]$Path, [string]$Label) {
    if (!(Test-Path -LiteralPath $Path)) { throw "Ausente: $Label -> $Path" }
}

Write-Host "[QT-DEV] Restaurando assets"
python tools/restore_large_assets.py
if ($LASTEXITCODE -ne 0) { throw "restore_large_assets falhou" }

Write-Host "[QT-DEV] Preparando metadata Windows"
python tools/prepare_release.py --version $Version --repository $Repository --run-number $RunNumber
if ($LASTEXITCODE -ne 0) { throw "prepare_release falhou" }

# prepare_release points main.py to the stable shell. Dev builds deliberately
# switch only the temporary CI workspace to the rebuilt Qt shell.
$MainPath = Join-Path $Root "main.py"
$MainSource = Get-Content -LiteralPath $MainPath -Raw
$MainSource = $MainSource.Replace("from gui_reference_release_1312 import JarvisGUI", "from gui_qt_dev import JarvisGUI")
$MainSource = $MainSource.Replace("from gui import JarvisGUI", "from gui_qt_dev import JarvisGUI")
Set-Content -LiteralPath $MainPath -Value $MainSource -Encoding utf8
if (-not ((Get-Content -LiteralPath $MainPath -Raw).Contains("from gui_qt_dev import JarvisGUI"))) {
    throw "Nao consegui ativar gui_qt_dev no entry point temporario"
}

# Identity of the frozen Dev build. Same semantic version is intentional: the
# updater compares BuildId as well as Version. PowerShell does not use backslash
# as a string escape, so keep the generated Python source free of \" sequences.
$VersionPy = @"
"""Canonical version identity generated for a JARVIS Dev candidate."""
from jarvis_identity import PUBLIC_NAME, WAKE_NAME, LEGACY_NAME
VERSION = "$Version"
BUILD = "$BuildId"
CHANNEL = "dev"
INTERNAL_NAME = "JARVIS"
def display_version():
    return VERSION
__all__ = ["VERSION", "BUILD", "CHANNEL", "PUBLIC_NAME", "INTERNAL_NAME", "WAKE_NAME", "LEGACY_NAME", "display_version"]
"@
$VersionPyPath = Join-Path $Root "jarvis_version.py"
Set-Content -LiteralPath $VersionPyPath -Value $VersionPy -Encoding utf8
python -m py_compile $VersionPyPath
if ($LASTEXITCODE -ne 0) { throw "jarvis_version.py Dev gerado com sintaxe invalida" }

$IconFile = Join-Path $Root "jarvis.ico"
$VersionFile = Join-Path $Root "build\version_info.txt"
$DataDir = Join-Path $Root "data"
$PluginsDir = Join-Path $Root "plugins"
$UpdateConfig = Join-Path $Root "update_config.json"
$DistDir = Join-Path $Root "dist"
$WorkDir = Join-Path $Root "build\pyinstaller-qt-dev"
$HooksDir = Join-Path $Root "build\pyinstaller_hooks_qt_dev"
$SpecDir = Join-Path $Root "build"
$ExePath = Join-Path $DistDir "JARVIS\JARVIS.exe"
$ReleaseDir = Join-Path $Root "release"
$IssFile = Join-Path $Root "build\JARVIS.iss"

foreach ($item in @(
    @($MainPath, "main.py"), @($IconFile, "jarvis.ico"), @($VersionFile, "version_info"),
    @($DataDir, "data"), @($PluginsDir, "plugins"), @($UpdateConfig, "update_config"), @($IssFile, "Inno script")
)) { Require-Path $item[0] $item[1] }

Remove-Item -Recurse -Force $WorkDir, (Join-Path $DistDir "JARVIS"), $HooksDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $WorkDir, $HooksDir | Out-Null

$WebRtcHook = @'
from PyInstaller.utils.hooks import copy_metadata
datas = copy_metadata("webrtcvad-wheels")
hiddenimports = ["_webrtcvad"]
'@
Set-Content -LiteralPath (Join-Path $HooksDir "hook-webrtcvad.py") -Value $WebRtcHook -Encoding utf8

$GoogleHook = @'
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
hiddenimports = collect_submodules("google.genai", filter=lambda name: not name.startswith("google.genai.tests"))
datas = collect_data_files("google.genai") + copy_metadata("google-genai")
'@
Set-Content -LiteralPath (Join-Path $HooksDir "hook-google.genai.py") -Value $GoogleHook -Encoding utf8

Write-Host "[QT-DEV] PyInstaller $Version / $BuildId"
$Args = @(
    "--noconfirm", "--clean", "--onedir", "--windowed", "--contents-directory", ".",
    "--name", "JARVIS", "--icon", $IconFile, "--version-file", $VersionFile,
    "--distpath", $DistDir, "--workpath", $WorkDir, "--specpath", $SpecDir,
    "--additional-hooks-dir", $HooksDir,
    "--add-data", "$DataDir;data", "--add-data", "$PluginsDir;plugins",
    "--add-data", "$UpdateConfig;.", "--add-data", "$IconFile;.",
    # Do not --collect-all PySide6. That pulled every Qt module/QML plugin into
    # the candidate, added minutes to Analysis and hundreds of unnecessary MB.
    # PyInstaller follows the real imports; these explicit modules cover the
    # rebuilt shell and the existing Qt voice overlay.
    "--hidden-import", "PySide6.QtCore", "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--collect-all", "customtkinter", "--collect-all", "sounddevice",
    "--collect-all", "vosk", "--collect-submodules", "edge_tts",
    "--hidden-import", "send2trash", "--hidden-import", "send2trash.win",
    "--hidden-import", "send2trash.win.modern", "--hidden-import", "send2trash.win.legacy",
    "--hidden-import", "send2trash.win.IFileOperationProgressSink", "--hidden-import", "pystray._win32",
    "--hidden-import", "_webrtcvad", "--hidden-import", "win32timezone",
    "--hidden-import", "pythoncom", "--hidden-import", "pywintypes", $MainPath
)
python -m PyInstaller @Args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller Qt Dev falhou" }
Require-Path $ExePath "JARVIS.exe"

$RuntimeReport = Join-Path $WorkDir "runtime-selftest.json"
Remove-Item -Force $RuntimeReport -ErrorAction SilentlyContinue
$Runtime = Start-Process -FilePath $ExePath -ArgumentList @("--runtime-selftest", $RuntimeReport) -Wait -PassThru
if ($Runtime.ExitCode -ne 0) {
    if (Test-Path -LiteralPath $RuntimeReport) {
        Write-Host "[QT-DEV] Runtime selftest report:"
        Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw)
    }
    throw "Runtime-selftest Qt Dev falhou: $($Runtime.ExitCode)"
}
$Report = Get-Content -LiteralPath $RuntimeReport -Raw | ConvertFrom-Json
if (-not $Report.ok -or -not $Report.checks.pyside6) {
    Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw)
    throw "Runtime congelado nao confirmou PySide6"
}

$Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source }
if (-not $Iscc) {
    $Candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "ISCC.exe nao encontrado" }

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
& $Iscc "/DMyAppVersion=$Version" $IssFile
if ($LASTEXITCODE -ne 0) { throw "Inno Setup Qt Dev falhou" }

$Installer = Join-Path $ReleaseDir "JARVIS_Setup_$Version.exe"
Require-Path $Installer "instalador Qt Dev"
$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  JARVIS_Setup_$Version.exe" | Set-Content "$Installer.sha256" -Encoding ascii

$Identity = @{
    version = $Version
    build_id = $BuildId
    channel = "dev"
    sha256 = $Hash
    size = (Get-Item -LiteralPath $Installer).Length
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $ReleaseDir "dev-build.json") -Value $Identity -Encoding utf8
Write-Host "[QT-DEV] OK $Version / $BuildId / $Hash"
