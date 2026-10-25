; Inno Setup script for Pulse-PC. Built by packaging/build.py, which passes
; /DAppVersion=… /DSourceDir=<PyInstaller output> /DOutputDir=….
;
; Per-user install (no administrator rights): %LOCALAPPDATA%\Programs\Pulse-PC.
; User data lives in %APPDATA%\Pulse-PC and is kept on update; on uninstall the user
; decides whether to delete it.

#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Pulse-PC"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{8C3B6E0A-2F5D-4B8E-9A61-5D0F7C2E41A9}
AppName=Pulse-PC
AppVersion={#AppVersion}
AppVerName=Pulse-PC {#AppVersion}
AppPublisher=KirDev
AppPublisherURL=https://github.com/kirdev07/Pulse-PC
AppSupportURL=https://github.com/kirdev07/Pulse-PC/issues
DefaultDirName={autopf}\Pulse-PC
DefaultGroupName=Pulse-PC
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Pulse-PC-{#AppVersion}-Setup
SetupIconFile=..\image\icon.ico
UninstallDisplayIcon={app}\Pulse-PC.exe
UninstallDisplayName=Pulse-PC
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
; Close a running Pulse-PC before replacing its files (update / uninstall).
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Pulse-PC

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать Pulse-PC вместе с Windows (свёрнутым в трей)"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files of the previous version that the new one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Pulse-PC"; Filename: "{app}\Pulse-PC.exe"
Name: "{group}\Удалить Pulse-PC"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Pulse-PC"; Filename: "{app}\Pulse-PC.exe"; Tasks: desktopicon

[Registry]
; The same value the app writes from «Настройки → Запускать вместе с Windows».
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PulsePC"; ValueData: """{app}\Pulse-PC.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Pulse-PC.exe"; Description: "Запустить Pulse-PC"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Pulse-PC.exe /F"; Flags: runhidden; RunOnceId: "StopPulsePC"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    { The app may have enabled autostart itself; never leave a dead entry behind. }
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'PulsePC');
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\Pulse-PC');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Удалить также настройки и данные Pulse-PC?' + #13#10#13#10 +
                'Папка: ' + DataDir + #13#10 +
                'В ней токен бота, подключённые телефоны, список программ, журнал и полученные файлы.' + #13#10#13#10 +
                'Нажмите «Нет», если собираетесь установить Pulse-PC снова.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
