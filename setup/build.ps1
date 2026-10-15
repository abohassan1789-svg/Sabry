# Builds the A-H CODE installer from the current working tree.
#   powershell -NoProfile -ExecutionPolicy Bypass -File setup\build.ps1
$ErrorActionPreference = "Stop"
$Setup = $PSScriptRoot
$Root  = Split-Path $Setup -Parent
Set-Location $Root

function Step($name, [scriptblock]$body) {
    Write-Host "==> $name" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

$Venv = Join-Path $Setup ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"
Step "Create clean venv" {
    if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }
    py -3.11 -m venv $Venv
}
Step "Install libraries (exact tested versions)" {
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -r (Join-Path $Setup "requirements-lock.txt") "pyinstaller==6.22.2"
}
Step "PyInstaller: app" {
    & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Setup "dist") `
        --workpath (Join-Path $Setup "build") (Join-Path $Setup "ahcode.spec")
}
Step "PyInstaller: dbcheck" {
    & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Setup "dist") `
        --workpath (Join-Path $Setup "build") (Join-Path $Setup "dbcheck.spec")
}
$Dist = Join-Path $Setup "dist\A-H CODE"
Step "Smoke: every module imports in the frozen app" {
    $out = Join-Path $Setup "build\smoke-imports.txt"
    $env:QT_QPA_PLATFORM = "offscreen"
    $p = Start-Process -FilePath (Join-Path $Dist "A-H CODE.exe") -ArgumentList "--smoke-imports", "`"$out`"" -Wait -PassThru
    Remove-Item Env:QT_QPA_PLATFORM
    if ($p.ExitCode -ne 0) { Get-Content $out | Select-String -Context 0,8 FAILED; throw "Frozen import smoke failed" }
}
Step "Smoke: helpers start" {
    & (Join-Path $Dist "ahcode-config.exe") --help | Out-Null
    & (Join-Path $Setup "dist\ahcode-dbcheck.exe") --help | Out-Null
}

$Iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
$Version = Get-Date -Format "yyyy.MM.dd"
Step "Inno Setup" { & $Iscc "/DAppVersion=$Version" (Join-Path $Setup "AHCODE_Setup.iss") }
Write-Host "Installer: $(Join-Path $Setup 'Output\A-H_CODE_Setup.exe')" -ForegroundColor Green
