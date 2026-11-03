<#
.SYNOPSIS
    把 VM 上的学习数据（data/ 与 config.json）备份回本机。

.DESCRIPTION
    在 VM 上打包 → scp 拉回本地 backups 目录 → 删除远端临时文件 → 清理过期备份。
    可用于手动备份，也可配 Windows 计划任务每日自动跑（见下方示例）。

.PARAMETER KeepDays
    本地备份保留天数，超过则自动删除，默认 30 天。

.EXAMPLE
    .\backup-from-vm.ps1 -VmHost 123.45.67.89

.EXAMPLE
    # 每日 23:00 自动备份（创建计划任务，只需执行一次）
    schtasks /Create /F /SC DAILY /ST 23:00 /TN "知源学伴每日备份" `
      /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"$PWD\backup-from-vm.ps1\" -VmHost 123.45.67.89"

.EXAMPLE
    # 查看/删除计划任务
    schtasks /Query /TN "知源学伴每日备份"
    schtasks /Delete /TN "知源学伴每日备份" /F
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VmHost,

    [string]$User = 'ubuntu',
    [int]$Port = 22,
    [string]$KeyFile = '',
    [string]$RemotePath = '/opt/zhiyuan-study',
    [string]$OutDir = '',
    [int]$KeepDays = 30
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }

foreach ($exe in @('scp', 'ssh')) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        throw "缺少命令 $exe —— 请在「设置 → 应用 → 可选功能」安装 OpenSSH 客户端。"
    }
}

if (-not $OutDir) { $OutDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'backups' }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

$sshTarget = "$User@$VmHost"
$sshArgs = @('-p', "$Port", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15')
$scpArgs = @('-P', "$Port", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15')
if ($KeyFile) {
    if (-not (Test-Path $KeyFile)) { throw "找不到私钥文件：$KeyFile" }
    $sshArgs += @('-i', $KeyFile)
    $scpArgs += @('-i', $KeyFile)
}

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $OutDir "zhiyuan-data-$stamp.tar.gz"

# ---------- 1) 远端打包 ----------
Write-Step "远端打包 $RemotePath/data 与 config.json"
$packCmd = @"
set -e
sudo mkdir -p /var/backups
sudo tar -czf /tmp/zy-backup.tar.gz -C '$RemotePath' data config.json 2>/dev/null || \
    sudo tar -czf /tmp/zy-backup.tar.gz -C '$RemotePath' data
sudo chmod 644 /tmp/zy-backup.tar.gz
du -h /tmp/zy-backup.tar.gz | cut -f1
"@
$size = (& ssh @sshArgs $sshTarget $packCmd | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0) { throw '远端打包失败（检查 SSH 连接与服务目录是否存在）' }
Write-Ok "远端包大小：$size"

# ---------- 2) 拉回本地 ----------
try {
    Write-Step "下载到 $outFile"
    & scp @scpArgs "${sshTarget}:/tmp/zy-backup.tar.gz" $outFile
    if ($LASTEXITCODE -ne 0) { throw "scp 下载失败（退出码 $LASTEXITCODE）" }
    $mb = [math]::Round((Get-Item $outFile).Length / 1MB, 2)
    Write-Ok "已保存：$outFile（$mb MB）"

    # 简单校验：tar 能读且包含 data/db
    $list = & tar -tzf $outFile 2>$null
    if ($list -match '^data/db') { Write-Ok '包内容校验通过（含 data/db）' }
    else { Write-Host '[!] 包里没看到 data/db，可能 VM 上还没有数据' -ForegroundColor Yellow }
} finally {
    # ---------- 3) 清理远端临时文件 ----------
    & ssh @sshArgs $sshTarget 'sudo rm -f /tmp/zy-backup.tar.gz' | Out-Null
}

# ---------- 4) 清理过期本地备份 ----------
$cutoff = (Get-Date).AddDays(-$KeepDays)
$old = Get-ChildItem $OutDir -Filter 'zhiyuan-data-*.tar.gz' |
       Where-Object { $_.LastWriteTime -lt $cutoff }
if ($old) {
    $old | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "    已清理过期备份：$($_.Name)" -ForegroundColor DarkGray
    }
}
$count = (Get-ChildItem $OutDir -Filter 'zhiyuan-data-*.tar.gz').Count
Write-Ok "本地共有 $count 份备份（保留 $KeepDays 天）"
