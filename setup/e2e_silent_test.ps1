# Silent install -> verify -> uninstall, against a throw-away database.
# Usage (elevated): setup\e2e_silent_test.ps1 -PasswordFile <file holding the local postgres password>
param([Parameter(Mandatory)] [string]$PasswordFile)
$ErrorActionPreference = "Stop"
$Setup = $PSScriptRoot
$Exe   = Join-Path $Setup "Output\A-H_CODE_Setup.exe"
$Db    = "ahcode_setup_test"   # lower case: unquoted SQL names are folded to lower case
$Dir   = "C:\AHCODE_E2E"
$Bk    = "C:\AHCODE_E2E_Backups"
$Psql  = (Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" | Sort-Object FullName -Descending | Select-Object -First 1).FullName
$env:PGPASSWORD = (Get-Content $PasswordFile -Raw).Trim()
$Profile = "C:\ProgramData\PHASEINV2\connection.json"
$BackupCfg = "C:\ProgramData\PHASEINV2\backup_settings.json"
$Saved = "$Profile.e2e-saved"
$SavedBk = "$BackupCfg.e2e-saved"
if (Test-Path $Profile) { Copy-Item $Profile $Saved -Force }
if (Test-Path $BackupCfg) { Copy-Item $BackupCfg $SavedBk -Force }
try {
    & $Psql -U postgres -h localhost -tAc "DROP DATABASE IF EXISTS $Db"
    $p = Start-Process $Exe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/DIR=`"$Dir`"", "/DBNAME=$Db", "/DBPASSFILE=`"$PasswordFile`"", "/LAN=0", "/BACKUPDIR=`"$Bk`"",
        "/LOG=`"$Setup\build\e2e-install.log`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Setup exit code $($p.ExitCode)" }
    if (-not (Test-Path "$Dir\A-H CODE.exe")) { throw "App not installed" }
    $exists = & $Psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='$Db'"
    if ($exists.Trim() -ne "1") { throw "Database not created" }
    $tables = & $Psql -U postgres -h localhost -d $Db -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
    $users = & $Psql -U postgres -h localhost -d $Db -tAc "SELECT count(*) FROM app_users"
    if ([int]$tables -lt 50 -or [int]$users -lt 1) { throw "Schema/admin missing ($tables tables, $users users)" }
    $json = Get-Content $Profile -Raw | ConvertFrom-Json
    if ($json.database.name -ne $Db -or $json.database.password -notlike "dpapi:*") { throw "Profile wrong" }
    if (-not (Select-String -Path "C:\ProgramData\PHASEINV2\backup_settings.json" -Pattern "AHCODE_E2E_Backups" -Quiet)) { throw "Backup dir not saved" }
    # Second run = upgrade: must keep data and succeed.
    & $Psql -U postgres -h localhost -d $Db -tAc "CREATE TABLE e2e_marker(x int); INSERT INTO e2e_marker VALUES (7)"
    $p = Start-Process $Exe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/DBNAME=$Db", "/DBPASSFILE=`"$PasswordFile`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Upgrade exit code $($p.ExitCode)" }
    if ((& $Psql -U postgres -h localhost -d $Db -tAc "SELECT x FROM e2e_marker").Trim() -ne "7") { throw "Upgrade touched data" }
    # Frozen app reaches the login window (offscreen, killed after 25 s).
    $env:QT_QPA_PLATFORM = "offscreen"
    $app = Start-Process "$Dir\A-H CODE.exe" -PassThru
    Start-Sleep 25
    $alive = -not $app.HasExited
    if ($alive) { Stop-Process $app -Force }
    Remove-Item Env:QT_QPA_PLATFORM
    if (-not $alive) { throw "App exited early (code $($app.ExitCode))" }
    # The startup backup must land in the folder chosen in setup, never under the install folder.
    if (-not (Get-ChildItem $Bk -Filter *.sql -ErrorAction SilentlyContinue)) { throw "No startup backup in $Bk" }
    if (Test-Path "$Dir\_internal\Backups") { throw "Backup written under the install folder" }
    $u = Start-Process "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES" -Wait -PassThru
    if (Test-Path $Dir) { throw "Uninstall left files: $((Get-ChildItem $Dir -Recurse -File | Select-Object -First 3).FullName -join ', ')" }
    if (-not (Test-Path $Profile)) { throw "Uninstall removed the connection file" }
    Write-Host "E2E PASSED" -ForegroundColor Green
}
finally {
    & $Psql -U postgres -h localhost -tAc "DROP DATABASE IF EXISTS $Db WITH (FORCE)"
    if (Test-Path $Saved) { Move-Item $Saved $Profile -Force } else { Remove-Item $Profile -ErrorAction SilentlyContinue }
    if (Test-Path $SavedBk) { Move-Item $SavedBk $BackupCfg -Force } else { Remove-Item $BackupCfg -ErrorAction SilentlyContinue }
    Remove-Item Env:PGPASSWORD
    foreach ($d in @($Bk, $Dir)) { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }
}
