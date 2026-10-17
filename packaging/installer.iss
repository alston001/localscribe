; Inno Setup 6 script: per-user installer (no administrator rights needed).
; 1. Build dist\LocalScribe with packaging\build.ps1
; 2. Compile:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
;    (built elsewhere?  add /DDistDir=..\dist_build\LocalScribe)
; The build is ~5 GB, so the installer is split into setup.exe + .bin files; keep them together.
; Slices stay under 1.9 GB because GitHub release assets must be smaller than 2 GiB.
; 3. packaging\release_assets.py builds the small update installer (update.iss) and latest.json.
; AppName, AppGuid and AppVersion can be given with /D (tests/test_installers.py installs a test copy).

#ifndef AppName
  #define AppName "LocalScribe"
#endif
#ifndef AppGuid
  #define AppGuid "8F3C2A51-6E4B-4D7A-9C1E-2B5F7A9D0E13"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.5"
#endif
#define AppExe "LocalScribe.exe"
#ifndef DistDir
  #define DistDir "..\dist\LocalScribe"
#endif

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LocalScribe-Setup-{#AppVersion}
SetupIconFile=localscribe.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=1900000000
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; LocalScribe starts again by itself after an update ([Run]); a restart by Windows would open a second copy.
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseTraditional.isl")
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; LocalScribe.exe, which holds the version the app reports, goes in last: Inno doesn't put back files it
; replaced, so an update that fails half way must leave the old version, which offers the update again.
Source: "{#DistDir}\*"; Excludes: "\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistDir}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

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

// ...so after a failed or cancelled install it comes back as it was ([Run] starts the new one).
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

function InitializeSetup: Boolean;
begin
  WaitForLocalScribe;
  Result := True;
end;

// The deepest bundled file is ~140 characters below {app}; Windows paths stop at 260.
// Silent installs call this too; /SUPPRESSMSGBOXES must still end them instead of waiting for OK.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and (Length(WizardDirValue) > 110) then
  begin
    SuppressibleMsgBox('This folder path is too long for Windows (260-character limit). Please choose a shorter folder, e.g. C:\LocalScribe.'
      + #13#10#13#10 + '安裝路徑太長（Windows 路徑上限 260 字元），請選擇較短的資料夾，例如 C:\LocalScribe。', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;
