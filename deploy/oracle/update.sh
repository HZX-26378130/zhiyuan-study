#!/usr/bin/env bash
# 更新已部署的知源学伴并重启（在 VM 上运行）
#
# 用法：sudo bash /opt/zhiyuan-study/deploy/oracle/update.sh
# 说明：先备份 data/ 与 config.json，再 git pull（或从本机 rsync 覆盖），最后重启服务

set -euo pipefail
APP_DIR="/opt/zhiyuan-study"
SERVICE="zhiyuan-study"
STAMP="$(date +%Y%m%d%H%M%S)"

log() { printf '\033[32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }

[[ $EUID -eq 0 ]] || { echo "请用 sudo 运行" >&2; exit 1; }
cd "$APP_DIR"

# 1) 备份数据（数据不进 git，更新不会覆盖，但多一层保险）
log "备份 data/ 与 config.json -> /root/zhiyuan-backup-$STAMP"
mkdir -p "/root/zhiyuan-backup-$STAMP"
cp -a data config.json "/root/zhiyuan-backup-$STAMP/" 2>/dev/null || true

# 2) 拉取代码
if [[ -d .git ]]; then
    log "git pull"
    git -c core.quotepath=false pull --ff-only
else
    log "未检测到 .git —— 请在本机执行 rsync 覆盖后再重启（脚本会跳过拉取）"
fi

# 3) 权限 + 重启
chown -R zhiyuan:zhiyuan "$APP_DIR"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" && log "服务已重启并运行中" || {
    echo "启动失败，日志：" >&2
    journalctl -u "$SERVICE" -n 40 --no-pager >&2
    exit 1
}

# 4) 清理旧备份（只留最近 5 份）
ls -1dt /root/zhiyuan-backup-* 2>/dev/null | tail -n +6 | xargs -r rm -rf
log "完成。日志：journalctl -u $SERVICE -f"
