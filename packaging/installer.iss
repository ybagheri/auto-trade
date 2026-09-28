[Unit]
Name=auto-trade
Version=0.1.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={autopf}\auto-trade
DefaultGroupName=auto-trade
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=auto-trade-setup-0.1.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The application is a local tool: no service, no firewall rule, no registry
; write beyond the start menu entry. A network execution surface is never
; installed.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole build folder, so the executable, its payload, the MT5 indicator, and
; the documentation stay in one versioned set.
Source: "..\dist\auto-trade\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\auto-trade"; Filename: "{app}\auto-trade.exe"; WorkingDir: "{app}"
Name: "{group}\Configure auto-trade"; Filename: "{app}\auto-trade.exe"; Parameters: "configure"; WorkingDir: "{app}"
Name: "{group}\Export diagnostics bundle"; Filename: "{app}\auto-trade.exe"; Parameters: "diagnostics-bundle"; WorkingDir: "{app}"
Name: "{group}\Install the read-only MT5 indicator"; Filename: "{app}\scripts\install-position-reader.ps1"; WorkingDir: "{app}"
Name: "{autodesktop}\auto-trade"; Filename: "{app}\auto-trade.exe"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\auto-trade.exe"; Parameters: "diagnostics"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
