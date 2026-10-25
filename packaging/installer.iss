; Inno Setup script for PulseDeck. Built by packaging/build.py, which passes
; /DAppVersion=… /DSourceDir=<PyInstaller output> /DOutputDir=….
;
; Per-user install (no administrator rights): %LOCALAPPDATA%\Programs\PulseDeck.
; User data lives in %APPDATA%\PulseDeck and is kept on update; on uninstall the user
; decides whether to delete it.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\PulseDeck"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{8C3B6E0A-2F5D-4B8E-9A61-5D0F7C2E41A9}
AppName=PulseDeck
AppVersion={#AppVersion}
AppVerName=PulseDeck {#AppVersion}
AppPublisher=KirDev
AppPublisherURL=https://github.com/kirdev07/Pulse-PC
AppSupportURL=https://github.com/kirdev07/Pulse-PC/issues
DefaultDirName={autopf}\PulseDeck
DefaultGroupName=PulseDeck
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=PulseDeck-{#AppVersion}-Setup
SetupIconFile=..\image\icon.ico
UninstallDisplayIcon={app}\PulseDeck.exe
UninstallDisplayName=PulseDeck
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
; Close a running PulseDeck before replacing its files (update / uninstall).
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=PulseDeck

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать PulseDeck вместе с Windows (свёрнутым в трей)"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files of the previous version that the new one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\PulseDeck"; Filename: "{app}\PulseDeck.exe"
Name: "{group}\Удалить PulseDeck"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PulseDeck"; Filename: "{app}\PulseDeck.exe"; Tasks: desktopicon

[Registry]
; The same value the app writes from «Настройки → Запускать вместе с Windows».
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PulseDeck"; ValueData: """{app}\PulseDeck.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue
; Entries of the previous name (Pulse-PC / Pulse PC 1.x) would start the old program twice.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "PulsePC"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "PulsePC_Bot"; Flags: deletevalue

[Run]
Filename: "{app}\PulseDeck.exe"; Description: "Запустить PulseDeck"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM PulseDeck.exe /F"; Flags: runhidden; RunOnceId: "StopPulseDeck"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    { The app may have enabled autostart itself; never leave a dead entry behind. }
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'PulseDeck');
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'PulsePC');
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\PulseDeck');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Удалить также настройки и данные PulseDeck?' + #13#10#13#10 +
                'Папка: ' + DataDir + #13#10 +
                'В ней токен бота, подключённые телефоны, список программ, журнал и полученные файлы.' + #13#10#13#10 +
                'Нажмите «Нет», если собираетесь установить PulseDeck снова.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
