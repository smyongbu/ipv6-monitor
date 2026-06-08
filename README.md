# IPv6 Monitor · 公网 IPv6 监控工具

一个带图形界面的小工具：定时检测本机的公网 IPv6 地址，发生变化时通过 QQ 邮箱自动发送邮件通知。

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20arm64-blue)

## 功能

- 图形界面配置 QQ 邮箱与授权码
- 自定义检测间隔
- 开始 / 停止 自动监控
- 立即检测、发送测试邮件
- 带时间戳的实时日志
- IPv6 变化时自动邮件通知

## 下载（免安装，独立运行）

前往 [**Releases**](../../releases) 页面下载对应平台的独立可执行文件，无需安装 Python：

| 平台 | 文件 |
|------|------|
| Windows (x64) | `IPv6Monitor-windows.exe` |
| macOS (Apple Silicon / arm64) | `IPv6Monitor-macos-arm64.zip` |

> macOS 首次打开若提示“无法验证开发者”，请在“系统设置 → 隐私与安全性”中点击“仍要打开”，或在终端执行 `xattr -dr com.apple.quarantine IPv6Monitor.app`。

## 从源码运行

```bash
pip install -r requirements.txt
python IPv6监控界面.py
```

## QQ 邮箱授权码

“授权码”不是邮箱登录密码。请在 QQ 邮箱 → 设置 → 账户 → 开启 SMTP 服务后获取授权码填入。

## 自行打包

```bash
pip install pyinstaller requests
pyinstaller --onefile --windowed --name IPv6Monitor IPv6监控界面.py
```

构建产物位于 `dist/` 目录。也可直接由仓库的 GitHub Actions 自动为 Windows 与 macOS arm64 打包并发布 Release。
