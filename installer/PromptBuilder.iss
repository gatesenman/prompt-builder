; PromptBuilder 2.6 — standard Inno Setup installer
; Wizard: Welcome → Directory → Tasks → Install → Finish
; AppId kept stable across 2.x for upgrades

#define MyAppName "提示词 Builder"
#define MyAppNameEn "PromptBuilder"
#define MyAppVersion "2.12.8"
#define MyAppPublisher "Allen49 Thompson"
#define MyAppExeName "PromptBuilder.exe"
#define MyAppId "PromptBuilder-Allen49-WebUI-200"
#define MyAppURL "https://localhost/promptbuilder"

[Setup]
AppId={{A49E7C2B-5D81-4F0A-9B3E-11C0DE210000}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=
InfoBeforeFile=
OutputDir=..\dist_installer
OutputBaseFilename=PromptBuilder-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=100
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
CloseApplications=yes
RestartApplications=no
DisableDirPage=no
AllowNoIcons=yes
MinVersion=10.0

[Languages]
; Simplified Chinese wizard when the translation ships with this Inno Setup, English otherwise
#define LangCN AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl"
#if FileExists(LangCN)
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "autostart"; Description: "开机时自动启动（托盘常驻）"; GroupDescription: "启动选项:"; Flags: unchecked

[InstallDelete]
; remove the previous version's program files first (stale modules from 2.3 / 2.4);
; user data lives in %LOCALAPPDATA%\PromptBuilder and is never touched
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\PromptBuilder.exe"

[Files]
; PyInstaller onedir output
Source: "..\dist\PromptBuilder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Optional autostart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PromptBuilder"; ValueData: """{app}\{#MyAppExeName}"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  EVENT_MODIFY_STATE = $0002;
  SYNCHRONIZE = $00100000;
  TASK_NAME = 'PromptBuilder\ElevatedStart';

function OpenEventW(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function OpenMutexW(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; lpName: String): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

{ Ask a running PromptBuilder (also an elevated one, which Restart Manager cannot close) to save and quit. }
procedure SignalAppQuit();
var
  h: THandle;
  i: Integer;
begin
  h := OpenEventW(EVENT_MODIFY_STATE, False, 'Local\PromptBuilder.Quit');
  if h = 0 then exit;
  SetEvent(h);
  CloseHandle(h);
  for i := 1 to 40 do
  begin
    h := OpenMutexW(SYNCHRONIZE, False, 'Local\PromptBuilder.SingleInstance');
    if h = 0 then exit;
    CloseHandle(h);
    Sleep(150);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  SignalAppQuit();
  Result := '';
end;

{ Uninstall: remove the "run as administrator" scheduled task if the user had enabled it. }
procedure RemoveElevatedTask();
var
  rc: Integer;
begin
  if Exec(ExpandConstant('{sys}\schtasks.exe'), '/Query /TN "' + TASK_NAME + '"', '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    ShellExec('runas', ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "' + TASK_NAME + '" /F', '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    SignalAppQuit();
    RemoveElevatedTask();
  end;
end;

function WebView2Installed(): Boolean;
var
  v: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    SuppressibleMsgBox('提示：本机未检测到 Microsoft Edge WebView2 运行时。' + #13#10 +
      '提示词 Builder 的界面依赖它（Windows 10/11 通常自带）。' + #13#10#13#10 +
      '安装可以继续；如果启动时提示缺少 WebView2，请从微软官网安装：' + #13#10 +
      'https://go.microsoft.com/fwlink/p/?LinkId=2124703', mbInformation, MB_OK, IDOK);
end;
