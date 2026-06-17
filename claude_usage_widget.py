"""
Claude Code 토큰 사용량 위젯 v3
- Anthropic OAuth Usage API 직접 조회 → 정확한 % + 재설정 시각
- 월간 추가 지출 바 (Max 플랜)
- 자동 갱신 주기 설정 (수동/5분/10분/30분/1시간)
- 오늘/이번세션/전체 상세 탭 (JSONL 파싱, 접기/펼치기 기본 접힘)
"""

import json
import pathlib
import threading
import urllib.request
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import customtkinter as ctk
import tkinter as tk

# ── 상수 ─────────────────────────────────────────────────────────────────────
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_5m": 3.75,  "cache_1h": 6.00,  "cache_read": 0.30},
    "claude-opus-4-8":   {"input": 5.00, "output": 25.00, "cache_5m": 6.25,  "cache_1h": 10.00, "cache_read": 0.50},
    "claude-opus-4-7":   {"input": 5.00, "output": 25.00, "cache_5m": 6.25,  "cache_1h": 10.00, "cache_read": 0.50},
    "claude-opus-4-6":   {"input": 5.00, "output": 25.00, "cache_5m": 6.25,  "cache_1h": 10.00, "cache_read": 0.50},
    "claude-haiku-4-5":  {"input": 1.00, "output": 5.00,  "cache_5m": 1.25,  "cache_1h": 2.00,  "cache_read": 0.10},
    "claude-fable-5":    {"input": 10.00,"output": 50.00, "cache_5m": 12.50, "cache_1h": 20.00, "cache_read": 1.00},
}
DEFAULT_PRICING = PRICING["claude-sonnet-4-6"]

PROJECTS_ROOT = pathlib.Path.home() / ".claude" / "projects"
CREDS_FILE    = pathlib.Path.home() / ".claude" / ".credentials.json"
SETTINGS_FILE = pathlib.Path.home() / ".claude" / "usage_widget_settings.json"
API_URL       = "https://api.anthropic.com/api/oauth/usage"
WINDOW_SECS   = 5 * 3600

REFRESH_INTERVALS = {
    "수동":  0,
    "5분":   5  * 60 * 1_000,
    "10분":  10 * 60 * 1_000,
    "30분":  30 * 60 * 1_000,
    "1시간": 60 * 60 * 1_000,
}
DEFAULT_INTERVAL = "30분"

H_COMPACT  = 455
H_EXPANDED = 668

C = {
    "bg":     "#1e1e2e", "surface": "#313244", "border": "#45475a",
    "text":   "#cdd6f4", "sub":     "#a6adc8",
    "green":  "#a6e3a1", "blue":    "#89b4fa",
    "yellow": "#f9e2af", "red":     "#f38ba8",
    "mauve":  "#cba6f7", "teal":    "#94e2d5",
    "peach":  "#fab387", "pink":    "#f5c2e7",
}

# ── 설정 파일 ─────────────────────────────────────────────────────────────────

def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_settings(d):
    SETTINGS_FILE.write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 유틸 ─────────────────────────────────────────────────────────────────────

def fmt_tokens(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(n)

def fmt_cost(c):
    return f"${c:.3f}" if c >= 1.0 else f"${c:.4f}"

def fmt_duration(secs):
    secs = max(0, int(secs))
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    if h:  return f"{h}시간 {m:02d}분"
    if m:  return f"{m}분 {s:02d}초"
    return f"{s}초"

def _bar_color(pct):
    if pct < 60: return C["green"]
    if pct < 85: return C["yellow"]
    return C["red"]


# ── Anthropic OAuth Usage API ─────────────────────────────────────────────────

def fetch_api_usage():
    token = json.loads(CREDS_FILE.read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"]
    req = urllib.request.Request(
        API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# ── JSONL 집계 (상세 탭 전용) ─────────────────────────────────────────────────

def _empty():
    return {"input": 0, "output": 0, "cache_5m": 0, "cache_1h": 0,
            "cache_read": 0, "cost": 0.0, "turns": 0}

def _add(stats, usage, model):
    p   = PRICING.get(model, DEFAULT_PRICING)
    cc  = usage.get("cache_creation", {})
    c5m = cc.get("ephemeral_5m_input_tokens", 0)
    c1h = cc.get("ephemeral_1h_input_tokens", 0)
    if c5m == 0 and c1h == 0:
        c1h = usage.get("cache_creation_input_tokens", 0)
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    crd = usage.get("cache_read_input_tokens", 0)
    stats["input"]      += inp;  stats["output"]     += out
    stats["cache_5m"]   += c5m;  stats["cache_1h"]   += c1h
    stats["cache_read"] += crd;  stats["turns"]      += 1
    stats["cost"] += (inp*p["input"] + out*p["output"] +
                      c5m*p["cache_5m"] + c1h*p["cache_1h"] +
                      crd*p["cache_read"]) / 1_000_000

def load_detail_stats():
    now        = datetime.now(timezone.utc)
    today_d    = now.date()
    win_cutoff = now - timedelta(seconds=WINDOW_SECS)

    total = _empty(); today_s = _empty(); session = _empty(); window_s = _empty()
    model_breakdown = defaultdict(lambda: _empty())

    latest_file = None; latest_mtime = 0.0
    for proj in PROJECTS_ROOT.iterdir():
        if not proj.is_dir(): continue
        for jf in proj.glob("*.jsonl"):
            m = jf.stat().st_mtime
            if m > latest_mtime: latest_mtime = m; latest_file = jf

    for proj in PROJECTS_ROOT.iterdir():
        if not proj.is_dir(): continue
        for jf in proj.glob("*.jsonl"):
            is_cur = (jf == latest_file)
            try:
                with open(jf, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line: continue
                        try: r = json.loads(line)
                        except: continue
                        if r.get("type") != "assistant": continue
                        msg = r.get("message", {}); usage = msg.get("usage")
                        if not usage: continue
                        model = msg.get("model", "claude-sonnet-4-6")
                        _add(total, usage, model)
                        _add(model_breakdown[model], usage, model)
                        ts_dt = None
                        try:
                            ts_dt = datetime.fromisoformat(
                                r.get("timestamp", "").replace("Z", "+00:00"))
                        except: pass
                        if ts_dt and ts_dt.date() == today_d: _add(today_s, usage, model)
                        if is_cur: _add(session, usage, model)
                        if ts_dt and ts_dt >= win_cutoff: _add(window_s, usage, model)
            except (OSError, PermissionError): continue

    return total, today_s, session, window_s, dict(model_breakdown), latest_mtime


# ── 설정 다이얼로그 ───────────────────────────────────────────────────────────

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, current_interval, on_change):
        super().__init__(master)
        self.title("설정")
        self.geometry("310x120")
        self.resizable(False, False)
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self._on_change = on_change

        ctk.CTkLabel(self, text="자동 갱신 주기",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["sub"]).pack(anchor="w", padx=14, pady=(14, 6))

        self._seg = ctk.CTkSegmentedButton(
            self,
            values=list(REFRESH_INTERVALS.keys()),
            command=self._changed,
            font=ctk.CTkFont(size=11),
            fg_color=C["surface"],
            selected_color=C["mauve"],
            selected_hover_color="#9a86d4",
            unselected_color=C["border"],
            unselected_hover_color=C["surface"],
            text_color=C["text"],
            text_color_disabled=C["sub"],
        )
        self._seg.set(current_interval)
        self._seg.pack(fill="x", padx=12, pady=(0, 14))

    def _changed(self, choice):
        self._on_change(choice)


# ── 메인 위젯 ─────────────────────────────────────────────────────────────────

class ClaudeUsageWidget(ctk.CTkToplevel):
    TIMER_MS = 1_000

    def __init__(self, master):
        super().__init__(master)
        self.title("Claude 토큰 사용량")
        self.geometry(f"340x{H_COMPACT}")
        self.resizable(False, False)
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)

        # 설정 로드
        cfg = load_settings()
        key = cfg.get("refresh_interval", DEFAULT_INTERVAL)
        if key not in REFRESH_INTERVALS:
            key = DEFAULT_INTERVAL
        self._interval_key = key
        self._refresh_ms   = REFRESH_INTERVALS[key]

        self._pin              = True
        self._refresh_id       = None
        self._timer_id         = None
        self._session_reset_at = None
        self._weekly_reset_at  = None
        self._detail_collapsed = True
        self._settings_win     = None

        self._build_ui()
        self._refresh()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # 헤더
        hdr = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        hdr.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(hdr, text="⬥  Claude 토큰 사용량",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["mauve"]).pack(side="left", padx=10, pady=6)
        # 핀
        self._pin_btn = ctk.CTkButton(
            hdr, text="📌", width=28, height=28, font=ctk.CTkFont(size=11),
            fg_color="transparent", hover_color=C["border"], command=self._toggle_pin)
        self._pin_btn.pack(side="right", padx=2, pady=4)
        # 설정
        ctk.CTkButton(
            hdr, text="⚙", width=28, height=28, font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=C["border"],
            command=self._open_settings).pack(side="right", padx=2, pady=4)
        # API 연결 상태 점
        self._api_dot = ctk.CTkLabel(hdr, text="●", font=ctk.CTkFont(size=14),
                                      text_color=C["border"])
        self._api_dot.pack(side="right", padx=(2, 4), pady=6)

        # 현재 세션 (5시간 롤링)
        self._make_limit_section(label="⚡  현재 세션  (5시간 롤링)",
                                  label_color=C["teal"], prefix="_sess")
        # 주간 한도
        self._make_limit_section(label="📅  주간 한도",
                                  label_color=C["peach"], prefix="_week")

        # 월간 추가 지출
        self._spend_frame = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        self._spend_frame.pack(fill="x", padx=8, pady=4)

        sp_top = ctk.CTkFrame(self._spend_frame, fg_color="transparent")
        sp_top.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(sp_top, text="💳  월간 추가 지출",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["pink"]).pack(side="left")
        self._spend_pct_lbl = ctk.CTkLabel(sp_top, text="—",
                                            font=ctk.CTkFont(size=11, weight="bold"),
                                            text_color=C["green"])
        self._spend_pct_lbl.pack(side="right")

        self._spend_canvas = tk.Canvas(self._spend_frame, height=8,
                                        bg=C["border"], highlightthickness=0, bd=0)
        self._spend_canvas.pack(fill="x", padx=10, pady=3)
        self._spend_rect = self._spend_canvas.create_rectangle(0, 0, 0, 8,
                                                                fill=C["green"], outline="")
        self._spend_amt_lbl = ctk.CTkLabel(self._spend_frame, text="",
                                            font=ctk.CTkFont(size=10), text_color=C["sub"])
        self._spend_amt_lbl.pack(anchor="center", pady=(0, 8))

        # 상세 내역 토글 헤더
        detail_hdr = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        detail_hdr.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(detail_hdr, text="상세 내역",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["sub"]).pack(side="left", padx=12, pady=6)
        self._detail_toggle_btn = ctk.CTkButton(
            detail_hdr, text="▶  펼치기", width=80, height=24,
            font=ctk.CTkFont(size=10), fg_color="transparent",
            hover_color=C["border"], text_color=C["sub"],
            command=self._toggle_detail)
        self._detail_toggle_btn.pack(side="right", padx=8, pady=4)

        # 탭 (기본: 숨김)
        self._tabs = ctk.CTkTabview(
            self, width=324, height=200,
            fg_color=C["surface"],
            segmented_button_fg_color=C["border"],
            segmented_button_selected_color=C["mauve"],
            segmented_button_selected_hover_color=C["mauve"],
            segmented_button_unselected_color=C["surface"],
            border_width=0)
        for name in ("오늘", "이번 세션", "전체"):
            self._tabs.add(name)
            tab = self._tabs.tab(name)
            tab.configure(fg_color=C["surface"])
            sf = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                         scrollbar_button_color=C["border"])
            sf.pack(fill="both", expand=True, padx=2, pady=2)
            tab._sf = sf

        # 푸터
        self._footer = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        self._footer.pack(fill="x", padx=8, pady=(4, 8))
        self._status_lbl = ctk.CTkLabel(self._footer, text="로딩 중...",
                                         font=ctk.CTkFont(size=10), text_color=C["sub"])
        self._status_lbl.pack(side="left", padx=10, pady=5)
        ctk.CTkButton(self._footer, text="↻", width=32, height=24,
                      font=ctk.CTkFont(size=14), fg_color="transparent",
                      hover_color=C["border"], command=self._refresh).pack(side="right", padx=4, pady=4)

    def _make_limit_section(self, label, label_color, prefix):
        frm = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        frm.pack(fill="x", padx=8, pady=4)

        top = ctk.CTkFrame(frm, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(top, text=label, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=label_color).pack(side="left")
        pct_lbl = ctk.CTkLabel(top, text="—",
                                font=ctk.CTkFont(size=11, weight="bold"),
                                text_color=C["green"])
        pct_lbl.pack(side="right")
        setattr(self, f"{prefix}_pct_lbl", pct_lbl)

        canvas = tk.Canvas(frm, height=8, bg=C["border"], highlightthickness=0, bd=0)
        canvas.pack(fill="x", padx=10, pady=3)
        rect = canvas.create_rectangle(0, 0, 0, 8, fill=C["green"], outline="")
        setattr(self, f"{prefix}_canvas", canvas)
        setattr(self, f"{prefix}_rect", rect)

        tok_lbl = ctk.CTkLabel(frm, text="", font=ctk.CTkFont(size=10),
                                text_color=C["sub"])
        tok_lbl.pack(anchor="center", pady=(0, 1))
        setattr(self, f"{prefix}_tok_lbl", tok_lbl)

        timer_row = ctk.CTkFrame(frm, fg_color="transparent")
        timer_row.pack(fill="x", padx=10, pady=(1, 8))
        ctk.CTkLabel(timer_row, text="⏱", font=ctk.CTkFont(size=10),
                     text_color=C["yellow"]).pack(side="left")
        timer_lbl = ctk.CTkLabel(timer_row, text="연결 중...",
                                  font=ctk.CTkFont(size=10), text_color=C["yellow"])
        timer_lbl.pack(side="left", padx=4)
        setattr(self, f"{prefix}_timer_lbl", timer_lbl)
        reset_at_lbl = ctk.CTkLabel(timer_row, text="",
                                     font=ctk.CTkFont(size=10), text_color=C["sub"])
        reset_at_lbl.pack(side="right")
        setattr(self, f"{prefix}_reset_at_lbl", reset_at_lbl)

    # ── 설정 다이얼로그 ───────────────────────────────────────────────────────

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus(); return
        self._settings_win = SettingsDialog(
            self, self._interval_key, self._set_interval)

    def _set_interval(self, choice):
        self._interval_key = choice
        self._refresh_ms   = REFRESH_INTERVALS[choice]
        save_settings({"refresh_interval": choice})
        # 기존 예약 취소 후 새 주기로 재설정
        if self._refresh_id:
            self.after_cancel(self._refresh_id)
            self._refresh_id = None
        if self._refresh_ms > 0:
            self._refresh_id = self.after(self._refresh_ms, self._refresh)
        self._update_status_text()

    def _update_status_text(self, prefix=""):
        interval_txt = f"  ·  {self._interval_key} 자동" if self._refresh_ms > 0 else "  ·  수동"
        self._status_lbl.configure(text=f"{prefix}{interval_txt}")

    # ── 상세 탭 접기/펼치기 ───────────────────────────────────────────────────

    def _toggle_detail(self):
        if self._detail_collapsed:
            self._footer.pack_forget()
            self._tabs.pack(fill="both", expand=True, padx=8, pady=4)
            self._footer.pack(fill="x", padx=8, pady=(4, 8))
            self._detail_toggle_btn.configure(text="▲  접기")
            self._detail_collapsed = False
            self.geometry(f"340x{H_EXPANDED}")
        else:
            self._tabs.pack_forget()
            self._detail_toggle_btn.configure(text="▶  펼치기")
            self._detail_collapsed = True
            self.geometry(f"340x{H_COMPACT}")

    # ── 데이터 갱신 ──────────────────────────────────────────────────────────

    def _refresh(self):
        if self._refresh_id:
            self.after_cancel(self._refresh_id); self._refresh_id = None
        self._status_lbl.configure(text="갱신 중...")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        api_data = None; detail_data = None; api_err = None
        try:
            api_data = fetch_api_usage()
        except Exception as e:
            api_err = str(e)[:60]
        try:
            detail_data = load_detail_stats()
        except Exception:
            pass
        self.after(0, lambda: self._update(api_data, detail_data, api_err))

    def _update(self, api_data, detail_data, api_err):
        interval_txt = f"  ·  {self._interval_key} 자동" if self._refresh_ms > 0 else "  ·  수동"

        if api_data:
            self._api_dot.configure(text_color=C["green"])

            # 현재 세션 (5시간 롤링)
            fh = api_data.get("five_hour") or {}
            self._session_reset_at = self._parse_dt(fh.get("resets_at"))
            self._draw_bar("_sess", float(fh.get("utilization", 0)))

            # 주간 한도
            sd = api_data.get("seven_day") or {}
            self._weekly_reset_at = self._parse_dt(sd.get("resets_at"))
            self._draw_bar("_week", float(sd.get("utilization", 0)))

            # 월간 추가 지출
            spend = api_data.get("spend") or {}
            if spend.get("enabled"):
                exp   = spend.get("used", {}).get("exponent", 2)
                div   = 10 ** exp
                used  = spend.get("used", {}).get("amount_minor", 0) / div
                limit = spend.get("limit", {}).get("amount_minor", 1) / div
                spct  = float(spend.get("percent", 0))
                color = _bar_color(spct)
                self._spend_pct_lbl.configure(text=f"{spct:.0f}% 사용됨", text_color=color)
                self._spend_amt_lbl.configure(text=f"${used:.2f} / ${limit:.2f}  이번 달")
                self.update_idletasks()
                w = self._spend_canvas.winfo_width() or 296
                fill_w = max(4 if spct > 0 else 0, int(w * spct / 100))
                self._spend_canvas.coords(self._spend_rect, 0, 0, fill_w, 8)
                self._spend_canvas.itemconfig(self._spend_rect, fill=color)
            else:
                self._spend_pct_lbl.configure(text="N/A", text_color=C["sub"])
                self._spend_amt_lbl.configure(text="추가 사용량 플랜 없음")

            self._start_timer()
            ts = datetime.now().strftime("%H:%M:%S")
            self._status_lbl.configure(
                text=f"API ●  {ts}{interval_txt}")
        else:
            self._api_dot.configure(text_color=C["red"])
            for prefix in ("_sess", "_week"):
                getattr(self, f"{prefix}_pct_lbl").configure(
                    text="연결 안됨", text_color=C["red"])
                getattr(self, f"{prefix}_timer_lbl").configure(
                    text="API 연결 실패", text_color=C["red"])
                getattr(self, f"{prefix}_reset_at_lbl").configure(text="")
            self._status_lbl.configure(
                text=f"오류: {api_err}{interval_txt}")

        # JSONL 상세 탭
        if detail_data:
            total, today_s, session, window_s, breakdown, _ = detail_data
            out = window_s["output"]
            self._sess_tok_lbl.configure(
                text=f"{fmt_tokens(out)} 출력 토큰 (5시간)" if out else "")
            for name, stats in [("오늘", today_s), ("이번 세션", session), ("전체", total)]:
                sf = self._tabs.tab(name)._sf
                for w in sf.winfo_children(): w.destroy()
                self._render_stats(sf, stats, name == "전체",
                                   breakdown if name == "전체" else None)

        # 다음 자동 갱신 예약 (수동이면 건너뜀)
        if self._refresh_ms > 0:
            self._refresh_id = self.after(self._refresh_ms, self._refresh)

    @staticmethod
    def _parse_dt(s):
        if not s: return None
        try: return datetime.fromisoformat(s)
        except: return None

    def _draw_bar(self, prefix, pct):
        color  = _bar_color(pct)
        canvas = getattr(self, f"{prefix}_canvas")
        rect   = getattr(self, f"{prefix}_rect")
        getattr(self, f"{prefix}_pct_lbl").configure(
            text=f"{pct:.0f}% 사용됨", text_color=color)
        self.update_idletasks()
        w = canvas.winfo_width() or 296
        fill_w = max(4 if pct > 0 else 0, int(w * pct / 100))
        canvas.coords(rect, 0, 0, fill_w, 8)
        canvas.itemconfig(rect, fill=color)

    # ── 카운트다운 타이머 ─────────────────────────────────────────────────────

    def _start_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id); self._timer_id = None
        self._tick()

    def _tick(self):
        now = datetime.now(timezone.utc)
        self._update_timer("_sess", self._session_reset_at, now)
        self._update_timer("_week", self._weekly_reset_at, now)
        self._timer_id = self.after(self.TIMER_MS, self._tick)

    def _update_timer(self, prefix, reset_at, now):
        if reset_at is None: return
        remaining    = (reset_at - now).total_seconds()
        timer_lbl    = getattr(self, f"{prefix}_timer_lbl")
        reset_at_lbl = getattr(self, f"{prefix}_reset_at_lbl")
        if remaining > 0:
            color = C["yellow"] if remaining > 1800 else C["red"]
            timer_lbl.configure(text=f"{fmt_duration(remaining)} 후 재설정",
                                 text_color=color)
            reset_at_lbl.configure(
                text=reset_at.astimezone().strftime("%H:%M 재설정"))
        else:
            timer_lbl.configure(text="재설정됨  (갱신 대기)", text_color=C["sub"])
            reset_at_lbl.configure(text="")

    # ── 상세 탭 렌더링 ────────────────────────────────────────────────────────

    def _render_stats(self, parent, stats, show_breakdown, breakdown):
        rows = [
            ("입력",          stats["input"],     C["blue"]),
            ("출력",          stats["output"],    C["green"]),
            ("캐시 쓰기 5분",  stats["cache_5m"],  C["yellow"]),
            ("캐시 쓰기 1h",   stats["cache_1h"],  C["yellow"]),
            ("캐시 읽기",     stats["cache_read"], C["sub"]),
        ]
        for label, val, color in rows:
            if val == 0: continue
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=4, pady=1)
            r.columnconfigure(0, weight=1); r.columnconfigure(1, weight=0)
            ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=11),
                         text_color=C["sub"]).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(r, text=fmt_tokens(val),
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=color).grid(row=0, column=1, sticky="e")

        ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(fill="x", pady=4)
        cr = ctk.CTkFrame(parent, fg_color="transparent")
        cr.pack(fill="x", padx=4, pady=2)
        cr.columnconfigure(0, weight=1); cr.columnconfigure(1, weight=0)
        ctk.CTkLabel(cr, text="총 비용",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(cr, text=fmt_cost(stats["cost"]),
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["mauve"]).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(parent, text=f"총 {stats['turns']:,} 턴",
                     font=ctk.CTkFont(size=10), text_color=C["sub"]).pack(
                         anchor="e", padx=4)

        if show_breakdown and breakdown:
            ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(fill="x", pady=(6, 2))
            ctk.CTkLabel(parent, text="모델별 비용",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["sub"]).pack(anchor="w", padx=4, pady=(2, 0))
            for model, s in sorted(breakdown.items(), key=lambda x: -x[1]["cost"]):
                if s["cost"] < 0.0001: continue
                row = ctk.CTkFrame(parent, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=1)
                row.columnconfigure(0, weight=1); row.columnconfigure(1, weight=0)
                ctk.CTkLabel(row, text=model.replace("claude-", "").replace("-", " "),
                             font=ctk.CTkFont(size=10),
                             text_color=C["sub"]).grid(row=0, column=0, sticky="w")
                ctk.CTkLabel(row, text=fmt_cost(s["cost"]),
                             font=ctk.CTkFont(size=10),
                             text_color=C["text"]).grid(row=0, column=1, sticky="e")

    # ── 핀 ────────────────────────────────────────────────────────────────────

    def _toggle_pin(self):
        self._pin = not self._pin
        self.attributes("-topmost", self._pin)
        self._pin_btn.configure(text_color=C["mauve"] if self._pin else C["sub"])


# ── 진입점 ───────────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()

    widget = ClaudeUsageWidget(root)
    widget.protocol("WM_DELETE_WINDOW", root.destroy)

    widget.update_idletasks()
    sw = widget.winfo_screenwidth()
    sh = widget.winfo_screenheight()
    widget.geometry(
        f"+{sw - widget.winfo_width() - 20}+{max(40, (sh - H_COMPACT) // 2)}")

    root.mainloop()


if __name__ == "__main__":
    main()
