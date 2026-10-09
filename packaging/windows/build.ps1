# Build the Windows distribution. Requires Python 3.12 on PATH; Inno Setup (iscc) optional.
# Output: dist\MusicPlayer\ (onedir), dist\musicplayer-<ver>-windows-x64.zip, installer if iscc exists.
param([string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not $Version) { $Version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value }

python -m pip install --upgrade pip
python -m pip install . pyinstaller
python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\windows\musicplayer.spec

Compress-Archive -Path dist\MusicPlayer -DestinationPath "dist\musicplayer-$Version-windows-x64.zip" -Force
if (Get-Command iscc -ErrorAction SilentlyContinue) {
  iscc "/DAppVersion=$Version" packaging\windows\installer.iss
}
