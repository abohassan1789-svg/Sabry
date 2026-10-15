; A-H CODE — client installer (new; independent of installer/, installer_final/, installer_new/)
#define AppName "A-H CODE"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "A-H CODE.exe"
#define CfgExe "ahcode-config.exe"

[Setup]
AppId={{B533D238-22C1-432E-B2B9-C7B6B74ED57A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=A-H_CODE_Setup
SetupIconFile=ahcode.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef PREVIEW
; Visual check of the wizard pages only (no UAC); never ship this build.
PrivilegesRequired=lowest
#else
PrivilegesRequired=admin
#endif
WizardStyle=modern
WizardSizePercent=120
SetupLogging=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{commonappdata}\PHASEINV2"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\PHASEINV2\logs"; Permissions: users-modify; Flags: uninsneveruninstall

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\A-H CODE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\ahcode-dbcheck.exe"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DbPage: TInputQueryWizardPage;
  LanPage: TInputOptionWizardPage;
  BackupPage: TInputDirWizardPage;
  TestButton: TNewButton;
  TestStatus: TNewStaticText;
  TestedKey: String;
  DbMissing: Boolean;
  LogFile: String;

procedure Log2(const Line: String);
var Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + '  ' + Line;
  SaveStringsToUTF8File(LogFile, Lines, True);
  Log(Line);
end;

function IsLocalHost(const Host: String): Boolean;
var H: String;
begin
  H := Lowercase(Trim(Host));
  Result := (H = 'localhost') or (H = '127.0.0.1') or (H = '::1') or (H = '.');
end;

function DbHost(): String; begin Result := Trim(DbPage.Values[0]); end;
function DbPort(): String; begin Result := Trim(DbPage.Values[1]); end;
function DbName(): String; begin Result := Trim(DbPage.Values[2]); end;
function DbUser(): String; begin Result := Trim(DbPage.Values[3]); end;

function CurrentKey(): String;
begin
  Result := DbHost() + '|' + DbPort() + '|' + DbName() + '|' + DbUser() + '|' + DbPage.Values[4];
end;

function JsonString(const Json, Key: String): String;
var P, I: Integer; C: Char; Esc: Boolean;
begin
  Result := '';
  P := Pos('"' + Key + '": "', Json);
  if P = 0 then Exit;
  I := P + Length(Key) + 5;
  Esc := False;
  while I <= Length(Json) do
  begin
    C := Json[I];
    if Esc then
    begin
      if C = 'n' then Result := Result + #13#10
      else if C = 't' then Result := Result + ' '
      else Result := Result + C;
      Esc := False;
    end
    else if C = '\' then Esc := True
    else if C = '"' then Exit
    else Result := Result + C;
    I := I + 1;
  end;
end;

function WritePasswordFile(): String;
var Lines: TArrayOfString;
begin
  Result := ExpandConstant('{tmp}\dbpass.txt');
  SetArrayLength(Lines, 1);
  Lines[0] := DbPage.Values[4];
  SaveStringsToUTF8File(Result, Lines, False);
end;

{ Quotes one command-line argument; doubles a trailing backslash so "D:\" stays a path. }
function Q(const S: String): String;
begin
  if (Length(S) > 0) and (S[Length(S)] = '\') then
    Result := '"' + S + '\"'
  else
    Result := '"' + S + '"';
end;

function ConnArgs(const PassFile: String): String;
begin
  Result := Format('--host "%s" --port %s --user "%s" --password-file "%s"', [DbHost(), DbPort(), DbUser(), PassFile]);
end;

{ Runs a tool with --result-file first; returns True on exit code 0. }
function RunTool(const Exe, Params, Title: String; var Msg, Output: String): Boolean;
var ResFile: String; Lines: TArrayOfString; Code, I: Integer;
begin
  ResFile := ExpandConstant('{tmp}\result.json');
  DeleteFile(ResFile);
  Msg := '';
  Output := '';
  if not Exec(Exe, '--result-file "' + ResFile + '" ' + Params, '', SW_HIDE,
              ewWaitUntilTerminated, Code) then
  begin
    Msg := 'Could not start ' + ExtractFileName(Exe) + ': ' + SysErrorMessage(Code);
    Log2(Title + ': ' + Msg);
    Result := False;
    Exit;
  end;
  if LoadStringsFromFile(ResFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      Output := Output + Lines[I];
  Msg := JsonString(Output, 'message');
  if Msg = '' then Msg := 'No details (exit code ' + IntToStr(Code) + ').';
  Result := (Code = 0);
  if Result then Log2(Title + ': OK - ' + Output) else Log2(Title + ': FAILED - ' + Output);
end;

function ValidPort(): Boolean;
var P: Integer;
begin
  P := StrToIntDef(DbPort(), 0);
  Result := (P >= 1) and (P <= 65535);
end;

function TestConnection(): Boolean;
var Msg, Output, PassFile, Extra: String;
begin
  Result := False;
  if (DbHost() = '') or (DbName() = '') or (DbUser() = '') or not ValidPort() then
  begin
    SuppressibleMsgBox('Please fill in Host, a Port between 1 and 65535, Database Name and User.',
                       mbError, MB_OK, IDOK);
    Exit;
  end;
  TestStatus.Caption := 'Testing the connection...';
  TestStatus.Font.Color := clGray;
  WizardForm.Repaint;
  ExtractTemporaryFile('ahcode-dbcheck.exe');
  PassFile := WritePasswordFile();
  Extra := '';
  if IsLocalHost(DbHost()) then Extra := ' --allow-missing-db';
  Result := RunTool(ExpandConstant('{tmp}\ahcode-dbcheck.exe'),
                    ConnArgs(PassFile) + ' --db "' + DbName() + '"' + Extra,
                    'Test connection', Msg, Output);
  DeleteFile(PassFile);
  if Result then
  begin
    TestedKey := CurrentKey();
    DbMissing := Pos('"db_missing": true', Output) > 0;
    TestStatus.Font.Color := clGreen;
    if DbMissing then
      TestStatus.Caption := 'Connected. Database "' + DbName() + '" will be created.'
    else
      TestStatus.Caption := 'Connected to "' + DbName() + '".';
  end
  else
  begin
    TestedKey := '';
    TestStatus.Font.Color := clRed;
    TestStatus.Caption := 'Connection failed.';
    SuppressibleMsgBox('Could not connect to PostgreSQL:' + #13#10#13#10 + Msg, mbError, MB_OK, IDOK);
  end;
end;

procedure TestButtonClick(Sender: TObject);
begin
  TestConnection();
end;

procedure DbFieldChange(Sender: TObject);
begin
  if CurrentKey() <> TestedKey then
  begin
    TestStatus.Caption := '';
  end;
end;

procedure InitializeWizard();
var I, RowTop: Integer; PassFile, BackupDefault: String; Lines: TArrayOfString;
begin
  LogFile := ExpandConstant('{commonappdata}\PHASEINV2\logs\install-') +
             GetDateTimeString('yyyymmdd-hhnnss', '-', '-') + '.log';
  ForceDirectories(ExtractFileDir(LogFile));

  DbPage := CreateInputQueryPage(wpSelectDir, 'Database Connection',
    'PostgreSQL connection used by the application',
    'For the MAIN machine keep Host = localhost.' + #13#10 +
    'For a NETWORK client, enter the main machine''s IP address as the Host.' + #13#10 +
    'These values are saved to C:\ProgramData\PHASEINV2\connection.json and can be edited later.');
  DbPage.Add('Server IP / Host:', False);
  DbPage.Add('Port:', False);
  DbPage.Add('Database Name:', False);
  DbPage.Add('User:', False);
  DbPage.Add('Password:', True);
  DbPage.Values[0] := GetPreviousData('DbHost', ExpandConstant('{param:DBHOST|localhost}'));
  DbPage.Values[1] := GetPreviousData('DbPort', ExpandConstant('{param:DBPORT|5432}'));
  DbPage.Values[2] := GetPreviousData('DbName', ExpandConstant('{param:DBNAME|SABCONTDB}'));
  DbPage.Values[3] := GetPreviousData('DbUser', ExpandConstant('{param:DBUSER|postgres}'));
  PassFile := ExpandConstant('{param:DBPASSFILE|}');
  if (PassFile <> '') and LoadStringsFromFile(PassFile, Lines) and (GetArrayLength(Lines) > 0) then
    DbPage.Values[4] := Lines[0];
  if WizardSilent() then
  begin
    DbPage.Values[0] := ExpandConstant('{param:DBHOST|' + DbPage.Values[0] + '}');
    DbPage.Values[1] := ExpandConstant('{param:DBPORT|' + DbPage.Values[1] + '}');
    DbPage.Values[2] := ExpandConstant('{param:DBNAME|' + DbPage.Values[2] + '}');
    DbPage.Values[3] := ExpandConstant('{param:DBUSER|' + DbPage.Values[3] + '}');
  end;
  RowTop := DbPage.SubCaptionLabel.Top + DbPage.SubCaptionLabel.Height + ScaleY(14);
  for I := 0 to 4 do
  begin
    DbPage.Edits[I].OnChange := @DbFieldChange;
    DbPage.PromptLabels[I].Left := 0;
    DbPage.PromptLabels[I].Width := ScaleX(120);
    DbPage.PromptLabels[I].Top := RowTop + I * ScaleY(32) + ScaleY(4);
    DbPage.Edits[I].Left := ScaleX(125);
    DbPage.Edits[I].Width := DbPage.SurfaceWidth - ScaleX(125);
    DbPage.Edits[I].Top := RowTop + I * ScaleY(32);
  end;

  TestButton := TNewButton.Create(DbPage);
  TestButton.Parent := DbPage.Surface;
  TestButton.Caption := 'Test Connection';
  TestButton.Width := ScaleX(130);
  TestButton.Height := ScaleY(25);
  TestButton.Left := DbPage.Edits[4].Left;
  TestButton.Top := DbPage.Edits[4].Top + DbPage.Edits[4].Height + ScaleY(8);
  TestButton.OnClick := @TestButtonClick;

  TestStatus := TNewStaticText.Create(DbPage);
  TestStatus.Parent := DbPage.Surface;
  TestStatus.Left := TestButton.Left + TestButton.Width + ScaleX(12);
  TestStatus.Top := TestButton.Top + ScaleY(5);
  TestStatus.Caption := '';

  LanPage := CreateInputOptionPage(DbPage.ID, 'Network',
    'Use this computer as the main machine for the network',
    'Tick the box if other computers will run A-H CODE against the database on this machine. ' +
    'Setup will let PostgreSQL accept connections from the same network and open port 5432 in Windows Firewall.',
    False, False);
  LanPage.Add('This is the MAIN machine - allow other computers on the network to connect');
  LanPage.Values[0] := (GetPreviousData('Lan', ExpandConstant('{param:LAN|0}')) = '1');

  BackupPage := CreateInputDirPage(LanPage.ID, 'Backup Folder',
    'Where should database backups be saved?',
    'Automatic and manual backups (.sql files) are written to this folder. ' +
    'You can choose an external drive or a network folder.', False, '');
  BackupPage.Add('');
  BackupDefault := ExpandConstant('{param:BACKUPDIR|}');
  if BackupDefault = '' then
    BackupDefault := ExpandConstant('{commonappdata}\PHASEINV2\Backups');
  BackupPage.Values[0] := GetPreviousData('BackupDir', BackupDefault);
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DbHost', DbHost());
  SetPreviousData(PreviousDataKey, 'DbPort', DbPort());
  SetPreviousData(PreviousDataKey, 'DbName', DbName());
  SetPreviousData(PreviousDataKey, 'DbUser', DbUser());
  if LanPage.Values[0] then SetPreviousData(PreviousDataKey, 'Lan', '1')
  else SetPreviousData(PreviousDataKey, 'Lan', '0');
  SetPreviousData(PreviousDataKey, 'BackupDir', BackupPage.Values[0]);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = LanPage.ID) and not IsLocalHost(DbHost());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
#ifdef PREVIEW
  if CurPageID = wpReady then
  begin
    MsgBox('Preview build: pages only, nothing is installed.', mbInformation, MB_OK);
    Result := False;
    Exit;
  end;
#endif
  if (CurPageID = DbPage.ID) and (CurrentKey() <> TestedKey) then
    Result := TestConnection();
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var Lan: String;
begin
  if IsLocalHost(DbHost()) and LanPage.Values[0] then Lan := 'Yes' else Lan := 'No';
  Result := MemoDirInfo + NewLine + NewLine +
    'Database:' + NewLine + Space + DbUser() + '@' + DbHost() + ':' + DbPort() + ' / ' + DbName() +
    NewLine + NewLine + 'Main machine for the network:' + NewLine + Space + Lan +
    NewLine + NewLine + 'Backup folder:' + NewLine + Space + BackupPage.Values[0];
end;

function StringChangeEx2(S: String; const FromStr, ToStr: String): String;
begin
  StringChangeEx(S, FromStr, ToStr, True);
  Result := S;
end;

function RunStep(const Title, Params: String): Boolean;
var Msg, Output, PassFile: String; Answer: Integer;
begin
  repeat
    WizardForm.StatusLabel.Caption := Title + '...';
    PassFile := WritePasswordFile();
    Result := RunTool(ExpandConstant('{app}\{#CfgExe}'),
                      StringChangeEx2(Params, '%PASS%', PassFile), Title, Msg, Output);
    DeleteFile(PassFile);
    if Result then Exit;
    Answer := SuppressibleMsgBox(Title + ' failed:' + #13#10#13#10 + Msg + #13#10#13#10 +
      'Log: ' + LogFile, mbError, MB_RETRYCANCEL, IDCANCEL);
  until Answer <> IDRETRY;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Conn, Db: String; Ok: Boolean;
begin
  if CurStep <> ssPostInstall then Exit;
  Conn := Format('--host "%s" --port %s --user "%s" --password-file "%%PASS%%"', [DbHost(), DbPort(), DbUser()]);
  Db := ' --db "' + DbName() + '"';
  Ok := RunStep('Saving the connection settings',
                'write --mode lan --address "' + DbHost() + '" --port ' + DbPort() + Db +
                ' --user "' + DbUser() + '" --password-file "%PASS%"');
  if Ok and IsLocalHost(DbHost()) then
    Ok := RunStep('Creating the database (only if missing)', 'create-db ' + Conn + Db);
  if Ok then
    Ok := RunStep('Preparing the database tables and default user', 'provision ' + Conn + Db);
  ForceDirectories(BackupPage.Values[0]);
  RunStep('Saving the backup folder', 'set-backup-dir --path ' + Q(BackupPage.Values[0]) +
          ' --out ' + Q(ExpandConstant('{commonappdata}\PHASEINV2\backup_settings.json')));
  if IsLocalHost(DbHost()) and LanPage.Values[0] then
    RunStep('Allowing network computers to connect', 'enable-lan ' + Conn);
end;
