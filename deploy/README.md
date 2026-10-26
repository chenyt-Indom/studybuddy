# StudyBuddy 手动部署手册（Linux 服务器）

目标：把本机跑通的 StudyBuddy 放到一台公网 Linux 服务器上，通过域名访问，重启不丢。

> 环境假设：Ubuntu 22.04 / Debian 12、有 sudo、Python ≥ 3.10。
> 用的是 SQLite + 单进程 uvicorn，**个人 / 小团队够用**，不需要 Docker 和数据库服务。

---

## 0. 动手前先确认三件事

| 要确认 | 怎么查 | 为什么 |
|---|---|---|
| 公网 IP | 云控制台 | 后面配域名解析用 |
| 系统版本 | `cat /etc/os-release` | Ubuntu 20.04 自带 Python 3.8，**不够**（代码用了 `X \| None` 语法） |
| 能不能连上 | `ssh 用户名@IP` | 若 22 端口被封：用云控制台的「网页终端 / VNC 登录」，或用你改过的 SSH 端口 |

```bash
python3 -V     # 必须 ≥ 3.10；3.8/3.9 会在导入时就报 TypeError
```

---

## 1. 把代码放到服务器

仓库是**公开**的（`private=false`），所以服务器上直接 clone 最省事，不需要配 SSH key：

```bash
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/chenyt-Indom/studybuddy.git
```

如果服务器访问 GitHub 慢/不通，改成本地打包再传（在 Windows 的 Git Bash 里执行）：

```bash
# 本地：只打包代码，别把 .venv 和 data 打进去
tar --exclude=.venv --exclude=data --exclude=__pycache__ --exclude=.git \
    -czf studybuddy.tgz studybuddy

# 传到服务器（把 2222 换成你实际能连的端口）
scp -P 2222 studybuddy.tgz 用户名@服务器IP:/tmp/

# 服务器上
sudo apt install -y tar && sudo tar xzf /tmp/studybuddy.tgz -C /opt
```

---

## 2. 建用户、装 Python 依赖

```bash
sudo adduser --system --group --home /opt/studybuddy studybuddy
sudo chown -R studybuddy:studybuddy /opt/studybuddy

sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 curl
```

**Ubuntu 20.04 需要额外装 3.11**（自带 3.8 跑不起来）：

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update && sudo apt install -y python3.11 python3.11-venv
# 后面所有 python3 换成 python3.11
```

---

## 3. 虚拟环境 + 装依赖

```bash
cd /opt/studybuddy
sudo -u studybuddy python3 -m venv .venv
sudo -u studybuddy .venv/bin/pip install -U pip
sudo -u studybuddy .venv/bin/pip install -r requirements.txt
```

依赖只有 7 个（fastapi / uvicorn / sqlalchemy / httpx / PyJWT / python-multipart / pypdf），
几十秒装完，不需要编译。

---

## 4. 配 API Key（Linux 上**千万别**用网页里保存）

原因：`secrets_store.py` 的加密是 **Windows DPAPI**，Linux 上没有 → 会退化成
「base64 明文 + chmod 600」，页面会显示 `⚠️ 加密存储不可用`。

所以走环境变量：

```bash
sudo -u studybuddy cp .env.example .env
sudo -u studybuddy nano .env            # 填 DEEPSEEK_API_KEY=sk-xxxx
sudo chmod 600 .env
sudo chown studybuddy:studybuddy .env
```

`.env` 内容至少这两行：

```ini
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_MODEL=deepseek-flash
```

`data/` 里不要从 Windows 搬 `secrets.bin` —— DPAPI 密文换机器解不开，搬过去也是空。

---

## 5. 前台跑一次（这步别跳，排错最快）

```bash
cd /opt/studybuddy
sudo -u studybuddy bash -c 'set -a; . ./.env; set +a; .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8787'
```

另开一个终端验证：

```bash
curl -s http://127.0.0.1:8787/api/health        # {"ok":true,...}
curl -s "http://127.0.0.1:8787/api/kp/overview?stage=senior" | head -c 200
```

首次启动会自动建表并写入 **140 个知识点 + 24 条跨科联动**（几秒），不需要额外 seed。
`Ctrl+C` 停掉，进入下一步。

---

## 6. 交给 systemd（开机自启 + 崩溃自动拉起）

```bash
sudo cp deploy/studybuddy.service /etc/systemd/system/studybuddy.service
sudo systemctl daemon-reload
sudo systemctl enable --now studybuddy

systemctl status studybuddy --no-pager      # 应该是 active (running)
journalctl -u studybuddy -n 40 --no-pager   # 有报错看这里
```

说明：`deploy/studybuddy.service` 里固定 `--workers 1`，**别改**：
SQLite 单文件多进程写会互锁；每晚自动整理是 lifespan 里的 asyncio 任务，多 worker 会跑好几份。

---

## 7. Nginx 反代 + HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

sudo cp deploy/nginx-studybuddy.conf /etc/nginx/sites-available/studybuddy
sudo nano /etc/nginx/sites-available/studybuddy      # 把 study.example.com 改成你的域名
sudo ln -s /etc/nginx/sites-available/studybuddy /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d study.你的域名.com           # 一键签证书并改 443
```

配置里两个值**不能省**：

| 配置 | 不改的后果 |
|---|---|
| `client_max_body_size 12m` | 上传题目图片（8MB 上限）直接 **413**，nginx 默认只给 1MB |
| `proxy_buffering off` | 流式对话被缓冲，思维链和正文「憋到最后一次性吐出来」，看起来像卡死 |

---

## 8. 防火墙（两层，很容易漏一层）

```bash
# 服务器本机
sudo ufw allow 80,443/tcp
sudo ufw allow 22/tcp        # 你的 SSH 端口
sudo ufw reload && sudo ufw status
```

**云厂商控制台还有一层防火墙**（腾讯云轻量：控制台 → 防火墙），
要在那里也放行 80/443 —— 只改 ufw 不改控制台，外网照样打不开。

8787 全程只监听 `127.0.0.1`，**不要**对外开放。

---

## 9. 验收清单

| 项目 | 怎么验 | 期望 |
|---|---|---|
| 健康检查 | `curl 域名/api/health` | `{"ok":true,...}` |
| 首页 | 浏览器打开域名 | 登录页，左下角有 `v0.1 · 数字` |
| 登录 | demo/demo123456 或自己注册 | 进入学科对话 |
| 流式 | 问一句，观察是否逐字出 | 逐字出，且「深度思考」块可展开 |
| 图片 | 传一张题目截图 | 气泡里显示图片（不是裂图） |
| 知识点 | 打开「📖 知识点」 | 140 条、可按年级/科目筛选 |
| 教材同步 | 设置页填 IMA 令牌 → 测试连接 | 列出 IMA 工具清单 |
| 重启自启 | `sudo reboot` 后等 1 分钟再访问 | 直接可用，无需手动启动 |

---

## 10. 更新代码

```bash
cd /opt/studybuddy
sudo -u studybuddy git pull
sudo systemctl restart studybuddy
```

前端资源带了 `?v=<文件修改时间>`，**不用清浏览器缓存**，刷新就是新的。

---

## 11. 备份（这三样丢了就真丢了）

| 路径 | 内容 |
|---|---|
| `data/app.db` | 账号、对话、成绩、错题、复习进度、知识点掌握度 |
| `data/uploads/` | 上传的题目图片 |
| `data/textbooks/` | 你导入的教材（**不要**提交到 git，版权问题） |
| `.env` | API Key |

```bash
# 热备份 SQLite（不要直接 cp，可能拷到写一半的文件）
sudo -u studybuddy sqlite3 /opt/studybuddy/data/app.db \
  ".backup '/opt/studybuddy/data/backup-$(date +%F).db'"

# 打包 data 与 .env
sudo tar czf /var/backups/studybuddy-$(date +%F).tgz \
  -C /opt/studybuddy data .env
```

想自动备份就加一条 crontab：`0 4 * * * /usr/local/bin/studybuddy-backup.sh`。

---

## 12. 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| 启动报 `TypeError: unsupported operand type(s) for \|` | Python < 3.10 | 装 3.11，重建 venv |
| 页面能开但没法登录/请求 502 | 服务没起或崩溃 | `journalctl -u studybuddy -n 50` |
| 上传图片 413 | nginx 默认 1MB | `client_max_body_size 12m` |
| 回答「一次性」出现，没有打字效果 | nginx 缓冲 SSE | `proxy_buffering off` + `proxy_read_timeout 300s` |
| 外网打不开但本机 curl 正常 | 云控制台防火墙没放行 | 控制台 → 防火墙 → 加 80/443 |
| 设置里填了 Key 但仍走离线模式 | `.env` 没被 systemd 读到 | `systemctl show studybuddy -p EnvironmentFiles`，或 `sudo systemctl restart` |
| 换了机器 Key 失效 | DPAPI 与 Windows 用户绑定 | Linux 用 `.env`，别搬 `secrets.bin` |
| 多人用同一个账号串数据 | 项目是「一人一库」设计 | 各自注册；SQLite 也能撑几十人，但**并发写**会锁 |

---

## 附：一键安装脚本

`deploy/install.sh` 把第 2～6 步串起来了（**不含** nginx 与证书，那两步取决于你的域名）：

```bash
cd /opt/studybuddy
sudo bash deploy/install.sh

# 换安装目录
sudo APP_DIR=/srv/studybuddy bash deploy/install.sh
```

脚本做的事：查 Python 版本 → 建用户/目录 → venv + 装依赖 → 生成 `.env`（600 权限）
→ 装 systemd 并启动 → `curl` 自检 → 打印后续手动步骤。
