param(
  [switch]$SkipTests,
  [switch]$RequireInstaller
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

$AppName = "ResumeScreeningAgent"
$BuildArch = "x64"
$Python = Join-Path $ProjectDir ".venv-windows\Scripts\python.exe"
$DistDir = Join-Path $ProjectDir "dist"
$AppDir = Join-Path $DistDir $AppName
$PortableZip = Join-Path $DistDir "$AppName-portable-$BuildArch.zip"
$IconFile = Join-Path $ProjectDir "build\windows\resume-agent.ico"
$LanguageFile = Join-Path $ProjectDir "build\windows\ChineseSimplified.isl"
$LanguageUrl = "https://raw.githubusercontent.com/jrsoftware/issrc/6054ca127cb6e4fa041350406287b997c4b54a9d/Files/Languages/ChineseSimplified.isl"
$LanguageSha256 = "e0b0b350e2245f3c5e65586dfe43d574f6e7f06f2261149aba284954b3fc9a8d"
$LgplFile = Join-Path $ProjectDir "build\windows\LGPL-3.0.txt"
$LgplUrl = "https://www.gnu.org/licenses/lgpl-3.0.txt"
$LgplSha256 = "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"

function Find-PythonLauncher {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return "py"
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    $Version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($Version -eq "3.12") {
      return "python"
    }
  }
  throw "Python 3.12 x64 was not found. Install it from python.org."
}

function Assert-LastExitCode([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE"
  }
}

function Write-Utf8NoBomLf([string]$Path, [string[]]$Lines) {
  $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  $Content = ($Lines -join "`n") + "`n"
  [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Find-InnoSetup {
  $Candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
  )
  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path $Candidate)) {
      return $Candidate
    }
  }
  return $null
}

if (-not (Test-Path $Python)) {
  $Launcher = Find-PythonLauncher
  if ($Launcher -eq "py") {
    & py -3.12 -m venv (Join-Path $ProjectDir ".venv-windows")
  } else {
    & python -m venv (Join-Path $ProjectDir ".venv-windows")
  }
  Assert-LastExitCode "Create Python virtual environment"
}

& $Python -m pip install --upgrade pip wheel
Assert-LastExitCode "Upgrade Python build tools"
& $Python -m pip install -e ".[dev]"
Assert-LastExitCode "Install project and packaging dependencies"

$AppVersion = (& $Python -c "from resume_agent import __version__; print(__version__)").Trim()
if (-not (Select-String -Quiet -SimpleMatch "ProductVersion', '$AppVersion'" "deploy/windows/version_info.txt")) {
  throw "deploy/windows/version_info.txt does not match package version $AppVersion"
}
if (-not (Select-String -Quiet -SimpleMatch "#define MyAppVersion `"$AppVersion`"" "deploy/windows/installer.iss")) {
  throw "deploy/windows/installer.iss does not match package version $AppVersion"
}

if (-not $SkipTests) {
  & $Python -m ruff check src tests
  Assert-LastExitCode "Lint"
  & $Python -m pytest
  Assert-LastExitCode "Tests"
}

New-Item -ItemType Directory -Force (Split-Path $IconFile) | Out-Null
& $Python deploy/windows/generate_icon.py $IconFile
Assert-LastExitCode "Generate Windows application icon"
Invoke-WebRequest -UseBasicParsing -Uri $LanguageUrl -OutFile $LanguageFile
$DownloadedLanguageHash = (Get-FileHash $LanguageFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($DownloadedLanguageHash -ne $LanguageSha256) {
  throw "Inno Setup language file checksum mismatch"
}
Invoke-WebRequest -UseBasicParsing -Uri $LgplUrl -OutFile $LgplFile
$DownloadedLgplHash = (Get-FileHash $LgplFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($DownloadedLgplHash -ne $LgplSha256) {
  throw "LGPL-3.0 license checksum mismatch"
}

if (Test-Path $AppDir) {
  Remove-Item -Recurse -Force $AppDir
}
if (Test-Path $PortableZip) {
  Remove-Item -Force $PortableZip
}

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name=$AppName `
  --icon=$IconFile `
  --version-file="deploy/windows/version_info.txt" `
  --paths=src `
  --collect-all=rapidocr `
  --collect-all=keyring `
  --hidden-import=keyring.backends.Windows `
  --add-data="resources;resources" `
  src/resume_agent/app/__main__.py
Assert-LastExitCode "Freeze Windows application"

$Executable = Join-Path $AppDir "$AppName.exe"
if (-not (Test-Path $Executable)) {
  throw "PyInstaller did not create the expected executable: $Executable"
}

Copy-Item "LICENSE" (Join-Path $AppDir "LICENSE.txt")
Copy-Item "THIRD_PARTY_NOTICES.md" (Join-Path $AppDir "THIRD_PARTY_NOTICES.md")
$BundledLicenseDir = Join-Path $AppDir "licenses"
New-Item -ItemType Directory -Force $BundledLicenseDir | Out-Null
Copy-Item $LgplFile (Join-Path $BundledLicenseDir "LGPL-3.0.txt")
Copy-Item "resources/tesseract/tessdata/LICENSE" (
  Join-Path $BundledLicenseDir "TESSERACT-TESSDATA-APACHE-2.0.txt"
)
$SitePackages = (& $Python -c "import site; print(site.getsitepackages()[0])").Trim()
& $Python deploy/windows/collect_licenses.py $SitePackages $BundledLicenseDir
Assert-LastExitCode "Collect dependency license texts"
$PdfiumNotice = Get-ChildItem $SitePackages -File -Filter "LicenseRef-PdfiumThirdParty.txt" -Recurse |
  Select-Object -First 1
if (-not $PdfiumNotice) {
  throw "pypdfium2 third-party license notice was not found"
}
Copy-Item $PdfiumNotice.FullName (Join-Path $BundledLicenseDir $PdfiumNotice.Name)

$env:QT_QPA_PLATFORM = "offscreen"
$env:RESUME_AGENT_SMOKE_TEST = "1"
$SmokeProcess = Start-Process -FilePath $Executable -Wait -PassThru
if ($SmokeProcess.ExitCode -ne 0) {
  throw "Packaged Windows application/OCR smoke test failed with exit code $($SmokeProcess.ExitCode)"
}
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:\RESUME_AGENT_SMOKE_TEST -ErrorAction SilentlyContinue

Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $PortableZip -CompressionLevel Optimal

$DependencyLines = @(& $Python -m pip list --format=freeze)
Assert-LastExitCode "Record Windows dependency versions"
Write-Utf8NoBomLf (
  Join-Path $DistDir "windows-dependencies.txt"
) $DependencyLines

$InnoSetup = Find-InnoSetup
if (-not $InnoSetup) {
  if ($RequireInstaller) {
    throw "Inno Setup 6 was not found; Setup.exe cannot be created."
  }
  Write-Warning "Inno Setup 6 was not found. Portable ZIP created; installer skipped."
} else {
  & $InnoSetup "deploy/windows/installer.iss"
  Assert-LastExitCode "Build Inno Setup installer"
}

$Hashes = Get-ChildItem $DistDir -File | Where-Object {
  $_.Name -like "$AppName-*.zip" -or $_.Name -like "$AppName-Setup-*.exe"
} | Sort-Object Name | Get-FileHash -Algorithm SHA256
$HashLines = @($Hashes | ForEach-Object {
  "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path $_.Path -Leaf)
})
if ($HashLines.Count -lt 2) {
  throw "Expected both installer and portable archive before writing checksums"
}
foreach ($HashLine in $HashLines) {
  if ($HashLine -notmatch '^([0-9a-f]{64})  (.+)$') {
    throw "Invalid checksum line: $HashLine"
  }
  $ExpectedHash = $Matches[1]
  $ArtifactPath = Join-Path $DistDir $Matches[2]
  if (-not (Test-Path $ArtifactPath -PathType Leaf)) {
    throw "Checksum references a missing artifact: $ArtifactPath"
  }
  $ActualHash = (Get-FileHash $ArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($ActualHash -ne $ExpectedHash) {
    throw "Checksum verification failed for $ArtifactPath"
  }
}
Write-Utf8NoBomLf (Join-Path $DistDir "windows-SHA256.txt") $HashLines

Write-Host "Windows build completed:"
Write-Host "  Portable: $PortableZip"
if ($InnoSetup) {
  $InstallerPath = Join-Path $DistDir "ResumeScreeningAgent-Setup-$BuildArch.exe"
  Write-Host "  Installer: $InstallerPath"
}
$HashPath = Join-Path $DistDir "windows-SHA256.txt"
Write-Host "  Checksums: $HashPath"
