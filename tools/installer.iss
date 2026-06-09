; Inno Setup script for PA Agent
#define MyAppName "PA Agent"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "PA Agent Team"
#define MyAppExeName "PA_Agent.exe"

[Setup]
AppId={{A4B8D2F1-7C3E-4A91-9F2D-PAAGENT2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PA_Agent_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"

[Files]
Source: "..\dist\PA_Agent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
