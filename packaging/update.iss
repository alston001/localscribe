; Inno Setup 6 script for the small update installer: only the files that changed since the
; versions in UpdateFrom, installed over an existing LocalScribe (per user, no administrator rights).
; LocalScribe runs it when someone clicks Update (localscribe\core\update.py); a double-click works too.
; packaging\release_assets.py writes the file list and compiles this script:
;   ISCC /DDistDir=<bundle folder> /DUpdateList=<file list> packaging\update.iss

#ifndef AppName
  #define AppName "LocalScribe"
#endif
#ifndef AppGuid
  #define AppGuid "8F3C2A51-6E4B-4D7A-9C1E-2B5F7A9D0E13"
#endif
#define AppExe "LocalScribe.exe"
#define AppURL "https://github.com/alston001/localscribe/releases"
#include UpdateList  ; AppVersion, UpdateFrom, [Files] and [InstallDelete]

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LocalScribe-Update-{#AppVersion}
SetupIconFile=localscribe.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/fast
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; LocalScribe starts again by itself ([Run]); a restart by Windows would open a second copy.
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseTraditional.isl")
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
#endif

[Run]
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent; Check: WantsRelaunch
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';
  SYNCHRONIZE = $00100000;

var
  Finished: Boolean;    // every file is in place
  Relaunched: Boolean;

function OpenProcess(dwDesiredAccess: Longword; bInheritHandle: Bool; dwProcessId: Longword): Longword;
external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle, dwMilliseconds: Longword): Longword;
external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: Longword): Bool;
external 'CloseHandle@kernel32.dll stdcall';

// LocalScribe passes /relaunch=1 when it runs this installer silently after quitting itself.
function WantsRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

// ...so after a refused, failed or cancelled update it comes back as it was ([Run] starts the new one).
procedure RelaunchInstalledCopy;
var
  Folder: String;
  Code: Integer;
begin
  if Relaunched or not WantsRelaunch then
    Exit;
  Relaunched := True;
  if RegQueryStringValue(HKCU, UninstallKey, 'Inno Setup: App Path', Folder)
    and FileExists(AddBackslash(Folder) + '{#AppExe}') then
  begin
    Log('Starting the LocalScribe that is still installed');
    ShellExec('', AddBackslash(Folder) + '{#AppExe}', '', Folder, SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    Finished := True;
end;

procedure DeinitializeSetup;
begin
  if not Finished then
    RelaunchInstalledCopy;
end;

// ...and /waitpid=<its process id>: its files can only be replaced once it has really ended.
procedure WaitForLocalScribe;
var
  Process: Longword;
begin
  Process := OpenProcess(SYNCHRONIZE, False, StrToIntDef(ExpandConstant('{param:waitpid|0}'), 0));
  if Process <> 0 then
  begin
    WaitForSingleObject(Process, 30000);
    CloseHandle(Process);
  end;
end;

// The update holds only the files that changed, so everything else must already be installed.
function InitializeSetup: Boolean;
var
  Installed, Folder, Versions: String;
begin
  WaitForLocalScribe;
  if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Installed) then
    Installed := '';
  if not RegQueryStringValue(HKCU, UninstallKey, 'Inno Setup: App Path', Folder) then
    Folder := '';
  Result := (Installed <> '') and (Pos(',' + Installed + ',', ',{#UpdateFrom},') > 0)
    and FileExists(AddBackslash(Folder) + '{#AppExe}');
  if not Result then
  begin
    Versions := '{#UpdateFrom}';
    StringChangeEx(Versions, ',', ', ', True);
    SuppressibleMsgBox('This update installs only over {#AppName} ' + Versions + '. Please download the full installer from {#AppURL}'
      + #13#10#13#10 + '這個更新檔只能裝在 {#AppName} ' + Versions + ' 上，請到 {#AppURL} 下載完整安裝檔。',
      mbError, MB_OK, IDOK);
    RelaunchInstalledCopy;  // whether or not Setup still calls DeinitializeSetup after this
  end;
end;
