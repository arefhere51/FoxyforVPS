#!/usr/bin/env bash
set -Eeuo pipefail
REPO="arefhere51/FoxyforVPS"
BRANCH="main"
APP_DIR="/opt/FoxyforVPS"
ETC_DIR="/etc/foxyforvps"
STATE_DIR="/var/lib/foxyforvps"
TMP_DIR=""

need_root(){ [[ "$(id -u)" -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }; }
cleanup(){ [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]] && rm -rf "$TMP_DIR" || true; }
trap cleanup EXIT

fetch_source(){
  TMP_DIR="$(mktemp -d /tmp/foxyforvps.XXXXXX)"
  echo "Downloading $REPO ($BRANCH)…"
  curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o "$TMP_DIR/source.tar.gz"
  tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR"
  SOURCE_DIR="$TMP_DIR/FoxyforVPS-${BRANCH}"
  [[ -d "$SOURCE_DIR" ]] || { echo "Repository archive has an unexpected layout." >&2; exit 1; }
}

install_or_update(){
  need_root
  fetch_source
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl git python3 python3-venv python3-pip build-essential golang-go openssl util-linux
  install -d -m 0700 "$ETC_DIR" "$STATE_DIR"
  local new_admin_password=0
  if [[ ! -s "$ETC_DIR/admin-password" ]]; then
    umask 077
    openssl rand -hex 20 > "$ETC_DIR/admin-password"
    chmod 0600 "$ETC_DIR/admin-password"
    new_admin_password=1
  fi
  systemctl stop foxyforvps-web.service foxyforvps-core.service 2>/dev/null || true
  install -d -m 0755 "$APP_DIR"
  cp -a "$SOURCE_DIR/." "$APP_DIR/"
  python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r "$APP_DIR/requirements.txt"
  if ! id -u foxyvpsbrowser >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/foxyforvps-browser --create-home --shell /usr/sbin/nologin foxyvpsbrowser
    touch "$ETC_DIR/.created-browser-user"
    chmod 0600 "$ETC_DIR/.created-browser-user"
  fi
  install -d -o foxyvpsbrowser -g foxyvpsbrowser -m 0700 /var/lib/foxyforvps-browser
  install -d -o root -g root -m 0755 /opt/foxyforvps-browsers
  if ! PLAYWRIGHT_BROWSERS_PATH=/opt/foxyforvps-browsers "$APP_DIR/.venv/bin/python" -c 'from playwright.sync_api import sync_playwright; import os; p=sync_playwright().start(); ok=os.path.isfile(p.chromium.executable_path) and os.access(p.chromium.executable_path, os.X_OK); p.stop(); raise SystemExit(0 if ok else 1)' >/dev/null 2>&1; then
    PLAYWRIGHT_BROWSERS_PATH=/opt/foxyforvps-browsers "$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
    chmod -R a+rX /opt/foxyforvps-browsers
  fi
  install -m 0644 "$APP_DIR/systemd/foxyforvps-web.service" /etc/systemd/system/foxyforvps-web.service
  install -m 0644 "$APP_DIR/systemd/foxyforvps-core.service" /etc/systemd/system/foxyforvps-core.service
  install -m 0755 "$APP_DIR/manager.sh" /usr/local/bin/foxyforvpsctl
  if [[ ! -x /usr/local/bin/foxy-sing-box || "${FORCE_BUILD_CORE:-0}" == "1" ]]; then
    bash "$APP_DIR/build-core.sh"
  fi
  systemctl daemon-reload
  systemctl enable foxyforvps-web.service
  systemctl restart foxyforvps-web.service
  echo
  echo "FoxyforVPS installed/updated."
  echo "Admin user: admin"
  if [[ "$new_admin_password" == "1" ]]; then
    echo "Admin password (save it now): $(cat "$ETC_DIR/admin-password")"
  else
    echo "Existing admin password was kept; it was not printed again."
  fi
  echo "Private backend: VPS 127.0.0.1:8778. SSH tunnel: ssh -L 8777:127.0.0.1:8778 USER@VPS"
  echo "Local panel URL: http://127.0.0.1:8777"
  echo "For public access, configure a DNS hostname first, then run: sudo foxyforvpsctl public enable your.domain"
  echo "The public endpoint uses HTTPS on TCP 8777; raw HTTP is never enabled."
}

install_caddy(){
  if systemctl is-active --quiet caddy.service; then
    echo "A Caddy service is already active; refusing to replace or reconfigure it." >&2
    echo "Configure its existing Caddyfile manually to reverse_proxy 127.0.0.1:8778 on your TLS hostname." >&2
    return 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https
  install -d -m 0755 /usr/share/keyrings
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  # Mask the package's generic service during installation; FoxyforVPS uses its own isolated Caddy unit/config.
  systemctl mask caddy.service 2>/dev/null || true
  apt-get install -y caddy
  systemctl disable --now caddy.service 2>/dev/null || true
  systemctl unmask caddy.service 2>/dev/null || true
}

public_enable(){
  need_root
  local domain="${1:-}"
  if [[ -z "$domain" ]]; then read -r -p "Public DNS hostname pointing to this VPS (e.g. vpn.example.com): " domain </dev/tty; fi
  domain="${domain,,}"
  if [[ ! "$domain" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; then
    echo "Invalid hostname. Use a DNS name, not an IP address or URL." >&2; return 2
  fi
  if [[ ! -s "$ETC_DIR/admin-password" ]]; then
    echo "Install FoxyforVPS first so the admin password and backend exist." >&2; return 1
  fi
  if systemctl is-active --quiet nginx.service || systemctl is-active --quiet apache2.service; then
    echo "Nginx/Apache is active. Refusing to modify services or compete for public ports." >&2; return 1
  fi
  if ss -ltnH 2>/dev/null | awk '$4 ~ /:(80|443|8777)$/ {found=1} END {exit !found}'; then
    echo "One of TCP ports 80, 443, or 8777 is already in use. Stop/configure that service first; no service was changed." >&2
    return 1
  fi
  install_caddy
  install -d -m 0750 "$ETC_DIR" "$STATE_DIR/caddy-data" "$STATE_DIR/caddy-config"
  printf '%s\n' "$domain" > "$ETC_DIR/public-domain"
  chmod 0600 "$ETC_DIR/public-domain"
  cat > "$ETC_DIR/Caddyfile" <<EOF
{
  admin off
}

${domain}:8777 {
  reverse_proxy 127.0.0.1:8778
}
EOF
  chmod 0640 "$ETC_DIR/Caddyfile"
  cat > /etc/systemd/system/foxyforvps-public.service <<EOF
[Unit]
Description=FoxyforVPS public HTTPS reverse proxy
After=network-online.target foxyforvps-web.service
Wants=network-online.target
Requires=foxyforvps-web.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$STATE_DIR
Environment=XDG_DATA_HOME=$STATE_DIR/caddy-data
Environment=XDG_CONFIG_HOME=$STATE_DIR/caddy-config
ExecStart=/usr/bin/caddy run --config $ETC_DIR/Caddyfile --adapter caddyfile
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$STATE_DIR/caddy-data $STATE_DIR/caddy-config

[Install]
WantedBy=multi-user.target
EOF
  /usr/bin/caddy validate --config "$ETC_DIR/Caddyfile" --adapter caddyfile
  systemctl daemon-reload
  systemctl enable --now foxyforvps-public.service
  echo
  echo "Public HTTPS panel configured: https://${domain}:8777"
  echo "Ensure DNS A/AAAA points to this VPS and allow inbound TCP 80, 443, and 8777 for automatic certificate challenges and HTTPS."
  echo "Keep the admin password private. Do not add a plaintext port-forward for 8777."
}

public_disable(){
  need_root
  systemctl disable --now foxyforvps-public.service 2>/dev/null || true
  rm -f /etc/systemd/system/foxyforvps-public.service "$ETC_DIR/Caddyfile" "$ETC_DIR/public-domain"
  rm -rf "$STATE_DIR/caddy-data" "$STATE_DIR/caddy-config"
  systemctl daemon-reload
  echo "FoxyforVPS public listener stopped and removed. The app backend remains on VPS loopback:8778."
}

remove_app(){
  need_root
  echo "This removes the application, Firefox OAuth credentials, proxy settings and bearer token."
  read -r -p "Type REMOVE to continue: " answer </dev/tty
  [[ "$answer" == "REMOVE" ]] || { echo "Cancelled."; return; }
  local remove_browser_user=0
  [[ -f "$ETC_DIR/.created-browser-user" ]] && remove_browser_user=1
  systemctl disable --now foxyforvps-public.service foxyforvps-web.service foxyforvps-core.service 2>/dev/null || true
  rm -f /etc/systemd/system/foxyforvps-public.service /etc/systemd/system/foxyforvps-web.service /etc/systemd/system/foxyforvps-core.service /usr/local/bin/foxyforvpsctl /usr/local/bin/foxy-sing-box "$ETC_DIR/Caddyfile" "$ETC_DIR/public-domain"
  rm -rf "$APP_DIR" "$ETC_DIR" "$STATE_DIR" /var/lib/foxyforvps-browser /opt/foxyforvps-browsers /usr/local/src/foxyforvps-sing-box
  if [[ "$remove_browser_user" == "1" ]]; then
    userdel foxyvpsbrowser 2>/dev/null || true
    groupdel foxyvpsbrowser 2>/dev/null || true
  fi
  systemctl daemon-reload
  echo "FoxyforVPS and its local account tokens have been removed. The Caddy package (if installed) is left in place."
}

show_status(){
  systemctl --no-pager --full status foxyforvps-web.service || true
  echo
  systemctl --no-pager --full status foxyforvps-core.service || true
  echo
  systemctl --no-pager --full status foxyforvps-public.service || true
}

menu(){
  need_root
  while true; do
    echo
    echo "FoxyforVPS manager"
    echo "1) Install"
    echo "2) Update from GitHub"
    echo "3) Remove completely"
    echo "4) Show service status"
    echo "5) Show recent logs"
    echo "6) Enable public HTTPS panel (domain required)"
    echo "7) Disable public panel"
    echo "0) Exit"
    read -r -p "Choose: " choice </dev/tty
    case "$choice" in
      1) install_or_update ;;
      2) install_or_update ;;
      3) remove_app ;;
      4) show_status ;;
      5) journalctl -u foxyforvps-web -u foxyforvps-core -u foxyforvps-public -n 100 --no-pager || true ;;
      6) public_enable ;;
      7) public_disable ;;
      0) exit 0 ;;
      *) echo "Invalid choice." ;;
    esac
  done
}

case "${1:-menu}" in
  install|update) install_or_update ;;
  remove|uninstall) remove_app ;;
  status) show_status ;;
  public)
    need_root
    action="${2:-}"
    case "$action" in
      enable) public_enable "${3:-}" ;;
      disable) public_disable ;;
      *) echo "Usage: $0 public {enable <hostname>|disable}" >&2; exit 2 ;;
    esac
    ;;
  menu) menu ;;
  *) echo "Usage: $0 {install|update|remove|status|public enable <hostname>|public disable|menu}" >&2; exit 2 ;;
esac
