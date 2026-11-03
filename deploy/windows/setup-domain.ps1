<#
.SYNOPSIS
    把知源学伴绑定到自己的域名（Cloudflare 命名隧道，永久固定地址，全程免费）。

.DESCRIPTION
    自动完成官方文档里的四步：
      1) cloudflared tunnel login          浏览器授权（只需一次）
      2) cloudflared tunnel create <名字>  创建命名隧道并生成凭据
      3) 写 ~/.cloudflared/config.yml      域名 → 本机服务 的转发规则
      4) cloudflared tunnel route dns      在 Cloudflare 里自动创建 CNAME

    跑完后用 tunnel-fixed.bat 启动即可，地址固定为 https://<你的域名>。

.PARAMETER Domain
    要绑定的域名，例如 study.example.com。域名必须已托管在 Cloudflare（NS 指向 Cloudflare）。

.PARAMETER TunnelName
    隧道名，默认 zhiyuan。

.PARAMETER Port
    本机服务端口，默认 8765。

.EXAMPLE
    .\setup-domain.ps1 -Domain study.example.com
#>
[CmdletBinding()]
param(
    [string]$Domain = '',
    [string]$TunnelName = 'zhiyuan',
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
function Write-Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
$cfCfg = Join-Path $cfDir 'config.yml'
$binDir = Join-Path $PSScriptRoot 'bin'
$cf = Join-Path $binDir 'cloudflared.exe'

# ---------- 0. 基本检查 ----------
if (-not $Domain) {
    $answer = Read-Host '请输入要绑定的域名（例如 study.example.com）'
    if ($answer) { $Domain = $answer.Trim() }   # Read-Host 无输入时返回 $null
}
if (-not $Domain) { throw '域名不能为空' }
if ($Domain -notmatch '^[a-zA-Z0-9][a-zA-Z0-9\.\-]+\.[a-zA-Z]{2,}$') {
    throw "域名格式看起来不对：$Domain"
}

if (-not (Test-Path $cf)) {
    Write-Warn "未找到 $cf —— 先运行一次 tunnel.bat，它会自动下载 cloudflared"
    $cand = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cand) { $cf = $cand.Source } else { throw '找不到 cloudflared，请先运行 tunnel.bat' }
}
Write-Ok "cloudflared: $cf"

New-Item -ItemType Directory -Path $cfDir -Force | Out-Null

# ---------- 1. 登录 ----------
$cert = Join-Path $cfDir 'cert.pem'
if (Test-Path $cert) {
    Write-Ok '已登录过 Cloudflare（cert.pem 存在），跳过登录'
} else {
    Write-Step '第 1/4 步：浏览器登录 Cloudflare（会弹出网页，选择你的域名并授权）'
    & $cf tunnel login
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $cert)) {
        throw '登录未完成（没有生成 cert.pem）。请重试，或确认域名已托管在 Cloudflare。'
    }
    Write-Ok '登录成功'
}

# ---------- 2. 创建 / 复用隧道 ----------
Write-Step "第 2/4 步：创建命名隧道 $TunnelName"
$tunnelId = $null
try {
    $listJson = & $cf tunnel list --output json 2>$null
    if ($LASTEXITCODE -eq 0 -and $listJson) {
        $list = $listJson | ConvertFrom-Json
        $hit = $list | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
        if ($hit) { $tunnelId = $hit.id }
    }
} catch { }

if ($tunnelId) {
    Write-Ok "隧道已存在，复用：$TunnelName（$tunnelId）"
} else {
    & $cf tunnel create $TunnelName
    if ($LASTEXITCODE -ne 0) { throw "创建隧道失败（名字可能已被占用）" }
    $listJson = & $cf tunnel list --output json
    $list = $listJson | ConvertFrom-Json
    $hit = $list | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
    if (-not $hit) { throw '创建后未在隧道列表里找到它，请检查 cloudflared tunnel list' }
    $tunnelId = $hit.id
    Write-Ok "已创建：$TunnelName（$tunnelId）"
}

$credFile = Join-Path $cfDir "$tunnelId.json"
if (-not (Test-Path $credFile)) {
    Write-Warn "凭据文件不存在：$credFile"
    Write-Warn "请重跑一次，或执行：cloudflared tunnel token $TunnelName"
}

# ---------- 3. 写 config.yml ----------
Write-Step "第 3/4 步：写入 $cfCfg"
$yaml = @"
# 知源学伴 · Cloudflare 命名隧道配置（由 setup-domain.ps1 生成）
tunnel: $tunnelId
credentials-file: $credFile

ingress:
  # 你的域名 → 本机服务
  - hostname: $Domain
    service: http://127.0.0.1:$Port
    originRequest:
      connectTimeout: 30s
      # 流式问答（SSE）不能被缓冲
      noTLSVerify: false
  # 兜底：其它请求返回 404
  - service: http_status:404
"@
Set-Content -Path $cfCfg -Value $yaml -Encoding UTF8
Write-Ok "已写入（$Domain → http://127.0.0.1:$Port）"

Write-Step '校验配置语法'
& $cf tunnel --config $cfCfg ingress validate
if ($LASTEXITCODE -ne 0) { throw "config.yml 校验未通过，见上面的报错" }
Write-Ok '校验通过'

# ---------- 4. 绑定 DNS ----------
Write-Step "第 4/4 步：在 Cloudflare 里创建 CNAME（$Domain → $TunnelName）"
& $cf tunnel route dns $TunnelName $Domain
if ($LASTEXITCODE -ne 0) {
    Write-Warn 'DNS 绑定返回非 0；如果该记录已存在属正常，可手动在 Cloudflare DNS 里确认 CNAME。'
} else {
    Write-Ok 'DNS 已绑定'
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " 完成！固定地址： https://$Domain" -ForegroundColor Green
Write-Host ''
Write-Host ' 启动方式：双击 deploy\windows\tunnel-fixed.bat' -ForegroundColor Green
Write-Host ' （或命令行： .\tunnel-fixed.ps1）' -ForegroundColor Green
Write-Host ''
Write-Host ' 首次访问可能要等 1-2 分钟让证书签发与 DNS 生效。' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Green
