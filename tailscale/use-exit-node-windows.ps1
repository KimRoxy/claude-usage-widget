# Windows 노트북에서 맥미니 Exit Node 켜기/끄기/확인
# 사용법 (PowerShell):
#   .\use-exit-node-windows.ps1 on      # 맥미니 경유 시작
#   .\use-exit-node-windows.ps1 off     # 해제 (현지 회선 직접 사용)
#   .\use-exit-node-windows.ps1 check   # 현재 IP 국가 / Claude 접속 확인
param(
    [ValidateSet("on", "off", "check")]
    [string]$Mode = "check",
    [string]$ExitNode = "mac-mini"
)

$ts = "C:\Program Files\Tailscale\tailscale.exe"
if (-not (Test-Path $ts)) { $ts = "tailscale" }

function Show-Check {
    try {
        $info = Invoke-RestMethod -Uri "https://ipinfo.io/json" -TimeoutSec 10
        Write-Host ("현재 공인 IP: {0}  국가: {1}  ({2})" -f $info.ip, $info.country, $info.org)
        if ($info.country -ne "KR") { Write-Host "!! 한국 IP가 아닙니다. Exit Node가 꺼져 있을 수 있습니다." -ForegroundColor Yellow }
    } catch { Write-Host "IP 확인 실패: $_" -ForegroundColor Red }
    try {
        $r = Invoke-WebRequest -Uri "https://claude.ai" -UseBasicParsing -TimeoutSec 15
        Write-Host ("claude.ai 응답: {0}" -f $r.StatusCode) -ForegroundColor Green
    } catch { Write-Host "claude.ai 접속 실패: $($_.Exception.Message)" -ForegroundColor Red }
}

switch ($Mode) {
    "on" {
        & $ts set --exit-node=$ExitNode --exit-node-allow-lan-access=true
        Start-Sleep -Seconds 2
        Show-Check
    }
    "off" {
        & $ts set --exit-node=
        Write-Host "Exit Node 해제됨"
    }
    "check" {
        & $ts status
        Show-Check
    }
}
