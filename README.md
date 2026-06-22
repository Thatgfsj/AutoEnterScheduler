# 定时自动回车 (AutoEnterScheduler)

> 凌晨睡觉，让工具帮你按回车。

## 这是什么

一个桌面小工具，用来**定时向指定窗口发送回车键（Enter）**。支持 Windows 和 Linux。

**我的使用场景**：AI 的额度每 5 个小时刷新一次。我希望在凌晨 5 点我睡觉的时候，工具自动帮我在终端里按回车，让 AI 继续跑起来，不用半夜爬起来手动操作。

## 功能

### 核心功能
- 🪟 **窗口多选** — 枚举所有可见窗口，支持 Ctrl/Shift 多选，适合同时管多个并行 Agent
- ⏰ **定时触发** — 设一个时刻（比如 05:00），到点自动发，每天循环
- 🔁 **重复发送** — 可以设置"到点后连续发 N 次，每次间隔 M 秒"
- 🎯 **多窗口串行** — 多个目标窗口依次处理，窗口间有可调间隔，避免前台焦点互相打架
- 🧪 **立即测试** — 点击后立刻向所有选中窗口各发一次回车，验证是否生效
- ▶️ **立即执行一次** — 不改变定时计划，立即发一次回车
- 🔄 **前台恢复** — 发完后自动把原来的前台窗口还给你，不打扰

### v1.1.0 新增
- 💾 **配置自动保存/加载** — 关闭时记住窗口选择、时间设置，下次打开自动恢复
- ⏱️ **倒计时显示** — 状态栏实时显示"距下次触发还有 X 时 X 分 X 秒"
- 📝 **日志文件** — 同时保存到 `log.txt`，方便排查问题
- 🔄 **窗口自动刷新** — 每 30 秒自动刷新窗口列表（保留选择）
- 🧹 **清空选择** — 一键清空已选窗口

### v1.1.1 修复
- 🐛 **修复定时发送失败** — 定时任务的发键参数顺序错误，导致发送时模式和间隔参数互换
- 🐛 **修复窗口选择丢失** — 点击时间/次数等输入框后，已选窗口被意外清空

### v1.2.0 修复 & 新增
- 🐛 **修复手动测试/立即执行的发键参数错误** — 同样的参数顺序问题也存在于手动测试和立即执行功能
- 🐧 **新增 Linux 版本** — 使用 xdotool 实现，支持 AppImage 打包

## 两种发键模式

| 模式 | 适用场景 | 说明 |
|------|---------|------|
| **前台注入**（默认） | Windows Terminal、Claude CLI、浏览器、Electron 应用 | 把目标窗口切到前台，用 `keybd_event` 发送真实键盘事件 |
| **后台投递** | 普通 Win32 程序（记事本、部分老软件） | 用 `PostMessage(WM_KEYDOWN)` 后台发送，不抢焦点 |

工具会根据窗口类名自动选择模式，也可以手动指定。

> 为什么 Claude/Terminal 不能后台发？因为它们用的是 XAML + DirectComposition 渲染，根本不走 Win32 消息循环，`PostMessage` 发过去会被直接丢弃。

## 截图

![主界面](screenshot.png)

## 下载

### Windows
去 [Releases](https://github.com/Thatgfsj/AutoEnterScheduler/releases) 下载最新的 `.exe`，单文件免安装，双击即可运行。

### Linux
下载 AppImage 文件，添加执行权限后直接运行：

```bash
chmod +x AutoEnterScheduler-*.AppImage
./AutoEnterScheduler-*.AppImage
```

**依赖**：需要安装 `xdotool`：
```bash
# Debian/Ubuntu
sudo apt install xdotool

# Arch Linux
sudo pacman -S xdotool

# Fedora
sudo dnf install xdotool
```

## 使用方法

1. 双击 `AutoEnterScheduler.exe`
2. 在 ① 区点"刷新窗口列表"，按 **Ctrl/Shift** 多选你要发回车的窗口
3. 在 ② 区设置触发时间（默认凌晨 5 点）、发送次数、间隔
4. 点 **"立即测试发送一次"**，确认目标窗口有反应
5. 点 **"▶ 启动"**，最小化去睡觉。到点自动触发，发完自动排明天

## 技术栈

### Windows 版
- **语言**: Python 3.11
- **GUI**: tkinter (ttk)
- **发键**: ctypes + Win32 API (`keybd_event` / `PostMessageW` / `AttachThreadInput`)
- **图标**: Pillow 程序化生成
- **打包**: PyInstaller (--onefile --windowed)

### Linux 版
- **语言**: Python 3.11
- **GUI**: tkinter (ttk)
- **发键**: xdotool (X11 窗口自动化工具)
- **打包**: PyInstaller + AppImage

## 开发

### Windows

```bash
# 安装依赖
pip install Pillow PyInstaller

# 生成图标
python make_icon.py

# 打包
pyinstaller --noconfirm --onefile --windowed --name AutoEnterScheduler --icon icon.ico --add-data "icon.ico;." auto_enter.py
```

### Linux

```bash
# 安装依赖
sudo apt install python3-tk xdotool
pip install PyInstaller

# 直接运行
python3 auto_enter_linux.py

# 打包成 AppImage
chmod +x build_appimage.sh
./build_appimage.sh
```

## 许可

MIT License

## 作者

[Thatgfsj](https://github.com/Thatgfsj)
