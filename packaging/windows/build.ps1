# Build the Windows distribution. Requires Python 3.12 on PATH; Inno Setup (iscc) optional.
# Output: dist\Hallucinate\ (onedir), dist\hallucinate-<ver>-windows-x64.zip, installer if iscc exists.
param([string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not $Version) { $Version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value }

python -m pip install --require-hashes -r packaging\build-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
python -m pip install --no-deps --no-build-isolation .
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
python -m PyInstaller --noconfirm --distpath dist --workpath build\pyinstaller packaging\windows\hallucinate.spec
python packaging\qt_prune.py dist\Hallucinate  # drop the parts of Qt the app never uses
if ($LASTEXITCODE -ne 0) { throw "qt_prune failed" }

Compress-Archive -Path dist\Hallucinate -DestinationPath "dist\hallucinate-$Version-windows-x64.zip" -Force
if (Get-Command iscc -ErrorAction SilentlyContinue) {
  iscc "/DAppVersion=$Version" packaging\windows\installer.iss
}
