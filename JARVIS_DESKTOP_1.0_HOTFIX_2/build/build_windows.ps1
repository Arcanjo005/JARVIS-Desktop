param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$RunNumber = "1"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location $Root

function Assert-Exists {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Label
    )
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Arquivo/pasta obrigatorio ausente: $Label -> $Path"
    }
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory=$true)][string]$Description,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    Write-Host "[JARVIS] $Description"
    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description falhou com codigo $LASTEXITCODE"
    }
}

$MainScript   = Join-Path $Root "main.py"
$IconFile     = Join-Path $Root "jarvis.ico"
$VersionFile  = Join-Path $Root "build\version_info.txt"
$DataDir      = Join-Path $Root "data"
$PluginsDir   = Join-Path $Root "plugins"
$UpdateConfig = Join-Path $Root "update_config.json"
$DistDir      = Join-Path $Root "dist"
$WorkDir      = Join-Path $Root "build\pyinstaller"
$HooksDir     = Join-Path $Root "build\pyinstaller_hooks"
$SpecDir      = Join-Path $Root "build"
$SpecFile     = Join-Path $SpecDir "JARVIS.spec"
$ExePath      = Join-Path $DistDir "JARVIS\JARVIS.exe"
$ReleaseDir   = Join-Path $Root "release"
$IssFile      = Join-Path $Root "build\JARVIS.iss"

Assert-Exists $MainScript "main.py"
Assert-Exists $IconFile "jarvis.ico"
Assert-Exists $DataDir "data"
Assert-Exists $PluginsDir "plugins"
Assert-Exists $UpdateConfig "update_config.json"
Assert-Exists $IssFile "build/JARVIS.iss"
Assert-Exists (Join-Path $Root "requirements.txt") "requirements.txt"
Assert-Exists (Join-Path $Root "build\requirements-build.txt") "build/requirements-build.txt"

Invoke-PythonStep "Restaurando assets grandes e validando integridade" @("tools/restore_large_assets.py")
Invoke-PythonStep "Preparando metadados da release $Version" @("tools/prepare_release.py", "--version", $Version, "--repository", $Repository, "--run-number", $RunNumber)

Assert-Exists $VersionFile "build/version_info.txt"

Invoke-PythonStep "Atualizando pip" @("-m", "pip", "install", "--upgrade", "pip")
Invoke-PythonStep "Instalando dependencias do JARVIS" @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-PythonStep "Instalando dependencias de build" @("-m", "pip", "install", "-r", "build/requirements-build.txt")

# Preflight especifico do VAD. O pacote de distribuicao se chama
# "webrtcvad-wheels", enquanto o modulo importado pelo JARVIS se chama
# "webrtcvad". Isso evita descobrir a incompatibilidade somente no PyInstaller.
Write-Host "[JARVIS] Validando WebRTC VAD e metadados"
& python -c "import importlib.metadata as m; import webrtcvad, _webrtcvad; print('webrtcvad-wheels=' + m.version('webrtcvad-wheels')); print('webrtcvad=' + str(getattr(webrtcvad, '__version__', 'unknown')))"
if ($LASTEXITCODE -ne 0) {
    throw "WebRTC VAD instalado de forma incompleta: webrtcvad-wheels/webrtcvad/_webrtcvad"
}

Write-Host "[JARVIS] Executando gates de regressao antes de empacotar"
& python -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw "compileall falhou com codigo $LASTEXITCODE" }
foreach ($TestFile in @("jarvis_desktop_selftest.py", "jarvis_build16_selftest.py", "jarvis_v8_selftest.py")) {
    & python $TestFile
    if ($LASTEXITCODE -ne 0) { throw "$TestFile falhou com codigo $LASTEXITCODE" }
}

Remove-Item -Recurse -Force $WorkDir, (Join-Path $DistDir "JARVIS"), $HooksDir -ErrorAction SilentlyContinue
Remove-Item -Force $SpecFile -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $WorkDir, $HooksDir | Out-Null

# HOTFIX 2:
# pyinstaller-hooks-contrib possui um hook chamado hook-webrtcvad.py que chama
# copy_metadata('webrtcvad'). No nosso runtime, o modulo e "webrtcvad", mas a
# distribuicao instalada e "webrtcvad-wheels". O hook oficial entao procura um
# metadado que nao existe e aborta a Analysis.
#
# --additional-hooks-dir tem precedencia sobre os hooks contribuidos; este hook
# local usa o nome correto da distribuicao e inclui explicitamente a extensao
# nativa _webrtcvad usada por webrtcvad.py.
$WebRtcHook = @'
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("webrtcvad-wheels")
hiddenimports = ["_webrtcvad"]
'@
$WebRtcHookPath = Join-Path $HooksDir "hook-webrtcvad.py"
Set-Content -LiteralPath $WebRtcHookPath -Value $WebRtcHook -Encoding utf8
Assert-Exists $WebRtcHookPath "hook local do webrtcvad"

# Hook local do google.genai: coleta submodulos/dados necessarios, mas ignora a
# arvore de testes do SDK. Isso elimina o aviso de pytest ausente e reduz lixo no
# executavel sem remover o SDK usado pelo JARVIS.
$GoogleGenAiHook = @'
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hiddenimports = collect_submodules(
    "google.genai",
    filter=lambda name: not name.startswith("google.genai.tests"),
)
datas = collect_data_files("google.genai")
datas += copy_metadata("google-genai")
'@
$GoogleGenAiHookPath = Join-Path $HooksDir "hook-google.genai.py"
Set-Content -LiteralPath $GoogleGenAiHookPath -Value $GoogleGenAiHook -Encoding utf8
Assert-Exists $GoogleGenAiHookPath "hook local do google.genai"

Write-Host "[JARVIS] Gerando JARVIS.exe standalone (onedir, runtime embutido)"
Write-Host "[JARVIS] Raiz do projeto: $Root"
Write-Host "[JARVIS] Dados: $DataDir"
Write-Host "[JARVIS] Plugins: $PluginsDir"
Write-Host "[JARVIS] Hooks locais: $HooksDir"

# Todos os caminhos-fonte sao ABSOLUTOS. O .spec e salvo em build/, portanto
# caminhos relativos seriam reinterpretados a partir de build/.
$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--contents-directory", ".",
    "--name", "JARVIS",
    "--icon", $IconFile,
    "--version-file", $VersionFile,
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir,
    "--additional-hooks-dir", $HooksDir,
    "--add-data", "$DataDir;data",
    "--add-data", "$PluginsDir;plugins",
    "--add-data", "$UpdateConfig;.",
    "--add-data", "$IconFile;.",
    "--collect-all", "customtkinter",
    "--collect-submodules", "edge_tts",
    "--hidden-import", "_webrtcvad",
    "--hidden-import", "win32timezone",
    "--hidden-import", "pythoncom",
    "--hidden-import", "pywintypes",
    $MainScript
)

& python -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller falhou com codigo $LASTEXITCODE"
}

if (!(Test-Path -LiteralPath $ExePath)) {
    throw "PyInstaller terminou sem criar o executavel esperado: $ExePath"
}

# Confirmacao estrutural antes de gerar o instalador.
Assert-Exists (Join-Path $DistDir "JARVIS\data") "data empacotado"
Assert-Exists (Join-Path $DistDir "JARVIS\plugins") "plugins empacotados"
Assert-Exists (Join-Path $DistDir "JARVIS\update_config.json") "update_config empacotado"

$RuntimeDirs = @(
    (Join-Path $DistDir "JARVIS\data"),
    (Join-Path $DistDir "JARVIS\logs"),
    (Join-Path $DistDir "JARVIS\screenshots")
)
foreach ($RuntimeDir in $RuntimeDirs) {
    New-Item -ItemType Directory -Force $RuntimeDir | Out-Null
}

Write-Host "[JARVIS] Montando instalador Inno Setup"
$IsccCandidates = @(
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$Iscc) {
    throw "ISCC.exe nao encontrado. Instale Inno Setup 6."
}

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
& $Iscc "/DMyAppVersion=$Version" $IssFile
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou com codigo $LASTEXITCODE" }

$Installer = Join-Path $ReleaseDir "JARVIS_Setup_$Version.exe"
if (!(Test-Path -LiteralPath $Installer)) { throw "Instalador nao encontrado: $Installer" }

$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  JARVIS_Setup_$Version.exe" | Set-Content "$Installer.sha256" -Encoding ascii

Write-Host "[JARVIS] OK: $Installer"
Write-Host "[JARVIS] SHA256: $Hash"
