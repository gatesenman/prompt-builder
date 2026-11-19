# 安装与卸载

## 安装
1. 运行 `PromptBuilder-Setup-2.7.0.exe`（正在运行的 2.6 会自动保存并退出；更早的版本由安装程序提示关闭）
2. 向导：欢迎 → 选择路径 → 勾选任务（桌面快捷方式 / 开机自启）→ 安装 → 完成
3. 默认路径：`%LOCALAPPDATA%\Programs\PromptBuilder`（无需管理员权限）
4. 覆盖安装 2.x 即可升级，AppId 不变

## 首次启动
- 程序常驻托盘；在任意输入框输入 `//` 唤醒浮框。再次双击程序图标会直接唤出已运行的窗口。
- 开机自启时只在托盘静默启动，不弹主窗口。
- 若从 2.x 升级：自动迁移你的模板，旧数据移到 `%LOCALAPPDATA%\PromptBuilder\legacy-2.x\`。
- 首次打开主窗口会显示 3 步新手引导（可跳过，之后在「帮助」里重新查看）。
- 主题默认跟随系统；2.5 默认的「深色」会改为「跟随系统」一次，之后你的选择会被保留。

## 卸载
- 「开始」菜单 → 提示词 Builder → 卸载，或「设置 → 应用 → 已安装的应用」
- 卸载不删除用户数据，可手动删除 `%LOCALAPPDATA%\PromptBuilder\`
- 如果开启过「以管理员身份启动」，卸载时会删除计划任务 `PromptBuilder\ElevatedStart`（会弹一次 UAC）

## 用户数据
`%LOCALAPPDATA%\PromptBuilder\`
- `prompts.json` 提示词库（含每个提示词的测试值）
- `settings.json` 设置
- `prompts.json.bak`、`backups\` 自动备份（最近 10 份）
- `logs\` 运行日志与崩溃记录
- `launch-intent.json` 管理员模式下普通启动转交给计划任务时的临时文件（自动删除）
- `legacy-2.x\` 2.x 旧数据备份（仅升级后存在）

## WebView2
启动时会检测 WebView2，缺失时弹窗说明并可直接打开微软下载页；也可手动安装 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

## 管理员窗口 / 安全软件
默认以普通权限运行，管理员窗口中不会弹出浮框；需要时在「设置 → 启动与权限」开启「以管理员身份启动」（只确认一次 UAC，之后通过计划任务启动）。被安全软件拦截时请将 `PromptBuilder.exe` 加入信任。详见 README「稳定性与限制」。
