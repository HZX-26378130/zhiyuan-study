# Linux VM 部署指南（Oracle 永久免费 / 其他云通用）

面向 **任意 Ubuntu 22.04/24.04 主机**（Oracle Always Free、Google Cloud e2-micro、AWS、阿里云/腾讯云轻量、自建 VPS 均适用），把知源学伴跑成公网可访问的多用户站点。
后端是纯标准库 Python，**不需要 pip 依赖**；数据存本机磁盘，重启不丢。
脚本会自动识别 `ufw` 是否启用（Oracle 用 iptables，其他云常见 ufw）。

> 换云厂商时唯一要改的是**云层防火墙**（安全组/安全列表/防火墙规则），位置见各小节与第 3 步。

---

## 0. 先决条件

- 一台 Ubuntu 实例（1 GB 内存即可），能 SSH 登录
- Oracle Always Free 规格：1 核 1G AMD ×2 或 4 核 24G ARM
- 云控制台放行入站端口（见第 3 步，最容易漏）

> ⚠️ Oracle 对**长期闲置**的免费实例可能回收，建议保持一定访问量，别让它空转几个月。

---

## 1. 创建实例（控制台）

| 项 | 建议值 |
|---|---|
| 镜像 | Canonical Ubuntu 22.04（或 24.04）—— 其他云同样选 Ubuntu |
| 形状 | Oracle：`VM.Standard.A1.Flex`（ARM，2 OCPU / 12 GB）或 `VM.Standard.E2.1.Micro`；GCP：`e2-micro`；轻量：1C1G 起 |
| 公网 IP | Oracle 勾选 Assign a public IPv4 address；GCP 选「临时/静态外部 IP」 |
| SSH 密钥 | 上传公钥，保存好私钥（Ubuntu 镜像用户名 `ubuntu`） |

ARM 形状经常"缺货"，多试几次或换可用域（AD）。1 GB 内存也够跑（本项目内存占用很低）。

> 其他云的最小可用配置：**1 vCPU / 1 GB RAM / 20 GB 磁盘**。GCP `e2-micro` 免费规格限制在
> `us-west1`、`us-central1`、`us-east1` 三个区域，且**每月仅 1 GB 免费出网流量**（超出按量计费）——
> 图片/讲义多的站点要注意；Oracle 的免费出网额度大得多（10 TB/月），这是它更常见的原因。

---

## 2. 上传代码并安装

在**你的 Windows 机器**上（Git Bash 或 PowerShell 的 `scp`）：

```bash
# 方式 A：VM 上直接 clone（仓库是 private，需要 GitHub 令牌或 Deploy Key）
ssh ubuntu@<公网IP>
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/HZX-26378130/zhiyuan-study.git
sudo chown -R ubuntu:ubuntu /opt/zhiyuan-study

# 方式 B：用现成脚本一键上传（Windows 无需 rsync，自动排除 .git/data-db/config.json）
#   cd deploy\windows
#   .\upload-to-vm.ps1 -VmHost <公网IP> -Install
#   详见 deploy/windows/README.md
ssh ubuntu@<公网IP> 'sudo mkdir -p /opt && sudo mv /tmp/zhiyuan-study /opt/zhiyuan-study'
```

然后一键安装：

```bash
ssh ubuntu@<公网IP>
sudo bash /opt/zhiyuan-study/deploy/oracle/install.sh
```

脚本会做：装依赖 → 建 `zhiyuan` 系统用户 → 生成 `.env`（含随机 `ZY_SECRET`）→ 写 systemd 服务并开机自启 → 放行 iptables 端口 → 自检接口 → 打印访问地址。

看到这段就成功了：

```
 本机访问 : http://127.0.0.1:8765
 公网访问 : http://<公网IP>:8765
```

---

## 3. 放行防火墙（两处，缺一不可）

### 3.1 VM 内部 iptables

`install.sh` 已自动放行 `8765/80/443` 并持久化。手动确认：

```bash
sudo iptables -L INPUT -n --line-numbers | head
```

### 3.2 Oracle 控制台安全列表 ⭐ 最常见的"打不开"原因

```
控制台 → 网络 → 虚拟云网络 → 点你的 VCN → 子网 → 点默认安全列表
→ 添加入站规则：
   源 CIDR: 0.0.0.0/0
   IP 协议: TCP
   目标端口范围: 8765     （上了 HTTPS 后再加 80、443）
```

没做这步，VM 里 `curl http://127.0.0.1:8765` 能通，但外网访问不了。

---

## 4. 首次使用

打开 `http://<公网IP>:8765` → **注册账号**（用户名 ≥2 字符，密码 ≥6 位）→ 登录。

- 账号存 `data/db/users.json`（PBKDF2-SHA256 加盐哈希，不是明文）
- 每个账号有独立档案、错题、积分、讲义；彼此数据隔离
- `ZY_AUTH=1` 已开启，未登录访问 API 一律 401

**AI 接入**（可选，不配也能用）：

登录后 → 侧栏「⚙ 接入设置 / API」→ 选「智谱 GLM」→ 填自己的 Key → 保存。

> 不填 Key 时走免 Key 公益通道（Pollinations），**限 1 次/45 秒、无视觉能力**，只适合应急。
> 想稳定又快，建议申请免费的 `glm-4-flash`（[open.bigmodel.cn](https://open.bigmodel.cn)，注册即免费）。

---

## 5. Caddy + 域名（强烈建议，否则密码明文传输）

`http://` 下登录密码是明文过网，公网用务必上 HTTPS。

**前提**：域名 A 记录指向公网 IP；安全列表放行 80/443。

```bash
# 装 Caddy（官方源）
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# 写配置（改域名）
sudo cp /opt/zhiyuan-study/deploy/oracle/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/^你的域名/study.example.com/' /etc/caddy/Caddyfile

# 让 Python 只监听本机，由 Caddy 对外
sudo sed -i 's/^ZY_HOST=.*/ZY_HOST=127.0.0.1/' /opt/zhiyuan-study/.env
sudo systemctl restart zhiyuan-study
sudo systemctl reload caddy
```

Caddy 会自动申请 Let's Encrypt 证书。之后访问 `https://study.example.com`。

> `Caddyfile` 里已针对 `/api/qa/stream` 关闭缓冲（`flush_interval -1`），否则流式问答会变成"等全部生成完才显示"。

---

## 6. 日常运维

```bash
sudo systemctl status zhiyuan-study      # 状态
sudo journalctl -u zhiyuan-study -f      # 实时日志
sudo systemctl restart zhiyuan-study     # 重启
sudo nano /opt/zhiyuan-study/.env        # 改配置（改完 restart）

# 更新代码（会先自动备份数据到 /root/zhiyuan-backup-<时间戳>）
sudo bash /opt/zhiyuan-study/deploy/oracle/update.sh
```

### 备份

```bash
# 方式一：网页里「⚙ 接入设置 → ⬇ 备份数据」导出 zip
# 方式二：直接打包数据目录
sudo tar czf /root/zhiyuan-$(date +%F).tar.gz -C /opt/zhiyuan-study data config.json
```

---

## 7. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 外网打不开，本机 curl 正常 | VCN 安全列表没放入站规则（第 3.2 步） |
| 完全连不上 | iptables 规则丢失（`netfilter-persistent save`），或实例没公网 IP |
| 页面能开但注册报错 | 看 `journalctl -u zhiyuan-study`；`.env` 里 `ZY_AUTH=1` 是否生效 |
| 所有人登录态突然失效 | `ZY_SECRET` 变了（换了 `.env` 或删了），属预期行为 |
| AI 一直"生成中"或很慢 | 没配 Key，走的是免 Key 公益通道（1 次/45 秒限流） |
| 流式问答不是逐字显示 | 前面挂了 Nginx/Caddy 但没关缓冲，见 Caddyfile 的 `flush_interval -1` |
| 服务起不来 | `journalctl -u zhiyuan-study -n 50 --no-pager`，常见是 `data/` 权限问题 |

---

## 8. 文件清单

| 文件 | 作用 |
|---|---|
| `install.sh` | 一键安装（root 执行） |
| `zhiyuan-study.service` | systemd 单元，含最小权限加固 |
| `update.sh` | 备份 + 更新 + 重启 |
| `Caddyfile` | HTTPS 反向代理模板（含 SSE 免缓冲） |

配置落地位置：

```
/opt/zhiyuan-study/
├── .env          # 运行配置（含 ZY_SECRET，权限 600）
├── config.json   # 大模型接入（权限 600）
└── data/db/      # 所有账号与学习数据
```
