param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$BuildId,
    [Parameter(Mandatory=$true)][string]$Repository,
    [string]$RunNumber = "1"
)
$ErrorActionPreference = "Stop"
$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location $Root
function Require-Path([string]$Path,[string]$Label){ if(!(Test-Path -LiteralPath $Path)){ throw "Missing: $Label -> $Path" } }

Write-Host "[QT-DEV] Restoring runtime assets"
python tools/restore_large_assets.py
if($LASTEXITCODE -ne 0){ throw "restore_large_assets failed" }

$LegacyVisualFiles=@(
 "gui_qt_dev.py","gui_qt_integrated.py","gui_qt_reference.py","gui_qt_reference_v2.py",
 "gui_reference_exact.py","gui_reference_exact_v2.py","gui_reference_exact_v3.py",
 "gui_reference_final_1311.py","gui_reference_final_1312.py","gui_reference_release_1312.py",
 "jarvis_reference_orb.py","jarvis_reference_scene_139.py","jarvis_visual_runtime.py",
 "voice_overlay_qt.py","jarvis_voice_overlay_139.py"
)
$FoundLegacy=@($LegacyVisualFiles|Where-Object{Test-Path -LiteralPath (Join-Path $Root $_)})
if($FoundLegacy.Count -gt 0){ throw "Legacy visual sources still exist in build workspace: $($FoundLegacy -join ', ')" }

Write-Host "[QT-DEV] Preparing metadata without changing UI entrypoint"
python tools/prepare_release.py --version $Version --repository $Repository --run-number $RunNumber --channel dev --build-id $BuildId
if($LASTEXITCODE -ne 0){ throw "prepare_release failed" }

$MainPath=Join-Path $Root "main.py"; $GuiPath=Join-Path $Root "gui.py"; $IconFile=Join-Path $Root "jarvis.ico"; $VersionFile=Join-Path $Root "build\version_info.txt"; $DataDir=Join-Path $Root "data"; $PluginsDir=Join-Path $Root "plugins"; $AssetsDir=Join-Path $Root "assets"; $UpdateConfig=Join-Path $Root "update_config.json"; $DistDir=Join-Path $Root "dist"; $WorkDir=Join-Path $Root "build\pyinstaller-qt-dev"; $HooksDir=Join-Path $Root "build\pyinstaller_hooks_qt_dev"; $SpecDir=Join-Path $Root "build"; $ExePath=Join-Path $DistDir "JARVIS\JARVIS.exe"; $ReleaseDir=Join-Path $Root "release"; $IssFile=Join-Path $Root "build\JARVIS.iss"
foreach($item in @(@($MainPath,"main.py"),@($GuiPath,"gui.py"),@($IconFile,"jarvis.ico"),@($VersionFile,"version_info"),@($DataDir,"data"),@($PluginsDir,"plugins"),@($AssetsDir,"approved assets"),@($UpdateConfig,"update_config"),@($IssFile,"Inno script"))){ Require-Path $item[0] $item[1] }
$RequiredAssets=@("workspace_bg.jpg","sphere_3d.png","update_neon_arrow.png","jarvis_logo.png","plus.png","mic.png","send.png")
foreach($Asset in $RequiredAssets){ Require-Path (Join-Path $AssetsDir $Asset) "approved UI asset $Asset" }
$MainSource=Get-Content -LiteralPath $MainPath -Raw
if(-not $MainSource.Contains("from gui import JarvisGUI")){ throw "main.py is not pointing directly to the single-source gui.py" }
$GuiSource=Get-Content -LiteralPath $GuiPath -Raw
foreach($Token in @("from gui_qt_","from gui_reference","JARVIS DESKTOP INTELLIGENCE","_paint_hologram","QRadialGradient")){ if($GuiSource.Contains($Token)){ throw "Forbidden legacy UI token in gui.py: $Token" } }

Remove-Item -Recurse -Force $WorkDir,(Join-Path $DistDir "JARVIS"),$HooksDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $WorkDir,$HooksDir|Out-Null
$WebRtcHook=@'
from PyInstaller.utils.hooks import copy_metadata
datas = copy_metadata("webrtcvad-wheels")
hiddenimports = ["_webrtcvad"]
'@
Set-Content -LiteralPath (Join-Path $HooksDir "hook-webrtcvad.py") -Value $WebRtcHook -Encoding utf8
$GoogleHook=@'
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
hiddenimports = collect_submodules("google.genai", filter=lambda name: not name.startswith("google.genai.tests"))
datas = collect_data_files("google.genai") + copy_metadata("google-genai")
'@
Set-Content -LiteralPath (Join-Path $HooksDir "hook-google.genai.py") -Value $GoogleHook -Encoding utf8

Write-Host "[QT-DEV] PyInstaller $Version / $BuildId"
$Args=@("--noconfirm","--clean","--onedir","--windowed","--contents-directory",".","--name","JARVIS","--icon",$IconFile,"--version-file",$VersionFile,"--distpath",$DistDir,"--workpath",$WorkDir,"--specpath",$SpecDir,"--additional-hooks-dir",$HooksDir,"--add-data","$DataDir;data","--add-data","$PluginsDir;plugins","--add-data","$UpdateConfig;.","--add-data","$IconFile;.","--hidden-import","PySide6.QtCore","--hidden-import","PySide6.QtGui","--hidden-import","PySide6.QtWidgets","--exclude-module","customtkinter","--collect-all","sounddevice","--collect-all","vosk","--collect-submodules","edge_tts","--hidden-import","send2trash","--hidden-import","send2trash.win","--hidden-import","send2trash.win.modern","--hidden-import","send2trash.win.legacy","--hidden-import","send2trash.win.IFileOperationProgressSink","--hidden-import","pystray._win32","--hidden-import","webrtcvad","--hidden-import","_webrtcvad","--hidden-import","voice_engine","--hidden-import","desktop_integration","--hidden-import","win32timezone","--hidden-import","pythoncom","--hidden-import","pywintypes",$MainPath)
foreach($Asset in $RequiredAssets){ $Args+=@("--add-data","$((Join-Path $AssetsDir $Asset));assets") }
python -m PyInstaller @Args
if($LASTEXITCODE -ne 0){ throw "PyInstaller Qt Dev failed" }
Require-Path $ExePath "JARVIS.exe"
$BundledAssets=Join-Path $DistDir "JARVIS\assets"
foreach($Asset in $RequiredAssets){ Require-Path (Join-Path $BundledAssets $Asset) "bundled approved UI asset $Asset" }

$RuntimeReport=Join-Path $WorkDir "runtime-selftest.json"; Remove-Item -Force $RuntimeReport -ErrorAction SilentlyContinue
$Runtime=Start-Process -FilePath $ExePath -ArgumentList @("--runtime-selftest",$RuntimeReport) -Wait -PassThru
if($Runtime.ExitCode -ne 0){ if(Test-Path -LiteralPath $RuntimeReport){ Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw) }; throw "Runtime selftest Qt Dev failed: $($Runtime.ExitCode)" }
$Report=Get-Content -LiteralPath $RuntimeReport -Raw|ConvertFrom-Json
if(-not $Report.ok -or -not $Report.checks.pyside6 -or -not $Report.checks.single_qt_ui){ Write-Host (Get-Content -LiteralPath $RuntimeReport -Raw); throw "Frozen runtime did not confirm the single-source Qt UI" }

$Iscc=(Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if(-not $Iscc){$Iscc=(Get-Command iscc.exe -ErrorAction SilentlyContinue).Source}
if(-not $Iscc){$Iscc=@("C:\Program Files (x86)\Inno Setup 6\ISCC.exe","C:\Program Files\Inno Setup 6\ISCC.exe")|Where-Object{Test-Path $_}|Select-Object -First 1}
if(-not $Iscc){throw "ISCC.exe not found"}
New-Item -ItemType Directory -Force $ReleaseDir|Out-Null
& $Iscc "/DMyAppVersion=$Version" $IssFile
if($LASTEXITCODE -ne 0){throw "Inno Setup Qt Dev failed"}
$Installer=Join-Path $ReleaseDir "JARVIS_Setup_$Version.exe"; Require-Path $Installer "Qt Dev installer"; $Hash=(Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant(); "$Hash  JARVIS_Setup_$Version.exe"|Set-Content "$Installer.sha256" -Encoding ascii
$Identity=@{version=$Version;build_id=$BuildId;channel="dev";sha256=$Hash;size=(Get-Item -LiteralPath $Installer).Length;ui_source="gui.py";approved_assets=$RequiredAssets}|ConvertTo-Json
Set-Content -LiteralPath (Join-Path $ReleaseDir "dev-build.json") -Value $Identity -Encoding utf8
Write-Host "[QT-DEV] OK $Version / $BuildId / $Hash"
