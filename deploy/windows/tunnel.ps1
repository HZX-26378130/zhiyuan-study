<#
.SYNOPSIS
    一条命令把本机的知源学伴临时发布到公网（Cloudflare 快速隧道，免注册免信用卡）。

.DESCRIPTION
    做三件事：
      1) 确保 cloudflared.exe 存在（优先 winget 安装，其次从 GitHub 下载到本目录 bin\）
      2) 本机启动 server.py（仅监听 127.0.0.1，外网只能经隧道访问）
      3) 起隧道并把 https://xxx.trycloudflare.com 地址打印出来

    关掉窗口（或 Ctrl+C）后：隧道断开、服务停止。
    想 24 小时可用，就别关电脑；或者改用国内学生机 / 免费试用。

.PARAMETER Port
    本地端口，默认 8765。

.PARAMETER NoServer
    只起隧道（服务已在别处运行）。

.EXAMPLE
    .\tunnel.ps1

.EXAMPLE
    .\tunnel.ps1 -Port 9000
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoServer,
    # 隧道是公网地址：默认开启账号体系（需注册/登录），加 -NoAuth 才允许匿名访问
    [switch]$NoAuth
)

$ErrorActionPreference = 'Stop'
function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$binDir = Join-Path $PSScriptRoot 'bin'
$cf = Join-Path $binDir 'cloudflared.exe'

if (-not (Test-Path $root\server.py)) { throw "在 $root 找不到 server.py" }

# ---------- 1) 准备 cloudflared ----------
function Get-CloudflaredByPython {
    param([string]$Dest)
    # 用项目自带的 Python 下载：会跟随 302 跳转到 release-assets.githubusercontent.com。
    # 这台机器上实测 Python 可通，而 curl.exe 不存在、Invoke-WebRequest 曾 TLS 失败。
    $code = @'
import sys, urllib.request
url, dest = sys.argv[1], sys.argv[2]
def hook(blocks, bs, total):
    if total > 0:
        sys.stdout.write("\r    下载中 %d%%" % min(100, blocks * bs * 100 // total))
        sys.stdout.flush()
urllib.request.urlretrieve(url, dest, hook)
print("\r    下载完成            ")
'@
    $tmp = Join-Path $env:TEMP 'cf_dl.py'
    Set-Content -Path $tmp -Value $code -Encoding UTF8
    & py -3 $tmp 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' $Dest
    $rc = $LASTEXITCODE
    Remove-Item $tmp -ErrorAction SilentlyContinue
    return ($rc -eq 0 -and (Test-Path $Dest))
}

if (-not (Test-Path $cf)) {
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    Write-Step '未找到 cloudflared.exe，尝试安装'
    $installed = $false

    # 1) winget（最省事，装完自动进 PATH）
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step '尝试 winget 安装 Cloudflare.cloudflared …'
        try {
            winget install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements --silent | Out-Null
            $cand = (Get-Command cloudflared -ErrorAction SilentlyContinue)
            if ($cand) { $cf = $cand.Source; $installed = $true }
        } catch { Write-Warn "winget 安装失败：$($_.Exception.Message)" }
    }

    # 2) Python 直接下载（本机实测最可靠）
    if (-not $installed) {
        Write-Step '用 Python 下载 cloudflared（约 40 MB，视网络 1–5 分钟）'
        try { if (Get-CloudflaredByPython -Dest $cf) { $installed = $true } }
        catch { Write-Warn "Python 下载失败：$($_.Exception.Message)" }
    }

    # 3) 系统 curl 兜底
    if (-not $installed -and (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        Write-Step '改用 curl.exe 下载'
        try {
            & curl.exe -L --fail --retry 2 -o $cf 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
            if ($LASTEXITCODE -eq 0 -and (Test-Path $cf)) { $installed = $true }
        } catch { Write-Warn "curl 下载失败：$($_.Exception.Message)" }
    }

    if (-not $installed -or -not (Test-Path $cf)) {
        throw "下载失败。可手动下载后放到：`n    $binDir`n    地址：https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    }
}
Write-Ok "cloudflared: $cf"

# ---------- 2) 启动本地服务 ----------
$serverProc = $null
if (-not $NoServer) {
    # 端口被占用就复用已有服务
    $busy = $false
    try { $busy = [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop) } catch { }
    if ($busy) {
        Write-Warn "端口 $Port 已被占用，直接复用已在运行的服务"
    } else {
        Write-Step "启动本机服务（127.0.0.1:$Port）"
        $env:ZY_HOST = '127.0.0.1'
        $env:PYTHONIOENCODING = 'utf-8'
        $env:PYTHONUNBUFFERED = '1'
        if ($NoAuth) {
            Write-Warn '已按 -NoAuth 关闭账号体系：任何拿到地址的人都能看全部数据'
            $env:ZY_AUTH = '0'
        } else {
            # 隧道地址是公网可访问的，默认要求注册/登录，避免学生数据裸奔
            $env:ZY_AUTH = '1'
            Write-Ok '已开启账号体系（首次访问需注册，数据按账号隔离）'
        }
        $serverProc = Start-Process -FilePath 'py' -ArgumentList @('-3', (Join-Path $root 'server.py'), "$Port") `
            -WorkingDirectory $root -PassThru -WindowStyle Minimized
        Start-Sleep -Seconds 3
        if ($serverProc.HasExited) { throw "服务启动失败（退出码 $($serverProc.ExitCode)），先单独跑 py -3 server.py 看报错" }
        Write-Ok "服务已启动（PID $($serverProc.Id)）"
    }
}

# ---------- 3) 起隧道 ----------
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' 正在建立 Cloudflare 隧道，下面会打印公网地址…' -ForegroundColor Green
Write-Host ' 拿到地址后直接发给同学；关掉本窗口即停止对外服务。' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

try {
    & $cf tunnel --no-autoupdate --url "http://127.0.0.1:$Port"
} finally {
    if ($serverProc -and -not $serverProc.HasExited) {
        Write-Step '正在停止本地服务…'
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
}
