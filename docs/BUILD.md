# 构建说明

## 环境
- Windows 10/11 x64，Python 3.10+（推荐 3.11）
- Inno Setup 6（找不到时脚本会尝试便携安装到 `tools\InnoSetup`）

## 一键构建
```bat
build-installer.bat
```
内部调用 `scripts/build_all.ps1`（可加 `-Verify` 运行打包后自检，`-Clean` 成功后删除 `.venv-build`、`tools`、`build`、`dist`）：

1. 预检必需文件（`web\*`、`data\examples.json`、全部 `src\*` 模块），并检查 spec 的 hiddenimports 与 iss / api.py 版本号一致
2. 创建/复用 `.venv-build`，安装 `requirements.txt`（pywebview 6.2.1 固定版本、pystray、Pillow、comtypes）+ PyInstaller 6.11.1；卸载 keyboard / pyperclip / pywin32（已不再使用）
   然后运行单元测试 `python -m unittest discover -s src\tests`
3. **预生成 comtypes 的 UIAutomation 包装模块**（打包后的程序无法在运行时生成，缺失时光标定位退回 GetGUIThreadInfo / MSAA / 鼠标）
4. `PyInstaller PromptBuilder.spec` → `dist\PromptBuilder\`（onedir，`_internal`）；校验 web 资源与所有本地模块确实打进包里
5. `ISCC installer\PromptBuilder.iss` → `dist_installer\PromptBuilder-Setup-2.7.0.exe`，复制到根目录并删除旧版本 Setup
6. 无 Inno 时退回 `installer\setup_main.py` 向导式 Setup

## 验证
```powershell
dist\PromptBuilder\PromptBuilder.exe --selftest selftest.json
dist\PromptBuilder\PromptBuilder.exe --verify-ui verify-ui.json   # 真正打开主窗口和浮框，确认两个页面都显示正常
dist\PromptBuilder\PromptBuilder.exe --smoke smoke.json --seconds 8
```
- selftest：模块导入、变量语法、WebView2 运行时、web 资源、低级键盘钩子安装、// 识别、UIA 可用性、光标捕获、剪贴板快照/恢复往返、界面地址（不带参数、文件与引用资源齐全）。verify-ui：按正常启动方式加载两个窗口，检查页面标记 `window.__pbPage`，结果含实际 URL；也可设环境变量 `PB_VERIFY_UI=输出.json` 后通过开始菜单快捷方式启动来验证。设置环境变量 `PB_SELFTEST_MIGRATE_DIR` 可同时测试 2.x 数据迁移。
- smoke：隐藏启动主窗口与浮框窗口，记录加载事件与钩子状态后自动退出（独立互斥名，不影响正在运行的实例）。
- `PROMPTBUILDER_DATA_DIR` 可把数据目录指到临时目录。
- `PB_POPUP_MODE=classic` 强制使用旧的显示/隐藏方式（用于对比测速；默认 `fast` = 预渲染 + DWM 隐身停放）。
- 浮框延迟测试：`python pb_e2e2.py dist\PromptBuilder\PromptBuilder.exe out.json`（只向自己创建的测试窗口发送按键；统计「成为前台」与「像素完全画好」两种耗时）。

## 开发运行
```powershell
powershell -File scripts\dev_run.ps1
```

## 源码结构
```
src/
  app.py            主程序：窗口、托盘、单实例（再次启动=唤出窗口，普通/管理员实例互通）、管理员模式转交、WebView2 检测、--selftest / --smoke / --verify-ui
  applog.py         日志与崩溃记录（logs\promptbuilder.log、crash.log）
  atomic_io.py      原子写入 + .bak + backups\ 快照 + 损坏恢复
  api.py            主窗口 JS 接口
  prompt_syntax.py  变量语法：解析 / 校验 / 渲染 / 统计（唯一真源）
  prompts_store.py  提示词库、2.x 迁移、导入导出
  settings_store.py 设置
  quickpick.py      // 浮框控制器（预渲染 + DWM 隐身停放）+ 浮框 JS 接口
  textcheck.py      插入前核对光标前是否为 //（Edit/RichEdit 直接读取、其余 UI Automation）+ 输入法状态判断
  elevation.py      管理员模式：计划任务 XML、注册/删除（UAC 一次）、转交启动、降权重启
  keyhook.py        低级键盘钩子（只监听不拦截）+ “//” 识别状态机 SlashDetector（看门狗自动重装）
  caret.py          光标定位（GetGUIThreadInfo → MSAA → UIA → 鼠标）与浮框摆放
  winput.py         SendInput、焦点切换、剪贴板快照/恢复、粘贴
  winapi.py         ctypes Win32 绑定
  tray_icon.py / autostart.py / paths.py
  tests/            单元测试（解析器边界情况、存储/迁移/恢复、2.6 核对/设置升级/撤销删除/任务 XML）
web/  index.html + quick.html，css/{base,app,quick}.css（base = 设计令牌：间距/字号/圆角、深浅两套配色），js/{app,quick,md,icons}.js
data/examples.json  两个示例提示词
```
