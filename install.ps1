<#
  Trading Bot - one-line installer for Windows.

      powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/jokingtim24688/Trading-Bot/HEAD/install.ps1 | iex"

  It checks for git and Python, installs whatever is missing with winget, clones the app to your user folder,
  puts a shortcut on the Desktop and starts it. Running it again just updates what is already there.
  Nothing here needs administrator rights, and it never touches your MT5 terminal or its logins.
#>
[CmdletBinding()]
param(
  [string]$Path = "$env:USERPROFILE\Trading-Bot",
  [string]$Repo = "https://github.com/jokingtim24688/Trading-Bot.git",
  [switch]$Yes,          # don't ask before installing git / Python
  [switch]$NoLaunch,     # set everything up but don't open the app
  [switch]$Check         # only report what is missing
)
$ErrorActionPreference = "Stop"
$ok = "  [ok]   "; $no = "  [--]   "; $go = "  [..]   "

function Say($m, $c = "Gray") { Write-Host $m -ForegroundColor $c }
function Head($m) { Write-Host ""; Write-Host $m -ForegroundColor Cyan }
function Have($cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }
function Ask($q) {
  if ($Yes) { return $true }
  $a = Read-Host "$q [Y/n]"
  return ($a -eq "" -or $a -match '^[Yy]')
}
function Winget($id, $what) {
  if (-not (Have winget)) {
    Say "$no $what is missing and winget isn't available on this Windows." Yellow
    Say "         Install it by hand, then run this again." Yellow
    throw "$what missing"
  }
  Say "$go installing $what with winget..."
  & { $ErrorActionPreference = "Continue"
      winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null }
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Head "Trading Bot - Windows setup"
Say  "  Folder: $Path"

# --- Windows version -------------------------------------------------------
$v = [Environment]::OSVersion.Version
if ($v.Major -lt 10) { Say "$no Windows 10 or 11 is needed (this is $($v.Major).$($v.Minor))." Red; return }
Say "$ok Windows $($v.Major) build $($v.Build)"

# --- Python ----------------------------------------------------------------
$py = $null
$tries = @(
  @{ exe = "py";     pre = @("-3.13") }, @{ exe = "py";     pre = @("-3.12") },
  @{ exe = "py";     pre = @("-3.11") }, @{ exe = "py";     pre = @("-3.10") },
  @{ exe = "python"; pre = @() },        @{ exe = "python3"; pre = @() })
foreach ($t in $tries) {
  if (-not (Have $t.exe)) { continue }
  $ver = ""
  try { $ver = (& $t.exe @($t.pre + @("-c", "import sys;print('%d.%d' % sys.version_info[:2])")) 2>$null | Select-Object -First 1) } catch { continue }
  if ("$ver" -match '^3\.1[0-3]$') { $py = (@($t.exe) + $t.pre) -join " "; Say "$ok Python $ver ($py)"; break }
}
if (-not $py) {
  Say "$no Python 3.10-3.13 not found."
  if ($Check) { } elseif (Ask "    Install Python 3.12?") { Winget "Python.Python.3.12" "Python 3.12"; $py = "py -3.12" }
  else { Say "    Nothing installed. Get it from python.org and run this again." Yellow; return }
}

# --- git -------------------------------------------------------------------
if (Have git) { Say "$ok git $((git --version) -replace 'git version ','')" }
else {
  Say "$no git not found."
  if ($Check) { } elseif (Ask "    Install git?") { Winget "Git.Git" "git" }
  else { Say "    Nothing installed. Get it from git-scm.com and run this again." Yellow; return }
}
if ($Check) { Head "Check only - nothing was changed."; return }

# --- the app ---------------------------------------------------------------
if (Test-Path (Join-Path $Path ".git")) {
  Say "$go updating the copy already in $Path..."
  & { $ErrorActionPreference = "Continue"; git -C $Path pull --ff-only }
  if ($LASTEXITCODE -ne 0) { Say "$no couldn't update (local changes?) - carrying on with what is there." Yellow }
} else {
  if ((Test-Path $Path) -and (Get-ChildItem $Path -Force | Measure-Object).Count) {
    Say "$no $Path already exists and isn't empty. Pass -Path to pick another folder." Red; return
  }
  Say "$go downloading the app..."
  & { $ErrorActionPreference = "Continue"; git clone --depth 50 $Repo $Path }
  if ($LASTEXITCODE -ne 0) { Say "$no the download failed. Check the connection and run this again." Red; return }
}
Say "$ok app in $Path"

# --- Desktop shortcut ------------------------------------------------------
try {
  $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Trading Bot.lnk"
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $s.TargetPath = Join-Path $Path "Trading Bot.bat"
  $s.WorkingDirectory = $Path
  $s.Description = "Open the Trading Bot app"
  $s.Save()
  Say "$ok shortcut on the Desktop"
} catch { Say "$no couldn't make the Desktop shortcut (not a problem: open 'Trading Bot.bat' in the folder)." Yellow }

Head "Done."
Say  "  Open it any time with the Desktop shortcut, or 'Trading Bot.bat' in $Path."
Say  "  The first start builds the Python environment, so give it a few minutes."
Say  "  MetaTrader 5 has to be installed and logged in for the MT5 side; the Solana side needs nothing."
if (-not $NoLaunch) {
  Head "Starting it now..."
  Start-Process -FilePath (Join-Path $Path "Trading Bot.bat") -WorkingDirectory $Path
}
