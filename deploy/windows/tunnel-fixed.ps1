<#
.SYNOPSIS
    用固定域名启动知源学伴（Cloudflare 命名隧道）。需先运行 setup-domain.ps1。

.DESCRIPTION
    1) 读取 ~/.cloudflared/config.yml，确认域名与端口
    2) 本机启动 server.py（默认开启账号体系）
    3) 运行命名隧道，地址固定为 https://<你的域名>

    关掉窗口即停止对外服务。

.PARAMETER NoAuth
    关闭账号体系（不建议：地址固定后更容易被扫到）。

.PARAMETER NoServer
    只跑隧道（服务已在别处运行）。
#>
[CmdletBinding()]
param(
    [switch]$NoAuth,
    [switch]$NoServer
)

$ErrorActionPreference = 'Stop'
function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
$cfCfg = Join-Path $cfDir 'config.yml'
$cf = Join-Path (Join-Path $PSScriptRoot 'bin') 'cloudflared.exe'
if (-not (Test-Path $cf)) {
    $cand = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cand) { $cf = $cand.Source } else { throw '找不到 cloudflared，请先运行 tunnel.bat 下载' }
}
if (-not (Test-Path $cfCfg)) {
    throw "找不到 $cfCfg —— 请先运行 setup-domain.ps1 绑定域名"
}

# 从 config.yml 读域名与端口（避免再让用户输入）
$yaml = Get-Content $cfCfg -Raw
$hostname = ([regex]::Match($yaml, '(?m)^\s*-\s*hostname:\s*(\S+)')).Groups[1].Value
$svc = ([regex]::Match($yaml, 'service:\s*http://127\.0\.0\.1:(\d+)')).Groups[1].Value
$port = if ($svc) { [int]$svc } else { 8765 }
$tunnel = ([regex]::Match($yaml, '(?m)^tunnel:\s*(\S+)')).Groups[1].Value

if (-not $hostname) { throw 'config.yml 里没找到 hostname，请重跑 setup-domain.ps1' }
Write-Ok "域名：https://$hostname → 本机 127.0.0.1:$port"

# ---------- 启动本机服务 ----------
$serverProc = $null
if (-not $NoServer) {
    $busy = $false
    try { $busy = [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) } catch { }
    if ($busy) {
        Write-Warn "端口 $port 已被占用，复用已在运行的服务"
    } else {
        Write-Step "启动本机服务（127.0.0.1:$port）"
        $env:ZY_HOST = '127.0.0.1'
        $env:PYTHONIOENCODING = 'utf-8'
        $env:PYTHONUNBUFFERED = '1'
        if ($NoAuth) {
            Write-Warn '已按 -NoAuth 关闭账号体系：任何拿到地址的人都能看全部数据'
            $env:ZY_AUTH = '0'
        } else {
            $env:ZY_AUTH = '1'
            Write-Ok '已开启账号体系（首次访问需注册）'
        }
        $serverProc = Start-Process -FilePath 'py' -ArgumentList @('-3', (Join-Path $root 'server.py'), "$port") `
            -WorkingDirectory $root -PassThru -WindowStyle Minimized
        Start-Sleep -Seconds 3
        if ($serverProc.HasExited) { throw "服务启动失败（退出码 $($serverProc.ExitCode)）" }
        Write-Ok "服务已启动（PID $($serverProc.Id)）"
    }
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " 固定地址： https://$hostname" -ForegroundColor Green
Write-Host ' 保持本窗口开着；Ctrl+C 或关窗即停止对外服务。' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

try {
    & $cf tunnel --config $cfCfg run
} finally {
    if ($serverProc -and -not $serverProc.HasExited) {
        Write-Step '正在停止本地服务…'
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
}
