<#
.SYNOPSIS
    把本机的知源学伴项目上传到 Oracle VM（或任意 Linux 主机）。

.DESCRIPTION
    Windows 没有自带 rsync，这里用系统自带的 tar.exe + scp 完成：
      1) 本地打包（排除 .git / data/db / _archive / config.json / __pycache__）
      2) scp 上传到 /tmp
      3) 远端解包到 /opt/zhiyuan-study（保留 VM 上已有的 data/ 与 .env）

.PARAMETER Install
    首次部署时加上此开关：解包后自动执行 deploy/oracle/install.sh

.EXAMPLE
    # 首次部署
    .\upload-to-vm.ps1 -VmHost 123.45.67.89 -Install

.EXAMPLE
    # 用私钥 + 自定义用户/端口
    .\upload-to-vm.ps1 -VmHost vm.example.com -User ubuntu -Port 2222 -KeyFile C:\keys\oracle.key

.EXAMPLE
    # 日常更新（不重装服务，只覆盖代码后重启）
    .\upload-to-vm.ps1 -VmHost 123.45.67.89
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VmHost,

    [string]$User = 'ubuntu',
    [int]$Port = 22,
    [string]$KeyFile = '',
    [string]$RemotePath = '/opt/zhiyuan-study',
    [switch]$Install
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }

# ---------- 依赖检查 ----------
foreach ($exe in @('tar', 'scp', 'ssh')) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        throw "缺少命令 $exe。Windows 10 1803+ 自带 tar/scp/ssh；请在「设置 → 应用 → 可选功能」里安装 OpenSSH 客户端。"
    }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not (Test-Path (Join-Path $root 'server.py'))) {
    throw "在 $root 找不到 server.py —— 请把脚本放在项目的 deploy\windows\ 目录下运行。"
}

$sshTarget = "$User@$VmHost"
$sshArgs = @('-p', "$Port", '-o', 'StrictHostKeyChecking=accept-new')
$scpArgs = @('-P', "$Port", '-o', 'StrictHostKeyChecking=accept-new')
if ($KeyFile) {
    if (-not (Test-Path $KeyFile)) { throw "找不到私钥文件：$KeyFile" }
    $sshArgs += @('-i', $KeyFile)
    $scpArgs += @('-i', $KeyFile)
}

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $env:TEMP "zhiyuan-upload-$stamp.tar.gz"

# ---------- 1) 打包 ----------
Write-Step "打包 $root（排除 .git / data\db / _archive / config.json / __pycache__）"
$excludes = @(
    '--exclude=.git',
    '--exclude=.git/*',
    '--exclude=data/db',
    '--exclude=data/db/*',
    '--exclude=data/materials',
    '--exclude=data/materials/*',
    '--exclude=_archive',
    '--exclude=_archive/*',
    '--exclude=config.json',
    '--exclude=.env',
    '--exclude=__pycache__',
    '--exclude=*/__pycache__',
    '--exclude=*.pyc',
    '--exclude=*.log'
)
& tar -czf $archive @excludes -C $root .
if ($LASTEXITCODE -ne 0) { throw "打包失败（tar 退出码 $LASTEXITCODE）" }
$sizeMB = [math]::Round((Get-Item $archive).Length / 1MB, 2)
Write-Ok "已打包：$archive（$sizeMB MB）"

try {
    # ---------- 2) 上传 ----------
    Write-Step "上传到 $sshTarget"
    & scp @scpArgs $archive "${sshTarget}:/tmp/zhiyuan-upload.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw "scp 上传失败（退出码 $LASTEXITCODE）—— 检查 IP/用户名/端口/密钥/安全组" }
    Write-Ok '上传完成'

    # ---------- 3) 远端解包 ----------
    Write-Step "远端解包到 $RemotePath（保留已有 data/ 与 .env）"
    $remoteCmd = @"
set -e
sudo mkdir -p '$RemotePath'
sudo tar -xzf /tmp/zhiyuan-upload.tar.gz -C '$RemotePath'
sudo rm -f /tmp/zhiyuan-upload.tar.gz
sudo chown -R zhiyuan:zhiyuan '$RemotePath' 2>/dev/null || sudo chown -R `$(id -un):`$(id -gn) '$RemotePath'
echo EXTRACT_OK
"@
    $out = & ssh @sshArgs $sshTarget $remoteCmd
    if ($LASTEXITCODE -ne 0 -or ($out -notmatch 'EXTRACT_OK')) {
        throw "远端解包失败。输出：$out"
    }
    Write-Ok '解包完成'

    # ---------- 4) 可选：安装/重启 ----------
    if ($Install) {
        Write-Step '执行安装脚本（建用户 / 写 .env / systemd / 防火墙）'
        & ssh @sshArgs $sshTarget "sudo bash $RemotePath/deploy/oracle/install.sh"
        if ($LASTEXITCODE -ne 0) { throw "安装脚本执行失败，请在 VM 上查看：journalctl -u zhiyuan-study -n 50" }
        Write-Ok '安装完成'
    } else {
        Write-Step '重启服务以加载新代码'
        & ssh @sshArgs $sshTarget "sudo systemctl restart zhiyuan-study 2>/dev/null && systemctl is-active zhiyuan-study || echo '服务未安装，跳过重启'"
    }
} finally {
    Remove-Item $archive -ErrorAction SilentlyContinue
}
