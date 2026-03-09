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
; Modeler-style default: install into Houdini user prefs (Documents\houdiniXX.X\monofx)
DefaultDirName={code:GetDefaultDirName}
; We provide our own Houdini version page; skip the standard dir page in code.
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=MonoFXSuite_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Source = repo root (chạy ISCC từ repo root)
Source: "..\..\apps\*"; DestDir: "{app}\apps"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
; Houdini loads packages from Documents\houdiniXX.X\packages. We extract the package json to {tmp}
; and copy it to each selected Houdini version in ssPostInstall.
Source: "..\..\packages\monofx.json"; DestDir: "{tmp}"; DestName: "monofx.json"; Flags: ignoreversion deleteafterinstall
Source: "..\..\toolbar\*"; DestDir: "{app}\toolbar"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
; MonoStudio version detection (optional): if MonoStudio is installed, drop VERSION into its tools folder.
Source: "..\..\VERSION"; DestDir: "{code:GetMonoStudioToolsSuiteDir}"; Flags: ignoreversion; Check: ShouldInstallMonoStudioVersion
; Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
; Bỏ .git nếu không cần updater từ git
; Source: "..\..\.git\*"; DestDir: "{app}\.git"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}"; Comment: "MonoFX Suite root folder"

[Dirs]
; Ensure install root exists before copying files
Name: "{app}"
Name: "{app}\notes"
; Keep docs folder empty for future user guide
Name: "{app}\docs"

; HOUDINI_PACKAGE_DIR: append path MonoFX. Toolbar loaded via package hpath ($MONOFX_SUITE/toolbar).
; Houdini version detection: HKLM\SOFTWARE\Side Effects Software\Houdini (subkeys = versions).
; MonoStudio integration: Option A (under MonoStudio) / B (user folder) / C (standalone).
; Option A path: read {localappdata}\MonoStudio\install_path.txt if present and valid, else {pf}\MonoStudio26\tools\MonoFXSuite.
[Code]
const
  HoudiniRegBase = 'SOFTWARE\Side Effects Software\Houdini';

var
  DetectedHoudiniVersions: string;
  _HoudiniUserPrefDir: string;
  _HoudiniUserDocsBase: string;
  HoudiniVersionPageID: Integer;
  HoudiniVersionNames: TArrayOfString;
  HoudiniVersionChecks: array of TNewCheckBox;
  LblHoudiniVersionHint: TNewStaticText;

function _try_parse_houdini_dir_name(const name: string; var major: Integer; var minor: Integer): Boolean;
var
  s, nums: string;
  p: Integer;
begin
  Result := False;
  major := 0;
  minor := 0;
  s := name;
  if CompareText(Copy(s, 1, 7), 'houdini') <> 0 then
    Exit;
  nums := Copy(s, 8, Length(s) - 7);
  p := Pos('.', nums);
  if p <= 0 then
    Exit;
  try
    major := StrToInt(Copy(nums, 1, p - 1));
    minor := StrToInt(Copy(nums, p + 1, Length(nums) - p));
    Result := True;
  except
    Result := False;
  end;
end;

function _houdini_dir_version_key(const name: string): Integer;
var
  major, minor: Integer;
begin
  { Key for sorting: major*1000 + minor; invalid -> -1 }
  if _try_parse_houdini_dir_name(name, major, minor) then
    Result := major * 1000 + minor
  else
    Result := -1;
end;

procedure _swap_str(var a: string; var b: string);
var
  t: string;
begin
  t := a;
  a := b;
  b := t;
end;

procedure _sort_houdini_dir_names_desc(var arr: TArrayOfString);
var
  i, j: Integer;
begin
  for i := 0 to GetArrayLength(arr) - 2 do
    for j := i + 1 to GetArrayLength(arr) - 1 do
      if _houdini_dir_version_key(arr[j]) > _houdini_dir_version_key(arr[i]) then
        _swap_str(arr[i], arr[j]);
end;

function GetHoudiniUserPrefDir: string;
var
  base, bestName, curName: string;
  fr: TFindRec;
  bestMajor, bestMinor, curMajor, curMinor: Integer;
begin
  if _HoudiniUserPrefDir <> '' then
  begin
    Result := _HoudiniUserPrefDir;
    Exit;
  end;

  base := ExpandConstant('{userdocs}');
  _HoudiniUserDocsBase := base;
  bestName := '';
  bestMajor := -1;
  bestMinor := -1;

  if FindFirst(base + '\houdini*', fr) then
  begin
    try
      repeat
        if (fr.Attributes and 16) <> 0 then
        begin
          curName := fr.Name;
          if _try_parse_houdini_dir_name(curName, curMajor, curMinor) then
          begin
            if (curMajor > bestMajor) or ((curMajor = bestMajor) and (curMinor > bestMinor)) then
            begin
              bestMajor := curMajor;
              bestMinor := curMinor;
              bestName := curName;
            end;
          end;
        end;
      until not FindNext(fr);
    finally
      FindClose(fr);
    end;
  end;

  if bestName <> '' then
    _HoudiniUserPrefDir := base + '\' + bestName
  else
  begin
    { Fallback: create a stable default folder under Documents }
    _HoudiniUserPrefDir := base + '\houdini';
  end;

  Result := _HoudiniUserPrefDir;
end;

function GetDefaultDirName(Param: string): string;
begin
  Result := GetHoudiniUserPrefDir + '\monofx';
end;

function GetHoudiniPackagesDir(Param: string): string;
begin
  Result := GetHoudiniUserPrefDir + '\packages';
end;

function GetMonoStudioToolsSuiteDir(Param: string): string;
var
  TxtPath, BasePath: string;
  Lines: TArrayOfString;
  n: Integer;
begin
  Result := '';
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

function ShouldInstallMonoStudioVersion: Boolean;
begin
  Result := GetMonoStudioToolsSuiteDir('') <> '';
end;

procedure InitializeWizard;
var
  Page: TWizardPage;
  base: string;
  fr: TFindRec;
  names: TArrayOfString;
  n: Integer;
  cb: TNewCheckBox;
  topY: Integer;
begin
  _HoudiniUserPrefDir := '';
  _HoudiniUserDocsBase := '';

  base := ExpandConstant('{userdocs}');
  _HoudiniUserDocsBase := base;

  { Build list of Documents\houdiniXX.X folders }
  SetArrayLength(names, 0);
  if FindFirst(base + '\houdini*', fr) then
  begin
    try
      repeat
        if (fr.Attributes and 16) <> 0 then
        begin
          if _houdini_dir_version_key(fr.Name) >= 0 then
          begin
            n := GetArrayLength(names);
            SetArrayLength(names, n + 1);
            names[n] := fr.Name;
          end;
        end;
      until not FindNext(fr);
    finally
      FindClose(fr);
    end;
  end;
  if GetArrayLength(names) > 1 then
    _sort_houdini_dir_names_desc(names);

  { Custom page: choose Houdini version folder }
  Page := CreateCustomPage(wpWelcome, 'Houdini version', 'Choose which Houdini user folder to install into (Modeler-style).');
  HoudiniVersionPageID := Page.ID;

  HoudiniVersionNames := names;
  SetArrayLength(HoudiniVersionChecks, 0);
  topY := 0;

  if GetArrayLength(HoudiniVersionNames) = 0 then
  begin
    SetArrayLength(HoudiniVersionNames, 1);
    HoudiniVersionNames[0] := 'houdini21.0';
  end;

  for n := 0 to GetArrayLength(HoudiniVersionNames) - 1 do
  begin
    cb := TNewCheckBox.Create(Page);
    cb.Parent := Page.Surface;
    cb.Left := 0;
    cb.Top := topY;
    cb.Width := Page.SurfaceWidth;
    cb.Caption := HoudiniVersionNames[n];
    cb.Checked := (n = 0); { default: newest only }
    topY := topY + cb.Height + 6;

    SetArrayLength(HoudiniVersionChecks, n + 1);
    HoudiniVersionChecks[n] := cb;
  end;

  LblHoudiniVersionHint := TNewStaticText.Create(Page);
  LblHoudiniVersionHint.Parent := Page.Surface;
  LblHoudiniVersionHint.Left := 0;
  LblHoudiniVersionHint.Top := topY + 6;
  LblHoudiniVersionHint.AutoSize := True;
  LblHoudiniVersionHint.Caption :=
    'Install path(s): ' + base + '\houdiniXX.X\monofx (checked versions).';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { We choose the install folder via the Houdini version page }
  Result := (PageID = wpSelectDir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  folder: string;
  i: Integer;
  anyChecked: Boolean;
begin
  Result := True;
  if CurPageID = HoudiniVersionPageID then
  begin
    anyChecked := False;
    folder := '';
    for i := 0 to GetArrayLength(HoudiniVersionChecks) - 1 do
    begin
      if (HoudiniVersionChecks[i] <> nil) and HoudiniVersionChecks[i].Checked then
      begin
        anyChecked := True;
        if folder = '' then
          folder := HoudiniVersionChecks[i].Caption; { primary install dir = first checked (newest order) }
      end;
    end;

    if not anyChecked then
    begin
      SuppressibleMsgBox('Select at least one Houdini version.', mbError, MB_OK, IDOK);
      Result := False;
      Exit;
    end;

    if (folder = '') or (Pos('houdini', folder) <> 1) then
      folder := 'houdini21.0';

    _HoudiniUserPrefDir := _HoudiniUserDocsBase + '\' + folder;
    WizardForm.DirEdit.Text := _HoudiniUserPrefDir + '\monofx';
  end;
end;

procedure _copy_dir_tree(const srcDir, dstDir: string);
var
  fr: TFindRec;
  srcPath, dstPath: string;
begin
  if (srcDir = '') or (dstDir = '') then Exit;
  if not DirExists(srcDir) then Exit;
  ForceDirectories(dstDir);

  if FindFirst(srcDir + '\*', fr) then
  begin
    try
      repeat
        if (fr.Name = '.') or (fr.Name = '..') then
          continue;
        srcPath := srcDir + '\' + fr.Name;
        dstPath := dstDir + '\' + fr.Name;
        if (fr.Attributes and 16) <> 0 then
          _copy_dir_tree(srcPath, dstPath)
        else
        begin
          ForceDirectories(ExtractFileDir(dstPath));
          CopyFile(srcPath, dstPath, False);
        end;
      until not FindNext(fr);
    finally
      FindClose(fr);
    end;
  end;
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
  i: Integer;
  baseDir, verName, targetPref, targetMonofx, targetPackages, srcMonofx, pkgSrc, pkgDst: string;
begin
  if CurStep = ssPostInstall then
  begin
    { Copy package json to each selected Houdini version, and replicate install to additional versions }
    baseDir := _HoudiniUserDocsBase;
    if baseDir = '' then
      baseDir := ExpandConstant('{userdocs}');

    srcMonofx := ExpandConstant('{app}');
    pkgSrc := ExpandConstant('{tmp}\monofx.json');

    for i := 0 to GetArrayLength(HoudiniVersionChecks) - 1 do
    begin
      if (HoudiniVersionChecks[i] = nil) or (not HoudiniVersionChecks[i].Checked) then
        Continue;

      verName := HoudiniVersionChecks[i].Caption;
      if (verName = '') or (Pos('houdini', verName) <> 1) then
        Continue;

      targetPref := baseDir + '\' + verName;
      targetMonofx := targetPref + '\monofx';
      targetPackages := targetPref + '\packages';

      (* If this is not the primary install location, mirror files from the primary install folder *)
      if Lowercase(Trim(targetMonofx)) <> Lowercase(Trim(srcMonofx)) then
        _copy_dir_tree(srcMonofx, targetMonofx);

      { Ensure monofx.json exists in packages for this Houdini version }
      if pkgSrc <> '' then
      begin
        ForceDirectories(targetPackages);
        pkgDst := targetPackages + '\monofx.json';
        CopyFile(pkgSrc, pkgDst, False);
      end;
    end;

    DetectedHoudiniVersions := DetectHoudiniVersions;
    CopyToolbarToUserHoudini;
  end;
end;
