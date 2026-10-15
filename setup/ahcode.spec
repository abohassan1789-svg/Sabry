# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(Path(SPECPATH) / "ahcode.ico")

hidden = (collect_submodules("app", filter=lambda n: not n.startswith("app.migrations"))
          + collect_submodules("num2words") + ["psycopg_binary"])

# Only the data files the app reads at runtime. Never walk the whole app/ tree:
# app/logs holds local logs and app/database/migrations holds a local script
# with the database password.
datas = [(str(ROOT / "app" / "database" / "schema" / "full_schema.sql"),
          "app/database/schema")]
for src in (ROOT / "app" / "ui" / "assets").rglob("*"):
    if src.is_file():
        datas.append((str(src), str(src.parent.relative_to(ROOT))))
datas += collect_data_files("qtawesome") + collect_data_files("arabic_reshaper")

common = dict(pathex=[str(ROOT)], hiddenimports=hidden, datas=datas,
              excludes=["pytest", "tkinter"])
a_app = Analysis([str(Path(SPECPATH) / "entry_app.py")], **common)
a_cfg = Analysis([str(Path(SPECPATH) / "entry_config.py")], **common)

exe_app = EXE(PYZ(a_app.pure), a_app.scripts, [], exclude_binaries=True,
              name="A-H CODE", console=False, icon=ICON, upx=False)
exe_cfg = EXE(PYZ(a_cfg.pure), a_cfg.scripts, [], exclude_binaries=True,
              name="ahcode-config", console=True, icon=ICON, upx=False)
coll = COLLECT(exe_app, a_app.binaries, a_app.datas,
               exe_cfg, a_cfg.binaries, a_cfg.datas,
               upx=False, name="A-H CODE")
