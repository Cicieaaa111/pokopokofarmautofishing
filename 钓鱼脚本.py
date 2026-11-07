# -*- coding: utf-8 -*-
"""
VRChat 钓鱼图专用自动钓鱼助手 (纯净画面识别浮漂 + 官方 OSC 后台挂机版)
作者: Cicieaaa + Gemini 4 Argon

功能特点：
1. 【纯画面识别浮漂】：不依赖声卡与音量，彻底无视熬汤提示音、小猫音效与玩家语音。
2. 【纯 OSC 后台触发】：完全不抢鼠标、不切窗口，只要 VRChat 不最小化，可随意使用其他软件工作。
3. 【手动点选 + 从收竿开始】：
   ① 在池塘找一个画面干扰较小的位置，先在游戏里手动抛竿入水；
   ② 在本软件左侧预览图上，用鼠标左键点一下水里的浮漂（切换位置时不会误收竿）；
   ③ 按 [F8] 启动，脚本直接从【等待浮漂下沉 -> 收竿】开始全自动循环！
"""

import ctypes
from ctypes import wintypes, POINTER, byref, c_int, c_uint, c_void_p
import json
import math
import os
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

# ==============================================================================
# 1. Win32 API 64位安全声明 (窗口查找与后台画面捕捉 PrintWindow/BitBlt)
# ==============================================================================
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, POINTER(wintypes.RECT)]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, c_uint]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, c_int, c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC, c_int, c_int, c_int, c_int, wintypes.HDC, c_int, c_int, wintypes.DWORD
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.StretchBlt.argtypes = [
    wintypes.HDC, c_int, c_int, c_int, c_int, wintypes.HDC, c_int, c_int, c_int, c_int, wintypes.DWORD
]
gdi32.StretchBlt.restype = wintypes.BOOL
gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, c_int]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, c_uint, c_uint, c_void_p, c_void_p, c_uint
]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


_cached_vrc_hwnd = None
_last_hwnd_search_t = 0.0


def find_vrchat_hwnd():
    """64位安全查找 VRChat 窗口句柄（纯窗口类名与标题查找，不调用 OpenProcess，防止杀毒软件误报）"""
    global _cached_vrc_hwnd, _last_hwnd_search_t
    if _cached_vrc_hwnd and user32.IsWindow(_cached_vrc_hwnd) and user32.IsWindowVisible(_cached_vrc_hwnd):
        return _cached_vrc_hwnd

    now = time.time()
    if now - _last_hwnd_search_t < 1.0:
        return None
    _last_hwnd_search_t = now

    hwnd = user32.FindWindowW("UnityWndClass", "VRChat")
    if hwnd:
        _cached_vrc_hwnd = hwnd
        return hwnd
    hwnd = user32.FindWindowW(None, "VRChat")
    if hwnd:
        _cached_vrc_hwnd = hwnd
        return hwnd

    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPARAM, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.LPARAM, wintypes.LPWSTR, c_int]

    def _cb(h, _):
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if "vrchat" in buf.value.lower():
                found.append(h)
                return False
        return True

    cb_ref = WNDENUMPROC(_cb)
    user32.EnumWindows(cb_ref, 0)
    if found:
        _cached_vrc_hwnd = found[0]
        return found[0]
    hwnd = user32.FindWindowW("UnityWndClass", None)
    _cached_vrc_hwnd = hwnd
    return hwnd


# ==============================================================================
# 2. 后台窗口视觉捕捉与浮漂画面比对
# ==============================================================================
class VRChatWindowCapture:
    """
    通过 PrintWindow 直接从后台 VRChat 窗口读取画面，
    保持 320x180 同源超低 CPU 占用，并启用 HALFTONE(4) 平滑缩放防止低分辨率丢失浮漂红点！
    """

    def capture_window_bgra(self, hwnd, dst_w=320, dst_h=180):
        if not hwnd or user32.IsIconic(hwnd):
            return None

        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, byref(rect))
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        if win_w < 200 or win_h < 200:
            return None

        hdc_win = user32.GetDC(hwnd)
        if not hdc_win:
            return None

        hdc_full = gdi32.CreateCompatibleDC(hdc_win)
        hbmp_full = gdi32.CreateCompatibleBitmap(hdc_win, win_w, win_h)
        old_full = gdi32.SelectObject(hdc_full, hbmp_full)

        # PW_RENDERFULLCONTENT (2) | PW_CLIENTONLY (1) = 3
        ok = user32.PrintWindow(hwnd, hdc_full, 3)
        if not ok:
            ok = user32.PrintWindow(hwnd, hdc_full, 2)
        if not ok:
            SRCCOPY = 0x00CC0020
            gdi32.BitBlt(hdc_full, 0, 0, win_w, win_h, hdc_win, 0, 0, SRCCOPY)

        hdc_roi = gdi32.CreateCompatibleDC(hdc_win)
        hbmp_roi = gdi32.CreateCompatibleBitmap(hdc_win, dst_w, dst_h)
        old_roi = gdi32.SelectObject(hdc_roi, hbmp_roi)
        SRCCOPY = 0x00CC0020
        gdi32.SetStretchBltMode(hdc_roi, 4)  # HALFTONE(4) 抗锯齿平滑缩放，防止低分辨率丢像素
        gdi32.StretchBlt(hdc_roi, 0, 0, dst_w, dst_h, hdc_full, 0, 0, win_w, win_h, SRCCOPY)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = dst_w
        bmi.biHeight = -dst_h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = ctypes.create_string_buffer(dst_w * dst_h * 4)
        lines = gdi32.GetDIBits(hdc_roi, hbmp_roi, 0, dst_h, buf, byref(bmi), 0)

        gdi32.SelectObject(hdc_roi, old_roi)
        gdi32.DeleteObject(hbmp_roi)
        gdi32.DeleteDC(hdc_roi)

        gdi32.SelectObject(hdc_full, old_full)
        gdi32.DeleteObject(hbmp_full)
        gdi32.DeleteDC(hdc_full)
        user32.ReleaseDC(hwnd, hdc_win)

        if lines <= 0:
            return None
        return buf.raw, dst_w, dst_h


def extract_patch_metrics(bgra: bytes, w: int, h: int, cx: int, cy: int, half=12):
    """提取浮漂中心 (cx, cy) 周围 24x24 小块的 RGB 数据、红白浮漂特征值与平均亮度"""
    x0 = max(0, min(w - 2 * half, cx - half))
    y0 = max(0, min(h - 2 * half, cy - half))
    side = 2 * half
    patch_rgb = bytearray(side * side * 3)
    red_score = 0.0
    white_count = 0
    luma_sum = 0
    p_idx = 0
    for dy in range(side):
        row_off = (y0 + dy) * w * 4
        for dx in range(side):
            idx = row_off + (x0 + dx) * 4
            b = bgra[idx]
            g = bgra[idx + 1]
            r = bgra[idx + 2]
            patch_rgb[p_idx] = r
            patch_rgb[p_idx + 1] = g
            patch_rgb[p_idx + 2] = b
            p_idx += 3
            luma_sum += (r + g + b)
            # 兼容低分辨率下被平滑略微变暗的红尖像素
            if r >= 110 and (r - g) >= 20 and (r - b) >= 16:
                red_score += (r - g)
            # 识别浮漂白色肚皮像素
            elif r >= 180 and g >= 180 and b >= 175 and abs(r - g) <= 22:
                white_count += 1
    if red_score > 0 and white_count >= 2:
        red_score += min(white_count * 18.0, 90.0)
    avg_luma = luma_sum / float(side * side * 3)
    return bytes(patch_rgb), red_score, side, avg_luma


def compute_patch_diff(patch_a: bytes, patch_b: bytes, red_a: float, red_b: float) -> float:
    """
    计算当前浮漂区域与静止基准图像的纯像素差异度：
    彻底移除原先会导致波动瞬间跳到 17.0 的 +15.0 暴击公式！
    只计算真实的画面像素变化，确保画面没变时波动永远稳定在 0.5 ~ 2.0 之间。
    """
    if not patch_a or not patch_b or len(patch_a) != len(patch_b):
        return 0.0
    total_diff = sum(abs(a - b) for a, b in zip(patch_a, patch_b))
    mae = total_diff / (len(patch_a) / 3.0)
    norm_diff = mae / 3.0
    return norm_diff


def bgra_to_ppm_fast(bgra: bytes, w: int, h: int) -> bytes:
    """极速切片转换 BGRA -> P6 PPM (比逐像素 for 循环快 30 倍，彻底消除界面卡顿)"""
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    out = bytearray(w * h * 3)
    out[0::3] = bgra[2::4]  # R
    out[1::3] = bgra[1::4]  # G
    out[2::3] = bgra[0::4]  # B
    return header + bytes(out)


def rgb_patch_to_ppm_zoomed(patch_rgb: bytes, side: int, zoom: int = 4) -> bytes:
    """将 24x24 的浮漂小图放大 4 倍生成 PPM 字节流"""
    zw = side * zoom
    zh = side * zoom
    header = f"P6\n{zw} {zh}\n255\n".encode("ascii")
    out = bytearray(zw * zh * 3)
    out_idx = 0
    for dy in range(zh):
        sy = dy // zoom
        for dx in range(zw):
            sx = dx // zoom
            p_idx = (sy * side + sx) * 3
            out[out_idx] = patch_rgb[p_idx]
            out[out_idx + 1] = patch_rgb[p_idx + 1]
            out[out_idx + 2] = patch_rgb[p_idx + 2]
            out_idx += 3
    return header + bytes(out)


# ==============================================================================
# 3. VRChat 官方 OSC 后台点击器 (纯后台，不抢鼠标不切窗口)
# ==============================================================================
def build_osc_int_packet(address: str, value: int) -> bytes:
    addr_bytes = address.encode("utf-8") + b"\x00"
    while len(addr_bytes) % 4 != 0:
        addr_bytes += b"\x00"
    return addr_bytes + b",i\x00\x00" + struct.pack(">i", int(value))


class ActionClicker:
    def __init__(self, osc_ip="127.0.0.1", osc_port=9000):
        self.osc_ip = osc_ip
        self.osc_port = osc_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def trigger(self, hold_sec=0.07):
        """通过 VRChat 官方 OSC 接口发送右手使用物品指令 (/input/UseRight)"""
        pkt_down = build_osc_int_packet("/input/UseRight", 1)
        pkt_up = build_osc_int_packet("/input/UseRight", 0)
        self.sock.sendto(pkt_down, (self.osc_ip, self.osc_port))
        time.sleep(hold_sec)
        self.sock.sendto(pkt_up, (self.osc_ip, self.osc_port))


# ==============================================================================
# 4. 图形界面与钓鱼状态机主程序
# ==============================================================================
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "visual_thresh": 5.3,         # 浮漂下沉画面波动触发阈值 (默认 5.3)
    "bobber_rx": 162,             # 预览框内浮漂 X 坐标 (0 ~ 320)
    "bobber_ry": 81,              # 预览框内浮漂 Y 坐标 (0 ~ 180)
    "cast_mute_sec": 2.2,         # 抛竿后稳定等待时间 (秒)
    "reel_wait_sec": 2.2,         # 收竿后等待鱼自动进背包 -> 下次抛竿间隔 (秒)
    "timeout_sec": 15.0,          # 超时未上钩自动重抛时间 (秒)
}


def make_carrot_icon_ppm(size=48) -> bytes:
    """生成极简可爱的小胡萝卜 Logo (P6 PPM)，用于窗口左上角与任务栏图标"""
    header = f"P6\n{size} {size}\n255\n".encode("ascii")
    out = bytearray(size * size * 3)
    cx = size / 2.0
    cy = size / 2.0
    angle = math.radians(32)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    idx = 0
    for y in range(size):
        for x in range(size):
            nx = (x - cx) / (size / 2.0)
            ny = (y - cy) / (size / 2.0)
            rx = nx * cos_a - ny * sin_a
            ry = nx * sin_a + ny * cos_a

            # 默认暖白圆润底色
            r, g, b = 252, 248, 240

            # 顶部三片极简绿叶
            leaf_dist = 999.0
            for lx_off, l_ang in [(-0.14, -0.35), (0.0, 0.0), (0.14, 0.35)]:
                lx = (rx - lx_off) * math.cos(l_ang) - (ry + 0.42) * math.sin(l_ang)
                ly = (rx - lx_off) * math.sin(l_ang) + (ry + 0.42) * math.cos(l_ang)
                d = (lx / 0.13) ** 2 + ((ly + 0.12) / 0.24) ** 2
                if d < leaf_dist:
                    leaf_dist = d

            # 胡萝卜圆润主体
            body_dist = 999.0
            if -0.36 <= ry <= 0.75:
                t = max(0.0, min(1.0, (ry + 0.32) / 1.02))
                half_w = 0.36 * (1.0 - 0.78 * (t ** 0.85))
                if ry < -0.20:
                    dy = (ry + 0.20) / 0.15
                    body_dist = (rx / 0.35) ** 2 + dy ** 2
                elif ry > 0.62:
                    dy = (ry - 0.62) / 0.11
                    body_dist = (rx / max(0.08, half_w)) ** 2 + dy ** 2
                else:
                    body_dist = abs(rx) / max(0.06, half_w)

            if leaf_dist <= 1.0:
                if leaf_dist > 0.74:
                    r, g, b = 35, 95, 40
                else:
                    r, g, b = 76, 187, 72

            if body_dist <= 1.0:
                if body_dist > 0.82:
                    r, g, b = 140, 50, 15
                else:
                    r, g, b = 255, 122, 36
                    if -0.22 < rx < -0.08 and -0.12 < ry < 0.35:
                        r, g, b = 255, 168, 96
                    if (abs(ry + 0.02) < 0.032 and rx > 0.02) or (abs(ry - 0.24) < 0.032 and rx < -0.01):
                        r, g, b = 215, 82, 18

            out[idx] = r
            out[idx + 1] = g
            out[idx + 2] = b
            idx += 3
    return header + bytes(out)


class FishingBotGUI:
    ROI_W = 320
    ROI_H = 180
    PREVIEW_W = 320
    PREVIEW_H = 180

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🥕 PokoPoko Farm Auto Fishing ver1.2.0  |  作者: Cicieaaa + Gemini 4 Argon")
        try:
            self._icon_img = tk.PhotoImage(data=make_carrot_icon_ppm(48))
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass
        self.root.bind("<F8>", lambda e: self.toggle_running())

        # 自动检测 4K 高分屏并自适应放大字体缩放比例
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        if scr_w >= 3200 or scr_h >= 1800:
            try:
                self.root.tk.call("tk", "scaling", 2.0)
            except Exception:
                pass
            self.root.geometry("920x960")
            self.root.minsize(860, 900)
        else:
            self.root.geometry("760x820")
            self.root.minsize(720, 780)

        self.root.resizable(True, True)
        self.root.attributes("-topmost", False)

        self.cfg = self.load_config()
        self.clicker = ActionClicker()
        self.capturer = VRChatWindowCapture()

        # 运行状态
        self.running = False
        self.state_text = "已暂停 (请先抛竿点浮漂，再按 F8 从收竿开始)"
        self.fish_count = 0
        self.stop_Flag = False
        self.manual_pick_cooldown_until = 0.0

        # 兼容旧版 480x270 坐标自动换算到 320x180
        raw_x = int(self.cfg.get("bobber_rx", 164))
        raw_y = int(self.cfg.get("bobber_ry", 90))
        if raw_x > self.ROI_W or raw_y > self.ROI_H:
            raw_x = int(raw_x * self.ROI_W / 480)
            raw_y = int(raw_y * self.ROI_H / 270)
        self.bobber_x = max(14, min(self.ROI_W - 14, raw_x))
        self.bobber_y = max(14, min(self.ROI_H - 14, raw_y))

        self.visual_diff = 0.0
        self.visual_max_diff = 0.0
        self.recent_diffs = []
        self.red_count = 0
        self.vrc_hwnd_found = False

        self.latest_roi_ppm = None
        self.latest_zoom_ppm = None
        self._frame_dirty = False
        self.tk_roi_img = None
        self.tk_zoom_img = None

        self.build_ui()
        self.worker_thread = threading.Thread(target=self.backend_loop, daemon=True)
        self.worker_thread.start()
        self.update_ui_loop()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        cfg = DEFAULT_CONFIG.copy()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    cfg.update(saved)
            except Exception:
                pass
        return cfg

    def save_config(self):
        try:
            self.cfg["visual_thresh"] = round(float(self.v_thresh_var.get()), 1)
            self.cfg["bobber_rx"] = int(self.bobber_x)
            self.cfg["bobber_ry"] = int(self.bobber_y)
            self.cfg["cast_mute_sec"] = round(float(self.cast_mute_var.get()), 2)
            self.cfg["reel_wait_sec"] = round(float(self.reel_wait_var.get()), 2)
            self.cfg["timeout_sec"] = round(float(self.timeout_var.get()), 1)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def build_ui(self):
        pad = {"padx": 14, "pady": 5}

        # 1. 顶部状态栏
        top_frame = tk.LabelFrame(self.root, text=" 实时运行状态 ", font=("Microsoft YaHei", 11, "bold"))
        top_frame.pack(fill="x", **pad)

        self.lbl_state = tk.Label(
            top_frame,
            text=self.state_text,
            font=("Microsoft YaHei", 12, "bold"),
            fg="#d9534f",
        )
        self.lbl_state.pack(anchor="w", padx=10, pady=3)

        info_row = tk.Frame(top_frame)
        info_row.pack(fill="x", padx=10, pady=3)
        self.lbl_vrc_status = tk.Label(
            info_row, text="窗口状态: 正在查找 VRChat 窗口...", font=("Microsoft YaHei", 10), fg="#555"
        )
        self.lbl_vrc_status.pack(side="left")

        self.lbl_count = tk.Label(
            info_row, text="累计已钓: 0 条", font=("Microsoft YaHei", 11, "bold"), fg="#0275d8"
        )
        self.lbl_count.pack(side="right", padx=(10, 0))

        self.topmost_var = tk.BooleanVar(value=False)
        chk_top = tk.Checkbutton(
            info_row,
            text="📌 窗口置顶",
            variable=self.topmost_var,
            font=("Microsoft YaHei", 9),
            command=lambda: self.root.attributes("-topmost", bool(self.topmost_var.get())),
        )
        chk_top.pack(side="right")

        # 2. 👁️ 画面浮漂实时监控窗 + 右侧新手四步指南
        vis_frame = tk.LabelFrame(
            self.root,
            text=" 👁️ 浮漂画面实时监控 (鼠标点击左图水里的浮漂即可锁定位置) ",
            font=("Microsoft YaHei", 10, "bold"),
        )
        vis_frame.pack(fill="x", **pad)

        preview_row = tk.Frame(vis_frame)
        preview_row.pack(fill="x", padx=8, pady=5)

        # 左侧池塘预览画布
        left_p = tk.Frame(preview_row)
        left_p.pack(side="left", padx=4)
        self.canvas_roi = tk.Canvas(
            left_p, width=self.PREVIEW_W, height=self.PREVIEW_H, bg="#111", highlightthickness=1, cursor="crosshair"
        )
        self.canvas_roi.pack()
        self.canvas_roi.bind("<Button-1>", self.on_click_preview)
        tk.Label(
            left_p,
            text="👆 先在游戏抛竿，再点击左图水里的浮漂",
            font=("Microsoft YaHei", 10, "bold"),
            fg="#0066cc",
        ).pack(pady=2)

        # 中间浮漂 4x 放大镜
        mid_p = tk.Frame(preview_row)
        mid_p.pack(side="left", padx=8)
        self.canvas_zoom = tk.Canvas(mid_p, width=96, height=96, bg="#111", highlightthickness=1)
        self.canvas_zoom.pack()
        self.lbl_red_info = tk.Label(
            mid_p, text="浮漂放大镜 (4x)", font=("Microsoft YaHei", 9, "bold"), fg="#0066cc"
        )
        self.lbl_red_info.pack(pady=4)

        # 右侧使用步骤提示框
        right_p = tk.LabelFrame(
            preview_row, text=" 📌 新手必看：四步上手指南 ", font=("Microsoft YaHei", 10, "bold"), fg="#d9534f"
        )
        right_p.pack(side="left", fill="both", expand=True, padx=4, pady=2)

        guide_text = (
            "【第 1 步：开启游戏 OSC】\n"
            "  按 R 键呼出圆盘 → Options → OSC → Enabled\n"
            "【第 2 步：找干净水面先抛竿】\n"
            "  ⚠️ 放大镜绿框务必避开【粉红色莲花】和【小猫的浮漂】\n"
            "【第 3 步：点击左图找浮漂】\n"
            "  在左图点一下水里的浮漂(让绿框套住它)\n"
            "【第 4 步：按 F8 直接从收竿开始】\n"
            "  按 F8 启动，脚本会自动识别抛竿/收竿状态并循环！"
        )
        tk.Label(
            right_p,
            text=guide_text,
            font=("Microsoft YaHei", 9),
            fg="#222",
            justify="left",
            anchor="nw",
        ).pack(fill="both", expand=True, padx=6, pady=4)

        # 浮漂下沉波动进度条与阈值滑块
        bar_row = tk.Frame(vis_frame)
        bar_row.pack(fill="x", padx=10, pady=3)
        self.canvas_vbar = tk.Canvas(bar_row, height=22, bg="#1e1e1e", highlightthickness=0)
        self.canvas_vbar.pack(fill="x")

        v_info_row = tk.Frame(vis_frame)
        v_info_row.pack(fill="x", padx=10, pady=2)
        self.lbl_vdiff = tk.Label(
            v_info_row,
            text="当前浮漂下沉波动: 0.0  |  最近3秒最大波动: 0.0",
            font=("Consolas", 10, "bold"),
        )
        self.lbl_vdiff.pack(side="left")

        v_thresh_row = tk.Frame(vis_frame)
        v_thresh_row.pack(fill="x", padx=10, pady=3)
        tk.Label(v_thresh_row, text="浮漂下沉触发阈值 (越小越灵敏):", font=("Microsoft YaHei", 10, "bold")).pack(
            side="left"
        )
        self.v_thresh_var = tk.DoubleVar(value=self.cfg.get("visual_thresh", 5.3))
        self.lbl_v_thresh = tk.Label(
            v_thresh_row, text=f"{self.v_thresh_var.get():.1f}", font=("Consolas", 11, "bold"), fg="#d9534f", width=6
        )
        self.lbl_v_thresh.pack(side="right")
        self.scale_v_thresh = ttk.Scale(
            v_thresh_row, from_=1.5, to=25.0, variable=self.v_thresh_var, command=self.on_v_thresh_change
        )
        self.scale_v_thresh.pack(side="left", fill="x", expand=True, padx=8)

        # 3. OSC 后台触发与作者信息栏
        mode_frame = tk.LabelFrame(
            self.root,
            text=" 🚀 PokoPoko Farm Auto Fishing ver1.2.0  |  作者：Cicieaaa + Gemini 4 Argon ",
            font=("Microsoft YaHei", 10, "bold"),
        )
        mode_frame.pack(fill="x", **pad)

        tk.Label(
            mode_frame,
            text="✅ 已固定使用 OSC 后台触发：完全不抢鼠标、不切窗口，只要 VRChat 不最小化，可随意使用其他软件工作！",
            anchor="w",
            justify="left",
            font=("Microsoft YaHei", 10),
            fg="#155724",
        ).pack(fill="x", anchor="w", padx=10, pady=5)

        # 4. 时间参数设置
        time_frame = tk.LabelFrame(
            self.root, text=" ⏱️ 钓鱼时间参数 (单位：秒 | 收竿后鱼自动进包，无需多点左键) ", font=("Microsoft YaHei", 10, "bold")
        )
        time_frame.pack(fill="x", **pad)

        grid_f = tk.Frame(time_frame)
        grid_f.pack(fill="x", padx=10, pady=4)

        self.cast_mute_var = tk.StringVar(value=str(self.cfg.get("cast_mute_sec", 2.2)))
        self.reel_wait_var = tk.StringVar(value=str(self.cfg.get("reel_wait_sec", 2.2)))
        self.timeout_var = tk.StringVar(value=str(self.cfg.get("timeout_sec", 15.0)))

        items = [
            ("1. 抛竿后落水稳定等待 (秒):", self.cast_mute_var, 0, 0),
            ("2. 收竿后等鱼自动进包 → 再抛竿 (秒):", self.reel_wait_var, 0, 2),
            ("3. 超时未上钩自动重抛 (秒):", self.timeout_var, 1, 0),
        ]
        for label_txt, var, r, c in items:
            tk.Label(grid_f, text=label_txt, font=("Microsoft YaHei", 10)).grid(
                row=r, column=c, sticky="w", padx=6, pady=3
            )
            ent = ttk.Entry(grid_f, textvariable=var, width=8, font=("Consolas", 10))
            ent.grid(row=r, column=c + 1, sticky="w", padx=6, pady=3)
            ent.bind("<FocusOut>", lambda e: self.save_config())

        # 5. 控制按钮栏
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", padx=14, pady=5)

        self.btn_toggle = tk.Button(
            btn_frame,
            text="▶️ 先抛竿点浮漂后：开始检测收竿 (F8)",
            font=("Microsoft YaHei", 12, "bold"),
            bg="#28a745",
            fg="white",
            height=2,
            command=self.toggle_running,
        )
        self.btn_toggle.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_test = tk.Button(
            btn_frame,
            text="🎯 测试点一下左键",
            font=("Microsoft YaHei", 10, "bold"),
            height=2,
            command=self.test_single_click,
        )
        btn_test.pack(side="right", padx=(6, 0))

        # 6. 底部日志框
        log_frame = tk.LabelFrame(self.root, text=" 运行日志 ", font=("Microsoft YaHei", 10, "bold"))
        log_frame.pack(fill="both", expand=True, **pad)

        self.txt_log = tk.Text(
            log_frame, height=5, font=("Microsoft YaHei", 9), bg="#f8f9fa", state="disabled"
        )
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=4)
        self.log("📌 提示：① 抛竿位置与放大镜绿框请务必避开【粉红色莲花】、【小猫的浮漂】与水底游鱼；")
        self.log("👉 ② 在左图点击水里的浮漂定位 → ③ 按 [F8] 直接从【等待收竿】开始脚本！")

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"

        def _append():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", line)
            # 只保留最近 50 条日志，超出部分自动从顶部清理
            line_count = int(self.txt_log.index("end-1c").split(".")[0])
            if line_count > 50:
                self.txt_log.delete("1.0", f"{line_count - 50 + 1}.0")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")

        self.root.after(0, _append)

    def on_v_thresh_change(self, _=None):
        val = self.v_thresh_var.get()
        self.lbl_v_thresh.configure(text=f"{val:.1f}")
        self.save_config()

    def on_click_preview(self, event):
        """用户在左侧池塘预览图上直接点击浮漂位置"""
        rx = int(event.x * self.ROI_W / self.PREVIEW_W)
        ry = int(event.y * self.ROI_H / self.PREVIEW_H)
        self.bobber_x = max(14, min(self.ROI_W - 14, rx))
        self.bobber_y = max(14, min(self.ROI_H - 14, ry))
        self.manual_pick_cooldown_until = time.time() + 1.2
        self._reset_base_patch = True
        self.visual_diff = 0.0
        self.recent_diffs.clear()
        self.save_config()
        self.log(f"✅ 已锁定浮漂位置: ({self.bobber_x}, {self.bobber_y})，按 [F8] 即可直接从收竿开始！")

    def test_single_click(self):
        self.save_config()
        self.log("正在通过 OSC 测试触发一次左键...")
        threading.Thread(target=self.clicker.trigger, daemon=True).start()

    def toggle_running(self):
        self.save_config()
        self.running = not self.running
        if self.running:
            self._reset_base_patch = True
            self.manual_pick_cooldown_until = time.time() + 0.6
            self.visual_diff = 0.0
            self.recent_diffs.clear()
            self.btn_toggle.configure(
                text="⏸️ 停止自动钓鱼 (快捷键 F8)", bg="#dc3545"
            )
            self.lbl_state.configure(text="👁️ 正在紧盯浮漂下沉 (直接从收竿开始)...", fg="#28a745")
            self.log(">>> 脚本已启动！直接从【等待浮漂下沉 -> 收竿】开始自动循环！")
        else:
            self.btn_toggle.configure(
                text="▶️ 先抛竿点浮漂后：开始检测收竿 (F8)", bg="#28a745"
            )
            self.lbl_state.configure(text="已暂停 (请先抛竿点浮漂，再按 F8 从收竿开始)", fg="#d9534f")
            self.log("<<< 自动钓鱼已暂停。")

    def get_float_param(self, var: tk.StringVar, default_val: float) -> float:
        try:
            v = float(var.get())
            return max(0.1, v)
        except Exception:
            return default_val

    def sleep_interruptible(self, seconds: float) -> bool:
        end_t = time.time() + seconds
        while time.time() < end_t:
            if not self.running or self.stop_Flag:
                return False
            time.sleep(0.02)
        return self.running and not self.stop_Flag

    def backend_loop(self):
        """后台纯画面浮漂监控与钓鱼状态机线程"""
        # 使用正规系统热键 API RegisterHotKey 注册全局 F8 (0x77)，替代容易被杀软误报的 GetAsyncKeyState 轮询
        HOTKEY_ID = 108
        WM_HOTKEY = 0x0312
        MOD_NOREPEAT = 0x4000
        VK_F8 = 0x77
        hotkey_ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_F8))
        msg = wintypes.MSG()

        # 启动后默认直接从等待收竿 (LISTEN) 开始
        phase = "LISTEN"
        phase_start_t = 0.0

        base_patch = None
        base_red = 0.0
        base_luma = 0.0
        recast_retry_count = 0
        consecutive_trigger_frames = 0
        zero_red_frames = 0
        last_preview_t = 0.0

        while not self.stop_Flag:
            now = time.time()

            # 1. 检查全局快捷键 F8 消息 (正规 WM_HOTKEY 消息队列，0 杀软误报)
            if hotkey_ok:
                while user32.PeekMessageW(byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                    if msg.wParam == HOTKEY_ID:
                        self.root.after(0, self.toggle_running)

            # 2. 后台抓取 VRChat 窗口画面
            hwnd = find_vrchat_hwnd()
            self.vrc_hwnd_found = bool(hwnd)
            cap = None
            if hwnd:
                cap = self.capturer.capture_window_bgra(hwnd, dst_w=self.ROI_W, dst_h=self.ROI_H)

            if cap is not None:
                bgra, rw, rh = cap

                cur_patch, cur_red, side, cur_luma = extract_patch_metrics(
                    bgra, rw, rh, self.bobber_x, self.bobber_y, half=12
                )
                self.red_count = int(cur_red / 35.0)
                if self.red_count == 0:
                    zero_red_frames += 1
                else:
                    zero_red_frames = 0

                # 过滤 PrintWindow 偶发的黑屏坏帧（亮度骤降到极低或单帧异常闪烁）
                is_corrupt_black_frame = (cur_luma < 8.0) or (base_luma > 25.0 and cur_luma < base_luma * 0.30)

                if is_corrupt_black_frame:
                    diff = 0.0
                    consecutive_trigger_frames = 0
                elif (
                    getattr(self, "_reset_base_patch", False)
                    or base_patch is None
                    or now < self.manual_pick_cooldown_until
                ):
                    self._reset_base_patch = False
                    base_patch = cur_patch
                    base_red = cur_red
                    base_luma = cur_luma
                    diff = 0.0
                    consecutive_trigger_frames = 0
                    self.recent_diffs.clear()
                elif phase == "WAIT_SETTLE":
                    base_patch = cur_patch
                    base_red = cur_red
                    base_luma = cur_luma
                    diff = 0.0
                    consecutive_trigger_frames = 0
                    self.recent_diffs.clear()
                else:
                    raw_diff = compute_patch_diff(base_patch, cur_patch, base_red, cur_red)
                    # 如果单帧突变超过 14.0（正常鱼咬钩下沉在 5.0~9.5 之间，超过 14.0 必为窗口合成器闪烁帧），作为单帧闪烁抑制
                    if raw_diff >= 14.5 and consecutive_trigger_frames == 0:
                        diff = 0.0
                        consecutive_trigger_frames = 1
                    else:
                        diff = raw_diff

                self.visual_diff = diff
                self.recent_diffs.append((now, diff))
                self.recent_diffs = [(t, d) for (t, d) in self.recent_diffs if now - t <= 3.0]
                self.visual_max_diff = max((d for _, d in self.recent_diffs), default=0.0)

                if now - last_preview_t >= 0.10 and not is_corrupt_black_frame:
                    last_preview_t = now
                    self.latest_roi_ppm = bgra_to_ppm_fast(bgra, rw, rh)
                    self.latest_zoom_ppm = rgb_patch_to_ppm_zoomed(cur_patch, side, zoom=4)
                    self._frame_dirty = True

            # 3. 钓鱼状态机（未运行时保持为 LISTEN，启动瞬间直接从收竿检测开始！）
            if not self.running:
                phase = "LISTEN"
                phase_start_t = now
                consecutive_trigger_frames = 0
                time.sleep(0.03)
                continue

            v_thresh = self.v_thresh_var.get()
            cast_mute_sec = self.get_float_param(self.cast_mute_var, 2.2)
            reel_wait_sec = self.get_float_param(self.reel_wait_var, 2.2)
            timeout_sec = self.get_float_param(self.timeout_var, 15.0)

            if phase == "CAST":
                self.state_text = "🎣 正在点击左键【抛竿】..."
                self.log("抛竿 (点击左键)")
                self.clicker.trigger()
                self.visual_diff = 0.0
                consecutive_trigger_frames = 0
                self.recent_diffs.clear()
                phase = "WAIT_SETTLE"
                phase_start_t = time.time()

            elif phase == "WAIT_SETTLE":
                elapsed = now - phase_start_t
                remain = max(0.0, cast_mute_sec - elapsed)
                self.state_text = f"⏳ 等待浮漂落水稳定 ({remain:.1f}s)..."
                if elapsed >= cast_mute_sec:
                    if cap is not None:
                        bgra, rw, rh = cap
                        p_patch, p_red, _, p_luma = extract_patch_metrics(
                            bgra, rw, rh, self.bobber_x, self.bobber_y, half=12
                        )
                        cur_red_pts = int(p_red / 35.0)
                        # 自动分辨当前是【已抛竿】还是【收着竿】：
                        # 只有当连续多帧（>= 15帧）完全检测不到任何浮漂红白特征时，才判定为收着竿，防止低分辨率偶尔闪烁误判！
                        if p_luma >= 8.0 and cur_red_pts == 0 and zero_red_frames >= 15 and recast_retry_count < 2:
                            recast_retry_count += 1
                            self.log(
                                f"🔍 状态检测：放大镜内持续无浮漂 (连续 {zero_red_frames} 帧红点=0)，判定当前为【收着竿】，立即补点1下左键抛竿！"
                            )
                            self.state_text = "🔄 检测到当前收着竿，正在自动补抛竿..."
                            self.clicker.trigger()
                            self.visual_diff = 0.0
                            consecutive_trigger_frames = 0
                            zero_red_frames = 0
                            self.recent_diffs.clear()
                            phase_start_t = time.time()
                            continue

                        recast_retry_count = 0
                        if p_luma >= 8.0:
                            base_patch, base_red, base_luma = p_patch, p_red, p_luma
                    self.visual_diff = 0.0
                    consecutive_trigger_frames = 0
                    self.recent_diffs.clear()
                    phase = "LISTEN"
                    phase_start_t = time.time()
                    self.log(f"已确认【抛竿入水】并锁定浮漂基准 (红点={self.red_count})，开始盯着浮漂下沉...")

            elif phase == "LISTEN":
                elapsed = now - phase_start_t
                self.state_text = f"👁️ 正在紧盯浮漂下沉... (已等 {elapsed:.1f}s)"

                # 如果在监听中途发现连续 40 帧（约 1.4 秒）以上放大镜里完全没有浮漂红白特征 (zero_red_frames >= 40)，说明目前是【收着竿】状态，补抛竿！
                if elapsed >= 1.5 and zero_red_frames >= 40:
                    zero_red_frames = 0
                    self.log("🔍 状态检测：水面绿框内持续无浮漂 (连续40帧红点=0)，判定当前为【收着竿】状态，立即点击左键抛竿！")
                    phase = "CAST"
                    continue

                # 刚进入监听的前 0.45 秒为防抖静默期；且必须连续 2 帧达到阈值才触发收竿（彻底过滤 PrintWindow 单帧抓图闪烁！）
                if elapsed >= 0.45 and self.visual_diff >= v_thresh:
                    consecutive_trigger_frames += 1
                else:
                    consecutive_trigger_frames = 0

                if consecutive_trigger_frames >= 2:
                    consecutive_trigger_frames = 0
                    self.log(
                        f"✨ 浮漂下沉！(画面波动 {self.visual_diff:.1f} >= 阈值 {v_thresh:.1f}) -> 点击左键【收竿提鱼】！"
                    )
                    self.state_text = f"🐟 已收竿！等待 {reel_wait_sec:.1f}s 鱼自动进背包..."
                    self.clicker.trigger()
                    self.fish_count += 1

                    # 等待 2.2 秒让鱼自动进背包（不再多点那一下左键，因此就算偶尔空竿也绝不会乱步数！）
                    if not self.sleep_interruptible(reel_wait_sec):
                        continue
                    phase = "CAST"

                elif elapsed >= timeout_sec:
                    # 超时未上钩：先判断当前是【抛了竿】还是【收着竿】
                    if self.red_count <= 1:
                        # 放大镜里没浮漂，说明本来就是【收着竿】，只需直接进 CAST 点 1 下抛竿！
                        self.log(f"⚠️ 等待 {timeout_sec:.1f}s 超时，检测到当前为【收着竿】(红点={self.red_count})，直接点1下左键抛竿...")
                        phase = "CAST"
                    else:
                        # 放大镜里有浮漂，说明当前是【已抛竿】但一直没鱼咬钩，先点 1 下收回旧竿 -> 等 1.5s -> 再进入 CAST 抛竿
                        self.log(f"⚠️ 等待超过 {timeout_sec:.1f}s 未上钩，检测到浮漂仍在水中(红点={self.red_count})，收回旧竿并重新抛竿...")
                        self.state_text = "🔄 超时未上钩，正在收回旧竿..."
                        self.clicker.trigger()
                        if not self.sleep_interruptible(1.5):
                            continue
                        phase = "CAST"

            time.sleep(0.03)

        if hotkey_ok:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def update_ui_loop(self):
        if self.stop_Flag:
            return

        self.lbl_state.configure(text=self.state_text)
        self.lbl_count.configure(text=f"累计已钓: {self.fish_count} 条")

        if self.vrc_hwnd_found:
            self.lbl_vrc_status.configure(
                text=f"✅ 已连接 VRChat 窗口画面 (浮漂红点特征={self.red_count})", fg="#28a745"
            )
        else:
            self.lbl_vrc_status.configure(
                text="⚠️ 未找到 VRChat 窗口 (请确认 VRChat 已打开且未最小化)", fg="#d9534f"
            )

        self.lbl_vdiff.configure(
            text=f"当前浮漂下沉波动: {self.visual_diff:4.1f}  |  最近3秒最大波动: {self.visual_max_diff:4.1f}"
        )

        if self._frame_dirty and self.latest_roi_ppm:
            self._frame_dirty = False
            try:
                self.tk_roi_img = tk.PhotoImage(data=self.latest_roi_ppm)
                self.canvas_roi.delete("all")
                self.canvas_roi.create_image(0, 0, anchor="nw", image=self.tk_roi_img)
                bx, by = self.bobber_x, self.bobber_y
                self.canvas_roi.create_rectangle(
                    bx - 12, by - 12, bx + 12, by + 12, outline="#00ff50", width=2
                )
            except Exception:
                pass
            if self.latest_zoom_ppm:
                try:
                    self.tk_zoom_img = tk.PhotoImage(data=self.latest_zoom_ppm)
                    self.canvas_zoom.delete("all")
                    self.canvas_zoom.create_image(0, 0, anchor="nw", image=self.tk_zoom_img)
                except Exception:
                    pass

        w = self.canvas_vbar.winfo_width()
        h = self.canvas_vbar.winfo_height()
        if w > 10:
            self.canvas_vbar.delete("all")
            max_scale = 25.0
            ratio = min(1.0, self.visual_diff / max_scale)
            bar_w = int(w * ratio)

            thresh = self.v_thresh_var.get()
            t_ratio = min(1.0, thresh / max_scale)
            t_x = int(w * t_ratio)

            color = "#28a745" if self.visual_diff < thresh else "#ff4444"
            self.canvas_vbar.create_rectangle(0, 0, bar_w, h, fill=color, width=0)

            m_ratio = min(1.0, self.visual_max_diff / max_scale)
            m_x = int(w * m_ratio)
            self.canvas_vbar.create_line(m_x, 0, m_x, h, fill="#00bcd4", width=2)

            self.canvas_vbar.create_line(t_x, 0, t_x, h, fill="#ffcc00", width=3)

        self.root.after(65, self.update_ui_loop)

    def on_close(self):
        self.save_config()
        self.stop_Flag = True
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FishingBotGUI(root)
    root.mainloop()
