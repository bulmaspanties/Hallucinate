; Inno Setup script. Build: iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1B7C1E-4F3A-4D5B-9E52-5B8A1E0D7A11}
AppName=Hallucinate
AppVersion={#AppVersion}
AppPublisher=Hallucinate contributors
AppPublisherURL=https://github.com/bulmaspanties/Hallucinate
DefaultDirName={autopf}\Hallucinate
DefaultGroupName=Hallucinate
OutputDir=..\..\dist
OutputBaseFilename=hallucinate-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\hallucinate\assets\hallucinate.ico
WizardImageFile=..\..\hallucinate\assets\setup-wizard.bmp
UninstallDisplayIcon={app}\Hallucinate.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source: "..\..\dist\Hallucinate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Hallucinate"; Filename: "{app}\Hallucinate.exe"
Name: "{autodesktop}\Hallucinate"; Filename: "{app}\Hallucinate.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Hallucinate.exe"; Description: "Launch Hallucinate"; Flags: nowait postinstall skipifsilent
