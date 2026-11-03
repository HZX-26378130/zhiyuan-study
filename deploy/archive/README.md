# 每日自动归档（应对免费容器平台的临时磁盘）

Hugging Face Spaces、Koyeb、Render 这类免费容器平台有两个硬限制，凑在一起很致命：

1. **磁盘是临时的** —— 重新部署、休眠唤醒、平台迁移，`data/db` 全部清空
2. **没有可用的 cron** —— HF Spaces 根本没有定时任务；Render 的 Cron Job 要付费；Koyeb 也没有

所以本项目内置了一套**进程内定时归档**：定时器跑在应用线程里（不依赖平台 cron），
到点就把 `data/db` 打成 zip，**主动推送到仓库外**（GitHub 私有仓库 / 任意 webhook）。

---

## 一、能力与边界

| 项 | 说明 |
|---|---|
| 触发时机 | 启动后 **60 秒** 跑第一次，之后每 `ZY_ARCHIVE_INTERVAL_HOURS`（默认 24）小时一次 |
| 为什么启动就跑 | 免费容器空闲会被冻结/重启，进程重启后立刻补一份，比"等满 24 小时"更安全 |
| 归档内容 | `data/db/**`（档案、错题、积分、讲义、图片、账号） |
| **不归档** | `config.json`（含 API Key）、`data/vocab` 等静态资源、`.env` |
| 保留策略 | 远端与本地各保留 `ZY_ARCHIVE_KEEP` 份（默认 7），按文件名时间裁剪 |
| 失败处理 | 只打日志、`ok=False`，不会影响正常请求 |

---

## 二、配置

全部用**环境变量**（`.env` 或平台 Secrets）：

| 变量 | 必填 | 说明 |
|---|---|---|
| `ZY_ARCHIVE_GITHUB_REPO` | 二选一 | `owner/repo`，建议用一个**私有**备份仓库 |
| `ZY_ARCHIVE_GITHUB_TOKEN` | 二选一 | 细粒度 PAT，只需 **Contents: Read and write** |
| `ZY_ARCHIVE_GITHUB_BRANCH` | 否 | 默认 `main` |
| `ZY_ARCHIVE_GITHUB_DIR` | 否 | 默认 `backups` |
| `ZY_ARCHIVE_WEBHOOK` | 二选一 | 把 zip 原样 `POST` 到这里（自建接收端 / 对象存储网关） |
| `ZY_ARCHIVE_INTERVAL_HOURS` | 否 | 默认 `24`；设 `0` 关闭定时器（仍可手动触发） |
| `ZY_ARCHIVE_KEEP` | 否 | 默认 `7` |
| `ZY_ARCHIVE_LOCAL` | 否 | 默认 `1`，同时留本地副本（容器里意义有限，但便于手动下载） |

> GitHub 与 webhook **可以同时配**，互为备份。

### 建备份仓库 + 拿 Token

1. 新建一个**私有**仓库，例如 `zhiyuan-backups`（空仓库即可，不要勾 README）
2. <https://github.com/settings/tokens?type=beta> → Fine-grained token →
   **Repository access** 选 `Only select repositories` → 选 `zhiyuan-backups` →
   **Permissions → Repository permissions → Contents: Read and write**
3. 复制 token，填进环境变量

---

## 三、各平台怎么设

### Hugging Face Spaces（Docker）

Space → **Settings → Variables and secrets** → 逐个添加（Token 用 *secret*）：

```
ZY_ARCHIVE_GITHUB_REPO   = 你的账号/zhiyuan-backups
ZY_ARCHIVE_GITHUB_TOKEN  = github_pat_xxx      （Secret）
ZY_AUTH                  = 1
ZY_HOST                  = 0.0.0.0
```

> HF Spaces 强制 7860 端口：`PORT=7860`，并让 Space 的 `app_port` 一致。

### Render

Service → **Environment** → Add Environment Variable（Token 选 *Secret*）。
注意免费 Web Service 15 分钟无流量会休眠，**醒来后 60 秒内会补跑一次归档**。

### Koyeb

Service → **Settings → Environment variables**，同样把 Token 设为 secret。

### 自建 VM / 本地

写进 `/opt/zhiyuan-study/.env`（`install.sh` 生成的）或项目根的 `.env`，重启服务即可。

---

## 四、验证

```bash
# 看状态（enabled / 间隔 / 目标 / 上次结果）
curl -s http://127.0.0.1:8765/api/archive/status

# 立刻跑一次（不用等定时器）
curl -s -X POST http://127.0.0.1:8765/api/archive/run
```

成功的返回形如：

```json
{"ok": true, "name": "data-20261101-2330.zip", "bytes": 313501,
 "detail": "GitHub 已上传，清理旧包 1 个；本地已保留（.../data/db/archive）"}
```

备份仓库里会看到：

```
backups/data-20261101-2330.zip
backups/data-20261031-2330.zip
...
```

日志里能看到 `[archive] OK ...` 或 `[archive] FAIL ...`（`journalctl -u zhiyuan-study -f`）。

---

## 五、还原

```bash
# 1) 从备份仓库下载某个 zip（网页下载，或 curl -L 带 token）
# 2) 传到服务器后解包
sudo tar -xzf zhiyuan-data-20261101-2330.tar.gz -C /opt/zhiyuan-study   # VM 上的 tar 包
#   容器平台没有 SSH，则：临时把 zip 内容解到 data/db 再重新部署
unzip data-20261101-2330.zip -d /tmp/restore
sudo cp -a /tmp/restore/zhiyuan-backup/. /opt/zhiyuan-study/data/db/
sudo chown -R zhiyuan:zhiyuan /opt/zhiyuan-study/data
sudo systemctl restart zhiyuan-study
```

> zip 内路径前缀是 `zhiyuan-backup/`，对应 `data/db/` 的内容。

---

## 六、定期演练

归档最容易在"需要它的时候"才发现失效。建议每月做一次：

1. 挑最新一份 zip 下载
2. 在本地按上面的还原步骤解到 `data/db`
3. `py -3 server.py` 起本地服务，确认能登录、能看到错题/积分
4. 确认无误后把本地 `data/db` 恢复成你自己的数据

自动化测试：`py -3 scripts/test_archive.py`（用本地桩服务器模拟 GitHub API，覆盖推送、裁剪、鉴权失败、webhook）。

---

## 七、其他可选目标

- **对象存储（Cloudflare R2 / B2 / S3）**：`ZY_ARCHIVE_WEBHOOK` 指向一个自建转发端点即可，
  不需要改本项目代码；R2 免费 10 GB，B2 免费 10 GB
- **不想要外部依赖**：只配 `ZY_ARCHIVE_LOCAL=1`，让归档留在 `data/db/archive`，
  再配合网页「⚙ 接入设置 → ⬇ 备份数据」手动下载 —— 但容器磁盘清空时同样会丢，**不推荐**
