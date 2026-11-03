# 构建 Windows 桌面版 exe（文件夹版）
#
# 用法（在项目根目录）：
#     powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#
# 前置：需要一个装了 PyInstaller 的 Python 环境。脚本会：
#   1) 复用/创建 .build-venv（与系统 Python 隔离，不污染全局）
#   2) 装 pyinstaller
#   3) 生成图标 → 打包 → 产物在 dist\知源学伴\
#
# 产物结构：
#   dist\知源学伴\知源学伴.exe      ← 双击运行
#   dist\知源学伴\_internal\...     ← 依赖与资源（不要删）
#   dist\知源学伴-便携版.zip        ← 可直接发给同学

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot          # 项目根
Set-Location $root

function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }

# ---------- 1. 构建环境 ----------
$venv = Join-Path $root '.build-venv'
$py = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Step "创建构建虚拟环境 $venv"
    $sysPy = (Get-Command py -ErrorAction SilentlyContinue)
    if ($sysPy) { & py -3 -m venv $venv } else { & python -m venv $venv }
    if (-not (Test-Path $py)) { throw '创建 venv 失败，请确认已安装 Python 3.8+ 并加入 PATH' }
}

Write-Step '检查 PyInstaller'
# $ErrorActionPreference='Stop' 时原生命令非 0 退出会抛 NativeCommandError，
# 所以用 try/catch 静默探测，不靠 $LASTEXITCODE。
$piVer = ''
try { $piVer = (& $py -c "import PyInstaller;print(PyInstaller.__version__)" 2>$null) } catch { $piVer = '' }
if (-not $piVer) {
    Write-Step '安装 PyInstaller（走阿里云镜像，国内更快）'
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -q pyinstaller -i https://mirrors.aliyun.com/pypi/simple/
    try { $piVer = (& $py -c "import PyInstaller;print(PyInstaller.__version__)" 2>$null) } catch { $piVer = '' }
    if (-not $piVer) { throw 'PyInstaller 安装失败（检查网络或 pip 镜像）' }
}
Write-Ok "PyInstaller $piVer"

# ---------- 2. 图标 ----------
Write-Step '生成图标'
& $py (Join-Path $root 'packaging\make_icon.py')
if (-not (Test-Path (Join-Path $root 'packaging\icon.ico'))) { throw '图标生成失败' }

# ---------- 3. 打包 ----------
Write-Step '开始打包（首次约 1-3 分钟）'
$dist = Join-Path $root 'dist'
$build = Join-Path $root 'build'
Remove-Item $dist, $build -Recurse -Force -ErrorAction SilentlyContinue

& $py -m PyInstaller --noconfirm --clean `
    --distpath $dist --workpath $build `
    (Join-Path $root 'packaging\zhiyuan.spec')
if ($LASTEXITCODE -ne 0) { throw '打包失败，请看上面的输出' }

$appDir = Join-Path $dist '知源学伴'
$exe = Join-Path $appDir '知源学伴.exe'
if (-not (Test-Path $exe)) { throw "没有生成 $exe" }
Write-Ok "产物: $exe"

# ---------- 4. 便携 zip ----------
Write-Step '打便携 zip（发给同学直接解压用）'
$zip = Join-Path $dist '知源学伴-便携版.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $appDir '*') -DestinationPath $zip -CompressionLevel Optimal
Write-Ok ("$zip  " + [math]::Round((Get-Item $zip).Length / 1MB, 1) + ' MB')

# ---------- 5. 冒烟启动 ----------
Write-Step '启动自检（5 秒后自动关闭）'
$env:ZY_DATA_DIR = Join-Path $env:TEMP ('zy_exe_smoke_' + [guid]::NewGuid().ToString('N').Substring(0, 6))
$p = Start-Process -FilePath $exe -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 5
$ok = $false
try {
    $r = Invoke-WebRequest 'http://127.0.0.1:8765/api/bootstrap' -TimeoutSec 8 -UseBasicParsing
    $ok = ($r.StatusCode -eq 200)
} catch {
    # 端口可能被别的实例占用，换一个探测
    foreach ($port in 8766, 8767, 8768) {
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:$port/api/bootstrap" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch { }
    }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Get-Process 知源学伴 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if ($ok) {
    Write-Ok '自检通过：exe 能起服务并响应 /api/bootstrap'
} else {
    Write-Host '[!] 自检没拿到 200，请手动双击 exe 看控制台报错' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' 构建完成' -ForegroundColor Green
Write-Host "   exe : $exe" -ForegroundColor Green
Write-Host "   zip : $zip（发给同学，解压后双击 exe）" -ForegroundColor Green
Write-Host '   数据: %APPDATA%\知源学伴（卸载 exe 不丢数据）' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
