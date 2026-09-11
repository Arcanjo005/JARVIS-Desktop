@echo off
setlocal
chcp 65001 >nul
set "EXE=C:\JARVIS\JARVIS.exe"
if not exist "%EXE%" (
  echo JARVIS.exe nao encontrado em C:\JARVIS
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%EXE%'; $v=(Get-Item -LiteralPath $p).VersionInfo.ProductVersion; Write-Host ('Executavel: '+$p); Write-Host ('ProductVersion: '+$v); if ($v -notlike '1.2.3*') { Write-Host 'ERRO: o executavel instalado nao e 1.2.3.' -ForegroundColor Red; exit 3 } else { Write-Host 'OK: executavel 1.2.3 instalado.' -ForegroundColor Green }"
echo.
echo Se aparecer ERRO acima, nao continue o teste: o instalador nao substituiu o EXE.
pause
