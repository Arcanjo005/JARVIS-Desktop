param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$RunNumber = "1"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[JARVIS] Restaurando assets grandes e validando integridade"
python tools/restore_large_assets.py

Write-Host "[JARVIS] Preparando metadados da release $Version"
python tools/prepare_release.py --version $Version --repository $Repository --run-number $RunNumber

Write-Host "[JARVIS] Instalando dependencias de build"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r build/requirements-build.txt

Write-Host "[JARVIS] Executando gates de regressao antes de empacotar"
python -m compileall -q .
python jarvis_desktop_selftest.py
python jarvis_build16_selftest.py
python jarvis_v8_selftest.py

Remove-Item -Recurse -Force build\pyinstaller, dist\JARVIS -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force build\pyinstaller | Out-Null

Write-Host "[JARVIS] Gerando JARVIS.exe standalone (onedir, runtime embutido)"
$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--contents-directory", ".",
    "--name", "JARVIS",
    "--icon", "jarvis.ico",
    "--version-file", "build/version_info.txt",
    "--distpath", "dist",
    "--workpath", "build/pyinstaller",
    "--specpath", "build",
    "--add-data", "data;data",
    "--add-data", "plugins;plugins",
    "--add-data", "update_config.json;.",
    "--add-data", "jarvis.ico;.",
    "--collect-all", "customtkinter",
    "--collect-all", "google.genai",
    "--collect-submodules", "edge_tts",
    "--hidden-import", "win32timezone",
    "--hidden-import", "pythoncom",
    "--hidden-import", "pywintypes",
    "main.py"
)
python -m PyInstaller @PyInstallerArgs

if (!(Test-Path "dist\JARVIS\JARVIS.exe")) {
    throw "PyInstaller nao gerou dist\\JARVIS\\JARVIS.exe"
}

# Runtime folders are intentionally writable; source code/binaries remain protected by the installer.
New-Item -ItemType Directory -Force dist\JARVIS\data, dist\JARVIS\logs, dist\JARVIS\screenshots | Out-Null

Write-Host "[JARVIS] Montando instalador Inno Setup"
$IsccCandidates = @(
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$Iscc) {
    throw "ISCC.exe nao encontrado. Instale Inno Setup 6."
}
New-Item -ItemType Directory -Force release | Out-Null
& $Iscc "/DMyAppVersion=$Version" "build\JARVIS.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou: $LASTEXITCODE" }

$Installer = "release\JARVIS_Setup_$Version.exe"
if (!(Test-Path $Installer)) { throw "Instalador nao encontrado: $Installer" }
$Hash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  JARVIS_Setup_$Version.exe" | Set-Content "$Installer.sha256" -Encoding ascii

Write-Host "[JARVIS] OK: $Installer"
Write-Host "[JARVIS] SHA256: $Hash"
