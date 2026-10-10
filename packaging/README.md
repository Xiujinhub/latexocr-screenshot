# 打包说明（做成安装包）

把整个工具（界面 + 依赖 + pix2tex 模型权重）打包成 **安装包** 或 **免安装目录**，
目标机器上不需要 Python / conda / 网络。

## 一键打包

双击 `build_installer.bat`（或在仓库根目录执行它），它会依次：

1. 生成图标 `packaging/latexocr.ico`
2. PyInstaller 打包 → `dist\LaTeXOCR\`（约 950 MB，含模型权重）
3. 用打包结果跑一遍自检（`latexocr-cli.exe --selfcheck`），失败就停下
4. Inno Setup 编译 → `dist\LaTeXOCR-Setup-1.0.0.exe`

首次打包约 8~10 分钟（PyInstaller 分析 + 压缩），之后有缓存会快一些。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `latexocr.spec` | PyInstaller 配置：两个入口（GUI + 命令行）、模型文件、隐藏导入、体积裁剪 |
| `installer.iss` | Inno Setup 安装脚本：免管理员安装、开始菜单 / 桌面快捷方式、卸载项 |
| `version_info.txt` | exe 的版本资源（显示在文件属性里） |
| `make_icon.py` | 生成浅绿圆角 + 白色 `x²` 的图标 |
| `ChineseSimplified.isl` | 安装向导的中文语言包（取自 Inno Setup 官方 issrc 仓库） |
| `extra/使用说明.txt` | 装进安装目录的使用说明 |
| `extra/检查环境.bat` | 装进安装目录的自检入口（双击出结果） |
| `build_installer.bat` | 一键打包脚本 |
| `tools/` | 临时放下载物，可删除 |

## 依赖的打包工具

* **PyInstaller**：已在 `OCR` 环境里（6.16.0）。手动跑：

  ```bat
  D:\Anaconda\envs\OCR\python.exe -m PyInstaller packaging\latexocr.spec --noconfirm --clean
  ```

* **Inno Setup 6**（生成安装包，必需）：

  ```bat
  winget install --id JRSoftware.InnoSetup -e
  ```

  装好后 `ISCC.exe` 在 `%LOCALAPPDATA%\Programs\Inno Setup 6\`。
  编译安装包：

  ```bat
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
  ```

## 打进去了什么

* Python 3.9 运行时 + 全部依赖：torch(CPU)、transformers、timm、PyQt5、matplotlib、
  OpenCV、PyMuPDF、sympy、pynput 等；
* **pix2tex 模型权重**（`weights.pth` 102 MB + `image_resizer.pth` 19 MB）与
  `tokenizer.json`、`config.yaml` → 放在 `_internal/pix2tex/model/` 下，离线可用；
* MSVC 运行库（`vcruntime140.dll`、`msvcp140.dll`）→ 目标机器不用装 VC++ 运行库。

**没有**打进去的：

* **TeX Live**（几个 GB，不适合内置）。没装时预览会自动退回 matplotlib mathtext，
  识别、复制、历史这些功能都不受影响；装了 xelatex 就自动用真实 LaTeX 渲染。
* 各种没用到的库（paddleocr / easyocr / PyQt6 / PySide6 …）已排除，省了 1 GB 以上。

## 目标机器要求

* Windows 10 / 11 **64 位**；
* 无需 Python、无需 conda、**无需联网**、无需管理员（默认装到用户目录）；
* 安装位置：`%LOCALAPPDATA%\Programs\LaTeXOCR`；
* 运行时数据：`%LOCALAPPDATA%\LaTeXOCR\history.jsonl`（关闭软件时自动清空）。

## 怎么验证打包结果

```bat
rem 1) 绿色版直接自检（会真跑一遍识别）
dist\LaTeXOCR\latexocr-cli.exe --selfcheck

rem 2) 模拟干净电脑：把 PATH 收窄到只剩系统目录，再跑一次
set "PATH=C:\Windows\system32;C:\Windows"
dist\LaTeXOCR\latexocr-cli.exe --selfcheck
```

安装包也可以静默安装到临时目录做验证（装完会自动创建开始菜单快捷方式和卸载项）：

```bat
dist\LaTeXOCR-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /LANG=chinese /DIR=D:\test\LaTeXOCR
D:\test\LaTeXOCR\latexocr-cli.exe --selfcheck
D:\test\LaTeXOCR\unins000.exe /VERYSILENT
```

## 改版本号

升级时同步两处：`installer.iss` 的 `MyAppVersion`、`version_info.txt` 的
`filevers/prodvers/Version`，然后重新打包。
