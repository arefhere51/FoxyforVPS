#!/usr/bin/env bash
set -Eeuo pipefail
TAG="v1.15.0-foxy-masque.2"
SRC="/usr/local/src/foxyforvps-sing-box"
if ! command -v go >/dev/null 2>&1; then
  echo "Go is required. Install golang-go (Go 1.21+); Go will download the module's pinned toolchain if needed." >&2
  exit 1
fi
install -d -m 0755 /usr/local/src
if [[ ! -d "$SRC/.git" ]]; then
  git clone --depth 1 --branch "$TAG" https://github.com/Vauth/sing-box.git "$SRC"
else
  git -C "$SRC" fetch --depth 1 origin "refs/tags/$TAG:refs/tags/$TAG"
  git -C "$SRC" checkout --detach "$TAG"
fi
git -C "$SRC" reset --hard "$TAG" >/dev/null
git -C "$SRC" clean -fd >/dev/null
python3 - "$SRC/cmd/sing-box/main.go" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = '''import "github.com/sagernet/sing-box/log"

func main() {
\tif err := mainCommand.Execute(); err != nil {
\t\tlog.Fatal(err)
\t}
}
'''
new = '''import (
\t"os"
\t"strings"
\t"time"

\t"github.com/sagernet/sing-box/log"
\ttransportHTTP "github.com/sagernet/sing-box/transport/http"
)

func installFoxyBearerWatcher() {
\tpath := os.Getenv("FOXY_TOKEN_FILE")
\tif path == "" {
\t\treturn
\t}
\tupdate := func() {
\t\tdata, err := os.ReadFile(path)
\t\tif err == nil {
\t\t\ttransportHTTP.SetDynamicBearerToken(strings.TrimSpace(string(data)))
\t\t}
\t}
\tupdate()
\tgo func() {
\t\tticker := time.NewTicker(2 * time.Second)
\t\tdefer ticker.Stop()
\t\tfor range ticker.C {
\t\t\tupdate()
\t\t}
\t}()
}

func main() {
\tinstallFoxyBearerWatcher()
\tif err := mainCommand.Execute(); err != nil {
\t\tlog.Fatal(err)
\t}
}
'''
if old not in s:
    raise SystemExit("Unexpected sing-box CLI entry point; refusing to patch an unknown source revision")
p.write_text(s.replace(old, new, 1))
PY
cd "$SRC"
GOTOOLCHAIN=auto GOMAXPROCS="${GOMAXPROCS:-2}" go build -tags with_utls -trimpath -o /usr/local/bin/foxy-sing-box ./cmd/sing-box
chmod 0755 /usr/local/bin/foxy-sing-box
/usr/local/bin/foxy-sing-box version
