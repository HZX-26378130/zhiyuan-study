<#
.SYNOPSIS
    用 ngrok 免费固定域名发布知源学伴（零成本、不要信用卡）。

.DESCRIPTION
    ngrok 免费档自带一个「固定 dev 域名」（形如 xxx.ngrok-free.dev），重启也不变，
    适合没有域名、又不想花钱的场景。

    代价（免费档限制）：
      · 浏览器首次访问会弹一个 ngrok 警告页，点一下「Visit Site」才能进
      · 流量 1 GB / 月、请求 20,000 / 月
      · 同一账号同时最多 3 个在线端点

    脚本做四件事：
      1) 准备 ngrok.exe（winget → 官方 zip 下载 → 解压到 bin\）
      2) 首次运行引导你填 authtoken（只需一次，存在本机 ngrok 配置里）
      3) 启动本机服务（默认开启账号体系）
      4) 起隧道并打印固定公网地址

.PARAMETER Port
    本机端口，默认 8765。

.PARAMETER Token
    ngrok authtoken。不传则首次运行时交互输入。

.PARAMETER NoAuth
    关闭账号体系（不建议）。

.PARAMETER NoServer
    只起隧道（服务已在跑）。

.EXAMPLE
    .\tunnel-ngrok.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$Token = '',
    [switch]$NoAuth,
    [switch]$NoServer
)

$ErrorActionPreference = 'Stop'
function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$binDir = Join-Path $PSScriptRoot 'bin'
$ngrok = Join-Path $binDir 'ngrok.exe'
$ngrokCfg = Join-Path $env:LOCALAPPDATA 'ngrok\ngrok.yml'

if (-not (Test-Path (Join-Path $root 'server.py'))) { throw "在 $root 找不到 server.py" }

# ---------- 1) 准备 ngrok.exe ----------
function Get-NgrokByPython {
    param([string]$DestDir)
    $code = @'
import os, sys, zipfile, urllib.request
url, dest = sys.argv[1], sys.argv[2]
zip_path = os.path.join(dest, "ngrok.zip")
def hook(blocks, bs, total):
    if total > 0:
        sys.stdout.write("\r    下载中 %d%%" % min(100, blocks * bs * 100 // total))
        sys.stdout.flush()
urllib.request.urlretrieve(url, zip_path, hook)
print("\r    解压中            ")
with zipfile.ZipFile(zip_path) as z:
    z.extractall(dest)
os.remove(zip_path)
print("    完成")
'@
    $tmp = Join-Path $env:TEMP 'ngrok_dl.py'
    Set-Content -Path $tmp -Value $code -Encoding UTF8
    & py -3 $tmp 'https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip' $DestDir
    $rc = $LASTEXITCODE
    Remove-Item $tmp -ErrorAction SilentlyContinue
    return ($rc -eq 0 -and (Test-Path (Join-Path $DestDir 'ngrok.exe')))
}

if (-not (Test-Path $ngrok)) {
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    Write-Step '未找到 ngrok.exe，尝试安装'
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step '尝试 winget 安装 ngrok.ngrok …'
        try {
            winget install --id ngrok.ngrok --accept-source-agreements --accept-package-agreements --silent | Out-Null
            $cand = Get-Command ngrok -ErrorAction SilentlyContinue
            if ($cand) { $ngrok = $cand.Source; $installed = $true }
        } catch { Write-Warn "winget 安装失败：$($_.Exception.Message)" }
    }

    if (-not $installed) {
        Write-Step '用 Python 下载官方稳定版并解压（约 10 MB）'
        try { if (Get-NgrokByPython -DestDir $binDir) { $installed = $true } }
        catch { Write-Warn "下载失败：$($_.Exception.Message)" }
    }

    if (-not $installed -or -not (Test-Path $ngrok)) {
        throw "安装失败。可手动下载后解压到：`n    $binDir`n    地址：https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
    }
}
Write-Ok "ngrok: $ngrok"

# ---------- 2) authtoken ----------
$hasCfg = (Test-Path $ngrokCfg) -and ((Get-Content $ngrokCfg -Raw -ErrorAction SilentlyContinue) -match 'authtoken')
if (-not $Token -and -not $hasCfg) {
    Write-Host ''
    Write-Host 'ngrok 需要 authtoken（免费注册，不要信用卡）' -ForegroundColor Yellow
    Write-Host '  1) 打开 https://dashboard.ngrok.com/signup 注册（邮箱即可）' -ForegroundColor Yellow
    Write-Host '  2) 打开 https://dashboard.ngrok.com/get-started/your-authtoken 复制 token' -ForegroundColor Yellow
    Write-Host ''
    $answer = Read-Host '粘贴 authtoken（直接回车跳过，若已配置过）'
    if ($answer) { $Token = $answer.Trim() }   # Read-Host 无输入时返回 $null，不能直接 .Trim()
}
if ($Token) {
    Write-Step '写入 authtoken 到本机 ngrok 配置'
    & $ngrok config add-authtoken $Token | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'authtoken 写入失败，请检查 token 是否正确' }
    Write-Ok 'authtoken 已保存（下次不再询问）'
} elseif (-not $hasCfg) {
    throw '没有 authtoken，无法建立隧道。请重跑并粘贴 token。'
} else {
    Write-Ok '已存在 ngrok 配置，跳过 authtoken'
}

# ---------- 3) 启动本机服务 ----------
$serverProc = $null
if (-not $NoServer) {
    $busy = $false
    try { $busy = [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop) } catch { }
    if ($busy) {
        Write-Warn "端口 $Port 已被占用，复用已在运行的服务"
    } else {
        Write-Step "启动本机服务（127.0.0.1:$Port）"
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
        $serverProc = Start-Process -FilePath 'py' -ArgumentList @('-3', (Join-Path $root 'server.py'), "$Port") `
            -WorkingDirectory $root -PassThru -WindowStyle Minimized
        Start-Sleep -Seconds 3
        if ($serverProc.HasExited) { throw "服务启动失败（退出码 $($serverProc.ExitCode)）" }
        Write-Ok "服务已启动（PID $($serverProc.Id)）"
    }
}

# ---------- 4) 起隧道并取固定地址 ----------
# 注意：ngrok v3 的 `ngrok http` 没有 --web-addr 参数（只有 --url/--log/--log-format 等），
# 状态 API 固定在默认 127.0.0.1:4040，且可能与别的 ngrok 实例混淆。
# 因此这里以「解析本进程日志」为主，API 为辅（按 addr 端口精确匹配）。
$log = Join-Path $env:TEMP 'ngrok-out.log'
Remove-Item $log -ErrorAction SilentlyContinue

Write-Step '启动 ngrok（免费固定 dev 域名）'
$ngrokProc = Start-Process -FilePath $ngrok `
    -ArgumentList @('http', "$Port", "--log=$log", '--log-format=logfmt', '--log-level=info') `
    -PassThru -WindowStyle Hidden

$publicUrl = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 800
    if ($ngrokProc.HasExited) { break }

    # 1) 从日志解析 url=https://xxx.ngrok-free.dev
    if (Test-Path $log) {
        $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
        if ($text) {
            $m = [regex]::Matches($text, 'url=(https://[^\s"]+)')
            foreach ($x in $m) {
                $u = $x.Groups[1].Value
                if ($u -match 'ngrok') { $publicUrl = $u; break }
            }
            if ($publicUrl) { break }
        }
    }

    # 2) 兜底：查本地状态 API，只认 upstream 端口匹配的
    try {
        $api = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2
        $t = $api.tunnels | Where-Object {
            $_.public_url -like 'https://*' -and $_.config.addr -match ":$Port$"
        } | Select-Object -First 1
        if ($t) { $publicUrl = $t.public_url; break }
    } catch { }
}

if (-not $publicUrl) {
    Write-Warn '没能自动取得公网地址，ngrok 日志如下：'
    if (Test-Path $log) { Get-Content $log -Tail 20 | ForEach-Object { "    $_" } }
    if ($serverProc -and -not $serverProc.HasExited) { Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue }
    throw 'ngrok 启动失败（常见原因：authtoken 无效、免费端点已占满 3 个、网络不通）'
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " 固定公网地址： $publicUrl" -ForegroundColor Green
Write-Host ''
Write-Host ' 说明：' -ForegroundColor Green
Write-Host '   · 这个地址重启后不变（ngrok 免费档的固定 dev 域名）' -ForegroundColor Green
Write-Host '   · 同学首次打开会看到 ngrok 警告页，点「Visit Site」即可' -ForegroundColor Green
Write-Host '   · 保持本窗口开着；Ctrl+C 或关窗即停止对外服务' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

try {
    $ngrokProc.WaitForExit()
    if (-not $NoServer -and $serverProc -and -not $serverProc.HasExited) {
        Write-Step 'ngrok 已退出，正在停止本地服务…'
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($ngrokProc.ExitCode -ne 0) {
        Write-Warn "ngrok 退出码 $($ngrokProc.ExitCode)，日志：$log"
        if (Test-Path $log) { Get-Content $log -Tail 10 | ForEach-Object { "    $_" } }
    }
} finally {
    if ($serverProc -and -not $serverProc.HasExited) {
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
}
