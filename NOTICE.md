# 第三方组件与许可

本项目自身只是把这些组件组合起来，二进制分发包里包含以下第三方内容，特此说明来源与许可。

## 直接依赖（随安装包一起分发）

| 组件 | 许可 | 用途 |
| --- | --- | --- |
| [pix2tex](https://github.com/lukas-blecher/LaTeX-OCR) (`pix2tex` 0.1.4) 与其模型权重 `weights.pth` / `image_resizer.pth` | MIT | 公式识别模型 |
| PyQt5 | GPL-3.0（或商业许可） | 图形界面 |
| PyMuPDF (`fitz`) | **AGPL-3.0**（或商业许可） | 预览把 PDF 转 PNG |
| PyTorch / torchvision | BSD-3-Clause | 推理运行时 |
| timm / x-transformers / einops | Apache-2.0 / MIT | 模型结构 |
| transformers / tokenizers | Apache-2.0 | 分词器 |
| albumentations | MIT | pix2tex 依赖 |
| OpenCV (`opencv-python`) | Apache-2.0 | 图像预处理 |
| matplotlib | PSF-based (BSD 兼容) | 预览降级渲染 |
| pynput | LGPL-3.0 | 全局快捷键 |
| sympy / latex2sympy2 | BSD-3-Clause / MIT | `Sympy` 输出格式 |
| Python 3.9 运行时 | PSF License | 运行时 |

## 打包/安装工具（仅构建时使用，不随程序分发）

* [PyInstaller](https://pyinstaller.org/)（GPL-2.0 + 例外条款，允许打包专有程序）
* [Inno Setup](https://jrsoftware.org/isinfo.php)（修改版 BSD 许可）
* `packaging/ChineseSimplified.isl`：Inno Setup 官方仓库 `jrsoftware/issrc` 的中文语言文件

## 注意

因为 PyQt5（GPL-3.0）与 PyMuPDF（AGPL-3.0）都被打包进安装包，**对外分发二进制时，
本项目也需要以兼容的许可证（通常选 GPL-3.0 或 AGPL-3.0）公开源码**。
如果不想受此约束，可以改用 PySide6（LGPL）并去掉/替换 PyMuPDF（预览只用 matplotlib）。
