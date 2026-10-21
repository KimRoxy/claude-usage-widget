# 맥미니 + Tailscale로 해외(오키나와) eSIM에서 Claude 쓰기

## 왜 필요한가
여행용 eSIM(Airalo, 말톡 등) 상당수는 데이터를 **홍콩·싱가포르 등 다른 나라 게이트웨이**로 내보냅니다.
홍콩처럼 Anthropic 미지원 지역 IP로 잡히면 claude.ai / Claude Code / 이 위젯이
"지원하지 않는 지역" 오류를 냅니다.

해결: 한국 집에 있는 맥미니를 **Tailscale Exit Node**로 만들고, 오키나와에서는
모든 트래픽을 맥미니를 거쳐 내보내면 항상 **한국 집 IP**로 접속됩니다.

```
[오키나와 노트북/폰] --eSIM--> (암호화 WireGuard 터널) --> [한국 집 맥미니] --> claude.ai / api.anthropic.com
```

---

## 1. 맥미니 설정 (출국 전, 집에서)

### 방법 A — 스크립트 (권장, 로그인 없이 부팅만 돼도 동작)
```bash
git clone <이 저장소> && cd claude-usage-widget/tailscale
bash setup-macmini-exit-node.sh
```
스크립트가 하는 일:
1. Homebrew로 `tailscale` 설치, `tailscaled`를 시스템 서비스로 등록 (부팅 시 자동 시작)
2. IP 포워딩 켜기 + 재부팅 후에도 유지되는 LaunchDaemon 등록
3. 잠자기 끄기, 정전 후 자동 부팅(`pmset autorestart 1`), 네트워크로 깨우기
4. `tailscale up --advertise-exit-node --hostname=mac-mini` 실행 → 출력되는 URL로 로그인

### 방법 B — GUI 앱 (간단하지만 맥 사용자 로그인 상태여야 함)
1. https://tailscale.com/download/mac 에서 Standalone 버전 설치 후 로그인
2. 메뉴바 Tailscale 아이콘 → **Exit Node → Run as Exit Node**
3. 시스템 설정 → 에너지: "디스플레이가 꺼져도 자동으로 잠자기 방지" 켜기,
   "정전 후 자동으로 시작" 켜기
4. 시스템 설정 → 사용자 및 그룹 → 자동 로그인 설정 (FileVault가 켜져 있으면 불가 → 방법 A 사용)

> A와 B를 동시에 설치하면 충돌합니다. 하나만 쓰세요.

### 관리 콘솔에서 승인 (필수)
https://login.tailscale.com/admin/machines
- `mac-mini` → `...` → **Edit route settings** → **Use as exit node** 체크
- `mac-mini` → `...` → **Disable key expiry** (여행 중 인증 만료로 끊기는 것 방지)

### 공유기
- 포트포워딩 **필요 없음** (Tailscale이 NAT를 알아서 통과)
- 맥미니는 가능하면 **유선 랜** 연결

---

## 2. 노트북 / 폰 설정

같은 Tailscale 계정으로 로그인한 뒤:

| 기기 | 방법 |
|---|---|
| **Windows** | 트레이 아이콘 → Exit node → `mac-mini` 선택, "Allow local network access" 체크<br>또는 PowerShell: `.\use-exit-node-windows.ps1 on` |
| **Mac** | 메뉴바 → Exit Node → `mac-mini` |
| **iPhone / Android** | 앱 → Exit Node → `mac-mini` 선택 → VPN 켜기 |
| **CLI 공통** | `tailscale set --exit-node=mac-mini --exit-node-allow-lan-access=true` |

해제: `tailscale set --exit-node=`  (또는 `.\use-exit-node-windows.ps1 off`)

### 확인
```powershell
.\use-exit-node-windows.ps1 check
```
`국가: KR` 이고 `claude.ai 응답: 200`이면 성공. 이후 claude.ai, Claude Code, 이 위젯 모두
별도 설정 없이 맥미니를 경유합니다 (위젯 코드 수정 불필요).

---

## 3. 출국 전 체크리스트
- [ ] 집 밖(휴대폰 핫스팟 등)에서 Exit Node 켜고 `KR` 나오는지 테스트
- [ ] 관리 콘솔에서 맥미니 **key expiry 해제**
- [ ] 맥미니 잠자기 꺼짐 확인: `pmset -g | grep sleep` → `sleep 0`
- [ ] 맥미니 재부팅 후 로그인 없이도 `tailscale status`에 온라인으로 뜨는지 확인 (방법 A)
- [ ] 노트북·폰 모두 Tailscale 로그인 + Exit Node 선택 연습

## 4. 문제 해결
| 증상 | 원인 / 조치 |
|---|---|
| Exit node 목록에 mac-mini가 없음 | 관리 콘솔에서 "Use as exit node" 승인 안 됨 |
| 켜면 인터넷이 아예 안 됨 | 맥미니 IP 포워딩 확인: `sysctl net.inet.ip.forwarding` → `1`이어야 함 |
| 느림 | `tailscale status`에서 `relay "tok"` 표시 = eSIM이 UDP를 막아 도쿄 DERP 중계 사용. 정상 동작이며 Claude 사용엔 충분 |
| mac-mini가 offline | 집 정전/공유기 재부팅. `autorestart` 설정 + 공유기도 정전 후 자동 켜짐인지 확인. 가족에게 전원 버튼 부탁 |
| 여전히 지역 오류 | 브라우저 캐시/쿠키 삭제 후 재로그인, `check`로 KR 확인 |
