import ctypes
from ctypes import wintypes
import math
import os
from queue import SimpleQueue
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
import wave

import pyaudiowpatch as pyaudio
import sv_ttk

BASE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
FFMPEG = BASE / "ffmpeg.exe"
OUTPUT = Path.home() / "ShortMaker" / "output" if getattr(sys, "frozen", False) else BASE / "output"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
user32 = ctypes.windll.user32
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except AttributeError:
    user32.SetProcessDPIAware()


def monitors():
    result = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD), ("device", wintypes.WCHAR * 32)]

    def collect(handle, dc, rect, data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.monitor
            result.append((info.device, r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.flags & 1)))
        return True

    handler = callback(collect)
    if not user32.EnumDisplayMonitors(None, None, handler, 0):
        raise ctypes.WinError()
    return result


def audio_devices():
    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    text = proc.stderr.decode("utf-8", errors="replace")
    return re.findall(r'"([^\"]+)"\s*\(audio\)', text)


def loopback_devices():
    # 스피커·헤드폰 등 출력 장치 이름 목록 (기본 출력 장치가 맨 앞)
    try:
        audio = pyaudio.PyAudio()
    except Exception:
        return []
    try:
        names = [d["name"].removesuffix(" [Loopback]") for d in audio.get_loopback_device_info_generator()]
        try:
            default = audio.get_default_wasapi_loopback()["name"].removesuffix(" [Loopback]")
        except Exception:
            default = None
        return sorted(names, key=lambda name: name != default)
    except Exception:
        return []
    finally:
        audio.terminate()


def video_start_time(log_text):
    match = re.search(r"Input #0, gdigrab.*?start: ([\d.]+)", log_text, re.S)
    return float(match.group(1)) if match else None


def audio_offset_filter(offset):
    # 오디오가 늦게 시작했으면 앞을 무음으로 밀고, 먼저 시작했으면 앞부분을 잘라 영상과 맞춘다
    if offset >= 0:
        return f"adelay={round(offset * 1000)}:all=1,apad"
    return f"atrim=start={-offset:.3f},asetpts=PTS-STARTPTS,apad"


class LoopbackRecorder:
    # 출력 장치로 나가는 소리를 WASAPI 루프백으로 WAV 파일에 녹음한다
    def __init__(self, name, path):
        self.audio = pyaudio.PyAudio()
        self.streams = []
        self.file = None
        self.started = None
        try:
            wasapi = self.audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
            devices = [self.audio.get_device_info_by_index(i) for i in range(self.audio.get_device_count())]
            source = next((d for d in devices if d.get("isLoopbackDevice") and d["name"] == name + " [Loopback]"), None)
            render = next((d for d in devices if d["hostApi"] == wasapi and not d.get("isLoopbackDevice") and d["name"] == name and d["maxOutputChannels"] > 0), None)
            if not source:
                raise RuntimeError(f"출력 장치를 찾을 수 없습니다: {name}")
            self.rate = int(source["defaultSampleRate"])
            channels = source["maxInputChannels"]
            self.file = wave.open(str(path), "wb")
            self.file.setnchannels(channels)
            self.file.setsampwidth(2)
            self.file.setframerate(self.rate)
            if render:
                # 소리가 없을 때 루프백 데이터가 끊기지 않도록 같은 장치에 무음을 계속 재생한다
                out_channels = render["maxOutputChannels"]
                self.streams.append(self.audio.open(format=pyaudio.paInt16, channels=out_channels, rate=int(render["defaultSampleRate"]), output=True, output_device_index=render["index"], stream_callback=lambda data, count, info, status: (bytes(count * out_channels * 2), pyaudio.paContinue)))
            self.streams.append(self.audio.open(format=pyaudio.paInt16, channels=channels, rate=self.rate, input=True, input_device_index=source["index"], frames_per_buffer=1024, stream_callback=self.capture))
        except Exception:
            self.stop()
            raise

    def capture(self, data, count, info, status):
        if self.started is None:
            self.started = time.time() - count / self.rate
        self.file.writeframes(data)
        return None, pyaudio.paContinue

    def stop(self):
        for stream in self.streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self.streams = []
        if self.audio:
            self.audio.terminate()
            self.audio = None
        if self.file:
            self.file.close()
            self.file = None


def selection_rect(start, end, width, height, vertical):
    x1, y1 = start
    x2 = max(0, min(width, end[0]))
    y2 = max(0, min(height, end[1]))
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    if vertical:
        dx = min(dx, int(dy * 9 / 16))
        dy = int(dx * 16 / 9)
    dx -= dx % 2
    dy -= dy % 2
    left = x1 if x2 >= x1 else x1 - dx
    top = y1 if y2 >= y1 else y1 - dy
    return left, top, dx, dy


def region_summary(monitor, region, confirmed):
    # 메인 창에 보여 줄 최종 녹화 범위 한 줄 요약
    if not monitor:
        return "모니터를 선택하세요"
    if region:
        text = f"지정 영역 · {region[2]}×{region[3]}"
    else:
        text = f"전체 모니터 · {monitor[3]}×{monitor[4]}"
    return f"✔ 확인됨 · {text}" if confirmed else f"● 미확인 · {text}"


def panel_y(top, height, screen_height, panel_height, margin=24):
    # 안내 패널이 녹화 범위를 가리지 않도록 위·아래 중 넓은 빈 곳의 가운데에 둔다
    above, below = top, screen_height - (top + height)
    if max(above, below) >= panel_height + margin * 2:
        return top // 2 if above > below else top + height + below // 2
    return top + height // 2


def crop_positions(points, width, height):
    crop_width = min(width, int(height * 9 / 16) // 2 * 2)
    current = max(0, (width - crop_width) / 2)
    previous = 0.0
    result = []
    for timestamp, x in points:
        target = max(0, min(width - crop_width, x - crop_width / 2))
        current += (target - current) * (1 - math.exp(-max(0, timestamp - previous) / 0.35))
        result.append((timestamp, round(current)))
        previous = timestamp
    return crop_width, result


class App:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.busy = False
        self.points = []
        self.results = SimpleQueue()
        self.monitor_list = []
        self.selected_region = None
        self.selection_window = None
        self.identification = None
        self.indicator = None
        self.recorder = None
        self.audio_sources = [None]
        root.title("Shorts Maker Pro")
        root.geometry("620x710")
        root.minsize(580, 690)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme()
        frame = ttk.Frame(root, padding=(28, 24))
        frame.pack(fill="both", expand=True)

        # 헤더: 앱 이름과 한 줄 설명
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="●", style="Logo.TLabel").pack(side="left", padx=(0, 10))
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text="Shorts Maker Pro", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="화면을 녹화해 9:16 세로 쇼츠 영상으로 바로 변환합니다.", style="Hint.TLabel").pack(anchor="w")

        # 1. 화면 카드: 모니터와 녹화 영역
        screen = self.card(frame, "화면")
        ttk.Label(screen, text="녹화할 모니터", style="Field.TLabel").pack(anchor="w")
        row = ttk.Frame(screen)
        row.pack(fill="x", pady=(4, 12))
        self.monitor_box = ttk.Combobox(row, state="readonly")
        self.monitor_box.pack(side="left", fill="x", expand=True)
        self.monitor_box.bind("<<ComboboxSelected>>", lambda event: self.reset_region())
        self.refresh_button = ttk.Button(row, text="새로고침", command=self.refresh)
        self.refresh_button.pack(side="left", padx=(8, 0))
        ttk.Label(screen, text="녹화 영역", style="Field.TLabel").pack(anchor="w")
        area_row = ttk.Frame(screen)
        area_row.pack(fill="x", pady=(4, 10))
        self.ratio = ttk.Combobox(area_row, state="readonly", values=["자유 비율", "9:16 고정"], width=12)
        self.ratio.current(0)
        self.ratio.pack(side="left")
        self.area_button = ttk.Button(area_row, text="영역 지정", command=self.select_area)
        self.area_button.pack(side="left", padx=8)
        self.reset_button = ttk.Button(area_row, text="전체 화면", command=self.reset_region)
        self.reset_button.pack(side="left")
        # 최종 녹화 범위 요약과 확인 버튼: 모니터 + 영역을 합친 결과를 한 줄로 보여 준다
        ttk.Separator(screen).pack(fill="x", pady=(0, 8))
        summary_row = ttk.Frame(screen)
        summary_row.pack(fill="x")
        self.area_status = tk.StringVar()
        self.area_label = ttk.Label(summary_row, textvariable=self.area_status, style="Pending.TLabel")
        self.area_label.pack(side="left", fill="x", expand=True)
        self.identify_button = ttk.Button(summary_row, text="녹화 범위 확인", command=self.identify_monitor)
        self.identify_button.pack(side="left", padx=(8, 0))
        self.set_confirmed(False)

        # 2. 소리 카드
        sound = self.card(frame, "소리")
        ttk.Label(sound, text="녹음 장치", style="Field.TLabel").pack(anchor="w")
        self.audio_box = ttk.Combobox(sound, state="readonly")
        self.audio_box.pack(fill="x", pady=(4, 6))
        ttk.Label(sound, text="PC 소리는 고른 출력 장치(스피커·헤드폰)로 나가는 소리를 녹음합니다.", style="CardHint.TLabel").pack(anchor="w")

        # 3. 출력 카드: 세로 변환 방식
        output = self.card(frame, "세로 영상")
        self.mode = tk.StringVar(value="커서 따라가기")
        self.mode_box = ttk.Combobox(output, textvariable=self.mode, state="readonly", values=["커서 따라가기", "블러 배경"])
        self.mode_box.pack(fill="x", pady=(0, 6))
        ttk.Label(output, text="커서 따라가기는 마우스를 부드럽게 추적하고, 블러 배경은 화면 전체를 담습니다.", style="CardHint.TLabel").pack(anchor="w")

        # 녹화 버튼과 상태 표시줄
        # 녹화 버튼은 로고·녹화 표시와 같은 빨강 계열로 맞춘다 (흰 글자 대비 5.4:1)
        self.button = tk.Button(frame, text="●  녹화 시작  (F8)", command=self.toggle, font=("맑은 고딕", 13, "bold"), relief="flat", bd=0, cursor="hand2", highlightthickness=0)
        self.button.pack(fill="x", pady=(6, 0), ipady=10)
        self.button_look("ready")
        self.status = tk.StringVar(value=f"준비됨 · 저장 위치: {OUTPUT}")
        ttk.Label(frame, textvariable=self.status, style="Status.TLabel", wraplength=540).pack(anchor="w", pady=(12, 0))
        self.hotkey = bool(user32.RegisterHotKey(None, 1, 0x4000, 0x77))
        if not self.hotkey:
            self.status.set("F8 단축키를 등록하지 못했습니다. 화면의 버튼을 사용하세요.")
        self.refresh()
        self.poll()

    def apply_theme(self):
        # Windows 11 스타일 Sun Valley 다크 테마와 한글 글꼴, 앱 전용 스타일을 적용한다
        sv_ttk.set_theme("dark", self.root)
        # 테마 변경 이벤트가 늦거나 누락돼도 배경·글자색이 확실히 적용되도록 직접 호출한다
        self.root.tk.call("configure_colors")
        for name in ("SunValleyCaptionFont", "SunValleyBodyFont", "SunValleyBodyStrongFont", "SunValleyBodyLargeFont", "SunValleySubtitleFont", "SunValleyTitleFont", "SunValleyTitleLargeFont", "SunValleyDisplayFont"):
            try:
                tkfont.nametofont(name).configure(family="맑은 고딕")
            except tk.TclError:
                pass
        style = ttk.Style()
        style.configure("Title.TLabel", font=("맑은 고딕", 20, "bold"))
        style.configure("Logo.TLabel", font=("맑은 고딕", 28, "bold"), foreground="#ff4b5c")
        style.configure("Hint.TLabel", font=("맑은 고딕", 10), foreground="#a7a7a7")
        style.configure("Field.TLabel", font=("맑은 고딕", 10, "bold"), foreground="#dcdcdc")
        style.configure("CardHint.TLabel", font=("맑은 고딕", 9), foreground="#8c8c8c")
        style.configure("Badge.TLabel", font=("맑은 고딕", 10, "bold"), foreground="#57c8ff")
        # 녹화 범위 확인 상태: 미확인(주황) · 확인됨(초록)
        style.configure("Pending.TLabel", font=("맑은 고딕", 10, "bold"), foreground="#f0b429")
        style.configure("Confirmed.TLabel", font=("맑은 고딕", 10, "bold"), foreground="#6ccb5f")
        style.configure("Status.TLabel", font=("맑은 고딕", 9), foreground="#a7a7a7")
        style.configure("TLabelframe.Label", font=("맑은 고딕", 11, "bold"))
        self.root.configure(background="#1c1c1c")
        self.root.after(10, self.dark_title_bar)

    def dark_title_bar(self):
        # 제목 표시줄도 어둡게 맞춘다 (Windows 10 20H1 이상, 실패해도 무시)
        try:
            hwnd = wintypes.HWND(int(self.root.wm_frame(), 16))
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            # 바로 다시 그리도록 창 크기를 1픽셀 흔든다
            width, height = self.root.winfo_width(), self.root.winfo_height()
            self.root.geometry(f"{width + 1}x{height}")
            self.root.after(20, lambda: self.root.geometry(f"{width}x{height}"))
        except Exception:
            pass

    def button_look(self, state):
        # 대기(빨강) · 녹화 중(진한 빨강) · 변환 중(회색) 색 구성
        colors = {"ready": ("#c62f3d", "#a82633"), "recording": ("#a82633", "#8e1f2a"), "busy": ("#3a3a3a", "#3a3a3a")}
        background, active = colors[state]
        self.button.configure(background=background, activebackground=active, foreground="#ffffff", activeforeground="#ffffff", disabledforeground="#c8c8c8")

    def card(self, parent, title):
        # 둥근 테두리 카드 안쪽 프레임을 돌려준다
        box = ttk.Labelframe(parent, text=f"  {title}  ", padding=(16, 10, 16, 14))
        box.pack(fill="x", pady=(0, 14))
        return box

    def refresh(self):
        try:
            if not FFMPEG.is_file():
                raise RuntimeError("ffmpeg.exe를 찾을 수 없습니다.")
            self.monitor_list = monitors()
            if not self.monitor_list:
                raise RuntimeError("사용 가능한 모니터가 없습니다.")
            labels = [f"{m[0]} · {m[3]}×{m[4]}" + (" · 기본 모니터" if m[5] else "") for m in self.monitor_list]
            self.monitor_box["values"] = labels
            self.monitor_box.current(next((i for i, m in enumerate(self.monitor_list) if m[5]), 0))
            self.reset_region()
            outputs = loopback_devices()
            devices = audio_devices()
            self.audio_sources = [None] + [("loopback", name) for name in outputs] + [("dshow", name) for name in devices]
            self.audio_box["values"] = ["녹음 안 함"] + [f"PC 소리 · {name}" for name in outputs] + devices
            self.audio_box.current(1 if outputs else 0)
        except Exception as exc:
            messagebox.showerror("장치 확인 실패", str(exc))

    def reset_region(self):
        self.selected_region = None
        self.set_confirmed(False)

    def current_monitor(self):
        index = self.monitor_box.current()
        return self.monitor_list[index] if 0 <= index < len(self.monitor_list) else None

    def set_confirmed(self, confirmed):
        # 범위가 바뀌면 미확인으로 되돌리고, 사용자가 확정하면 확인됨으로 표시한다
        self.region_confirmed = confirmed
        self.area_status.set(region_summary(self.current_monitor(), self.selected_region, confirmed))
        self.area_label.configure(style="Confirmed.TLabel" if confirmed else "Pending.TLabel")

    def select_area(self):
        if self.selection_window and self.selection_window.winfo_exists():
            return
        index = self.monitor_box.current()
        if index < 0:
            return
        monitor = self.monitor_list[index]
        _, left, top, width, height, _ = monitor
        if monitor not in monitors():
            messagebox.showerror("모니터 변경", "모니터 구성이 변경되었습니다. 새로고침 후 다시 선택하세요.")
            return
        window = tk.Toplevel(self.root)
        self.selection_window = window
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.35)
        canvas = tk.Canvas(window, bg="black", cursor="crosshair", highlightthickness=0, width=width, height=height)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(width // 2, 50, text="마우스로 드래그한 뒤 놓으면 선택 완료 · Esc 취소", fill="white", font=("맑은 고딕", 18, "bold"))
        rectangle = canvas.create_rectangle(0, 0, 0, 0, outline="#ff4055", width=4)
        state = {"start": None, "rect": None}

        def drag(event):
            if state["start"] is None:
                return
            rect = selection_rect(state["start"], (event.x, event.y), width, height, self.ratio.get() == "9:16 고정")
            state["rect"] = rect
            x, y, w, h = rect
            canvas.coords(rectangle, x, y, x + w, y + h)

        def start(event):
            state["start"] = (max(0, min(width, event.x)), max(0, min(height, event.y)))
            drag(event)

        def confirm(event):
            drag(event)
            rect = state["rect"]
            if not rect or rect[2] < 32 or rect[3] < 32:
                return
            self.selected_region = (left + rect[0], top + rect[1], rect[2], rect[3])
            # 드래그로 직접 지정한 영역은 그 자체로 확정으로 본다
            self.set_confirmed(True)
            self.status.set("녹화 영역을 확정했습니다. 녹화 범위 확인으로 다시 볼 수 있습니다.")
            window.destroy()
            self.root.deiconify()
            self.root.lift()

        canvas.bind("<ButtonPress-1>", start)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", confirm)
        window.bind("<Escape>", lambda event: window.destroy())
        window.geometry(f"{width}x{height}+0+0")
        window.update_idletasks()
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos(window.winfo_id(), None, left, top, width, height, 0x0040)
        window.focus_force()

    def show_on_monitor(self, monitor, text):
        window = tk.Toplevel(self.root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        label = tk.Label(window, text=text, bg="#a51b2b", fg="white", font=("맑은 고딕", 14, "bold"), padx=18, pady=10)
        label.pack()
        window.update_idletasks()
        _, left, top, width, _, _ = monitor
        handle = window.winfo_id()
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos(handle, None, left + (width - window.winfo_reqwidth()) // 2, top + 30, 0, 0, 0x0011)
        return window

    def identify_monitor(self):
        # 실제로 녹화될 범위(전체 모니터 또는 지정 영역)만 밝게 두고 나머지를 어둡게 덮어
        # 사용자가 [확인] 또는 [취소]로 직접 결정하게 한다
        monitor = self.current_monitor()
        if not monitor:
            return
        if self.identification and self.identification.winfo_exists():
            self.identification.destroy()
        if monitor not in monitors():
            messagebox.showerror("모니터 변경", "모니터 구성이 변경되었습니다. 새로고침 후 다시 선택하세요.")
            return
        _, left, top, width, height, _ = monitor
        if self.selected_region:
            rx, ry, rw, rh = self.selected_region
            rx, ry = rx - left, ry - top
        else:
            rx, ry, rw, rh = 0, 0, width, height
        hole = "#ff00fe"  # 이 색은 투명 처리되어 녹화 범위가 그대로 비쳐 보인다
        window = tk.Toplevel(self.root)
        self.identification = window
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.75)
        window.attributes("-transparentcolor", hole)
        canvas = tk.Canvas(window, bg="#000000", highlightthickness=0, width=width, height=height)
        canvas.pack(fill="both", expand=True)
        # 녹화 범위 밖은 어둡게, 안쪽은 투명하게 두고 테두리를 굵게 그린다
        canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill=hole, outline="")
        border = 6
        canvas.create_rectangle(rx + border // 2, ry + border // 2, rx + rw - border // 2, ry + rh - border // 2, outline="#ff4055", width=border)

        # 안내 패널: 무엇이 녹화되는지와 결정 버튼
        # 반투명 덮개와 분리된 불투명 창으로 띄워 전체 모니터일 때도 잘 읽히게 한다
        popup = tk.Toplevel(window)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        panel = tk.Frame(popup, bg="#202020", highlightbackground="#ff4055", highlightthickness=2, padx=22, pady=16)
        panel.pack()
        kind = "지정 영역" if self.selected_region else "전체 모니터"
        tk.Label(panel, text="빨간 테두리 안이 녹화됩니다", bg="#202020", fg="white", font=("맑은 고딕", 16, "bold")).pack()
        tk.Label(panel, text=f"{monitor[0]} · {kind} · {rw}×{rh}", bg="#202020", fg="#57c8ff", font=("맑은 고딕", 11, "bold")).pack(pady=(4, 12))
        buttons = tk.Frame(panel, bg="#202020")
        buttons.pack()

        def decide(confirmed):
            if window.winfo_exists():
                window.destroy()
            self.set_confirmed(confirmed)
            if confirmed:
                self.status.set("녹화 범위를 확인했습니다. 녹화 시작(F8)을 누르세요.")
            else:
                self.status.set("녹화 범위 확인을 취소했습니다. 영역 지정 또는 전체 화면으로 다시 고르세요.")
            self.root.deiconify()
            self.root.lift()

        tk.Button(buttons, text="✔  확인 (Enter)", command=lambda: decide(True), bg="#2f8f46", fg="white", activebackground="#25733a", activeforeground="white", font=("맑은 고딕", 11, "bold"), relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=6)
        tk.Button(buttons, text="취소 (Esc)", command=lambda: decide(False), bg="#3a3a3a", fg="white", activebackground="#4a4a4a", activeforeground="white", font=("맑은 고딕", 11), relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=6)
        for target in (window, popup):
            target.bind("<Return>", lambda event: decide(True))
            target.bind("<Escape>", lambda event: decide(False))
        window.geometry(f"{width}x{height}+0+0")
        window.update_idletasks()
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos(window.winfo_id(), None, left, top, width, height, 0x0040)
        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
        py = panel_y(ry, rh, height, ph)
        # winfo_id()는 내부 창이라 위치가 어긋나므로 실제 최상위 창(wm_frame)을 옮긴다
        user32.SetWindowPos(int(popup.wm_frame(), 16), None, left + (width - pw) // 2, top + py - ph // 2, pw, ph, 0x0040)
        popup.lift(window)
        popup.focus_force()
        self.identification_popup = popup

    def poll(self):
        if not self.results.empty():
            self.complete(self.results.get())
        msg = wintypes.MSG()
        if self.hotkey and user32.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 1):
            self.toggle()
        if self.process and not self.busy:
            if self.process.poll() is not None:
                self.finish_recording()
            else:
                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    _, left, top, width, height, _ = self.selected_monitor
                    if left <= point.x < left + width and top <= point.y < top + height:
                        self.points.append((time.monotonic() - self.started, point.x - left))
        self.root.after(50, self.poll)

    def controls(self, enabled):
        state = "readonly" if enabled else "disabled"
        for widget in (self.monitor_box, self.audio_box, self.mode_box, self.ratio):
            widget.configure(state=state)
        self.refresh_button.configure(state="normal" if enabled else "disabled")
        self.identify_button.configure(state="normal" if enabled else "disabled")
        self.area_button.configure(state="normal" if enabled else "disabled")
        self.reset_button.configure(state="normal" if enabled else "disabled")

    def toggle(self):
        if self.selection_window and self.selection_window.winfo_exists():
            return
        if self.busy:
            return
        if self.process:
            self.finish_recording()
            return
        try:
            index = self.monitor_box.current()
            if index < 0 or index >= len(self.monitor_list):
                raise RuntimeError("녹화할 모니터를 선택하세요.")
            monitor = self.monitor_list[index]
            if self.identification and self.identification.winfo_exists():
                self.identification.destroy()
            if monitor not in monitors():
                raise RuntimeError("모니터 구성이 변경되었습니다. 새로고침 후 다시 선택하세요.")
            if self.selected_region:
                left, top, width, height = self.selected_region
                self.selected_monitor = (monitor[0], left, top, width, height, monitor[5])
            else:
                self.selected_monitor = monitor
                _, left, top, width, height, _ = monitor
            OUTPUT.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1000000000:09d}"
            self.original = OUTPUT / f"{stamp}_원본.mkv"
            self.result = OUTPUT / f"{stamp}_쇼츠.mp4"
            self.log_path = OUTPUT / f"{stamp}_오류.log"
            self.log = open(self.log_path, "wb")
            source = self.audio_sources[self.audio_box.current()] if 0 <= self.audio_box.current() < len(self.audio_sources) else None
            self.video_path = self.original
            command = [str(FFMPEG), "-hide_banner", "-y", "-f", "gdigrab", "-framerate", "30", "-draw_mouse", "1", "-offset_x", str(left), "-offset_y", str(top), "-video_size", f"{width}x{height}", "-i", "desktop"]
            if source and source[0] == "dshow":
                command += ["-f", "dshow", "-i", "audio=" + source[1], "-c:a", "aac"]
            elif source:
                # PC 소리는 따로 녹음한 뒤 녹화가 끝나면 원본에 합친다
                self.video_path = OUTPUT / f"{stamp}_영상.mkv"
                self.audio_path = OUTPUT / f"{stamp}_소리.wav"
                self.recorder = LoopbackRecorder(source[1], self.audio_path)
            command += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(self.video_path)]
            self.points = []
            self.started = time.monotonic()
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log, creationflags=CREATE_NO_WINDOW)
            self.controls(False)
            self.button.configure(text="■  녹화 종료  (F8)")
            self.button_look("recording")
            self.status.set("녹화 중 · F8 또는 버튼을 눌러 종료하세요.")
            self.indicator = self.show_on_monitor(monitor, "● 녹화 중  ·  F8로 종료")
        except Exception as exc:
            if self.recorder:
                self.recorder.stop()
                self.recorder = None
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.process = None
            if hasattr(self, "log") and not self.log.closed:
                self.log.close()
            messagebox.showerror("녹화 시작 실패", str(exc))

    def finish_recording(self):
        if self.busy or not self.process:
            return
        self.busy = True
        if self.indicator and self.indicator.winfo_exists():
            self.indicator.destroy()
        self.indicator = None
        self.selected_mode = self.mode.get()
        self.button.configure(state="disabled", text="변환 중…")
        self.button_look("busy")
        self.status.set("녹화를 마무리하고 세로 영상으로 변환합니다. 잠시 기다려 주세요.")
        threading.Thread(target=self.convert, daemon=True).start()

    def convert(self):
        command_file = None
        error = None
        try:
            if self.process.poll() is None:
                self.process.stdin.write(b"q\n")
                self.process.stdin.flush()
            code = self.process.wait(timeout=30)
            self.log.close()
            if self.recorder:
                self.recorder.stop()
            if code != 0 or not self.video_path.exists() or self.video_path.stat().st_size == 0:
                raise RuntimeError(f"녹화에 실패했습니다. 오류 기록: {self.log_path}")
            if self.recorder:
                video_start = video_start_time(self.log_path.read_text("utf-8", errors="replace"))
                if self.recorder.started is None or video_start is None:
                    raise RuntimeError(f"PC 소리를 받지 못했습니다. 영상은 보존됩니다: {self.video_path}")
                with open(self.log_path, "ab") as log:
                    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-y", "-i", str(self.video_path), "-i", str(self.audio_path), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", audio_offset_filter(self.recorder.started - video_start), "-c:a", "aac", "-shortest", str(self.original)], stdout=subprocess.DEVNULL, stderr=log, creationflags=CREATE_NO_WINDOW)
                if proc.returncode:
                    raise RuntimeError(f"PC 소리를 합치지 못했습니다. 영상과 소리 파일은 보존됩니다. 오류 기록: {self.log_path}")
                self.video_path.unlink(missing_ok=True)
                self.audio_path.unlink(missing_ok=True)
            if self.selected_mode == "블러 배경":
                filters = "[0:v]split[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[blur];[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];[blur][front]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
            else:
                _, _, _, width, height, _ = self.selected_monitor
                crop_width, positions = crop_positions(self.points, width, height)
                command_file = OUTPUT / (self.original.stem + "_cursor.txt")
                with open(command_file, "w", encoding="ascii") as file:
                    for timestamp, x in positions:
                        file.write(f"{timestamp:.3f} crop@follow x {x};\n")
                send = f"sendcmd=f='{command_file.name}'," if positions else ""
                filters = f"[0:v]{send}crop@follow={crop_width}:ih:(iw-ow)/2:0,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v]"
            with open(self.log_path, "ab") as log:
                proc = subprocess.run([str(FFMPEG), "-hide_banner", "-y", "-i", str(self.original), "-filter_complex", filters, "-map", "[v]", "-map", "0:a?", "-r", "30", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(self.result)], cwd=OUTPUT, stdout=subprocess.DEVNULL, stderr=log, creationflags=CREATE_NO_WINDOW)
            if proc.returncode:
                raise RuntimeError(f"변환에 실패했습니다. 원본은 보존됩니다. 오류 기록: {self.log_path}")
            self.log_path.unlink(missing_ok=True)
        except Exception as exc:
            if self.recorder:
                self.recorder.stop()
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            if not self.log.closed:
                self.log.close()
            error = str(exc)
        finally:
            if command_file:
                command_file.unlink(missing_ok=True)
            self.results.put(error)

    def complete(self, error):
        self.process = None
        self.recorder = None
        self.busy = False
        self.controls(True)
        self.button.configure(state="normal", text="●  녹화 시작  (F8)")
        self.button_look("ready")
        if error:
            self.status.set("작업 실패 · 원본과 오류 기록을 확인하세요.")
            messagebox.showerror("작업 실패", error)
        else:
            self.status.set(f"저장 완료 · {self.result.name}")
            if messagebox.askyesno("완료", "세로 영상이 저장되었습니다. 저장 폴더를 열까요?"):
                os.startfile(OUTPUT)

    def close(self):
        if self.process or self.busy:
            messagebox.showinfo("작업 중", "녹화 또는 변환이 끝난 후 종료해 주세요.")
            return
        if self.hotkey:
            user32.UnregisterHotKey(None, 1)
        self.root.destroy()


if __name__ == "__main__":
    App(tk.Tk()).root.mainloop()
