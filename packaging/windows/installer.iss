; Inno Setup script. Build: iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1B7C1E-4F3A-4D5B-9E52-5B8A1E0D7A11}
AppName=Music Player
AppVersion={#AppVersion}
AppPublisher=Music Player contributors
AppPublisherURL=https://github.com/bulmaspanties/music-player
DefaultDirName={autopf}\Music Player
DefaultGroupName=Music Player
OutputDir=..\..\dist
OutputBaseFilename=musicplayer-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\musicplayer\assets\musicplayer.ico
UninstallDisplayIcon={app}\MusicPlayer.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source: "..\..\dist\MusicPlayer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Music Player"; Filename: "{app}\MusicPlayer.exe"
Name: "{autodesktop}\Music Player"; Filename: "{app}\MusicPlayer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\MusicPlayer.exe"; Description: "Launch Music Player"; Flags: nowait postinstall skipifsilent
