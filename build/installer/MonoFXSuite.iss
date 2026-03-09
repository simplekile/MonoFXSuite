; MonoFX Suite — Inno Setup script (skeleton)
; Chỉnh lại AppId, version, paths khi build thật.

#define MyAppName "MonoFX Suite"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "MonoFX"
#define MyAppURL "https://github.com/simplekile/MonoFXSuite"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\MonoFXSuite
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=MonoFXSuite_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Source = repo root (chạy ISCC từ repo root)
Source: "..\..\apps\*"; DestDir: "{app}\apps"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\packages\*"; DestDir: "{app}\packages"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\toolbar\*"; DestDir: "{app}\toolbar"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
; Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
; Bỏ .git nếu không cần updater từ git
; Source: "..\..\.git\*"; DestDir: "{app}\.git"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}"; Comment: "MonoFX Suite root folder"

[Dirs]
; Force creation of install path (e.g. ...\MonoStudio26\tools\MonoFXSuite) before copying files
Name: "{app}"
Name: "{app}\notes"

; HOUDINI_PACKAGE_DIR: append path MonoFX. Toolbar loaded via package hpath ($MONOFX_SUITE/toolbar).
; Houdini version detection: HKLM\SOFTWARE\Side Effects Software\Houdini (subkeys = versions).
; MonoStudio integration: Option A (under MonoStudio) / B (user folder) / C (standalone).
; Option A path: read {localappdata}\MonoStudio\install_path.txt if present and valid, else {pf}\MonoStudio26\tools\MonoFXSuite.
[Code]
const
  EnvKey = 'Environment';
  VarName = 'HOUDINI_PACKAGE_DIR';
  HoudiniRegBase = 'SOFTWARE\Side Effects Software\Houdini';
  InstallChoiceMonoStudio = 0;
  InstallChoiceUser = 1;
  InstallChoiceStandalone = 2;

var
  DetectedHoudiniVersions: string;
  InstallLocationPageID: Integer;
  InstallChoice: Integer;
  PrevPageID: Integer;
  OptMonoStudio, OptUser, OptStandalone: TNewRadioButton;
  LblMonoStudio, LblUser: TNewStaticText;

function GetMonoStudioPath: string;
var
  TxtPath, BasePath: string;
  Lines: TArrayOfString;
  n: Integer;
begin
  Result := ExpandConstant('{pf}\MonoStudio26\tools\MonoFXSuite');
  TxtPath := ExpandConstant('{localappdata}\MonoStudio\install_path.txt');
  if FileExists(TxtPath) and LoadStringsFromFile(TxtPath, Lines) and (GetArrayLength(Lines) > 0) then
  begin
    BasePath := Trim(Lines[0]);
    n := Length(BasePath);
    if (n > 10) and (CompareText(Copy(BasePath, n - 9, 10), '\_internal') = 0) then
      BasePath := Copy(BasePath, 1, n - 10);
    if (BasePath <> '') and DirExists(BasePath) then
      Result := BasePath + '\tools\MonoFXSuite';
  end;
end;

function GetUserPath: string;
begin
  Result := ExpandConstant('{localappdata}\MonoStudio\tools\MonoFXSuite');
end;

procedure InitializeWizard;
var
  Page: TWizardPage;
begin
  Page := CreateCustomPage(wpWelcome, 'Install location', 'Choose where to install MonoFX Suite. MonoStudio can detect the installed version and offer updates when installed under Option A or B.');
  InstallLocationPageID := Page.ID;

  OptMonoStudio := TNewRadioButton.Create(Page);
  OptMonoStudio.Parent := Page.Surface;
  OptMonoStudio.Left := 0;
  OptMonoStudio.Top := 0;
  OptMonoStudio.Width := Page.SurfaceWidth;
  OptMonoStudio.Caption := 'Under MonoStudio (recommended for Settings -> Updates integration)';
  OptMonoStudio.Checked := True;

  LblMonoStudio := TNewStaticText.Create(Page);
  LblMonoStudio.Parent := Page.Surface;
  LblMonoStudio.Left := 20;
  LblMonoStudio.Top := 22;
  LblMonoStudio.Caption := 'Path: ' + GetMonoStudioPath;
  LblMonoStudio.AutoSize := True;

  OptUser := TNewRadioButton.Create(Page);
  OptUser.Parent := Page.Surface;
  OptUser.Left := 0;
  OptUser.Top := 50;
  OptUser.Width := Page.SurfaceWidth;
  OptUser.Caption := 'User folder (no admin; MonoStudio still detects for updates)';

  LblUser := TNewStaticText.Create(Page);
  LblUser.Parent := Page.Surface;
  LblUser.Left := 20;
  LblUser.Top := 72;
  LblUser.Caption := 'Path: ' + GetUserPath;
  LblUser.AutoSize := True;

  OptStandalone := TNewRadioButton.Create(Page);
  OptStandalone.Parent := Page.Surface;
  OptStandalone.Left := 0;
  OptStandalone.Top := 100;
  OptStandalone.Width := Page.SurfaceWidth;
  OptStandalone.Caption := 'Standalone (choose folder on next page)';

  PrevPageID := -1;
  InstallChoice := InstallChoiceMonoStudio;
end;

function DetectHoudiniVersions: string;
var
  Names: TArrayOfString;
  i: Integer;
  VerList: string;
begin
  Result := '';
  VerList := '';
  if RegGetSubkeyNames(HKEY_LOCAL_MACHINE, HoudiniRegBase, Names) then
  begin
    for i := 0 to GetArrayLength(Names) - 1 do
    begin
      if VerList <> '' then VerList := VerList + ', ';
      VerList := VerList + Names[i];
    end;
    Result := VerList;
  end;
  if Result = '' then
    Result := '(none detected)';
end;

procedure CopyToolbarIcons(const AppToolbar, DestDir: string);
var
  IconDir, DestIconDir: string;
  FindRec: TFindRec;
begin
  IconDir := AppToolbar + '\icons';
  if not DirExists(IconDir) then Exit;
  DestIconDir := DestDir + '\icons';
  ForceDirectories(DestIconDir);
  if FindFirst(IconDir + '\*.svg', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and 16) = 0 then
          CopyFile(IconDir + '\' + FindRec.Name, DestIconDir + '\' + FindRec.Name, False);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CopyConfigIconsToUser(const AppDir, HoudiniUserDir: string);
var
  SrcIcons, DestIcons: string;
  FindRec: TFindRec;
begin
  SrcIcons := AppDir + '\config\Icons';
  if not DirExists(SrcIcons) then Exit;
  DestIcons := HoudiniUserDir + '\config\Icons';
  ForceDirectories(DestIcons);
  if FindFirst(SrcIcons + '\*.svg', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and 16) = 0 then
          CopyFile(SrcIcons + '\' + FindRec.Name, DestIcons + '\' + FindRec.Name, False);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure WriteMonofxShelfPackage(const HoudiniUserDir: string);
var
  PkgPath, PkgContent: string;
begin
  ForceDirectories(HoudiniUserDir + '\packages');
  PkgPath := HoudiniUserDir + '\packages\monofx_shelf.json';
  PkgContent := '{"enable":true,"hpath":"$HOUDINI_USER_PREF_DIR/monofx","show":false}';
  SaveStringToFile(PkgPath, PkgContent, False);
end;

procedure CopyToolbarToUserHoudini;
var
  Names: TArrayOfString;
  i: Integer;
  UserDocs, AppDir, AppToolbar, MonofxDir, DestToolbar, DestFile, HoudiniUserDir: string;
  FindRec: TFindRec;
begin
  UserDocs := ExpandConstant('{userdocs}');
  AppDir := ExpandConstant('{app}');
  AppToolbar := AppDir + '\toolbar';
  if not FileExists(AppToolbar + '\MonoFX.shelf') then
    Exit;
  if RegGetSubkeyNames(HKEY_LOCAL_MACHINE, HoudiniRegBase, Names) then
    for i := 0 to GetArrayLength(Names) - 1 do
    begin
      HoudiniUserDir := UserDocs + '\houdini' + Names[i];
      MonofxDir := HoudiniUserDir + '\monofx';
      DestToolbar := MonofxDir + '\toolbar';
      ForceDirectories(DestToolbar);
      DestFile := DestToolbar + '\MonoFX.shelf';
      CopyFile(AppToolbar + '\MonoFX.shelf', DestFile, False);
      CopyToolbarIcons(AppToolbar, DestToolbar);
      CopyConfigIconsToUser(AppDir, MonofxDir);
      WriteMonofxShelfPackage(HoudiniUserDir);
    end;
  if FindFirst(UserDocs + '\houdini*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and 16) <> 0 then
        begin
          HoudiniUserDir := UserDocs + '\' + FindRec.Name;
          MonofxDir := HoudiniUserDir + '\monofx';
          DestToolbar := MonofxDir + '\toolbar';
          ForceDirectories(DestToolbar);
          DestFile := DestToolbar + '\MonoFX.shelf';
          CopyFile(AppToolbar + '\MonoFX.shelf', DestFile, False);
          CopyToolbarIcons(AppToolbar, DestToolbar);
          CopyConfigIconsToUser(AppDir, MonofxDir);
          WriteMonofxShelfPackage(HoudiniUserDir);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Current, NewPath, Sep: string;
begin
  if CurStep = ssPostInstall then
  begin
    NewPath := ExpandConstant('{app}\packages');
    Sep := ';';
    if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, VarName, Current) then
      Current := '';
    Current := Trim(Current);
    if Current = '' then
      Current := NewPath
    else if Pos(Lowercase(NewPath), Lowercase(Current)) = 0 then
      Current := Current + Sep + NewPath;
    RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, VarName, Current);
    { Ensure tools can resolve suite root even if Houdini packages are not loaded yet }
    RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, 'MONOFX_SUITE', ExpandConstant('{app}'));
    DetectedHoudiniVersions := DetectHoudiniVersions;
    CopyToolbarToUserHoudini;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if PrevPageID = InstallLocationPageID then
  begin
    if OptMonoStudio.Checked then InstallChoice := InstallChoiceMonoStudio
    else if OptUser.Checked then InstallChoice := InstallChoiceUser
    else InstallChoice := InstallChoiceStandalone;
  end;
  if CurPageID = wpSelectDir then
  begin
    if InstallChoice = InstallChoiceMonoStudio then
      WizardForm.DirEdit.Text := GetMonoStudioPath
    else if InstallChoice = InstallChoiceUser then
      WizardForm.DirEdit.Text := GetUserPath
    else
      WizardForm.DirEdit.Text := ExpandConstant('{autopf}\MonoFXSuite');
  end;
  PrevPageID := CurPageID;

  if CurPageID = wpFinished then
  begin
    if DetectedHoudiniVersions = '' then
      DetectedHoudiniVersions := DetectHoudiniVersions;
    WizardForm.FinishedLabel.Caption :=
      'MonoFX Suite has been installed.' + #13#10 + #13#10 +
      'HOUDINI_PACKAGE_DIR has been updated. Restart Houdini to load the MonoFX package and toolbar.' + #13#10 + #13#10 +
      'Detected Houdini versions (registry): ' + DetectedHoudiniVersions;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Current, RemovePath, Part, NewValue: string;
  i: Integer;
  SuiteVar: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemovePath := ExpandConstant('{app}\packages');
    if RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, VarName, Current) then
    begin
      NewValue := '';
      Current := Current + ';';
      i := 1;
      while i <= Length(Current) do
      begin
        Part := '';
        while (i <= Length(Current)) and (Current[i] <> ';') do
        begin
          Part := Part + Current[i];
          i := i + 1;
        end;
        i := i + 1;
        Part := Trim(Part);
        if (Part <> '') and (Lowercase(Part) <> Lowercase(RemovePath)) then
        begin
          if NewValue <> '' then NewValue := NewValue + ';';
          NewValue := NewValue + Part;
        end;
      end;
      if NewValue = '' then
        RegDeleteValue(HKEY_CURRENT_USER, EnvKey, VarName)
      else
        RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, VarName, NewValue);
    end;
    { Remove MONOFX_SUITE only if it points to this install }
    if RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'MONOFX_SUITE', SuiteVar) then
      if Lowercase(Trim(SuiteVar)) = Lowercase(Trim(ExpandConstant('{app}'))) then
        RegDeleteValue(HKEY_CURRENT_USER, EnvKey, 'MONOFX_SUITE');
  end;
end;
