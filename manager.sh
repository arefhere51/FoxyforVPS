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
  apt-get install -y ca-certificates curl git python3 python3-venv python3-pip build-essential golang-go openssl
  install -d -m 0700 "$ETC_DIR" "$STATE_DIR"
  if [[ ! -s "$ETC_DIR/admin-password" ]]; then
    umask 077
    openssl rand -hex 20 > "$ETC_DIR/admin-password"
    chmod 0600 "$ETC_DIR/admin-password"
  fi
  systemctl stop foxyforvps-web.service foxyforvps-core.service 2>/dev/null || true
  install -d -m 0755 "$APP_DIR"
  cp -a "$SOURCE_DIR/." "$APP_DIR/"
  python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r "$APP_DIR/requirements.txt"
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
  echo "Admin password (save it now): $(cat "$ETC_DIR/admin-password")"
  echo "Panel is private on VPS localhost:8777. Use: ssh -L 8777:127.0.0.1:8777 USER@VPS"
  echo "Then open http://127.0.0.1:8777 and enter the admin password when prompted."
  echo "Do not expose port 8777 to the public Internet."
}

remove_app(){
  need_root
  echo "This removes the application, Firefox OAuth credentials, proxy settings and bearer token."
  read -r -p "Type REMOVE to continue: " answer </dev/tty
  [[ "$answer" == "REMOVE" ]] || { echo "Cancelled."; return; }
  systemctl disable --now foxyforvps-web.service foxyforvps-core.service 2>/dev/null || true
  rm -f /etc/systemd/system/foxyforvps-web.service /etc/systemd/system/foxyforvps-core.service /usr/local/bin/foxyforvpsctl /usr/local/bin/foxy-sing-box
  rm -rf "$APP_DIR" "$ETC_DIR" "$STATE_DIR" /usr/local/src/foxyforvps-sing-box
  systemctl daemon-reload
  echo "FoxyforVPS and its local account tokens have been removed."
}

show_status(){
  systemctl --no-pager --full status foxyforvps-web.service || true
  echo
  systemctl --no-pager --full status foxyforvps-core.service || true
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
    echo "0) Exit"
    read -r -p "Choose: " choice </dev/tty
    case "$choice" in
      1) install_or_update ;;
      2) install_or_update ;;
      3) remove_app ;;
      4) show_status ;;
      5) journalctl -u foxyforvps-web -u foxyforvps-core -n 100 --no-pager || true ;;
      0) exit 0 ;;
      *) echo "Invalid choice." ;;
    esac
  done
}

case "${1:-menu}" in
  install|update) install_or_update ;;
  remove|uninstall) remove_app ;;
  status) show_status ;;
  menu) menu ;;
  *) echo "Usage: $0 {install|update|remove|status|menu}" >&2; exit 2 ;;
esac
