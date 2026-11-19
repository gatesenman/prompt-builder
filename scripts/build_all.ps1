# PromptBuilder - standard product build (ASCII only: Windows PowerShell 5.1 reads BOM-less scripts as ANSI)
# 1) preflight  2) venv (.venv-build)  3) PyInstaller onedir  4) bundle check
# 5) Inno Setup ISCC -> PromptBuilder-Setup-x.y.z.exe  (fallback: PyInstaller wizard setup)
#
#   -Verify  run the frozen exe's --selftest (isolated temp data dir; the user's data is not touched)
#   -Clean   after success remove .venv-build, tools, build, dist (leaves only source + Setup)
param([switch]$Verify, [switch]$Clean)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Version = (Get-Content VERSION.txt -Raw).Trim()
if (-not $Version) { $Version = "2.12.8" }
$sw = [Diagnostics.Stopwatch]::StartNew()

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
}
function Copy-Tree([string]$Src, [string]$Dst) {
  if (-not (Test-Path $Src)) { throw "missing source: $Src" }
  Ensure-Dir (Split-Path $Dst -Parent)
  if (Test-Path $Dst) { Remove-Item -Recurse -Force $Dst }
  Copy-Item -Recurse -Force $Src $Dst
}
function Remove-Quiet([string[]]$Paths) {
  foreach ($p in $Paths) { if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue } }
}

$appModules = @("app", "api", "paths", "settings_store", "prompt_syntax", "prompts_store", "library_model", "atomic_io", "applog",
                "winapi", "winput", "keyhook", "caret", "quickpick", "tray_icon", "autostart", "textcheck", "elevation",
                "revisions_store", "history_store", "ai_crypto", "ai_providers", "ai_service")
$webFiles = @("web\index.html", "web\quick.html", "web\css\base.css", "web\css\app.css", "web\css\quick.css",
              "web\js\app.js", "web\js\quick.js", "web\js\md.js", "web\js\icons.js")

Write-Host "==> Preflight PromptBuilder $Version"
$required = @("data\examples.json", "data\builtins.json", "assets\icon.ico", "assets\icon.png", "PromptBuilder.spec",
              "installer\PromptBuilder.iss", "installer\setup_main.py") + $webFiles
$required += $appModules | ForEach-Object { "src\$_.py" }
$required | ForEach-Object { if (-not (Test-Path $_)) { throw "missing required file: $_" } }
$specText = Get-Content PromptBuilder.spec -Raw
foreach ($m in $appModules) {
  if ($m -ne "app" -and $specText -notmatch "'$m'") { throw "PromptBuilder.spec hiddenimports is missing '$m'" }
}
$issText = Get-Content installer\PromptBuilder.iss -Raw
if ($issText -notmatch [regex]::Escape("#define MyAppVersion `"$Version`"")) { throw "installer\PromptBuilder.iss version != $Version" }
if ((Get-Content src\api.py -Raw) -notmatch [regex]::Escape("APP_VERSION = `"$Version`"")) { throw "src\api.py APP_VERSION != $Version" }

Write-Host "==> Local venv (.venv-build)"
function Find-HostPython {
  # Prefer official installs first — some PATH shims (e.g. version-fox) may lack stdlib modules.
  $cands = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
  )
  foreach ($name in @("py", "python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $cands += $cmd.Source }
  }
  $cands += @("$env:USERPROFILE\.version-fox\sdks\python\python.exe")
  foreach ($c in $cands) {
    if (-not ($c -and (Test-Path $c))) { continue }
    & $c -c "import calendar, ssl, urllib.request" 2>$null
    if ($LASTEXITCODE -eq 0) { return $c }
    Write-Host ("    skip broken python: " + $c)
  }
  throw "python not found on PATH or in common install locations"
}
if (-not (Test-Path .venv-build\Scripts\python.exe)) {
  $hostPy = Find-HostPython
  Write-Host ("    host python: " + $hostPy)
  & $hostPy -m venv .venv-build
  if (-not (Test-Path .venv-build\Scripts\python.exe)) {
    Write-Host "    venv with pip failed; retry --without-pip"
    Remove-Quiet @(".venv-build")
    & $hostPy -m venv --without-pip .venv-build
  }
  if (-not (Test-Path .venv-build\Scripts\python.exe)) { throw "venv create failed" }
}
$py = ".\.venv-build\Scripts\python.exe"
$eap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $py -m pip --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "    bootstrapping pip via ensurepip"
  & $py -m ensurepip --upgrade 2>&1 | Out-Null
}
if (($LASTEXITCODE -ne 0)) {
  Write-Host "    ensurepip failed; downloading get-pip.py"
  $gp = Join-Path $env:TEMP "get-pip.py"
  Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $gp
  & $py $gp 2>&1 | Out-Null
  Remove-Item $gp -Force -ErrorAction SilentlyContinue
}
& $py -m pip install -q --disable-pip-version-check --upgrade pip 2>&1 | Out-Null
$ErrorActionPreference = $eap
& $py -m pip install -q --disable-pip-version-check -r requirements.txt "pyinstaller==6.15.0"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
$ErrorActionPreference = "Continue"
& $py -m pip uninstall -y -q keyboard pyperclip pywin32 *> $null
$ErrorActionPreference = $eap

Write-Host "==> Unit tests (parser / storage)"
& $py -m unittest discover -s src\tests
if ($LASTEXITCODE -ne 0) { throw "unit tests failed" }

Write-Host "==> Pre-generate comtypes UIAutomation wrapper (frozen app cannot generate it)"
& $py -c "import comtypes.client as c; c.GetModule('UIAutomationCore.dll'); from comtypes.gen import UIAutomationClient; print('comtypes UIA OK')"
if ($LASTEXITCODE -ne 0) { Write-Host "WARN: comtypes UIA generation failed - caret falls back to GetGUIThreadInfo/MSAA/mouse" }

Write-Host "==> Clean build artifacts"
Remove-Quiet @("build", "dist", "dist_installer", "build_setup", "installer\payload", "PLEASE_USE_SETUP.txt")
Ensure-Dir dist_installer

Write-Host "==> PyInstaller onedir (WebUI)"
& $py -m PyInstaller --noconfirm --clean --log-level WARN PromptBuilder.spec
if (-not (Test-Path "dist\PromptBuilder\PromptBuilder.exe")) { throw "onedir failed" }

Write-Host "==> Ensure bundled WebUI/data/assets"
$internal = "dist\PromptBuilder\_internal"
if (-not (Test-Path (Join-Path $internal "web\index.html"))) {
  Copy-Tree "web" (Join-Path $internal "web")
  Copy-Tree "data" (Join-Path $internal "data")
  Copy-Tree "assets" (Join-Path $internal "assets")
}
foreach ($f in $webFiles + @("data\examples.json", "data\builtins.json", "assets\icon.png", "assets\icon.ico")) {
  if (-not (Test-Path (Join-Path $internal $f))) { throw "bundle is missing $f" }
}
# every local module must be inside the PYZ archive (hiddenimports)
$toc = Get-ChildItem build\PromptBuilder\PYZ-00.toc -ErrorAction SilentlyContinue
if ($toc) {
  $tocText = Get-Content $toc.FullName -Raw
  foreach ($m in $appModules) {
    if ($m -ne "app" -and $tocText -notmatch "\('$m',") { throw "module '$m' is not in the bundle" }
  }
  Write-Host "bundle modules OK ($($appModules.Count) local modules + web assets)"
}
Copy-Item VERSION.txt "dist\PromptBuilder\VERSION.txt" -Force
$bundleMB = [math]::Round(((Get-ChildItem dist\PromptBuilder -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "onedir size: $bundleMB MB"

if ($Verify) {
  Write-Host "==> Frozen selftest (isolated data dir)"
  $tmpData = Join-Path $env:TEMP ("pb-selftest-" + [guid]::NewGuid().ToString("N"))
  Ensure-Dir $tmpData
  $env:PROMPTBUILDER_DATA_DIR = $tmpData
  $out = Join-Path $tmpData "selftest.json"
  $p = Start-Process -FilePath "dist\PromptBuilder\PromptBuilder.exe" -ArgumentList @("--selftest", "`"$out`"") -Wait -PassThru
  Remove-Item Env:\PROMPTBUILDER_DATA_DIR
  if (-not (Test-Path $out)) { throw "selftest produced no output" }
  $st = Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json
  $st.checks.PSObject.Properties | ForEach-Object { Write-Host ("  {0,-26} {1}" -f $_.Name, $(if ($_.Value.ok) { "OK" } else { "FAIL " + $_.Value.error })) }
  if (-not $st.ok) { throw "frozen selftest failed (exit $($p.ExitCode))" }

  # Real UI load: open the main window + popup exactly like a normal launch, from a foreign
  # working directory (System32), and prove both pages render (2.6.0 shipped a URL WebView2
  # could not open). Runs beside an already-running PromptBuilder (separate mutex), no hook.
  Write-Host "==> Frozen UI load check (main window + popup, cwd=System32)"
  $env:PROMPTBUILDER_DATA_DIR = $tmpData
  $vout = Join-Path $tmpData "verify-ui.json"
  $exe = (Resolve-Path "dist\PromptBuilder\PromptBuilder.exe").Path
  $p = Start-Process -FilePath $exe -ArgumentList @("--verify-ui", "`"$vout`"") -WorkingDirectory "$env:SystemRoot\System32" -Wait -PassThru
  Remove-Item Env:\PROMPTBUILDER_DATA_DIR
  if (-not (Test-Path $vout)) { throw "UI load check produced no output" }
  $vu = Get-Content $vout -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($k in @("main", "quick")) {
    $c = $vu.page_checks.$k
    Write-Host ("  {0,-26} {1}  {2}" -f "page_$k", $(if ($c.ok) { "OK" } else { "FAIL" }), $c.current_url)
  }
  if (-not $vu.pages_ok) { throw "UI load check failed: a window did not show the real page" }
  Remove-Quiet @($tmpData)
}

function Find-ISCC {
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$Root\tools\InnoSetup\ISCC.exe",
    "$Root\installer\tools\InnoSetup\ISCC.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  return $null
}

function Ensure-PortableInno {
  $dest = Join-Path $Root "tools\InnoSetup"
  $isccPath = Join-Path $dest "ISCC.exe"
  if (Test-Path $isccPath) { return $isccPath }
  Write-Host "==> Fetching Inno Setup 6 into tools\InnoSetup ..."
  Ensure-Dir $dest
  $url = "https://jrsoftware.org/download.php/is.exe"
  $installer = Join-Path $env:TEMP "innosetup-install.exe"
  try {
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    $p = Start-Process -FilePath $installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", ("/DIR=" + $dest)) -Wait -PassThru
    if ($p.ExitCode -ne 0) { Write-Host ("Inno silent install exit " + $p.ExitCode) }
  } catch {
    Write-Host ("Inno download/install failed: " + $_)
  }
  if (Test-Path $isccPath) { return $isccPath }
  return $null
}

$setupName = "PromptBuilder-Setup-$Version.exe"
$iscc = Find-ISCC
if (-not $iscc) { $iscc = Ensure-PortableInno }

if ($iscc) {
  Write-Host ("==> Inno Setup: " + $iscc)
  & $iscc /Q "installer\PromptBuilder.iss"
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path ("dist_installer\" + $setupName))) {
    throw ("Inno Setup did not produce " + $setupName)
  }
} else {
  Write-Host "==> Fallback: wizard Setup.exe (PyInstaller + setup_main.py)"
  Ensure-Dir "installer\payload"
  Push-Location dist\PromptBuilder
  Compress-Archive -Path * -DestinationPath ..\..\installer\payload\app.zip -Force
  Pop-Location
  & $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ("PromptBuilder-Setup-" + $Version) `
    --icon assets\icon.ico `
    --add-data "installer\payload\app.zip;payload" `
    --distpath dist_installer `
    --workpath build_setup `
    installer\setup_main.py
  if (-not (Test-Path ("dist_installer\" + $setupName))) { throw "fallback setup failed" }
}

Copy-Item ("dist_installer\" + $setupName) (".\" + $setupName) -Force
Get-ChildItem .\PromptBuilder-Setup-*.exe | Where-Object { $_.Name -ne $setupName } | Remove-Item -Force
Remove-Quiet @("dist_installer", "build_setup", "installer\payload", "PLEASE_USE_SETUP.txt", "PromptBuilder-Setup-*.spec")
if ($Clean) {
  Write-Host "==> Clean: removing build leftovers"
  Remove-Quiet @("build", "dist", ".venv-build", "tools", "src\__pycache__", "src\tests\__pycache__", "installer\__pycache__")
}

$setupPath = Join-Path $Root $setupName
$setupMB = [math]::Round((Get-Item $setupPath).Length / 1MB, 2)
$sha = [System.Security.Cryptography.SHA256]::Create()
$fs = [System.IO.File]::OpenRead($setupPath)
try { $hash = ([BitConverter]::ToString($sha.ComputeHash($fs))).Replace("-","").ToLowerInvariant() }
finally { $fs.Close(); $sha.Dispose() }
Write-Host ("DONE {0} ({1} MB) in {2:N0}s" -f $setupName, $setupMB, $sw.Elapsed.TotalSeconds)
Write-Host ("SHA256 {0}" -f $hash)
