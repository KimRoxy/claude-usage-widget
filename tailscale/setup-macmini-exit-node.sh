#!/bin/bash
# 맥미니를 Tailscale Exit Node(출구 노드)로 설정
# 해외(오키나와 등)에서 eSIM으로 접속해도 집 맥미니의 한국 IP로 Claude를 사용하기 위함
#
# 사용법:  bash setup-macmini-exit-node.sh
# 다시 실행해도 안전함 (이미 된 단계는 그대로 둠)
set -euo pipefail

HOSTNAME_TS="${HOSTNAME_TS:-mac-mini}"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "이 스크립트는 macOS(맥미니)에서 실행하세요." >&2
  exit 1
fi

echo "== 1. Homebrew 확인"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew가 없습니다. 먼저 설치하세요: https://brew.sh" >&2
  exit 1
fi

echo "== 2. Tailscale(데몬 버전) 설치"
# GUI 앱과 달리 로그인 전(부팅 직후)에도 동작하므로 서버 용도에 적합
if [[ -d "/Applications/Tailscale.app" ]]; then
  echo "!! /Applications/Tailscale.app (GUI 버전)이 이미 설치되어 있습니다."
  echo "   두 버전을 동시에 쓰면 충돌합니다. GUI 앱을 종료/삭제하거나,"
  echo "   GUI 앱 메뉴에서 'Exit Node > Run as Exit Node'를 쓰는 방법(README 참고)을 선택하세요."
  exit 1
fi
brew list tailscale >/dev/null 2>&1 || brew install tailscale

echo "== 3. tailscaled 를 시스템 서비스로 등록(부팅 시 자동 시작)"
sudo brew services start tailscale || sudo brew services restart tailscale
sleep 3

echo "== 4. IP 포워딩 활성화"
sudo sysctl -w net.inet.ip.forwarding=1
sudo sysctl -w net.inet6.ip6.forwarding=1
# 재부팅 후에도 유지되도록 LaunchDaemon 등록
PLIST=/Library/LaunchDaemons/com.local.ipforwarding.plist
sudo tee "$PLIST" >/dev/null <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.local.ipforwarding</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>/usr/sbin/sysctl -w net.inet.ip.forwarding=1 net.inet6.ip6.forwarding=1</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PL
sudo chown root:wheel "$PLIST"
sudo chmod 644 "$PLIST"
sudo launchctl bootout system "$PLIST" 2>/dev/null || true
sudo launchctl bootstrap system "$PLIST"

echo "== 5. 잠자기 방지 / 정전 후 자동 켜짐"
sudo pmset -a sleep 0 disksleep 0 displaysleep 10
sudo pmset -a womp 1          # 네트워크 접근 시 깨우기
sudo pmset -a autorestart 1   # 정전 후 전원 복구 시 자동 부팅
sudo pmset -a tcpkeepalive 1

echo "== 6. Tailscale 로그인 + Exit Node 광고"
echo "   (처음이면 브라우저 로그인 URL이 출력됩니다. 휴대폰/노트북과 같은 계정으로 로그인)"
sudo tailscale up --advertise-exit-node --hostname="$HOSTNAME_TS" --accept-dns=false

echo
echo "== 완료. 현재 상태:"
tailscale status | head -20
echo
echo "남은 작업 (관리 콘솔 https://login.tailscale.com/admin/machines):"
echo "  1) '$HOSTNAME_TS' 오른쪽 ... > Edit route settings > 'Use as exit node' 체크"
echo "  2) '$HOSTNAME_TS' 오른쪽 ... > Disable key expiry (180일 후 끊김 방지)"
