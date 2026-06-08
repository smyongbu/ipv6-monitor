# -*- coding: utf-8 -*-
"""
公网 IPv6 监控工具 —— 图形界面版

功能:
  - 配置 QQ 邮箱与授权码
  - 自定义检测间隔
  - 启动 / 停止 自动监控
  - 立即检测一次
  - 检测到 IPv6 变化时自动发送邮件通知
  - 实时日志显示
"""

import os
import time
import threading
import smtplib
from email.mime.text import MIMEText
from email.header import Header

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import requests

# ----------------------------------------------------------------------------
# 配置文件
# ----------------------------------------------------------------------------
CONFIG_FILE = "last_ipv6.txt"


def load_config():
    """从配置文件中加载配置信息"""
    config = {"QQ_EMAIL": "", "QQ_PASSWORD": "", "LAST_IPV6": ""}

    if os.path.exists(CONFIG_FILE):
        content = None
        for encoding in ("utf-8", "gbk"):
            try:
                with open(CONFIG_FILE, "r", encoding=encoding) as f:
                    content = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            return config

        for line in content:
            if line.startswith("QQ_EMAIL:"):
                config["QQ_EMAIL"] = line.split(":", 1)[1].strip()
            elif line.startswith("QQ_PASSWORD:"):
                config["QQ_PASSWORD"] = line.split(":", 1)[1].strip()
            elif line.startswith("LAST_IPV6:"):
                config["LAST_IPV6"] = line.split(":", 1)[1].strip()

    return config


def save_config(config):
    """保存配置信息到文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("# 邮箱配置\n")
        f.write(f"QQ_EMAIL: {config['QQ_EMAIL']}\n")
        f.write(f"QQ_PASSWORD: {config['QQ_PASSWORD']}\n")
        f.write("# 上次的IPv6地址\n")
        f.write(f"LAST_IPV6: {config['LAST_IPV6']}\n")


def get_public_ipv6():
    """获取公网 IPv6 地址"""
    response = requests.get("https://api64.ipify.org", timeout=10)
    return response.text.strip()


def send_email(config, new_ipv6):
    """发送邮件通知 IPv6 地址变更"""
    smtp_server = "smtp.qq.com"
    smtp_port = 587

    message = MIMEText(new_ipv6)
    message["From"] = config["QQ_EMAIL"]
    message["To"] = config["QQ_EMAIL"]
    message["Subject"] = Header("公网IPv6地址变更通知", "utf-8")

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()
    server.login(config["QQ_EMAIL"], config["QQ_PASSWORD"])
    server.sendmail(config["QQ_EMAIL"], [config["QQ_EMAIL"]], message.as_string())
    server.quit()


# ----------------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------------
class IPv6MonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("公网 IPv6 监控工具")
        self.root.geometry("640x560")
        self.root.minsize(560, 480)

        self.monitoring = False
        self.worker = None
        self.stop_event = threading.Event()

        cfg = load_config()
        self.email_var = tk.StringVar(value=cfg["QQ_EMAIL"])
        self.password_var = tk.StringVar(value=cfg["QQ_PASSWORD"])
        self.interval_var = tk.StringVar(value="60")
        self.last_ipv6 = cfg["LAST_IPV6"]
        self.current_ipv6_var = tk.StringVar(value="尚未检测")
        self.last_ipv6_var = tk.StringVar(value=self.last_ipv6 or "无记录")
        self.status_var = tk.StringVar(value="● 已停止")

        self._build_ui()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- 邮箱配置区 ---
        cfg_frame = ttk.LabelFrame(self.root, text="邮箱配置")
        cfg_frame.pack(fill="x", padx=12, pady=(12, 6))

        ttk.Label(cfg_frame, text="QQ 邮箱：").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(cfg_frame, textvariable=self.email_var, width=36).grid(
            row=0, column=1, sticky="we", **pad
        )

        ttk.Label(cfg_frame, text="授权码：").grid(row=1, column=0, sticky="e", **pad)
        self.pwd_entry = ttk.Entry(
            cfg_frame, textvariable=self.password_var, width=36, show="*"
        )
        self.pwd_entry.grid(row=1, column=1, sticky="we", **pad)

        self.show_pwd_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cfg_frame,
            text="显示",
            variable=self.show_pwd_var,
            command=self._toggle_password,
        ).grid(row=1, column=2, sticky="w", **pad)

        ttk.Label(cfg_frame, text="检测间隔(秒)：").grid(
            row=2, column=0, sticky="e", **pad
        )
        ttk.Spinbox(
            cfg_frame, from_=1, to=86400, textvariable=self.interval_var, width=10
        ).grid(row=2, column=1, sticky="w", **pad)

        ttk.Button(cfg_frame, text="保存配置", command=self._save).grid(
            row=2, column=2, sticky="e", **pad
        )

        cfg_frame.columnconfigure(1, weight=1)

        # --- 状态区 ---
        st_frame = ttk.LabelFrame(self.root, text="状态")
        st_frame.pack(fill="x", padx=12, pady=6)

        ttk.Label(st_frame, text="当前 IPv6：").grid(row=0, column=0, sticky="e", **pad)
        ttk.Label(
            st_frame, textvariable=self.current_ipv6_var, foreground="#0a64a4"
        ).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(st_frame, text="上次记录：").grid(row=1, column=0, sticky="e", **pad)
        ttk.Label(st_frame, textvariable=self.last_ipv6_var).grid(
            row=1, column=1, sticky="w", **pad
        )

        ttk.Label(st_frame, text="运行状态：").grid(row=2, column=0, sticky="e", **pad)
        self.status_label = ttk.Label(
            st_frame, textvariable=self.status_var, foreground="#999999"
        )
        self.status_label.grid(row=2, column=1, sticky="w", **pad)

        # --- 控制按钮区 ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=12, pady=6)

        self.start_btn = ttk.Button(
            btn_frame, text="▶ 开始监控", command=self.start_monitor
        )
        self.start_btn.pack(side="left", padx=4)

        self.stop_btn = ttk.Button(
            btn_frame, text="■ 停止", command=self.stop_monitor, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=4)

        ttk.Button(btn_frame, text="⟳ 立即检测", command=self.check_once).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="✉ 发送测试邮件", command=self.send_test).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(
            side="right", padx=4
        )

        # --- 日志区 ---
        log_frame = ttk.LabelFrame(self.root, text="日志")
        log_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=10, state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _toggle_password(self):
        self.pwd_entry.config(show="" if self.show_pwd_var.get() else "*")

    def log(self, msg):
        """线程安全地写日志"""
        def _append():
            ts = time.strftime("%H:%M:%S")
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"[{ts}] {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        self.root.after(0, _append)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _set_status(self, text, color):
        def _apply():
            self.status_var.set(text)
            self.status_label.config(foreground=color)

        self.root.after(0, _apply)

    def _current_config(self):
        return {
            "QQ_EMAIL": self.email_var.get().strip(),
            "QQ_PASSWORD": self.password_var.get().strip(),
            "LAST_IPV6": self.last_ipv6,
        }

    def _validate_config(self):
        cfg = self._current_config()
        if not cfg["QQ_EMAIL"] or not cfg["QQ_PASSWORD"]:
            messagebox.showwarning("提示", "请先填写 QQ 邮箱和授权码！")
            return None
        return cfg

    def _save(self):
        save_config(self._current_config())
        self.log("配置已保存")
        messagebox.showinfo("提示", "配置已保存")

    # ------------------------------------------------------------------
    # 业务逻辑
    # ------------------------------------------------------------------
    def _do_check(self, cfg, send_on_change=True):
        """执行一次检测，返回当前 IPv6（失败返回 None）。在工作线程中调用。"""
        try:
            current = get_public_ipv6()
        except Exception as e:
            self.log(f"获取公网 IPv6 失败: {e}")
            return None

        self.root.after(0, lambda: self.current_ipv6_var.set(current))
        self.log(f"当前公网 IPv6: {current}")

        if current != self.last_ipv6:
            self.log("检测到 IPv6 地址变更")
            if send_on_change:
                try:
                    send_email(cfg, current)
                    self.log("邮件发送成功")
                except Exception as e:
                    self.log(f"邮件发送失败: {e}")
                    return current
            self.last_ipv6 = current
            cfg["LAST_IPV6"] = current
            save_config(cfg)
            self.root.after(0, lambda: self.last_ipv6_var.set(current))
        else:
            self.log("IPv6 地址未发生变化")

        return current

    def check_once(self):
        cfg = self._validate_config()
        if not cfg:
            return
        threading.Thread(
            target=self._do_check, args=(cfg,), daemon=True
        ).start()

    def send_test(self):
        cfg = self._validate_config()
        if not cfg:
            return

        def _task():
            self.log("正在发送测试邮件...")
            try:
                send_email(cfg, "这是一封测试邮件，IPv6 监控配置正常。")
                self.log("测试邮件发送成功")
            except Exception as e:
                self.log(f"测试邮件发送失败: {e}")

        threading.Thread(target=_task, daemon=True).start()

    def start_monitor(self):
        cfg = self._validate_config()
        if not cfg:
            return

        try:
            interval = max(1, int(self.interval_var.get()))
        except ValueError:
            messagebox.showwarning("提示", "检测间隔必须是数字")
            return

        save_config(cfg)
        self.monitoring = True
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("● 监控中", "#1a8f3c")
        self.log(f"开始监控，每 {interval} 秒检测一次")

        self.worker = threading.Thread(
            target=self._monitor_loop, args=(cfg, interval), daemon=True
        )
        self.worker.start()

    def _monitor_loop(self, cfg, interval):
        while not self.stop_event.is_set():
            self._do_check(cfg)
            # 用可中断的等待，方便快速停止
            self.stop_event.wait(interval)
        self.log("监控已停止")
        self._set_status("● 已停止", "#999999")

    def stop_monitor(self):
        self.monitoring = False
        self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    IPv6MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
