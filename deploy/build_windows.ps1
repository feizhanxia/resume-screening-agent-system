param(
  [switch]$SkipTests,
  [switch]$RequireInstaller
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

$AppName = "简历筛选工作台"
$BuildArch = "x64"
$Python = Join-Path $ProjectDir ".venv-windows\Scripts\python.exe"
$DistDir = Join-Path $ProjectDir "dist"
$AppDir = Join-Path $DistDir $AppName
$PortableZip = Join-Path $DistDir "$AppName-portable-$BuildArch.zip"
$IconFile = Join-Path $ProjectDir "build\windows\resume-agent.ico"

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
  throw "未找到 Python 3.12。请从 python.org 安装 64 位 Python 3.12。"
}

function Assert-LastExitCode([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step 失败，退出码：$LASTEXITCODE"
  }
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
  Assert-LastExitCode "创建 Python 虚拟环境"
}

& $Python -m pip install --upgrade pip wheel
Assert-LastExitCode "升级 Python 构建工具"
& $Python -m pip install -e ".[dev]" pyinstaller
Assert-LastExitCode "安装项目和打包依赖"

if (-not $SkipTests) {
  & $Python -m ruff check src tests
  Assert-LastExitCode "代码检查"
  & $Python -m pytest
  Assert-LastExitCode "自动化测试"
}

New-Item -ItemType Directory -Force (Split-Path $IconFile) | Out-Null
& $Python deploy/windows/generate_icon.py $IconFile
Assert-LastExitCode "生成 Windows 应用图标"

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
Assert-LastExitCode "冻结 Windows 应用"

$Executable = Join-Path $AppDir "$AppName.exe"
if (-not (Test-Path $Executable)) {
  throw "PyInstaller 未生成预期程序：$Executable"
}

$env:QT_QPA_PLATFORM = "offscreen"
$env:RESUME_AGENT_SMOKE_TEST = "1"
& $Executable
Assert-LastExitCode "Windows 打包产物启动/OCR 自检"
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:\RESUME_AGENT_SMOKE_TEST -ErrorAction SilentlyContinue

Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $PortableZip -CompressionLevel Optimal

$InnoSetup = Find-InnoSetup
if (-not $InnoSetup) {
  if ($RequireInstaller) {
    throw "未找到 Inno Setup 6，无法生成 Setup.exe。请先安装 Inno Setup 6。"
  }
  Write-Warning "未找到 Inno Setup 6；已生成便携 ZIP，跳过安装器。"
} else {
  & $InnoSetup "deploy/windows/installer.iss"
  Assert-LastExitCode "Inno Setup 安装器构建"
}

$Hashes = Get-ChildItem $DistDir -File | Where-Object {
  $_.Name -like "$AppName-*.zip" -or $_.Name -like "$AppName-Setup-*.exe"
} | Get-FileHash -Algorithm SHA256
$Hashes | ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), $_.Path } |
  Set-Content -Encoding UTF8 (Join-Path $DistDir "windows-SHA256.txt")

Write-Host "Windows 构建完成："
Write-Host "  便携版：$PortableZip"
if ($InnoSetup) {
  Write-Host "  安装器：$(Join-Path $DistDir "$AppName-Setup-$BuildArch.exe")"
}
Write-Host "  校验值：$(Join-Path $DistDir "windows-SHA256.txt")"
