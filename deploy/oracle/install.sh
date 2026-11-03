#!/usr/bin/env bash
# 知源学伴 · Oracle Cloud 永久免费 VM 一键安装脚本
#
# 适用：Oracle Cloud Always Free 的 Ubuntu 22.04 / 24.04（x86 或 ARM 均可）
# 前提：仓库已放到 /opt/zhiyuan-study（git clone 或从本机 rsync 上传）
# 用法：sudo bash /opt/zhiyuan-study/deploy/oracle/install.sh
#
# 做四件事：装依赖 → 建系统用户 → 写 .env 与 systemd 服务 → 放行防火墙并启动

set -euo pipefail

APP_DIR="/opt/zhiyuan-study"
APP_USER="zhiyuan"
SERVICE="zhiyuan-study"
PORT="${PORT:-8765}"
ENV_FILE="$APP_DIR/.env"

log()  { printf '\033[32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 0. 前置检查 ----------
[[ $EUID -eq 0 ]] || die "请用 sudo 运行：sudo bash $0"
[[ -f "$APP_DIR/server.py" ]] || die "找不到 $APP_DIR/server.py —— 请先把项目放到 $APP_DIR"
command -v python3 >/dev/null || die "缺少 python3"
python3 - <<'EOF' || die "Python 版本过低，需要 3.8+"
import sys
assert sys.version_info >= (3, 8), sys.version
EOF

log "应用目录: $APP_DIR | 端口: $PORT | 架构: $(uname -m)"

# ---------- 1. 依赖 ----------
log "安装依赖（python3 / curl / iptables-persistent）…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 curl iptables-persistent >/dev/null
log "依赖就绪"

# ---------- 2. 系统用户 ----------
if ! id "$APP_USER" >/dev/null 2>&1; then
    log "创建系统用户 $APP_USER"
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
else
    log "系统用户 $APP_USER 已存在"
fi

# 数据目录 + 权限（应用只需写 data/ 与 config.json）
mkdir -p "$APP_DIR/data"
if [[ ! -f "$APP_DIR/config.json" ]]; then
    log "生成默认 config.json（离线模式 + 免 Key 兜底通道）"
    cat > "$APP_DIR/config.json" <<'JSON'
{
  "llm": {
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "",
    "model": "glm-4-flash",
    "vision_model": "glm-4v-flash",
    "stream_url": "",
    "fallback": [
      {"base_url": "https://text.pollinations.ai/openai", "model": "openai-fast", "vision_model": ""}
    ]
  },
  "search": {"provider": "", "api_key": ""}
}
JSON
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/config.json"
log "权限已设置"

# ---------- 3. .env（含会话签名密钥） ----------
if [[ ! -f "$ENV_FILE" ]]; then
    SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    ADMIN_TOKEN="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    cat > "$ENV_FILE" <<EOF
# 知源学伴运行配置（此文件含密钥，勿提交/勿外传）
# 监听地址：首次用 IP 直接访问就保持 0.0.0.0；上了 Caddy+HTTPS 改成 127.0.0.1
ZY_HOST=0.0.0.0
ZY_AUTH=1
# 会话签名密钥（已自动生成，改动会让所有人登录态失效）
ZY_SECRET=$SECRET
# 管理端口令（只有拿到它的人能看全班数据；忘记可改这里再重启）
ZY_ADMIN_TOKEN=$ADMIN_TOKEN
# 也可以改成「只允许某个账号」：填注册时的用户名（优先级高于上面的口令）
# ZY_ADMIN_USER=你的账号名
PYTHONUNBUFFERED=1
PYTHONIOENCODING=utf-8
# ProtectSystem=strict 下应用目录只读，禁止写 .pyc（否则每次启动都报权限警告）
PYTHONDONTWRITEBYTECODE=1
# —— 可选：接入自己的大模型（不填则走免 Key 兜底通道，较慢）——
# LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
# LLM_API_KEY=
# LLM_MODEL=glm-4-flash
# LLM_STREAM_URL=
EOF
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    log "已生成 $ENV_FILE（含随机 ZY_SECRET）"
else
    log "$ENV_FILE 已存在，保留原配置"
fi

# ---------- 4. systemd ----------
log "安装 systemd 服务"
install -m 644 "$APP_DIR/deploy/oracle/$SERVICE.service" "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
    warn "服务未能启动，最近日志："
    journalctl -u "$SERVICE" -n 30 --no-pager || true
    die "启动失败"
}
log "服务已启动并设为开机自启"

# ---------- 5. 防火墙 ----------
# 本脚本适用于任何 Ubuntu 主机（Oracle / GCP / AWS / 阿里云 / 腾讯云 / 自建）：
#   - Oracle 的 Ubuntu 镜像默认 iptables 只放行 22，必须显式放行
#   - 其他云常见 ufw 生效中，也需要放行
#   - 各家控制台的「安全组 / 安全列表」是另一层，脚本改不了，见文末提示
log "放行主机防火墙端口 $PORT / 80 / 443"
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    for p in "$PORT" 80 443; do ufw allow "$p"/tcp >/dev/null 2>&1 || true; done
    log "已通过 ufw 放行"
fi
if command -v iptables >/dev/null; then
    for p in "$PORT" 80 443; do
        iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || \
            iptables -I INPUT 1 -p tcp --dport "$p" -j ACCEPT || true
    done
    if command -v netfilter-persistent >/dev/null; then
        netfilter-persistent save >/dev/null 2>&1 || warn "iptables 规则持久化失败（重启后可能失效）"
    fi
fi

# ---------- 6. 自检 ----------
log "本机自检 http://127.0.0.1:$PORT/api/bootstrap"
if curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/bootstrap" >/tmp/zy_boot.json 2>/dev/null; then
    python3 - <<'PY'
import json
d = json.load(open('/tmp/zy_boot.json', encoding='utf-8'))
print('    build=%s llm=%s auth=%s' % (d.get('build'), d.get('llm'), d.get('auth')))
PY
else
    warn "自检请求失败，请查看：journalctl -u $SERVICE -n 50 --no-pager"
fi

PUBIP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
cat <<EOF

============================================================
 安装完成

 本机访问 : http://127.0.0.1:$PORT
 公网访问 : http://${PUBIP:-<你的公网IP>}:$PORT
            （云层防火墙要在云厂商控制台放行入站 TCP $PORT）

 常用命令：
   systemctl status $SERVICE        # 查看状态
   journalctl -u $SERVICE -f        # 实时日志
   systemctl restart $SERVICE       # 重启
   nano $ENV_FILE                   # 改配置（改完 restart）

 注册账号：打开网页 → 登录页 → 注册
            （ZY_AUTH=1 已开启；账号存在 $APP_DIR/data/db/users.json）

 管理端  ：只有管理员可见（侧栏「管理端」）。
            口令已随机生成，存在 $ENV_FILE 的 ZY_ADMIN_TOKEN
            查看：grep ZY_ADMIN_TOKEN $ENV_FILE
            想换成「只允许某个账号」：在该文件里加 ZY_ADMIN_USER=<你的用户名> 再 restart

 想上 HTTPS：见 deploy/oracle/README.md 的「Caddy + 域名」一节
============================================================
EOF
