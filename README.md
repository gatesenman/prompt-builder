# PromptBuilder

**2.12.8** · 提示词构建与管理工作台：编写、组织、导入技能包，并可选接入大模型做生成与润色。

## 功能特性

- 桌面工作台管理提示词与技能（见根目录 README 与 `docs/`）。
- 可用 `PromptBuilder-skills-import.json` 导入技能包。
- Python 后端 + Web 界面；Windows 下可用 `启动.bat` 或 `run.py`。

## 技术栈

- Python
- Web 前端（`web/`）
- 版本见 `VERSION.txt`（2.12.8）

## 从源码运行

本仓库在根目录即可运行（`run.py`、`requirements.txt`、`src/`、`web/`）。不包含现成安装包。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Windows 也可双击 `启动.bat`。安装与构建细节见 `docs/INSTALL.md`、`docs/BUILD.md`。

## 文档

- [README](README.md)
- [安装](docs/INSTALL.md)
- [构建](docs/BUILD.md)
- [更新日志](docs/CHANGELOG.md)

## 贡献

欢迎通过 Issue 和 Pull Request 参与，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。参与时请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

本仓库尚未附带 LICENSE 文件，许可证未指定。

---

## English

# PromptBuilder

**2.12.8** · A prompt building and management workbench: write and organize prompts, import skill packs, and optionally call an LLM to generate or refine them.

## Features

- Desktop workbench for prompts and skills (see the root README and `docs/`).
- Import skill packs via `PromptBuilder-skills-import.json`.
- Python backend plus a web UI; on Windows you can use `启动.bat` or `run.py`.

## Tech stack

- Python
- Web 前端（`web/`）
- 版本见 `VERSION.txt`（2.12.8）

## Getting started

You can run from the repository root (`run.py`, `requirements.txt`, `src/`, `web/`). Ready-made installers are not included.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

On Windows you can also double-click `启动.bat`. See `docs/INSTALL.md` and `docs/BUILD.md` for install and build details.

## Documentation

- [README](README.md)
- [安装](docs/INSTALL.md)
- [构建](docs/BUILD.md)
- [更新日志](docs/CHANGELOG.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately via [SECURITY.md](SECURITY.md). This project follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

No LICENSE file is included in this repository; the license is unspecified.
