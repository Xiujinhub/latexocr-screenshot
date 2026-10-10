# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：把工具、全部依赖和 pix2tex 模型权重打成一个绿色免安装目录。

用法（仓库根目录执行）::

    D:\\Anaconda\\envs\\OCR\\python.exe -m PyInstaller packaging\\latexocr.spec --noconfirm

产物：``dist\\LaTeXOCR\\``

* ``LaTeXOCR.exe``      —— 图形界面（双击即用，无控制台窗口）
* ``latexocr-cli.exe``  —— 命令行版，可 ``--selfcheck`` / ``--doctor`` / ``--json``
* ``_internal\\``       —— 依赖与模型权重（含 weights.pth 与 image_resizer.pth）
"""
import os

import pix2tex
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))          # noqa: F821
ICON = os.path.join(ROOT, 'packaging', 'latexocr.ico')
VERSION_FILE = os.path.join(ROOT, 'packaging', 'version_info.txt')
PIX2TEX_MODEL = os.path.join(os.path.dirname(os.path.abspath(pix2tex.__file__)), 'model')

# --- 必须一起带走的模型文件（pix2tex 按“包内相对路径”找它们） ---------------
datas = [
    (os.path.join(PIX2TEX_MODEL, 'settings', 'config.yaml'), 'pix2tex/model/settings'),
    (os.path.join(PIX2TEX_MODEL, 'settings', 'config-vit.yaml'), 'pix2tex/model/settings'),
    (os.path.join(PIX2TEX_MODEL, 'dataset', 'tokenizer.json'), 'pix2tex/model/dataset'),
    (os.path.join(PIX2TEX_MODEL, 'checkpoints', 'weights.pth'), 'pix2tex/model/checkpoints'),
    (os.path.join(PIX2TEX_MODEL, 'checkpoints', 'image_resizer.pth'), 'pix2tex/model/checkpoints'),
]

# --- 静态分析找不到、但运行时确实会用到的模块 -------------------------------
hiddenimports = [
    # pix2tex 的内部结构（models 是包，不是 models.py）
    'pix2tex.cli', 'pix2tex.models', 'pix2tex.models.utils', 'pix2tex.models.hybrid',
    'pix2tex.models.vit', 'pix2tex.models.transformer', 'pix2tex.utils',
    'pix2tex.dataset.transforms', 'pix2tex.dataset.latex2png',
    'pix2tex.model.checkpoints.get_latest_checkpoint',
    # 模型依赖
    'timm', 'timm.models.resnetv2', 'timm.models.layers', 'timm.models.registry',
    'timm.models.vision_transformer', 'timm.models.vision_transformer_hybrid',
    'timm.models.helpers', 'timm.models.features',
    'x_transformers', 'x_transformers.autoregressive_wrapper', 'einops', 'munch',
    'transformers', 'transformers.tokenization_utils_fast', 'tokenizers', 'safetensors',
    'albumentations', 'albumentations.pytorch', 'albumentations.core.serialization',
    'cv2', 'yaml', 'pandas.io.clipboard',
    # 界面与预览
    'PyQt5.sip', 'matplotlib.backends.backend_qt5agg', 'fitz', 'PIL.ImageGrab',
    'pynput.keyboard._win32', 'pynput.mouse._win32', 'pynput._util.win32',
]
hiddenimports += collect_submodules('latex2sympy2')            # noqa: F821

# --- 明确用不到的大块头，排掉能省 1GB 以上 ---------------------------------
excludes = [
    'paddle', 'paddleocr', 'paddle2onnx', 'easyocr', 'visualdl', 'onnx', 'onnxoptimizer',
    'PySide6', 'PyQt6', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
    'tkinter', 'IPython', 'jupyter', 'notebook', 'pdf2docx', 'docx', 'screeninfo',
    'wandb', 'tensorboard', 'torch.utils.tensorboard', 'pytest',
    'matplotlib.tests', 'matplotlib.testing', 'pandas.tests', 'numpy.tests',
]

common = dict(datas=datas, hiddenimports=hiddenimports, excludes=excludes,
              hookspath=[], hooksconfig={}, runtime_hooks=[], noarchive=False)

gui = Analysis([os.path.join(ROOT, 'screenshot_latex.py')], pathex=[ROOT], **common)
cli = Analysis([os.path.join(ROOT, 'latex_ocr_cli.py')], pathex=[ROOT], **common)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
              name='LaTeXOCR', debug=False, bootloader_ignore_signals=False, strip=False,
              upx=False, console=False, disable_windowed_traceback=False,
              icon=ICON, version=VERSION_FILE)

cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True,
              name='latexocr-cli', debug=False, bootloader_ignore_signals=False, strip=False,
              upx=False, console=True, icon=ICON, version=VERSION_FILE)

COLLECT(gui_exe, gui.binaries, gui.datas,
        cli_exe, cli.binaries, cli.datas,
        strip=False, upx=False, upx_exclude=[], name='LaTeXOCR')
