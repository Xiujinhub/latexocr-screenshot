# -*- coding: utf-8 -*-
"""公式截图识别工具（PyQt5 + pix2tex）。

用法::

    python screenshot_latex.py                # 启动后按 Ctrl+Alt+M 截图
    python screenshot_latex.py --hotkey "<ctrl>+<shift>+s"

功能：
* 全局快捷键呼出截图遮罩，鼠标框选公式区域后自动识别；
* 结果可直接复制为 Raw / ``$...$`` / ``$$...$$`` / Sympy 形式；
* 内置历史记录与 LaTeX 预览，支持“重试”换一个采样结果；
* 框选的截图会存到 ``output/captures``，方便事后复查。

截图坐标说明：遮罩铺满整个虚拟桌面，截取的图像是物理像素，而 Qt 控件可能是逻辑像素
（高 DPI 缩放），因此统一用 ``图像宽 / 控件宽`` 的比例做坐标映射，避免缩放后选区错位。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime

from PIL import Image, ImageGrab

import latex_render
from latex_ocr_core import (DEFAULT_SAMPLES, DEFAULT_TEMPERATURE, LatexOcrEngine,
                            LatexOcrError, checkpoint_paths, describe_environment,
                            grab_virtual_desktop, resolution_hint, split_latex_rows)

from PyQt5.QtCore import (QObject, QPoint, QRect, QSize, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt5.QtGui import (QColor, QCursor, QFont, QImage, QKeySequence, QPainter,
                         QPen, QPixmap)
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QMainWindow,
                             QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                             QShortcut, QSpinBox, QSplitter, QVBoxLayout, QWidget)

APP_TITLE = '公式截图识别 (LaTeX-OCR)'
DEFAULT_HOTKEY = '<ctrl>+<alt>+m'
LOCAL_SHORTCUT = 'Ctrl+Alt+M'

#: 框选时向外扩的像素（避免把下标/分数线切掉），显示坐标下的像素数
SELECTION_MARGIN = 6

#: 小于这个尺寸的框选视为误触（显示坐标下的像素数）
MIN_SELECTION = 8

FORMATS = ['Raw', 'LaTeX-$', 'LaTeX-$$', 'Sympy']

#: 界面统一字体（走 QFont；样式表里不要再写 font-family，否则会盖掉 setFont）
UI_FONT = 'Microsoft YaHei UI'
UI_FONT_SIZE = 9

# ---------------------------------------------------------------------------
# 配色与主题（浅绿 / 简洁）
# ---------------------------------------------------------------------------
COLOR_BG = '#f3faf5'          # 窗口底色
COLOR_CARD = '#ffffff'        # 卡片、输入框
COLOR_BORDER = '#d7ecdf'      # 常规边框
COLOR_ACCENT = '#4aa678'      # 主色（按钮、强调）
COLOR_ACCENT_HI = '#3d8f66'   # 悬浮 / 按下
COLOR_ACCENT_PRESS = '#357c58'
COLOR_ACCENT_BG = '#e8f5ee'   # 浅绿底（选中、hover）
COLOR_TEXT = '#24402f'        # 主文字
COLOR_MUTED = '#7a9a87'       # 次要文字

#: 全局样式表：轻量、平面、圆角，主色只用一种绿
_QSS_TEMPLATE = """
QWidget {
    background: %(bg)s;
    color: %(text)s;
}
QMainWindow, QDialog { background: %(bg)s; }
QLabel { background: transparent; }
QLabel#titleLabel { color: %(accent)s; font-size: 16px; font-weight: bold; }
QLabel#hintLabel { color: %(muted)s; }
QLabel#sectionLabel { color: %(accent)s; font-weight: bold; }
QLabel#previewStatus { color: %(muted)s; font-size: 11px; }
QLabel#previewCard {
    background: %(card)s; border: 1px solid %(border)s; border-radius: 8px;
}
QFrame#separator { border: none; border-top: 1px solid %(border)s; max-height: 1px; }

QPushButton {
    background: %(card)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 6px; padding: 6px 12px;
}
QPushButton:hover { background: %(accent_bg)s; border-color: %(accent)s; }
QPushButton:pressed { background: #dcefe4; }
QPushButton:disabled { color: #a9bfb2; background: #f7fbf8; border-color: #e6f0e9; }
QPushButton#primaryButton {
    background: %(accent)s; color: #ffffff; border: 1px solid %(accent)s;
    font-weight: bold; padding: 7px 14px;
}
QPushButton#primaryButton:hover { background: %(accent_hi)s; border-color: %(accent_hi)s; }
QPushButton#primaryButton:pressed { background: %(accent_press)s; }
QPushButton#primaryButton:disabled {
    background: #c4ddcd; border-color: #c4ddcd; color: #f3f9f5;
}

QPlainTextEdit {
    background: %(card)s; border: 1px solid %(border)s; border-radius: 6px;
    padding: 6px 8px; selection-background-color: %(accent_bg)s; selection-color: %(text)s;
}
QPlainTextEdit:focus { border-color: %(accent)s; }
/* 只读的“将复制的内容”用稍浅的字色，层级更清楚 */
QPlainTextEdit#formattedEdit { color: #46685a; }
/* 注意：这里不要再写 font-family —— 样式表会盖掉 setFont()，导致 LaTeX 变成宋体。
   界面字体统一走 QFont（见 UI_FONT），等宽的代码框由 setFont(Consolas) 指定。 */

QComboBox {
    background: %(card)s; border: 1px solid %(border)s; border-radius: 6px;
    padding: 4px 8px; min-width: 86px;
}
QComboBox:hover { border-color: %(accent)s; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow {
    image: none; width: 0; height: 0; margin-right: 6px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid %(muted)s;
}
QComboBox QAbstractItemView {
    background: %(card)s; border: 1px solid %(border)s; padding: 2px;
    outline: none; selection-background-color: %(accent_bg)s; selection-color: %(text)s;
}

QSpinBox, QDoubleSpinBox {
    background: %(card)s; border: 1px solid %(border)s; border-radius: 6px; padding: 4px 6px;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: %(accent)s; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; border: none; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid %(border)s;
    border-radius: 3px; background: %(card)s;
}
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

QListWidget {
    background: %(card)s; border: 1px solid %(border)s; border-radius: 6px;
    outline: none; padding: 2px;
}
QListWidget::item { padding: 5px 6px; border-radius: 4px; }
QListWidget::item:hover { background: %(accent_bg)s; }
QListWidget::item:selected { background: %(accent_bg)s; color: %(accent_hi)s; }

QStatusBar { background: %(accent_bg)s; color: %(accent_hi)s; border-top: 1px solid %(border)s; }
QStatusBar::item { border: none; }

QToolTip {
    background: %(card)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 6px;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cfe6d9; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollArea { border: none; background: %(bg)s; }
"""

THEME = _QSS_TEMPLATE % {
    'bg': COLOR_BG, 'card': COLOR_CARD, 'border': COLOR_BORDER,
    'accent': COLOR_ACCENT, 'accent_hi': COLOR_ACCENT_HI,
    'accent_press': COLOR_ACCENT_PRESS, 'accent_bg': COLOR_ACCENT_BG,
    'text': COLOR_TEXT, 'muted': COLOR_MUTED,
}

#: 主行裁剪策略：界面文字 → 引擎参数（True / 'auto' / False）
TRIM_CHOICES = [('总是只保留主行（推荐）', True),
                ('自动（结果不干净时才裁）', 'auto'),
                ('关闭（矩阵 / 分段函数）', False)]
#: 命令行字符串 → 引擎参数
TRIM_VALUES = {'on': True, 'auto': 'auto', 'off': False}
MAX_HISTORY = 200
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff')


def trim_index(mode) -> int:
    """把引擎参数（True / 'auto' / False）映射成下拉框下标。"""
    values = [value for _label, value in TRIM_CHOICES]
    return values.index(mode) if mode in values else 0


# -- 小工具：统一风格的分节标题 / 分隔线 / 表单标签 -------------------------
def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName('sectionLabel')
    return label


def _form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName('hintLabel')
    return label


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName('separator')
    line.setFrameShape(QFrame.HLine)
    return line


def default_outdir(base: str) -> str:
    """默认的历史记录目录。

    源码运行时用脚本目录下的 output；打包安装后程序装在 Program Files 之类的地方
    （那里不可写），所以改用用户目录 %LOCALAPPDATA%\\LaTeXOCR。
    """
    if getattr(sys, 'frozen', False):
        root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(root, 'LaTeXOCR')
    return os.path.join(base, 'output')


def _render_sample_formula(path: str):
    """画一张 $x^{2}+y^{2}=z^{2}$ 的图，用于自检（不依赖 TeX Live）。"""
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(6, 1.4), dpi=150)
    figure.text(0.02, 0.5, r'$x^{2}+y^{2}=z^{2}$', fontsize=30, va='center')
    figure.savefig(path, dpi=150, facecolor='white')
    plt.close(figure)
    return Image.open(path)


def enable_dpi_awareness() -> None:
    """让进程感知 DPI，避免 Windows 位图拉伸导致的模糊。

    使用“系统级 DPI 感知”（等级 1）：配合 Qt 的高 DPI 缩放，界面清晰，且整个虚拟桌面
    与截图之间存在统一缩放比，选区映射仍然准确。
    """
    if sys.platform != 'win32':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class Signals(QObject):
    """跨线程信号总线：工作线程只发信号，界面线程负责更新。"""

    progress = pyqtSignal(str)
    model_loaded = pyqtSignal(bool, str)
    recognized = pyqtSignal(object, str, float)
    recognize_failed = pyqtSignal(str)
    hotkey_fired = pyqtSignal()


class GlobalHotkey:
    """基于 pynput 的全局快捷键（注册失败不影响其它功能）。"""

    def __init__(self, combo: str, on_fire):
        self.combo = combo
        self._on_fire = on_fire
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.GlobalHotKeys({self.combo: self._on_fire})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


class RegionSelector(QWidget):
    """全屏遮罩：冻结屏幕画面，让用户拖拽框选公式区域。"""

    captured = pyqtSignal(object)     # PIL.Image
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        self.setWindowTitle('框选公式区域')
        self._shot = None        # 原始截图（PIL，物理像素）
        self._pixmap = None      # 用于显示的 QPixmap
        self._origin = None
        self._current = None
        self._hint_font = QFont(UI_FONT, 12)

    # -- 生命周期 -----------------------------------------------------------
    def start(self) -> bool:
        """冻结屏幕并显示遮罩；返回是否成功启动。"""
        try:
            self._shot = grab_virtual_desktop()
        except Exception:                                    # noqa: BLE001
            self._shot = None
            self.cancelled.emit()
            return False
        rgb = self._shot.convert('RGB')
        buffer = rgb.tobytes('raw', 'RGB')
        qt_image = QImage(buffer, rgb.width, rgb.height, rgb.width * 3,
                          QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qt_image)

        screen = QApplication.primaryScreen()
        self.setGeometry(screen.virtualGeometry() if screen else QRect(0, 0, 1280, 720))
        self._origin = None
        self._current = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.grabKeyboard()
        QApplication.setOverrideCursor(QCursor(Qt.CrossCursor))
        self.update()
        return True

    def _finish(self) -> None:
        self.releaseKeyboard()
        QApplication.restoreOverrideCursor()
        self.hide()

    def _cancel(self) -> None:
        self._finish()
        self.cancelled.emit()

    # -- 选区 ---------------------------------------------------------------
    def selection(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    def _image_rect(self, selection: QRect):
        """控件坐标 → 截图坐标，并向外扩一点边距。

        返回 ``(left, top, right, bottom)``；选区太小或无效时返回 ``None``。
        """
        if self._pixmap is None or self._shot is None:
            return None
        scale_x = self._pixmap.width() / max(1, self.width())
        scale_y = self._pixmap.height() / max(1, self.height())
        if selection.width() * scale_x < MIN_SELECTION or selection.height() * scale_y < MIN_SELECTION:
            return None
        # 边距按缩放比折算，保证不同 DPI 下都是同样的视觉留白
        margin_x = max(2, int(round(SELECTION_MARGIN * scale_x)))
        margin_y = max(2, int(round(SELECTION_MARGIN * scale_y)))
        left = max(0, int(round(selection.left() * scale_x)) - margin_x)
        top = max(0, int(round(selection.top() * scale_y)) - margin_y)
        right = min(self._shot.width, int(round((selection.right() + 1) * scale_x)) + margin_x)
        bottom = min(self._shot.height, int(round((selection.bottom() + 1) * scale_y)) + margin_y)
        if right - left < 2 or bottom - top < 2:
            return None
        return left, top, right, bottom

    # -- 事件 ---------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        if self._pixmap is not None:
            painter.drawPixmap(self.rect(), self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        selection = self.selection()
        if selection.isNull():
            painter.setPen(QPen(QColor(255, 255, 255, 230)))
            painter.setFont(self._hint_font)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             '拖动鼠标框选公式区域\n按 Esc 或右键取消')
            return

        # 选区内的画面还原（不加暗色遮罩）
        painter.save()
        painter.setClipRect(selection)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.restore()

        painter.setPen(QPen(QColor(COLOR_ACCENT), 2))
        painter.drawRect(selection.adjusted(0, 0, -1, -1))

        label = '%d × %d' % (selection.width(), selection.height())
        painter.setFont(self._hint_font)
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(label).adjusted(-6, -3, 6, 3)
        anchor = selection.topLeft() - QPoint(0, text_rect.height() + 4)
        if anchor.y() < 0:
            anchor = selection.topLeft() + QPoint(0, 4)
        text_rect.moveTopLeft(anchor)
        painter.fillRect(text_rect, QColor(36, 64, 47, 200))
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(text_rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._cancel()
            return
        self._origin = event.pos()
        self._current = event.pos()
        self.update()

    def mouseMoveEvent(self, event):
        if self._origin is None:
            return
        self._current = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton or self._origin is None:
            return
        self._current = event.pos()
        selection = self.selection()
        box = self._image_rect(selection)
        if box is None:                      # 只是单击/误触，继续等待
            self._origin = None
            self._current = None
            self.update()
            return
        crop = self._shot.crop(box)
        self._finish()
        self._origin = None
        self._current = None
        self.captured.emit(crop)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)


class ModelLoader(QThread):
    """后台加载模型，避免启动时界面卡死。"""

    def __init__(self, engine: LatexOcrEngine, signals: Signals, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._signals = signals

    def run(self):
        try:
            self._engine.load()
        except LatexOcrError as exc:
            self._signals.model_loaded.emit(False, str(exc))
            return
        except Exception as exc:                             # noqa: BLE001
            self._signals.model_loaded.emit(False, '%s: %s' % (type(exc).__name__, exc))
            return
        self._signals.model_loaded.emit(True, '')


class RecognizeWorker(QThread):
    """后台执行一次识别。"""

    def __init__(self, engine: LatexOcrEngine, image: Image.Image, temperature: float,
                 signals: Signals, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._image = image
        self._temperature = temperature
        self._signals = signals

    def run(self):
        started = time.time()
        try:
            latex = self._engine.predict(self._image, temperature=self._temperature)
        except LatexOcrError as exc:
            self._signals.recognize_failed.emit(str(exc))
            return
        except Exception as exc:                             # noqa: BLE001
            self._signals.recognize_failed.emit('%s: %s' % (type(exc).__name__, exc))
            return
        self._signals.recognized.emit(self._image, latex, time.time() - started)


class PreviewWorker(QThread):
    """后台把 LaTeX 渲染成 PNG（xelatex 一次 1~2 秒，不能卡住界面）。"""

    rendered = pyqtSignal(str, str, str)          # latex, png_path, error

    def __init__(self, latex: str, cache_dir: str, dpi: int, parent=None):
        super().__init__(parent)
        self._latex = latex
        self._cache_dir = cache_dir
        self._dpi = dpi

    def run(self):
        try:
            path = latex_render.render_cached(self._latex, self._cache_dir, dpi=self._dpi)
        except Exception as exc:                              # noqa: BLE001
            self.rendered.emit(self._latex, '', str(exc))
            return
        self.rendered.emit(self._latex, path, '')


class LatexPreview(QWidget):
    """LaTeX 预览。

    默认用本机 TeX Live 的 xelatex 渲染（``\\left``/``\\right``、``\\begin{array}`` 等都能显示），
    找不到 xelatex 时退回 matplotlib 的 mathtext，并先把 TeX 写法规范化再渲染。
    """

    #: 输入变化后等一会儿再渲染，避免连续敲键盘时反复调用 xelatex
    DEBOUNCE_MS = 350

    def __init__(self, enabled: bool = True, engine: str = 'auto',
                 cache_dir: str = None, dpi: int = 180, parent=None):
        super().__init__(parent)
        self.last_ok = None                 # True / False / None(还没渲染)
        self.last_error = ''
        self._rendered_text = ''
        self._image_label = QLabel()
        self._image_label.setObjectName('previewCard')
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumHeight(72)
        self._status = QLabel('')
        self._status.setObjectName('previewStatus')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._canvas = None
        self._pixmap = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._image_label, 1)
        layout.addWidget(self._status)
        self.setMinimumHeight(96)

        self._enabled = bool(enabled)
        self._cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), 'latexocr-preview')
        self._dpi = max(72, int(dpi))
        self._requested = None
        self._worker = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_now)

        if not self._enabled:
            self._image_label.hide()
            self._status.setText('预览已关闭')
            return

        available = latex_render.latex_available()
        self._use_latex = available and engine in ('auto', 'latex')
        if engine == 'latex' and not available:
            self._status.setText('没有找到 xelatex，已改用 mathtext 预览')
        if not self._use_latex:
            self._init_mathtext()

    # -- 对外接口 -----------------------------------------------------------
    def engine_name(self) -> str:
        if not self._enabled:
            return '已关闭'
        return 'xelatex（TeX Live）' if self._use_latex else 'matplotlib mathtext（降级）'

    def show_latex(self, latex: str) -> None:
        """请求渲染（内部有防抖和缓存，可以随便调用）。"""
        if not self._enabled:
            return
        text = (latex or '').strip()
        if text == self._requested:
            return
        self._requested = text
        self._timer.stop()
        if not text:
            self._clear()
            return
        self._timer.start(self.DEBOUNCE_MS)

    def shutdown(self) -> None:
        """退出前收尾：等后台渲染线程结束。"""
        self._timer.stop()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)

    # -- 渲染 ---------------------------------------------------------------
    def _clear(self) -> None:
        self._pixmap = None
        self._image_label.clear()
        if self._canvas is not None:
            self._canvas.figure.clear()
            self._canvas.draw()
        self._status.setText('')
        self.last_ok, self.last_error = True, ''

    def _render_now(self) -> None:
        text = self._requested
        if not text:
            return
        if not self._use_latex:
            self._draw_mathtext(text)
            return
        if self._worker is not None and self._worker.isRunning():
            return                     # 上一个还没结束，它收尾时会补渲染
        self._status.setText('渲染中…')
        self._worker = PreviewWorker(text, self._cache_dir, self._dpi)
        self._worker.rendered.connect(self._on_rendered)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()
    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._requested and self._requested != self._rendered_text:
            self._timer.start(30)          # 渲染期间内容又变了 → 再渲染一次

    def _on_rendered(self, latex: str, png_path: str, error: str) -> None:
        self._rendered_text = latex
        if latex != self._requested:       # 过期结果，丢掉
            return
        if error:
            self.last_ok, self.last_error = False, error
            self._pixmap = None
            self._image_label.clear()
            self._status.setText('无法预览：%s（不影响识别结果和复制）' % error)
            return
        pixmap = QPixmap(png_path)
        if pixmap.isNull():
            self.last_ok, self.last_error = False, '预览图读取失败'
            self._status.setText(self.last_error)
            return
        self._pixmap = pixmap
        self.last_ok, self.last_error = True, ''
        self._update_pixmap()
        self._status.setText('')

    def _update_pixmap(self) -> None:
        if self._pixmap is None:
            return
        area = self._image_label.size() - QSize(10, 10)
        if area.width() < 20 or area.height() < 20:
            return
        self._image_label.setPixmap(
            self._pixmap.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()

    # -- mathtext 降级路径 --------------------------------------------------
    def _init_mathtext(self) -> None:
        try:
            import matplotlib
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            matplotlib.rcParams['mathtext.fontset'] = 'cm'      # 更接近 LaTeX 的样子
            self._canvas = FigureCanvasQTAgg(Figure(figsize=(4, 1.1), dpi=100))
            self._canvas.figure.patch.set_facecolor(COLOR_CARD)
            self._canvas.setMinimumHeight(72)
            self.layout().insertWidget(0, self._canvas, 1)
            self._image_label.hide()
            self._status.setText('预览引擎：matplotlib mathtext（\\left/\\right 等已自动处理）')
        except Exception as exc:                              # noqa: BLE001
            self._status.setText('预览不可用：%s' % exc)

    def _draw_mathtext(self, latex: str) -> None:
        """mathtext 渲染：array 等多行结果按行分别绘制。"""
        if self._canvas is None:
            return
        figure = self._canvas.figure
        figure.clear()
        axes = figure.add_subplot(111)
        axes.axis('off')
        _spec, rows = split_latex_rows(latex)
        rows = [row for row in rows if row.strip()] or [latex]
        try:
            for index, row in enumerate(rows):
                axes.text(0.5, 1 - (index + 0.5) / len(rows),
                          '$%s$' % latex_render.normalize_for_mathtext(row),
                          ha='center', va='center', fontsize=12)
            self._canvas.draw()
            self.last_ok, self.last_error = True, ''
            self._status.setText('')
        except Exception as exc:                              # noqa: BLE001
            figure.clear()
            axes = figure.add_subplot(111)
            axes.axis('off')
            axes.text(0.5, 0.5, '无法预览（mathtext 不支持该命令）',
                      ha='center', va='center', fontsize=10, color=COLOR_MUTED)
            self._canvas.draw()
            self.last_ok, self.last_error = False, str(exc)
            self._status.setText('mathtext 不支持这段公式：%s' % str(exc)[:90])


class MainWindow(QMainWindow):
    """主窗口：快捷键、截图、结果展示与历史记录。"""

    def __init__(self, args):
        super().__init__()
        self.args = args
        base = os.path.dirname(os.path.abspath(__file__))
        self.outdir = os.path.abspath(args.outdir or default_outdir(base))
        self.capture_dir = os.path.join(self.outdir, 'captures')
        self.history_file = os.path.join(self.outdir, 'history.jsonl')
        #: 默认不落盘：output 目录里只保留 history.jsonl（关闭软件时会清空它）
        self.save_captures = bool(args.save_captures)
        #: 预览渲染的缓存放系统临时目录，不往项目里堆文件
        self.preview_cache_dir = os.path.join(tempfile.gettempdir(), 'latexocr-preview')
        try:
            os.makedirs(self.outdir, exist_ok=True)
        except OSError:
            pass

        self.signals = Signals()
        self.engine = LatexOcrEngine(temperature=args.temperature, device=args.device,
                                     samples=args.samples,
                                     trim_lines=TRIM_VALUES[args.trim_lines],
                                     on_progress=self.signals.progress.emit)
        self.selector = RegionSelector()
        self.hotkey = None
        self._worker = None
        self._loader = None
        self._last_image = None
        self._last_capture_path = ''
        self._raw_latex = ''
        self._model_ready = False
        self._busy = False
        self._snip_pending = False

        self._build_ui()
        self._connect()
        self._load_history()
        self.start_hotkey()
        self.load_model_async()
        self._set_busy(False)          # 模型就绪前禁用识别按钮

    # -- 界面 ---------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(APP_TITLE)
        self.resize(660, 860)
        self.setMinimumSize(560, 640)
        self.setStyleSheet(THEME)
        # 统一界面字体：样式表会和字体族“打架”，所以在这里同时设定应用字体
        # （否则被样式表 polish 过的控件会退回系统默认字体，中文会变成宋体）
        ui_font = QFont(UI_FONT, UI_FONT_SIZE)
        app = QApplication.instance()
        if app is not None:
            app.setFont(ui_font)
        self.setFont(ui_font)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(8)
        # 内容放进滚动区：窗口拉小的时候滚动，而不是把控件压扁（压扁会让文字显示不全）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        self._scroll = scroll

        # 顶部标题 + 提示
        self.title_label = QLabel('公式截图识别')
        self.title_label.setObjectName('titleLabel')
        layout.addWidget(self.title_label)
        self.hint = QLabel('按 %s 呼出截图，框选公式后自动识别' % self.args.hotkey_display)
        self.hint.setObjectName('hintLabel')
        layout.addWidget(self.hint)

        # 主要动作
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.snip_button = QPushButton('截图识别 (%s)' % LOCAL_SHORTCUT)
        self.snip_button.setObjectName('primaryButton')
        self.clip_button = QPushButton('识别剪贴板')
        self.open_button = QPushButton('打开图片…')
        self.retry_button = QPushButton('重试')
        self.retry_button.setEnabled(False)
        for widget in (self.snip_button, self.clip_button, self.open_button, self.retry_button):
            buttons.addWidget(widget)
        layout.addLayout(buttons)

        layout.addWidget(_separator())

        # 识别结果
        layout.addWidget(_section_label('识别结果（可手动修正，预览会同步）'))
        self.result_edit = QPlainTextEdit()
        self.result_edit.setObjectName('resultEdit')
        self.result_edit.setPlaceholderText('识别出的 LaTeX 会出现在这里')
        self.result_edit.setFont(QFont('Consolas', 11))
        self.result_edit.setMinimumHeight(76)
        layout.addWidget(self.result_edit, 2)

        # 输出格式（真正要复制出去的内容）
        format_row = QHBoxLayout()
        format_row.setSpacing(8)
        format_row.addWidget(_section_label('输出格式'))
        self.format_box = QComboBox()
        self.format_box.addItems(FORMATS)
        self.format_box.setCurrentText('LaTeX-$')
        format_row.addWidget(self.format_box)
        self.auto_copy = QCheckBox('自动复制')
        self.auto_copy.setChecked(True)
        format_row.addWidget(self.auto_copy)
        format_row.addStretch(1)
        self.copy_button = QPushButton('复制')
        format_row.addWidget(self.copy_button)
        layout.addLayout(format_row)

        self.formatted_edit = QPlainTextEdit()
        self.formatted_edit.setObjectName('formattedEdit')
        self.formatted_edit.setReadOnly(True)
        self.formatted_edit.setFont(QFont('Consolas', 10))
        self.formatted_edit.setMaximumHeight(56)
        layout.addWidget(self.formatted_edit)

        # 公式预览
        self.preview = LatexPreview(enabled=not self.args.no_preview,
                                    engine=self.args.preview_engine,
                                    cache_dir=self.preview_cache_dir,
                                    dpi=self.args.preview_dpi)
        layout.addWidget(self.preview)

        layout.addWidget(_separator())

        # 设置：合并成 3 行，保持紧凑
        settings = QFormLayout()
        settings.setContentsMargins(0, 2, 0, 2)
        settings.setHorizontalSpacing(12)
        settings.setVerticalSpacing(8)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.01, 1.0)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setValue(self.args.temperature)
        self.temp_spin.setToolTip('采样温度：越小越稳定，越大越随机。点“重试”会自动调高一点。')
        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(1, 9)
        self.samples_spin.setValue(self.args.samples)
        self.samples_spin.setToolTip('识别几次并按行投票：编造出来的行每次都不一样，会被投票去掉。\n'
                                     '次数越多越准也越慢，1 表示只跑一次。')
        first_row = QHBoxLayout()
        first_row.setSpacing(6)
        first_row.addWidget(_form_label('采样温度'))
        first_row.addWidget(self.temp_spin)
        first_row.addSpacing(12)
        first_row.addWidget(_form_label('采样次数'))
        first_row.addWidget(self.samples_spin)
        first_row.addStretch(1)
        settings.addRow(first_row)

        self.trim_box = QComboBox()
        self.trim_box.addItems([label for label, _value in TRIM_CHOICES])
        self.trim_box.setCurrentIndex(trim_index(TRIM_VALUES[self.args.trim_lines]))
        self.trim_box.setToolTip('框选偏大、把上下另一行也框进来时：\n'
                                 '总是 = 只识别主要的那一行（推荐）\n'
                                 '自动 = 先识别原图，结果不干净时才补跑主行\n'
                                 '关闭 = 原样识别（矩阵、分段函数等多行公式用这个）')
        settings.addRow(_form_label('主行裁剪'), self.trim_box)

        self.on_top = QCheckBox('窗口置顶')
        self.preview_label = QLabel(self.preview.engine_name())
        self.preview_label.setObjectName('hintLabel')
        self.preview_label.setToolTip('有 TeX Live 时用 xelatex 渲染，效果与真实排版一致；\n'
                                      '否则退回 matplotlib mathtext（支持的命令会更少）。')
        last_row = QHBoxLayout()
        last_row.setSpacing(8)
        last_row.addWidget(self.on_top)
        last_row.addStretch(1)
        last_row.addWidget(_form_label('预览引擎'))
        last_row.addWidget(self.preview_label)
        settings.addRow(last_row)
        layout.addLayout(settings)

        # 历史记录
        layout.addWidget(_section_label('历史记录（双击载入）'))
        self.history = QListWidget()
        self.history.setMinimumHeight(88)
        layout.addWidget(self.history, 1)

        # 模型状态放在状态栏右侧，省一行高度也更显眼
        self.model_label = QLabel('正在加载模型…')
        self.model_label.setObjectName('hintLabel')
        self.statusBar().addPermanentWidget(self.model_label)

    def _connect(self) -> None:
        self.snip_button.clicked.connect(self.start_snip)
        self.clip_button.clicked.connect(self.recognize_clipboard)
        self.open_button.clicked.connect(self.open_image)
        self.retry_button.clicked.connect(self.retry)
        self.copy_button.clicked.connect(self.copy_result)

        self.selector.captured.connect(self.on_captured)
        self.selector.cancelled.connect(lambda: self.statusBar().showMessage('已取消截图', 3000))

        self.signals.progress.connect(self.statusBar().showMessage)
        self.signals.model_loaded.connect(self.on_model_loaded)
        self.signals.recognized.connect(self.on_recognized)
        self.signals.recognize_failed.connect(self.on_recognize_failed)
        self.signals.hotkey_fired.connect(self.start_snip)

        self.result_edit.textChanged.connect(self.on_result_changed)
        self.format_box.currentTextChanged.connect(lambda _text: self.refresh_formatted())
        self.temp_spin.valueChanged.connect(self.on_temperature_changed)
        self.samples_spin.valueChanged.connect(self.on_samples_changed)
        self.trim_box.currentIndexChanged.connect(self.on_trim_changed)
        self.on_top.toggled.connect(self.on_top_changed)
        self.history.itemDoubleClicked.connect(self.on_history_activated)

        self._shortcuts = []
        for keys, slot in (('Ctrl+Alt+M', self.start_snip),
                           ('Ctrl+O', self.open_image),
                           ('Ctrl+V', self.recognize_clipboard)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

    # -- 快捷键与模型 -------------------------------------------------------
    def start_hotkey(self) -> None:
        if self.args.no_hotkey:
            self.hint.setText('全局快捷键已禁用，请用按钮或窗口内 %s' % LOCAL_SHORTCUT)
            return
        try:
            self.hotkey = GlobalHotkey(self.args.hotkey, self.signals.hotkey_fired.emit)
            self.hotkey.start()
        except Exception as exc:                             # noqa: BLE001
            self.hotkey = None
            self.hint.setText('全局快捷键注册失败（%s），请用窗口内 %s' % (exc, LOCAL_SHORTCUT))

    def load_model_async(self) -> None:
        self._loader = ModelLoader(self.engine, self.signals)
        self._loader.start()

    def on_model_loaded(self, ok: bool, error: str) -> None:
        self._model_ready = ok
        if ok:
            self.model_label.setText('已就绪（设备 %s，加载 %.1fs）'
                                     % (self.engine.device or 'auto', self.engine.load_seconds or 0))
            self.model_label.setStyleSheet('color: %s;' % COLOR_ACCENT_HI)
            self.statusBar().showMessage('模型就绪，按 %s 开始截图' % self.args.hotkey_display, 8000)
        else:
            self.model_label.setText('加载失败：%s' % error)
            self.model_label.setStyleSheet('color: #c0564d;')
            QMessageBox.critical(self, APP_TITLE, '模型加载失败：\n%s' % error)
        self._set_busy(False)

    # -- 截图 ---------------------------------------------------------------
    def start_snip(self) -> None:
        if self._busy:
            self.statusBar().showMessage('上一次识别还没结束，请稍候…', 3000)
            return
        # 全局快捷键和窗口内快捷键可能同时触发，这里去重
        if self._snip_pending or self.selector.isVisible():
            return
        if not self._model_ready:
            QMessageBox.information(self, APP_TITLE, '模型还在加载，请稍等片刻。')
            return
        self._snip_pending = True
        self.hide()                     # 先藏起主窗口，别把自己截进去
        QTimer.singleShot(160, self._do_snip)

    def _do_snip(self) -> None:
        self._snip_pending = False
        if not self.selector.start():
            self.show()
            self.statusBar().showMessage('截屏失败，请检查屏幕捕获权限', 5000)

    def on_captured(self, image: Image.Image) -> None:
        self.show()
        self._last_image = image
        self._last_capture_path = self.save_capture(image)
        self.retry_button.setEnabled(self._model_ready)
        self.run_recognition(image, self.temp_spin.value())

    # -- 识别 ---------------------------------------------------------------
    def run_recognition(self, image: Image.Image, temperature: float) -> None:
        if self._busy:
            return
        if not self._model_ready:
            QMessageBox.information(self, APP_TITLE, '模型还在加载，请稍等片刻。')
            return
        self._set_busy(True)
        self.statusBar().showMessage('识别中…')
        self._worker = RecognizeWorker(self.engine, image, temperature, self.signals)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def on_recognized(self, image: Image.Image, latex: str, seconds: float) -> None:
        self._set_busy(False)
        self._last_image = image
        self._raw_latex = latex
        self.result_edit.setPlainText(latex)          # 触发 on_result_changed：预览 + 格式化
        self.refresh_formatted(copy=True)
        self._add_history(latex, self._last_capture_path)
        message = '识别完成（%.2fs，%d 次采样）' % (seconds, self.engine.samples)
        hint = resolution_hint(image)
        if hint:
            message += '　提示：%s' % hint
        self.statusBar().showMessage(message, 15000)

    def on_recognize_failed(self, message: str) -> None:
        self._set_busy(False)
        self.statusBar().showMessage(message, 8000)
        if '没有找到公式' not in message:
            QMessageBox.warning(self, APP_TITLE, message)

    def retry(self) -> None:
        if self._last_image is None:
            return
        temperature = min(1.0, round(self.temp_spin.value() * 1.5, 2))
        self.temp_spin.setValue(temperature)
        self.statusBar().showMessage('换个采样重试（temperature=%.2f）…' % temperature)
        self.run_recognition(self._last_image, temperature)

    def recognize_clipboard(self) -> None:
        try:
            data = ImageGrab.grabclipboard()
        except Exception as exc:                             # noqa: BLE001
            QMessageBox.warning(self, APP_TITLE, '读取剪贴板失败：%s' % exc)
            return
        image = None
        if isinstance(data, Image.Image):
            image = data
        elif isinstance(data, list):
            for path in data:
                if str(path).lower().endswith(IMAGE_SUFFIXES):
                    image = Image.open(path)
                    break
        if image is None:
            QMessageBox.information(self, APP_TITLE, '剪贴板里没有图片，请先截图或复制图片文件。')
            return
        self._last_image = image
        self.retry_button.setEnabled(self._model_ready)
        self.run_recognition(image, self.temp_spin.value())

    def open_image(self) -> None:
        pattern = '图片 (*%s)' % ' *'.join(IMAGE_SUFFIXES)
        path, _selected = QFileDialog.getOpenFileName(self, '选择公式图片', '', pattern)
        if not path:
            return
        try:
            image = Image.open(path)
        except Exception as exc:                             # noqa: BLE001
            QMessageBox.warning(self, APP_TITLE, '打开图片失败：%s' % exc)
            return
        self._last_image = image
        self.retry_button.setEnabled(self._model_ready)
        self.run_recognition(image, self.temp_spin.value())

    # -- 状态 ---------------------------------------------------------------
    def _set_busy(self, value: bool) -> None:
        self._busy = value
        for widget in (self.snip_button, self.clip_button, self.open_button):
            widget.setEnabled(not value and self._model_ready)
        self.retry_button.setEnabled(not value and self._model_ready
                                     and self._last_image is not None)

    # -- 结果与格式 ---------------------------------------------------------
    def on_result_changed(self) -> None:
        self._raw_latex = self.result_edit.toPlainText()
        self.refresh_formatted(copy=False)
        self.preview.show_latex(self._raw_latex)

    def selected_format(self) -> str:
        return self.format_box.currentText()

    def format_latex(self, raw: str = None) -> str:
        """按当前选择的格式输出。"""
        text = self._raw_latex if raw is None else raw
        text = (text or '').strip()
        while len(text) > 1 and text.startswith('$') and text.endswith('$'):
            text = text[1:-1].strip()
        if not text:
            return ''
        fmt = self.selected_format()
        if fmt == 'Raw':
            return text
        if fmt == 'LaTeX-$':
            return '$%s$' % text
        if fmt == 'LaTeX-$$':
            return '$$%s$$' % text
        return self.to_sympy(text)

    def to_sympy(self, raw: str) -> str:
        try:
            from latex2sympy2 import latex2sympy

            normalized = re.sub(r'operatorname\*{(\w+)}', r'\g<1>', raw)
            return str(latex2sympy('$%s$' % normalized))
        except Exception as exc:                             # noqa: BLE001
            self.statusBar().showMessage('无法转换成 Sympy：%s' % exc, 6000)
            return raw

    def refresh_formatted(self, copy: bool = False) -> None:
        text = self.format_latex()
        self.formatted_edit.setPlainText(text)
        if copy and text and self.auto_copy.isChecked():
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage('已复制到剪贴板', 3000)

    def copy_result(self) -> None:
        text = self.format_latex()
        if not text:
            self.statusBar().showMessage('还没有可复制的内容', 3000)
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage('已复制到剪贴板', 3000)

    def on_temperature_changed(self, value: float) -> None:
        self.engine.temperature = float(value)

    def on_samples_changed(self, value: int) -> None:
        self.engine.samples = max(1, int(value))

    def on_trim_changed(self, index: int) -> None:
        self.engine.trim_lines = TRIM_CHOICES[index][1]

    def on_top_changed(self, checked: bool) -> None:
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    # -- 截图文件与历史 -----------------------------------------------------
    def save_capture(self, image: Image.Image) -> str:
        """把框选的切片存到 output/captures（只有显式加 --save-captures 时才存）。"""
        if not self.save_captures:
            return ''
        try:
            os.makedirs(self.capture_dir, exist_ok=True)
            name = 'capture-%s.png' % datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]
            path = os.path.join(self.capture_dir, name)
            image.save(path)
            return path
        except Exception:                                    # noqa: BLE001
            return ''

    def _load_history(self) -> None:
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, 'r', encoding='utf-8') as handle:
                entries = [json.loads(line) for line in handle if line.strip()]
        except Exception:                                    # noqa: BLE001
            return
        for entry in reversed(entries[-MAX_HISTORY:]):
            self._insert_history_item(entry)

    def _insert_history_item(self, entry: dict) -> None:
        stamp = str(entry.get('time', ''))[11:] or '--:--:--'
        latex = str(entry.get('latex', ''))
        text = latex if len(latex) <= 60 else latex[:57] + '…'
        item = QListWidgetItem('[%s] %s' % (stamp, text))
        item.setData(Qt.UserRole, entry)
        item.setToolTip(latex)
        self.history.insertItem(0, item)

    def _add_history(self, latex: str, capture_path: str = '') -> None:
        entry = {'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'latex': latex,
                 'capture': capture_path or ''}
        self._insert_history_item(entry)
        while self.history.count() > MAX_HISTORY:
            self.history.takeItem(self.history.count() - 1)
        try:
            with open(self.history_file, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception:                                    # noqa: BLE001
            pass

    def on_history_activated(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.UserRole) or {}
        latex = str(entry.get('latex', ''))
        if not latex:
            return
        self.result_edit.setPlainText(latex)
        self.statusBar().showMessage('已载入历史记录', 3000)

    #  -- 退出 ---------------------------------------------------------------
    def _clear_history_file(self) -> None:
        """退出时清空历史文件（history.jsonl 只作为本次会话的记录保留）。"""
        try:
            with open(self.history_file, 'w', encoding='utf-8'):
                pass
        except OSError:
            pass

    def closeEvent(self, event):
        if self._busy:
            reply = QMessageBox.question(self, APP_TITLE, '正在识别，确定要退出吗？',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        if self.hotkey is not None:
            self.hotkey.stop()
        self.preview.shutdown()
        self.selector.close()
        self._clear_history_file()
        event.accept()


def hotkey_display(combo: str) -> str:
    """把 pynput 语法转成好看一点的显示形式。"""
    parts = [part.strip() for part in combo.replace('<', '').replace('>', '').split('+')
             if part.strip()]
    pretty = []
    for part in parts:
        if part.lower() in ('ctrl', 'alt', 'shift', 'cmd', 'win'):
            pretty.append(part.capitalize())
        elif len(part) == 1:
            pretty.append(part.upper())
        else:
            pretty.append(part)
    return '+'.join(pretty)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='screenshot_latex.py',
        description='截图识别公式为 LaTeX（PyQt5 + pix2tex）')
    parser.add_argument('--hotkey', default=DEFAULT_HOTKEY,
                        help='全局快捷键，pynput 语法（默认 %(default)s）')
    parser.add_argument('-t', '--temperature', type=float, default=DEFAULT_TEMPERATURE,
                        help='采样温度，越大越随机（默认 %(default)s）')
    parser.add_argument('--samples', type=int, default=DEFAULT_SAMPLES,
                        help='采样次数，多次采样按行投票可去掉编造出来的行（默认 %(default)s）')
    parser.add_argument('--trim-lines', choices=['on', 'auto', 'off'], default='on',
                        help='“只保留主行”策略：on=检测到明显分离的另一行时只识别主行（默认，'
                             '实测最准最快）、auto=先跑原图、结果不干净时才补跑主行、'
                             'off=原样识别（矩阵/分段函数等多行公式用 off）')
    parser.add_argument('-d', '--device', choices=['cpu', 'cuda'], default=None,
                        help='推理设备（默认自动检测）')
    parser.add_argument('--outdir', default=None,
                        help='history.jsonl 的存放目录（默认脚本目录下的 output）')
    parser.add_argument('--save-captures', action='store_true',
                        help='额外把每次框选的切片存到 outdir/captures（默认不存）')
    parser.add_argument('--no-preview', action='store_true', help='关闭 LaTeX 预览')
    parser.add_argument('--preview-engine', choices=['auto', 'latex', 'mathtext'], default='auto',
                        help='预览渲染方式：auto=有 TeX Live 就用 xelatex（默认）、'
                             'latex=强制用 xelatex、mathtext=用 matplotlib')
    parser.add_argument('--preview-dpi', type=int, default=180,
                        help='预览渲染分辨率（默认 %(default)s）')
    parser.add_argument('--no-hotkey', action='store_true', help='不注册全局快捷键')
    parser.add_argument('--doctor', action='store_true',
                        help='不开界面，只打印运行环境与权重是否就绪后退出')
    parser.add_argument('--selfcheck', action='store_true',
                        help='不开界面，真跑一遍识别来验证安装是否可用后退出')
    parser.add_argument('--report', default=None,
                        help='把 --doctor/--selfcheck 的结果写到该文件（打包后没有控制台）')
    return parser


def run_selfcheck(args) -> int:
    """无界面自检：环境 + 权重 + 真跑一遍识别。

    打包成窗口程序后没有控制台可看，所以结果会同时写到 ``--report`` 指定的文件
    （默认在系统临时目录），安装后可以用它确认“这台机器能不能用”。
    """
    lines = []
    problems = []

    def emit(message: str = '') -> None:
        text = str(message)
        lines.append(text)
        try:
            print(text, flush=True)          # 有控制台时顺便打一份
        except Exception:                    # noqa: BLE001  窗口程序没有 stdout
            pass

    emit('=== 公式截图识别：安装自检 ===')
    emit('可执行文件   %s' % sys.executable)
    emit('打包运行     %s' % bool(getattr(sys, 'frozen', False)))
    emit('Python       %s' % sys.version.split()[0])
    for key, value in describe_environment().items():
        emit('%-12s %s' % (key, value))
    emit('预览引擎     %s' % latex_render.engine_name())
    if not latex_render.latex_available():
        emit('             （没找到 xelatex，预览会自动用 matplotlib mathtext，功能不受影响）')
    emit('历史目录     %s' % default_outdir(os.path.dirname(os.path.abspath(__file__))))

    weights, resizer = checkpoint_paths()
    for path in (weights, resizer):
        ready = os.path.exists(path)
        emit('%-12s %s %s' % ('模型权重', 'OK  ' if ready else '缺失', path))
        if not ready:
            problems.append('缺少权重文件：%s' % os.path.basename(path))

    if args.selfcheck and not problems:
        emit('')
        emit('开始识别测试图 …')
        try:
            png = os.path.join(tempfile.gettempdir(), 'latexocr-selfcheck.png')
            image = _render_sample_formula(png)
            engine = LatexOcrEngine(samples=1, on_progress=emit)
            engine.load()
            text = engine.predict(image)
            ok = 'x^{2}+y^{2}=z^{2}' in text.replace(' ', '')
            emit('识别结果     %s' % text)
            emit('识别耗时     %.2fs' % (engine.load_seconds or 0) + '（含模型加载）')
            if not ok:
                problems.append('识别结果与预期不符：%s' % text)
        except Exception as exc:                             # noqa: BLE001
            emit('识别失败     %s: %s' % (type(exc).__name__, exc))
            problems.append('识别过程异常：%s' % type(exc).__name__)

    emit('')
    emit('结论         %s' % ('PASS，这台机器可以直接用' if not problems
                             else 'FAIL -> %s' % '；'.join(problems)))

    target = args.report or os.path.join(tempfile.gettempdir(), 'latexocr-selfcheck.txt')
    try:
        with open(target, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
        emit('报告文件     %s' % target)
    except OSError as exc:
        emit('写报告失败   %s' % exc)
    return 0 if not problems else 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.doctor or args.selfcheck:
        return run_selfcheck(args)
    args.hotkey_display = hotkey_display(args.hotkey)

    enable_dpi_awareness()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_TITLE)
    app.setFont(QFont(UI_FONT, UI_FONT_SIZE))

    window = MainWindow(args)
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())


