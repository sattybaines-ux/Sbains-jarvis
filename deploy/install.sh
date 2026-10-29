#!/usr/bin/env bash
# Sets up (or updates) Jarvis on an Ubuntu 24.04 server. Safe to run again.
# Usage: sudo DOMAIN=satty-jarvis.duckdns.org DUCKDNS_TOKEN=... bash deploy/install.sh
set -euo pipefail
: "${DOMAIN:?DOMAIN is required, e.g. satty-jarvis.duckdns.org}"
APP=/opt/jarvis/app
DATA=/var/lib/jarvis

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https netfilter-persistent >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

echo "== firewall (Oracle's Ubuntu image only allows SSH by default)"
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "== swap (helps voice transcription on small servers)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== user and folders"
id jarvis >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/jarvis --shell /usr/sbin/nologin jarvis
mkdir -p "$DATA"
ln -sfn "$DATA" "$APP/out"   # state (tokens, latest brief, push subscriptions) survives updates
chown -R jarvis:jarvis /opt/jarvis "$DATA"
chmod 700 "$DATA"
[ -f /etc/jarvis.env ] && chown root:jarvis /etc/jarvis.env && chmod 640 /etc/jarvis.env

echo "== python packages"
sudo -u jarvis python3 -m venv /opt/jarvis/venv
sudo -u jarvis /opt/jarvis/venv/bin/pip install -q --upgrade pip
sudo -u jarvis /opt/jarvis/venv/bin/pip install -q -r "$APP/requirements.txt" -r "$APP/server/requirements.txt"

# Small servers (Google's free e2-micro has 1 GB) get the lighter, faster speech model.
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
WHISPER=$([ "$mem_mb" -lt 3000 ] && echo tiny.en || echo base.en)

echo "== service"
cat > /etc/systemd/system/jarvis.service <<UNIT
[Unit]
Description=Jarvis assistant
After=network-online.target
Wants=network-online.target

[Service]
User=jarvis
WorkingDirectory=$APP
EnvironmentFile=/etc/jarvis.env
Environment=HOME=/opt/jarvis
Environment=WHISPER_MODEL=$WHISPER
ExecStart=/opt/jarvis/venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DATA /opt/jarvis /tmp

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
  encode gzip
  reverse_proxy 127.0.0.1:8000 {
    flush_interval -1
  }
}
CADDY

if [ -n "${DUCKDNS_TOKEN:-}" ]; then
  echo "== keep the DuckDNS address pointed at this server"
  sub="${DOMAIN%%.duckdns.org}"
  echo "*/10 * * * * root curl -fsS 'https://www.duckdns.org/update?domains=$sub&token=$DUCKDNS_TOKEN&ip=' >/dev/null" > /etc/cron.d/duckdns
  chmod 600 /etc/cron.d/duckdns
  curl -fsS "https://www.duckdns.org/update?domains=$sub&token=$DUCKDNS_TOKEN&ip=" >/dev/null || true
fi

systemctl daemon-reload
systemctl enable --now jarvis >/dev/null
systemctl restart jarvis
systemctl reload caddy || systemctl restart caddy

echo "== checking"
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health && echo " Jarvis is running at https://$DOMAIN"
