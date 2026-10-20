; Per-user install. No token, credential or admin elevation is embedded.
[Setup]
AppId=CI-Operations-Desktop
AppName=CI Operations
AppVersion=1.0.6
AppPublisher=Local CI Tools
DefaultDirName={localappdata}\Programs\CIOperations
DefaultGroupName=CI Operations
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=CI-Operations-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\CI-Operations.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\CI-Operations\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CI Operations"; Filename: "{app}\CI-Operations.exe"; WorkingDir: "{app}"
Name: "{group}\GitHub Settings"; Filename: "{app}\CI-Operations.exe"; Parameters: "--configure"; WorkingDir: "{app}"
Name: "{group}\Uninstall CI Operations"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CI Operations"; Filename: "{app}\CI-Operations.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "CIOperations"; Flags: uninsdeletevalue

[UninstallDelete]
Type: files; Name: "{localappdata}\CIOperations\settings.dat"
Type: files; Name: "{localappdata}\CIOperations\settings.tmp"

[Code]
function ValidRuntimeVersion(RootKey: Integer; const Key: String): Boolean;
var
  Version: String;
  Major: Integer;
begin
  Result := False;
  if RegQueryStringValue(RootKey, Key, 'pv', Version) then
  begin
    Major := StrToIntDef(Copy(Version, 1, Pos('.', Version) - 1), 0);
    Result := Major >= 86;
  end;
end;

function InitializeSetup(): Boolean;
var
  RuntimeKey: String;
  Release: Cardinal;
  NetReady: Boolean;
begin
  RuntimeKey := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  NetReady := RegQueryDWordValue(HKLM32, 'Software\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
  if NetReady then NetReady := Release >= 394802;
  Result := NetReady and (ValidRuntimeVersion(HKCU, RuntimeKey) or
    ValidRuntimeVersion(HKLM32, RuntimeKey) or ValidRuntimeVersion(HKLM64, RuntimeKey));
  if not Result then
    SuppressibleMsgBox('CI Operations requires Microsoft Edge WebView2 Runtime and .NET Framework 4.6.2 or later.' + #13#10 +
      'Install the official WebView2 Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ and run Setup again.' + #13#10 +
      'On older Windows versions, also install .NET Framework from Microsoft.', mbCriticalError, MB_OK, IDOK);
end;

[Run]
Filename: "{app}\CI-Operations.exe"; Description: "Open CI Operations"; Flags: nowait postinstall skipifsilent
