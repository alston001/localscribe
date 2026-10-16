; Inno Setup 6 script: per-user installer (no administrator rights needed).
; 1. Build dist\LocalScribe with packaging\build.ps1
; 2. Compile:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
;    (built elsewhere?  add /DDistDir=..\dist_build\LocalScribe)
; The build is ~5 GB, so the installer is split into setup.exe + .bin files; keep them together.
; Slices stay under 1.9 GB because GitHub release assets must be smaller than 2 GiB.

#define AppName "LocalScribe"
#define AppVersion "0.1.2"
#define AppExe "LocalScribe.exe"
#ifndef DistDir
  #define DistDir "..\dist\LocalScribe"
#endif

[Setup]
AppId={{8F3C2A51-6E4B-4D7A-9C1E-2B5F7A9D0E13}
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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseTraditional.isl")
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// The deepest bundled file is ~140 characters below {app}; Windows paths stop at 260.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and (Length(WizardDirValue) > 110) then
  begin
    MsgBox('This folder path is too long for Windows (260-character limit). Please choose a shorter folder, e.g. C:\LocalScribe.'
      + #13#10#13#10 + '安裝路徑太長（Windows 路徑上限 260 字元），請選擇較短的資料夾，例如 C:\LocalScribe。', mbError, MB_OK);
    Result := False;
  end;
end;
