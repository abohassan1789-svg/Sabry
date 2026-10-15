# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent
a = Analysis([str(Path(SPECPATH) / "entry_dbcheck.py")], pathex=[str(ROOT)],
             hiddenimports=["psycopg_binary"],
             excludes=["PySide6", "sqlalchemy", "reportlab", "openpyxl", "PIL",
                       "cryptography", "pytest", "tkinter"])
exe = EXE(PYZ(a.pure), a.scripts, a.binaries, a.datas, [], name="ahcode-dbcheck",
          console=True, upx=False, icon=str(Path(SPECPATH) / "ahcode.ico"))
