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

Write-Host "[JARVIS] Validando dependencias nativas de voz e bandeja"
& python -c "import sounddevice, vosk, pystray, pystray._win32, send2trash; print('sounddevice=' + str(getattr(sounddevice, '__version__', 'ok'))); print('vosk=ok'); print('pystray=ok'); print('send2trash=ok')"
if ($LASTEXITCODE -ne 0) {
    throw "Runtime Windows incompleto: sounddevice/vosk/pystray/send2trash nao puderam ser importados antes do PyInstaller."
}

Write-Host "[JARVIS] Executando gates de regressao antes de empacotar"
& python -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw "compileall falhou com codigo $LASTEXITCODE" }
foreach ($TestFile in @("jarvis_hot_update_selftest.py", "jarvis_desktop_selftest.py", "jarvis_build16_selftest.py", "jarvis_v8_selftest.py")) {
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
    "--collect-all", "sounddevice",
    "--collect-all", "vosk",
    "--collect-submodules", "edge_tts",
    "--hidden-import", "pystray._win32",
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

# Smoke test do EXE FINAL, não do ambiente Python do runner. Isso pega
# exatamente as regressões que só aparecem depois do PyInstaller: PortAudio,
# Vosk/modelo de wake, WebRTC VAD, pystray/Win32 e overlay Qt ausentes.
$RuntimeReport = Join-Path $WorkDir "runtime-selftest.json"
Remove-Item -Force $RuntimeReport -ErrorAction SilentlyContinue
Write-Host "[JARVIS] Testando runtime congelado antes do instalador"
$RuntimeProcess = Start-Process -FilePath $ExePath -ArgumentList @("--runtime-selftest", $RuntimeReport) -Wait -PassThru
if ($RuntimeProcess.ExitCode -ne 0) {
    if (Test-Path -LiteralPath $RuntimeReport) {
        Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw)
    }
    throw "JARVIS.exe falhou no runtime-selftest com codigo $($RuntimeProcess.ExitCode)."
}
Assert-Exists $RuntimeReport "relatorio runtime-selftest"
$RuntimeSmoke = Get-Content -LiteralPath $RuntimeReport -Raw | ConvertFrom-Json
if (-not $RuntimeSmoke.ok) {
    Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw)
    throw "JARVIS.exe foi gerado, mas voz/bandeja/overlay nao estao completos no runtime congelado."
}
Write-Host "[JARVIS] Runtime congelado validado: voz + bandeja + overlay presentes"

# Prova a arquitetura de hot update no EXE FINAL. A partir do PyInstaller 6.22
# o importador é baseado em sys.path; este gate impede publicar uma base em que
# os módulos do AppData não consigam sobrepor o PYZ congelado.
$HotSmokeRoot = Join-Path $WorkDir "hot-runtime-smoke"
$HotSmokeLocal = Join-Path $HotSmokeRoot "localappdata"
$HotSmokeZip = Join-Path $HotSmokeRoot "hot-smoke.zip"
$HotSmokeBuilder = Join-Path $HotSmokeRoot "make_hot_smoke.py"
$HotSmokeReport = Join-Path $HotSmokeRoot "runtime-selftest-hot.json"
Remove-Item -Recurse -Force $HotSmokeRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $HotSmokeRoot, $HotSmokeLocal | Out-Null
$HotSmokePython = @'
import hashlib, json, sys, zipfile
from pathlib import Path
out = Path(sys.argv[1])
version = "99.99.99"
data = (
    'VERSION = "99.99.99"\n'
    'BUILD = "ci-hot-import"\n'
    'CHANNEL = "stable"\n'
    'PUBLIC_NAME = "JARVIS"\n'
    'INTERNAL_NAME = "JARVIS"\n'
).encode("utf-8")
manifest = {
    "format": 1, "runtime_api": 1, "version": version,
    "minimum_bootstrap": "1.1.0",
    "files": [{"path": "jarvis_version.py", "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest()}],
}
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("jarvis_version.py", data)
    z.writestr("runtime_manifest.json", json.dumps(manifest))
'@
Set-Content -LiteralPath $HotSmokeBuilder -Value $HotSmokePython -Encoding utf8
& python $HotSmokeBuilder $HotSmokeZip
if ($LASTEXITCODE -ne 0) { throw "Nao consegui criar pacote hot de smoke test." }

$SavedLocalAppData = $env:LOCALAPPDATA
$SavedHotExpected = $env:JARVIS_EXPECT_HOT_VERSION
try {
    $env:LOCALAPPDATA = $HotSmokeLocal
    & python -c "from hot_update_runtime import install_hot_package; import sys; install_hot_package(sys.argv[1], expected_version='99.99.99')" $HotSmokeZip
    if ($LASTEXITCODE -ne 0) { throw "Nao consegui preparar hot runtime sintetico para o EXE." }
    $env:JARVIS_EXPECT_HOT_VERSION = "99.99.99"
    $HotProcess = Start-Process -FilePath $ExePath -ArgumentList @("--runtime-selftest", $HotSmokeReport) -Wait -PassThru
    if ($HotProcess.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $HotSmokeReport) { Write-Host (Get-Content -LiteralPath $HotSmokeReport -Raw) }
        throw "JARVIS.exe nao conseguiu carregar codigo pelo Hot Runtime (codigo $($HotProcess.ExitCode))."
    }
    $HotSmoke = Get-Content -LiteralPath $HotSmokeReport -Raw | ConvertFrom-Json
    if (-not $HotSmoke.ok -or -not $HotSmoke.checks.hot_runtime_import_precedence) {
        Write-Host (Get-Content -LiteralPath $HotSmokeReport -Raw)
        throw "Import precedence do Hot Runtime nao foi comprovada no EXE congelado."
    }
    Write-Host "[JARVIS] Hot Runtime validado no EXE: AppData sobrepoe o bundle com seguranca"
}
finally {
    $env:LOCALAPPDATA = $SavedLocalAppData
    $env:JARVIS_EXPECT_HOT_VERSION = $SavedHotExpected
}

$RuntimeDirs = @(
    (Join-Path $DistDir "JARVIS\data"),
    (Join-Path $DistDir "JARVIS\logs"),
    (Join-Path $DistDir "JARVIS\screenshots")
)
foreach ($RuntimeDir in $RuntimeDirs) {
    New-Item -ItemType Directory -Force $RuntimeDir | Out-Null
}

Write-Host "[JARVIS] Montando instalador Inno Setup"

function Resolve-IsccPath {
    # 1) PATH / shim do Chocolatey.
    foreach ($CommandName in @("ISCC.exe", "iscc.exe", "ISCC", "iscc")) {
        $Command = Get-Command $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Command -and $Command.Source -and (Test-Path -LiteralPath $Command.Source)) {
            return [System.IO.Path]::GetFullPath($Command.Source)
        }
    }

    # 2) Caminhos oficiais. A variavel ProgramFiles(x86) precisa ser lida
    # explicitamente; "$env:ProgramFiles(x86)" nao funciona como esperado.
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $ProgramFiles64 = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $LocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
    $ChocolateyInstall = [Environment]::GetEnvironmentVariable("ChocolateyInstall")
    if ([string]::IsNullOrWhiteSpace($ChocolateyInstall)) {
        $ChocolateyInstall = "C:\ProgramData\chocolatey"
    }

    $Candidates = New-Object System.Collections.Generic.List[string]
    foreach ($Base in @($ProgramFilesX86, $ProgramFiles64)) {
        if (![string]::IsNullOrWhiteSpace($Base)) {
            $Candidates.Add((Join-Path $Base "Inno Setup 6\ISCC.exe"))
            $Candidates.Add((Join-Path $Base "Inno Setup 5\ISCC.exe"))
        }
    }
    if (![string]::IsNullOrWhiteSpace($LocalAppData)) {
        $Candidates.Add((Join-Path $LocalAppData "Programs\Inno Setup 6\ISCC.exe"))
    }
    if (![string]::IsNullOrWhiteSpace($ChocolateyInstall)) {
        $Candidates.Add((Join-Path $ChocolateyInstall "bin\ISCC.exe"))
        $Candidates.Add((Join-Path $ChocolateyInstall "lib\innosetup\tools\ISCC.exe"))
    }

    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate)) {
            return [System.IO.Path]::GetFullPath($Candidate)
        }
    }

    # 3) Fallback para mudancas de layout do pacote Chocolatey. A busca fica
    # limitada ao pacote innosetup para nao percorrer o disco inteiro.
    if (![string]::IsNullOrWhiteSpace($ChocolateyInstall)) {
        $ChocoLib = Join-Path $ChocolateyInstall "lib"
        if (Test-Path -LiteralPath $ChocoLib) {
            $PackageDirs = Get-ChildItem -LiteralPath $ChocoLib -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like "innosetup*" }
            foreach ($PackageDir in $PackageDirs) {
                $Found = Get-ChildItem -LiteralPath $PackageDir.FullName -Filter "ISCC.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($Found) {
                    return [System.IO.Path]::GetFullPath($Found.FullName)
                }
            }
        }
    }

    return $null
}

$Iscc = Resolve-IsccPath
if (!$Iscc) {
    Write-Host "[JARVIS] ProgramFiles: $([Environment]::GetEnvironmentVariable('ProgramFiles'))"
    Write-Host "[JARVIS] ProgramFiles(x86): $([Environment]::GetEnvironmentVariable('ProgramFiles(x86)'))"
    Write-Host "[JARVIS] ChocolateyInstall: $([Environment]::GetEnvironmentVariable('ChocolateyInstall'))"
    throw "ISCC.exe nao encontrado apos procurar PATH, Program Files e Chocolatey."
}

Write-Host "[JARVIS] Inno Setup encontrado: $Iscc"

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
& $Iscc "/DMyAppVersion=$Version" $IssFile
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou com codigo $LASTEXITCODE" }

$Installer = Join-Path $ReleaseDir "JARVIS_Setup_$Version.exe"
if (!(Test-Path -LiteralPath $Installer)) { throw "Instalador nao encontrado: $Installer" }

$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  JARVIS_Setup_$Version.exe" | Set-Content "$Installer.sha256" -Encoding ascii

Write-Host "[JARVIS] OK: $Installer"
Write-Host "[JARVIS] SHA256: $Hash"
