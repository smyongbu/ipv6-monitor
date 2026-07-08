# -*- coding: utf-8 -*-
"""
公网 IPv6 监控工具 - 图形界面版

功能:
  - 配置 QQ 邮箱与授权码
  - 选择本机网卡 / IPv6 地址
  - 自定义检测间隔
  - 启动 / 停止自动监控
  - 立即检测一次
  - 检测到 IPv6 变化时自动发送邮件通知
  - 实时日志显示
"""

import ipaddress
import json
import os
import platform
import socket
import ssl
import subprocess
import threading
import time
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import requests


# ----------------------------------------------------------------------------
# 配置文件
# ----------------------------------------------------------------------------
CONFIG_FILE = "last_ipv6.txt"


def load_config():
    """从配置文件中加载配置信息。"""
    config = {
        "QQ_EMAIL": "",
        "QQ_PASSWORD": "",
        "LAST_IPV6": "",
        "SELECTED_IPV6": "",
    }

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
            elif line.startswith("SELECTED_IPV6:"):
                config["SELECTED_IPV6"] = line.split(":", 1)[1].strip()

    return config


def save_config(config):
    """保存配置信息到文件。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("# 邮箱配置\n")
        f.write(f"QQ_EMAIL: {config['QQ_EMAIL']}\n")
        f.write(f"QQ_PASSWORD: {config['QQ_PASSWORD']}\n")
        f.write("# 上次检测到的公网 IPv6 地址\n")
        f.write(f"LAST_IPV6: {config['LAST_IPV6']}\n")
        f.write("# 选中的本机 IPv6 地址\n")
        f.write(f"SELECTED_IPV6: {config.get('SELECTED_IPV6', '')}\n")


def _is_usable_ipv6(address):
    try:
        ip = ipaddress.IPv6Address(address.split("%", 1)[0])
    except ValueError:
        return False

    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_private
    )


def _normalize_powershell_json(output):
    if not output.strip():
        return []
    data = json.loads(output)
    if isinstance(data, dict):
        return [data]
    return data


def _add_ipv6_choice(choices, seen, interface, ip):
    ip = ip.split("(", 1)[0].strip()
    if "%" in ip:
        ip = ip.split("%", 1)[0]
    if not _is_usable_ipv6(ip) or ip in seen:
        return
    seen.add(ip)
    choices.append({"interface": interface.strip() or "本机", "ip": ip})


def _get_ipv6_choices_from_ipconfig(seen):
    choices = []
    current_interface = ""

    try:
        result = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            check=False,
        )
    except Exception:
        return choices

    if result.returncode != 0:
        return choices

    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if not raw_line.startswith(" ") and stripped.endswith(":"):
            current_interface = stripped[:-1]
            continue

        if ":" not in stripped or "IPv6" not in stripped:
            continue
        if "Link-local" in stripped or "本地链接" in stripped:
            continue

        ip = stripped.split(":", 1)[1].strip()
        _add_ipv6_choice(choices, seen, current_interface, ip)

    return choices


def get_local_ipv6_choices():
    """获取本机可用于公网访问的 IPv6 地址列表。"""
    choices = []
    seen = set()

    if platform.system().lower() == "windows":
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "Get-NetIPAddress -AddressFamily IPv6 "
                "| Where-Object { $_.AddressState -eq 'Preferred' } "
                "| Select-Object InterfaceAlias,IPAddress,PrefixOrigin,SuffixOrigin "
                "| ConvertTo-Json -Compress"
            ),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                for item in _normalize_powershell_json(result.stdout):
                    ip = item.get("IPAddress", "").strip()
                    interface = item.get("InterfaceAlias", "未知网卡")
                    _add_ipv6_choice(choices, seen, interface, ip)
        except Exception:
            pass

    if not choices and platform.system().lower() == "windows":
        choices.extend(_get_ipv6_choices_from_ipconfig(seen))

    if not choices:
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET6):
                ip = info[4][0]
                _add_ipv6_choice(choices, seen, "本机", ip)
        except Exception:
            pass

    return choices


def get_public_ipv6(source_ip=None):
    """获取公网 IPv6 地址；传入 source_ip 时从指定本机 IPv6 发出请求。"""
    if source_ip:
        return get_public_ipv6_from_source(source_ip)

    response = requests.get("https://api64.ipify.org", timeout=10)
    response.raise_for_status()
    return response.text.strip()


def get_public_ipv6_from_source(source_ip):
    """通过指定的本机 IPv6 地址建立 HTTPS 连接并查询公网地址。"""
    host = "api6.ipify.org"
    port = 443
    last_error = None

    infos = socket.getaddrinfo(host, port, socket.AF_INET6, socket.SOCK_STREAM)
    for family, socktype, proto, _, sockaddr in infos:
        raw_sock = None
        try:
            raw_sock = socket.socket(family, socktype, proto)
            raw_sock.settimeout(10)
            raw_sock.bind((source_ip, 0, 0, 0))
            raw_sock.connect(sockaddr)

            context = ssl.create_default_context()
            with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                request = (
                    f"GET / HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "User-Agent: IPv6Monitor/1.0\r\n"
                    "Connection: close\r\n\r\n"
                )
                tls_sock.sendall(request.encode("ascii"))

                chunks = []
                while True:
                    chunk = tls_sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)

            raw_response = b"".join(chunks).decode("utf-8", errors="replace")
            header, _, body = raw_response.partition("\r\n\r\n")
            status_line = header.splitlines()[0] if header else ""
            if " 200 " not in status_line:
                raise RuntimeError(status_line or "公网 IPv6 查询失败")
            return body.strip()
        except Exception as e:
            last_error = e
            if raw_sock is not None:
                try:
                    raw_sock.close()
                except OSError:
                    pass

    raise RuntimeError(f"使用所选 IPv6 查询失败: {last_error}")


def send_email(config, new_ipv6):
    """发送邮件通知 IPv6 地址变更。"""
    smtp_server = "smtp.qq.com"
    smtp_port = 587

    message = MIMEText(new_ipv6, "plain", "utf-8")
    message["From"] = config["QQ_EMAIL"]
    message["To"] = config["QQ_EMAIL"]
    message["Subject"] = Header("公网 IPv6 地址变更通知", "utf-8")

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
        self.root.geometry("760x640")
        self.root.minsize(660, 520)

        self.monitoring = False
        self.worker = None
        self.stop_event = threading.Event()
        self.ip_choices = []

        cfg = load_config()
        self.email_var = tk.StringVar(value=cfg["QQ_EMAIL"])
        self.password_var = tk.StringVar(value=cfg["QQ_PASSWORD"])
        self.interval_var = tk.StringVar(value="60")
        self.selected_ipv6_var = tk.StringVar(value=cfg["SELECTED_IPV6"])
        self.last_ipv6 = cfg["LAST_IPV6"]
        self.current_ipv6_var = tk.StringVar(value="尚未检测")
        self.last_ipv6_var = tk.StringVar(value=self.last_ipv6 or "无记录")
        self.status_var = tk.StringVar(value="● 已停止")

        self._build_ui()
        self.refresh_ip_choices(initial=True)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

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

        ttk.Label(cfg_frame, text="检测间隔（秒）：").grid(
            row=2, column=0, sticky="e", **pad
        )
        ttk.Spinbox(
            cfg_frame, from_=1, to=86400, textvariable=self.interval_var, width=10
        ).grid(row=2, column=1, sticky="w", **pad)

        ttk.Button(cfg_frame, text="保存配置", command=self._save).grid(
            row=2, column=2, sticky="e", **pad
        )

        cfg_frame.columnconfigure(1, weight=1)

        net_frame = ttk.LabelFrame(self.root, text="网卡 / IPv6 选择")
        net_frame.pack(fill="x", padx=12, pady=6)

        ttk.Label(net_frame, text="使用地址：").grid(row=0, column=0, sticky="e", **pad)
        self.ip_combo = ttk.Combobox(
            net_frame,
            textvariable=self.selected_ipv6_var,
            state="readonly",
        )
        self.ip_combo.grid(row=0, column=1, sticky="we", **pad)

        ttk.Button(net_frame, text="刷新", command=self.refresh_ip_choices).grid(
            row=0, column=2, sticky="e", **pad
        )
        net_frame.columnconfigure(1, weight=1)

        st_frame = ttk.LabelFrame(self.root, text="状态")
        st_frame.pack(fill="x", padx=12, pady=6)

        ttk.Label(st_frame, text="当前公网 IPv6：").grid(
            row=0, column=0, sticky="e", **pad
        )
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
        st_frame.columnconfigure(1, weight=1)

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

        ttk.Button(btn_frame, text="🔍 立即检测", command=self.check_once).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="✉ 发送测试邮件", command=self.send_test).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(
            side="right", padx=4
        )

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
        """线程安全地写日志。"""

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

    def _selected_source_ip(self):
        value = self.selected_ipv6_var.get().strip()
        if not value:
            return ""
        return value.rsplit(" - ", 1)[-1].strip()

    def _current_config(self):
        return {
            "QQ_EMAIL": self.email_var.get().strip(),
            "QQ_PASSWORD": self.password_var.get().strip(),
            "LAST_IPV6": self.last_ipv6,
            "SELECTED_IPV6": self._selected_source_ip(),
        }

    def _validate_config(self):
        cfg = self._current_config()
        if not cfg["QQ_EMAIL"] or not cfg["QQ_PASSWORD"]:
            messagebox.showwarning("提示", "请先填写 QQ 邮箱和授权码！")
            return None
        if not cfg["SELECTED_IPV6"]:
            messagebox.showwarning("提示", "请先选择一个可用的本机 IPv6 地址！")
            return None
        return cfg

    def _save(self):
        save_config(self._current_config())
        self.log("配置已保存")
        messagebox.showinfo("提示", "配置已保存")

    def refresh_ip_choices(self, initial=False):
        previous_ip = self._selected_source_ip() or self.selected_ipv6_var.get().strip()
        self.ip_choices = get_local_ipv6_choices()
        display_values = [
            f"{item['interface']} - {item['ip']}" for item in self.ip_choices
        ]
        self.ip_combo["values"] = display_values

        selected_value = ""
        for value in display_values:
            if value.endswith(previous_ip):
                selected_value = value
                break
        if not selected_value and display_values:
            selected_value = display_values[0]

        self.selected_ipv6_var.set(selected_value)

        if not initial:
            self.log(f"已刷新 IPv6 列表，找到 {len(display_values)} 个可用地址")
        elif display_values:
            self.log(f"已找到 {len(display_values)} 个可用 IPv6 地址")
        else:
            self.log("没有找到可用的公网 IPv6 地址，请确认网卡已获得 IPv6")

    # ------------------------------------------------------------------
    # 业务逻辑
    # ------------------------------------------------------------------
    def _do_check(self, cfg, send_on_change=True):
        """执行一次检测，返回当前 IPv6；失败返回 None。在工作线程中调用。"""
        source_ip = cfg.get("SELECTED_IPV6") or None
        try:
            current = get_public_ipv6(source_ip)
        except Exception as e:
            if source_ip:
                current = source_ip
                self.log(f"外部 IPv6 查询失败，改用所选本机公网 IPv6: {e}")
            else:
                self.log(f"获取公网 IPv6 失败: {e}")
                return None

        self.root.after(0, lambda: self.current_ipv6_var.set(current))
        self.log(f"当前公网 IPv6: {current}")
        if source_ip:
            self.log(f"本次使用本机 IPv6: {source_ip}")

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
        threading.Thread(target=self._do_check, args=(cfg,), daemon=True).start()

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
