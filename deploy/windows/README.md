# Windows → Oracle VM 工具脚本

Windows 没有自带 `rsync`，所以这里用系统自带的 **`tar.exe` + `scp` + `ssh`**（Win10 1803+ 内置）完成上传与备份。

> 前置检查：在 PowerShell 里执行 `tar --version`、`ssh -V`，都应输出正常。
> 若提示找不到命令：设置 → 应用 → 可选功能 → 添加「OpenSSH 客户端」。

---

## 0. 最省事：双击 `.bat`（IP 只需输入一次）

| 双击 | 作用 |
|---|---|
| **`deploy.bat`** | 首次部署：输入 VM 公网 IP → 上传 → 自动安装（建用户 / 写 .env / systemd / 防火墙） |
| **`update.bat`** | 只更新代码并重启（保留 VM 上的 `data/` 和 `.env`） |
| **`backup.bat`** | 把 VM 上的数据备份到本地 `backups\` |
| **`tunnel.bat`** | **不需要服务器**：把本机服务发布到公网（Cloudflare 快速隧道，免注册免信用卡，地址每次变） |
| **`tunnel-ngrok.bat`** | **零成本固定地址**：ngrok 免费档的固定 dev 域名（需邮箱注册，1 GB/月） |
| **`setup-domain.bat`** | 一次性：把服务绑定到你的域名（**地址固定**，需自己买域名） |
| **`tunnel-fixed.bat`** | 用固定域名启动（需先跑 `setup-domain.bat`） |

第一次运行会让你输入 VM 公网 IP，之后缓存到 `vm-host.txt`（该文件已 gitignore），后续双击不再询问。
要换机就删掉 `vm-host.txt` 重新运行，或直接用下面 PowerShell 脚本传 `-VmHost`。

> **VM 公网 IP 在哪看**：Oracle 控制台 → 计算 → 实例 → 点开实例 →「实例信息 → 公共 IP 地址」。
> 想固定 IP（避免停止/启动后变化）：资源 → 保留的公共 IP → 分配一个并关联到该实例。
> Ubuntu 镜像的 SSH 用户名是 `ubuntu`（Oracle Linux 是 `opc`）。

---

## 0.5 没有服务器？用 `tunnel.bat` 直接发到公网

**不需要信用卡、不需要注册、不需要买服务器** —— 只要这台电脑开着，同学就能访问。

双击 **`tunnel.bat`**，它会：

1. 自动准备 `cloudflared.exe`（优先 `winget`，其次用本机 Python 下载到 `bin\`，约 52 MB）
2. 本机启动服务（只监听 `127.0.0.1`，外网只能经隧道进来）
3. **默认开启账号体系**（`ZY_AUTH=1`）：公网地址谁都能打开，必须注册登录才看得到数据
4. 打印一个 `https://xxx.trycloudflare.com` 地址 —— 直接发给同学

实测输出示例：

```
INF Requesting new quick Tunnel on trycloudflare.com...
INF |  https://clearance-dat-continuously-offering.trycloudflare.com  |
INF Registered tunnel connection ... location=hkg11 protocol=quic
```

注意事项：

| 项 | 说明 |
|---|---|
| 电脑必须开着 | 关机/睡眠 → 同学打不开 |
| 地址每次会变 | 快速隧道是临时域名；绑自己域名可固定（`cloudflared tunnel login` + 命名隧道） |
| 无 SLA | Cloudflare 明确说明快速隧道不保证可用性，适合试用/小范围 |
| 数据 | 始终在你自己硬盘上，`data/db/` |
| 想匿名访问 | `tunnel.bat -NoAuth`（**不建议**，等于公开所有数据） |

命令行等价用法：

```powershell
.\tunnel.ps1                 # 默认：开账号体系
.\tunnel.ps1 -Port 9000      # 换端口
.\tunnel.ps1 -NoAuth         # 关闭登录（仅自己临时看时用）
.\tunnel.ps1 -NoServer       # 服务已在跑，只起隧道
```

> 想把地址固定下来：**双击 `setup-domain.bat`，输入你的域名**，四步全自动完成（见 0.6）。

---

## 0.6 绑定自己的域名（固定地址，仍然免费）

临时隧道每次重启地址都会变。绑自己的域名后就固定成 `https://study.你的域名.com`。

**前提**：域名已托管在 Cloudflare（NS 指向 Cloudflare，免费套餐即可）；
**不需要信用卡**，Cloudflare 免费账号足够。

```
1) 双击 setup-domain.bat → 输入 study.example.com
2) 脚本自动完成四步：
     ① cloudflared tunnel login          浏览器授权（弹窗里选你的域名）
     ② cloudflared tunnel create zhiyuan 创建命名隧道（已存在则复用）
     ③ 写 ~/.cloudflared/config.yml      域名 → 127.0.0.1:8765
     ④ cloudflared tunnel route dns      自动创建 CNAME
3) 以后启动：双击 tunnel-fixed.bat
```

脚本内部还会跑 `cloudflared tunnel ingress validate` 校验配置，不合法会当场报错并给出原因。

命令行等价：

```powershell
.\setup-domain.ps1 -Domain study.example.com          # 一次性绑定
.\tunnel-fixed.ps1                                   # 以后启动（固定地址）
.\tunnel-fixed.ps1 -NoAuth                           # 关闭登录（不建议）
.\tunnel-fixed.ps1 -NoServer                         # 服务已在跑，只跑隧道
```

**开机自启**（可选，配合固定域名更省事）：

```powershell
schtasks /Create /F /SC ONLOGON /TN "知源学伴固定域名" `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\path\to\zhiyuan-study\deploy\windows\tunnel-fixed.ps1\""
```

常见问题：

| 现象 | 原因 |
|---|---|
| 浏览器 502 | 本机服务没起来（先单独 `py -3 server.py` 看报错），或端口与 config.yml 不一致 |
| 1033 / 隧道未就绪 | 隧道进程没在跑，`tunnel-fixed.bat` 要一直开着 |
| DNS 记录已存在 | 手动去 Cloudflare DNS 删掉旧的同名 A/CNAME 再重跑 |
| 证书一直不签发 | 域名还没解析到 Cloudflare（NS 未生效），或该域名有过 CAA 限制 |

配置文件参考：[cloudflared/config.example.yml](cloudflared/config.example.yml)（已用 `cloudflared ... ingress validate` 校验通过）。

---

## 0.7 零成本固定地址：ngrok 免费档

不想买域名、又嫌 Cloudflare 快速隧道地址老变？**ngrok 免费档自带一个固定 dev 域名**
（形如 `xxx.ngrok-free.dev`，**重启也不变**），邮箱注册即可，不要信用卡。

```
1) 打开 https://dashboard.ngrok.com/signup 注册（邮箱即可）
2) 打开 https://dashboard.ngrok.com/get-started/your-authtoken 复制 token
3) 双击 tunnel-ngrok.bat → 粘贴 token（只需一次，存进本机 ngrok 配置）
4) 拿到固定地址后发给同学
```

免费档代价（[官方限制](https://ngrok.com/docs/pricing-limits/free-plan-limits)）：

| 限制 | 值 | 对本科的影响 |
|---|---|---|
| 浏览器首次访问 | 会弹 ngrok 警告页，点「Visit Site」才进 | ⚠️ 每台浏览器一次，能接受但不好看 |
| 流量 | 1 GB / 月 | 纯文字/JSON 够用；经常传图片会超 |
| 请求数 | 20,000 / 月 | 够一个班用 |
| 同时在线端点 | 3 个 | 单机部署无影响 |

> 只要地址好看的老师/同学看得舒服，还是建议花 20 块买个域名走 `setup-domain.bat`。
> ngrok 适合**先跑起来再说**的阶段。

命令行：

```powershell
.\tunnel-ngrok.ps1                        # 默认开账号体系
.\tunnel-ngrok.ps1 -Token 你的token        # 免交互
.\tunnel-ngrok.ps1 -Port 9000
```

脚本行为：ngrok.exe 缺失时自动装（winget → 官方 zip 下载解压到 `bin\`）；
起隧道后从 ngrok 本地状态 API（`127.0.0.1:4041`）取回公网地址并打印；
退出时自动停掉本机服务。

---

## 1. 上传代码到 VM

```powershell
cd C:\path\to\zhiyuan-study\deploy\windows

# 首次部署：上传 + 自动执行 install.sh（建用户/写 .env/systemd/放行防火墙）
.\upload-to-vm.ps1 -VmHost 123.45.67.89 -Install

# 日常更新：只覆盖代码并重启服务（保留 VM 上的 data/ 与 .env）
.\upload-to-vm.ps1 -VmHost 123.45.67.89

# 用私钥 + 非默认用户/端口
.\upload-to-vm.ps1 -VmHost vm.example.com -User ubuntu -Port 2222 -KeyFile C:\keys\oracle.key
```

脚本做的事：

1. 本地打包（排除 `.git`、`data/db`、`data/materials`、`_archive`、`config.json`、`.env`、`__pycache__`、`*.pyc`、`*.log`）
2. `scp` 上传到 `/tmp`
3. 远端解包到 `/opt/zhiyuan-study` 并修正属主
4. `-Install` 时执行 `deploy/oracle/install.sh`，否则仅 `systemctl restart zhiyuan-study`

> 如果 `scp` 报 `Connection timed out`：九成是 Oracle 的 **VCN 安全列表**没放行 22 端口，或实例的公网 IP 变了（保留 IP 未配置时重启会变）。

---

## 2. 备份 VM 数据到本机

```powershell
# 手动备份一次（自动存到项目下 backups\）
.\backup-from-vm.ps1 -VmHost 123.45.67.89

# 自定义保留天数与目录
.\backup-from-vm.ps1 -VmHost 123.45.67.89 -KeepDays 90 -OutDir D:\zy-backups
```

产出：`backups\zhiyuan-data-20261101-2300.tar.gz`，内含 `data/` 与 `config.json`。
超过 `-KeepDays`（默认 30 天）的旧包会被自动清理。

还原到 VM：

```bash
sudo tar -xzf zhiyuan-data-20261101-2300.tar.gz -C /opt/zhiyuan-study
sudo chown -R zhiyuan:zhiyuan /opt/zhiyuan-study
sudo systemctl restart zhiyuan-study
```

---

## 3. 每日自动备份（Windows 计划任务）

**必须用密钥登录**，否则计划任务会卡在密码提示上。先在 VM 上装好公钥：

```powershell
# 本机：没有密钥就先生成（一路回车即可）
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\oracle_zy

# 把公钥追加到 VM 的授权列表
$pub = Get-Content $env:USERPROFILE\.ssh\oracle_zy.pub
ssh ubuntu@123.45.67.89 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pub' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

# 验证免密登录
ssh -i $env:USERPROFILE\.ssh\oracle_zy ubuntu@123.45.67.89 'echo ok'
```

创建每天 23:00 的备份任务：

```powershell
schtasks /Create /F /SC DAILY /ST 23:00 /TN "知源学伴每日备份" `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\path\to\zhiyuan-study\deploy\windows\backup-from-vm.ps1\" -VmHost 123.45.67.89 -KeyFile C:\Users\<你>\.ssh\oracle_zy"
```

管理：

```powershell
schtasks /Query  /TN "知源学伴每日备份"     # 查看
schtasks /Run    /TN "知源学伴每日备份"     # 立即跑一次测试
schtasks /Delete /TN "知源学伴每日备份" /F  # 删除
```

> 计划任务默认只在用户登录时运行；要"开机不登录也跑"，在「任务计划程序」里把该任务改为
> 「不管用户是否登录都要运行」，并勾选「使用最高权限运行」。
