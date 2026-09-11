#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "JARVIS Desktop"
#define MyAppPublisher "JARVIS Desktop"
#define MyAppExeName "JARVIS.exe"

[Setup]
AppId={{A7AD4F0A-1E31-4C65-B722-130E42E2D52A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\JARVIS
DefaultGroupName=JARVIS Desktop
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=JARVIS_Setup_{#MyAppVersion}
SetupIconFile=..\jarvis.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dark windows11 hidebevels includetitlebar
WizardSizePercent=120,120
WizardResizable=no
WizardBackColor=#07111F
WizardImageFile=..\installer\jarvis_wizard.png
WizardImageBackColor=#07111F
WizardSmallImageFile=..\installer\jarvis_small.png
WizardSmallImageBackColor=#07111F
DisableWelcomePage=no
DisableReadyPage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName=JARVIS Desktop
VersionInfoDescription=Instalador do JARVIS Desktop
VersionInfoCompany=JARVIS Desktop
VersionInfoProductVersion={#MyAppVersion}.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "startup"; Description: "Iniciar o JARVIS com o Windows"; GroupDescription: "Inicialização:"; Flags: unchecked

[InstallDelete]
; Migração de instalações antigas baseadas em Python. Nunca apaga .env nem dados do usuário.
Type: files; Name: "{app}\*.py"
Type: files; Name: "{app}\*.pyc"
Type: files; Name: "{app}\*.bat"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\backups"
Type: filesandordirs; Name: "{app}\_backup_*"

[Files]
; O pacote PyInstaller é plano para que os caminhos de dados do JARVIS continuem consistentes.
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\tts_pronunciation.json"
; Pronúncias podem ser aprendidas pelo usuário e nunca devem ser sobrescritas por update.
Source: "..\dist\JARVIS\data\tts_pronunciation.json"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\logs"; Permissions: users-modify
Name: "{app}\screenshots"; Permissions: users-modify

[Icons]
Name: "{group}\JARVIS Desktop"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Configurar API Gemini"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure-api"; WorkingDir: "{app}"
Name: "{autodesktop}\JARVIS Desktop"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\JARVIS Desktop"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startup

[Run]
; Em instalação manual, a configuração da chave aparece ANTES da primeira abertura.
; Atualizações automáticas são silenciosas e preservam a chave existente.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure-api"; WorkingDir: "{app}"; Flags: waituntilterminated skipifsilent; Check: not IsUpdateMode
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir JARVIS Desktop"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Check: not IsUpdateMode
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Flags: nowait; Check: IsUpdateMode

[Code]
function HasCommandLineSwitch(const SwitchName: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), SwitchName) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsUpdateMode: Boolean;
begin
  Result := HasCommandLineSwitch('/UPDATE=1');
end;

procedure StopRunningJarvis;
var
  ResultCode: Integer;
begin
  { A janela pode ter sido ocultada na bandeja e continuar segurando o mutex.
    Encerra somente JARVIS.exe antes de substituir os arquivos. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM JARVIS.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure ResetHotRuntimePointers;
begin
  { O instalador completo é a fonte de verdade. Remove somente os ponteiros
    efêmeros do Hot Runtime; não toca em chave, conversas ou preferências. }
  DeleteFile(ExpandConstant('{localappdata}\JARVIS\runtime\active.json'));
  DeleteFile(ExpandConstant('{localappdata}\JARVIS\runtime\booting.json'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningJarvis;
  ResetHotRuntimePointers;
  Result := '';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then
    WizardForm.NextButton.Caption := 'INSTALAR'
  else if CurPageID = wpFinished then
    WizardForm.NextButton.Caption := 'CONCLUIR'
  else
    WizardForm.NextButton.Caption := 'AVANCAR';

  WizardForm.BackButton.Caption := 'VOLTAR';
  WizardForm.CancelButton.Caption := 'CANCELAR';
end;
