# A-H CODE Client Installer Design

## Goal

Produce one self-contained installer, `A-H_CODE_Setup.exe`, that the user hands
to a client. It installs the latest application with Python and every library
bundled, connects it to PostgreSQL (installed separately by the user), creates
and provisions the `SABCONTDB` database when missing, and supports both a
single machine and several machines sharing one database over the LAN. No manual
script or file edit is needed after running it.

## Scope

- New, independent files under `setup/`. The old `installer/`,
  `installer_final/` and `installer_new/` folders are read for reference only
  and are not reused, imported or edited.
- PostgreSQL itself is NOT installed by this installer.
- One small app change: the main window title becomes `A-H CODE` (was `KSA`).
- A small frozen-mode change so writable files never land under
  `Program Files` (see "Writable files").

## Decisions (confirmed with the user, 2026-10-15)

| Topic | Decision |
| --- | --- |
| Product name | `A-H CODE` (installer, shortcuts, Start menu, window title) |
| Wizard language | English, matching the user's screenshot |
| Packaging | PyInstaller one-folder build; no Python needed on the client |
| Missing database | Create `SABCONTDB` empty, then build schema + default admin + permissions; an existing database's data is never touched |
| Connection test fails | Blocks `Next` until it succeeds, with a clear message |
| LAN access on main machine | Installer configures PostgreSQL when the user ticks the option |
| Backup folder | Wizard page; default `C:\ProgramData\PHASEINV2\Backups` |
| Shortcuts | Desktop + Start menu |
| Uninstall | Removes program files and shortcuts only; database, connection file, backups and settings stay |

## Components

### 1. `setup/build.ps1` (developer machine only)

1. Creates a clean virtual environment `setup/.venv` with Python 3.11 and
   installs `requirements.txt` minus test-only packages, plus `pyinstaller`.
2. Runs PyInstaller with `setup/ahcode.spec`.
3. Runs a smoke test on the frozen output: `ahcode-config.exe --help` and an
   import check of every module under `app/` inside the frozen build.
4. Runs Inno Setup 6 (`ISCC.exe`) on `setup/AHCODE_Setup.iss`.
5. Output: `setup/Output/A-H_CODE_Setup.exe`.

The build fails loudly on any step error. Build outputs (`.venv`, `build`,
`dist`, `Output`) are gitignored. The `.spec` file is force-added because
`*.spec` is globally ignored.

### 2. `setup/ahcode.spec` + entry scripts

One PyInstaller analysis, two executables sharing one `_internal` folder:

- `A-H CODE.exe` (windowed) — entry `setup/entry_app.py`, runs `app.main`.
- `ahcode-config.exe` (console, run hidden by the wizard) — entry
  `setup/entry_config.py`, runs `app.config.configure_cli.main`.

Bundled data: `app/database/**/*.sql`, `app/ui/assets/**`, the `assets/`
images the app loads, qtawesome fonts, and PySide6 QtWebEngine (the contracting
report preview/print uses it). Hidden imports are gathered with
`collect_submodules("app")` so lazily imported screens are included.

### 3. Writable files

In a frozen build the code's "app root" is inside `Program Files`, which normal
users cannot write to. Before importing the app, both entry scripts set:

- `BACKUP_SETTINGS_PATH=%ProgramData%\PHASEINV2\backup_settings.json`
- the equivalent overrides for any other writable file the app keeps next to
  the code (logs, report settings, WhatsApp settings). The implementation audits
  every write under the app root and routes each to `%ProgramData%\PHASEINV2\`.

Existing env vars win, so development runs are unchanged.

### 4. `setup/AHCODE_Setup.iss` (Inno Setup 6, new script)

Wizard pages, in order:

1. Welcome.
2. Install folder (default `C:\Program Files\A-H CODE`).
3. **Database Connection** — same layout and help text as the screenshot:
   `Server IP / Host` = `localhost`, `Port` = `5432`, `Database Name` =
   `SABCONTDB`, `User` = `postgres`, `Password` (empty, masked).
   A `Test Connection` button calls `ahcode-config.exe test-db`. When the host
   is `localhost` and the database is missing, a reachable server counts as a
   pass (the database is created later). `Next` is blocked until a test passes
   with the current values; editing any field resets the pass.
4. **Network** (shown only when Host is `localhost`/`127.0.0.1`): checkbox
   "This is the MAIN machine — allow other computers on the network to connect".
5. **Backup Folder** — default `C:\ProgramData\PHASEINV2\Backups`.
6. Ready → Install → Finish (with "Launch A-H CODE").

The password never appears on a command line: the wizard writes it to a
temporary file under `{tmp}`, passes `--password-file`, and deletes it right
after each call. Every step's JSON output is logged to
`C:\ProgramData\PHASEINV2\logs\install-<timestamp>.log` with the password
scrubbed.

### 5. Post-install steps (run by the wizard, in order)

1. `ahcode-config.exe write` → encrypted profile at
   `C:\ProgramData\PHASEINV2\connection.json` (DPAPI, machine scope). The app
   already reads this file.
2. `ahcode-config.exe create-db` → `CREATE DATABASE SABCONTDB` only if absent.
3. `ahcode-config.exe provision` → schema, default admin, roles, permissions,
   attachments schema. Idempotent; never deletes or overwrites data.
4. `ahcode-config.exe set-backup-dir` → `backup_settings.json` in ProgramData.
5. Only when the Network option is ticked: `ahcode-config.exe enable-lan`
   (new sub-command, see below).
6. Grants `Users` modify rights on `C:\ProgramData\PHASEINV2` so the app runs
   without admin rights.

Any failing step shows the step's message and offers Retry / Cancel; the
connection profile is already saved, so the app can still open and show its
own connection screen.

### 6. New `configure_cli enable-lan` sub-command

Runs elevated (the installer is elevated). Steps:

1. Locates the PostgreSQL data directory: `SHOW data_directory` over the
   tested connection; falls back to the Windows service registry entry.
2. Backs up `postgresql.conf` and `pg_hba.conf` to `*.ahcode-bak-<timestamp>`.
3. Sets `listen_addresses = '*'` (replaces the active line or appends one).
4. Appends `host all all samenet scram-sha-256` to `pg_hba.conf` only if an
   equivalent line is not already present.
5. Restarts the PostgreSQL Windows service (found by its data directory).
6. Adds the Windows Firewall rule "A-H CODE PostgreSQL" for inbound TCP on the
   configured port, if missing.
7. Prints JSON `{ok, message, steps}`. Re-running is a no-op.

### 7. Client (network) machines

Same installer. The user types the main machine's IP as the host. The test must
pass (the database already exists on the main machine). `create-db` is skipped
for a non-local host; `provision` still runs (safe no-op on an existing schema).

### 8. Upgrade and uninstall

- Fixed `AppId` GUID, so running a newer setup upgrades in place. On upgrade
  the Database Connection page is pre-filled from the existing profile (the
  password is required again only if the test fails).
- Uninstall removes `{app}` and shortcuts only. `ProgramData\PHASEINV2`,
  the database and backups are never removed.

### 9. Client handover guide

`setup/دليل_التثبيت_للعميل.md` (Arabic): prerequisites, steps for a single
machine, main machine and client machines, default login, file locations, and
troubleshooting (wrong password, firewall, service not running).

## Testing

- Unit tests (pytest) for `enable-lan` against temporary copies of
  `postgresql.conf` / `pg_hba.conf` with the service restart and firewall calls
  injected as fakes; and for the writable-path redirection in the entry scripts.
- Existing suites: `test_schema_bootstrap`, `test_permission_system`,
  `test_permission_ui_parity`, `test_live_lists` plus any touched file.
- Build `setup/build.ps1` end to end on this machine.
- Silent install (`/VERYSILENT` with test parameters) into a temporary folder
  against a throw-away database `AHCODE_SETUP_TEST`: verify the profile file,
  database creation, schema and admin seed, then launch the frozen app
  offscreen to the login window, then uninstall and drop the test database.
  `SABCONTDB` and the real PostgreSQL configuration are never touched by tests.
