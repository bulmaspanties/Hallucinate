# PyInstaller spec: pyinstaller --noconfirm packaging/windows/hallucinate.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent.parent
pkg = root / "hallucinate"

a = Analysis(
    [str(Path(SPECPATH) / "run_hallucinate.py")],
    pathex=[str(root)],
    datas=[
        (str(pkg / "qml"), "hallucinate/qml"),
        (str(pkg / "assets"), "hallucinate/assets"),
        (str(pkg / "themes"), "hallucinate/themes"),
    ],
    # keyring picks its backend dynamically (Windows Credential Manager).
    hiddenimports=collect_submodules("keyring.backends") + ["PySide6.QtMultimedia", "PySide6.QtQuickControls2"],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtDBus"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hallucinate",
    console=False,
    icon=str(pkg / "assets" / "hallucinate.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Hallucinate")
