#!/usr/bin/env bash
# StudyBuddy 一键安装脚本（Ubuntu / Debian）
#
# 做什么：建用户 → 建目录 → venv → 装依赖 → 装 systemd → 启动 → 打印下一步
# 不做：nginx / 域名 / HTTPS（那三步要按你的域名来，见 README 部署章节）
#
# 用法（在项目根目录执行）：
#   sudo bash deploy/install.sh
# 可选：换安装目录
#   sudo APP_DIR=/srv/studybuddy bash deploy/install.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/studybuddy}"
APP_USER="${APP_USER:-studybuddy}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 sudo 运行"

say "1/7 检查 Python"
command -v python3 >/dev/null || die "没装 python3：apt install -y python3 python3-venv"
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
python3 - <<'PY' || die "Python 版本低于 3.10，请升级（本项目用了 X | None 语法）"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
echo "    python3 $PYV"

say "2/7 系统依赖"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3-venv python3-pip sqlite3 curl >/dev/null
fi

say "3/7 建用户与目录：$APP_DIR"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
# 只同步代码，别把本地的 .venv / data / 缓存带上去
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  command -v rsync >/dev/null && rsync -a --delete \
      --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
      --exclude '.git' --exclude '*.pyc' \
      "$SRC_DIR"/ "$APP_DIR"/ || cp -r "$SRC_DIR"/. "$APP_DIR"/
fi
mkdir -p "$APP_DIR/data"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

say "4/7 虚拟环境与依赖"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

say "5/7 .env（API Key 走环境变量）"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "    已生成 $APP_DIR/.env —— 记得编辑它填 DEEPSEEK_API_KEY"
else
  echo "    已存在，跳过"
fi

say "6/7 systemd 服务"
cp "$APP_DIR/deploy/studybuddy.service" /etc/systemd/system/studybuddy.service
# 允许自定义目录
sed -i "s#/opt/studybuddy#$APP_DIR#g" /etc/systemd/system/studybuddy.service
systemctl daemon-reload
systemctl enable --now studybuddy

say "7/7 自检"
sleep 3
if curl -fsS --max-time 5 http://127.0.0.1:8787/api/health >/dev/null; then
  echo "    ✅ 服务已在 127.0.0.1:8787 跑起来"
else
  echo "    ❌ 没起来，看日志：journalctl -u studybuddy -n 50 --no-pager"
fi

cat <<EOF

下一步（手动）：
  1) 填 Key：      sudo -u $APP_USER nano $APP_DIR/.env   → DEEPSEEK_API_KEY=...
                   sudo systemctl restart studybuddy
  2) 反代 + HTTPS：sudo cp $APP_DIR/deploy/nginx-studybuddy.conf /etc/nginx/sites-available/studybuddy
                   sudo nano /etc/nginx/sites-available/studybuddy   # 改 server_name
                   sudo ln -s /etc/nginx/sites-available/studybuddy /etc/nginx/sites-enabled/
                   sudo nginx -t && sudo systemctl reload nginx
                   sudo certbot --nginx -d 你的域名
  3) 防火墙：      sudo ufw allow 80,443/tcp   （8787 不要对外开放）
EOF
