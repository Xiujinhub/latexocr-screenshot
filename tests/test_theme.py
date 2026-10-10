"""界面主题回归：配色是否生效、字体有没有被样式表接管。

用法（在仓库根目录执行）::

    D:\\Anaconda\\envs\\OCR\\python.exe -u tests\\test_theme.py

全部通过时最后打印 ``THEMEVERIFY PASS``。
"""
import os
import re
import sys
import tempfile
import time

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QColor, QFontDatabase
from PyQt5.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screenshot_latex as sl  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems = []


def check(name, ok, detail=''):
    print('%-30s %s %s' % (name, 'OK  ' if ok else 'FAIL', detail), flush=True)
    if not ok:
        problems.append(name)


# QFontDatabase 需要先有 QApplication
app = QApplication([sys.argv[0]])

# --- 1) 样式表本身的静态检查（去掉注释再查） ---
qss = re.sub(r'/\*.*?\*/', '', sl.THEME, flags=re.S)
check('样式表无未替换占位符', '%(' not in qss)
check('样式表不写 font-family（写了会盖掉 setFont，中文变宋体）', 'font-family' not in qss)
check('界面字体确实存在', sl.UI_FONT in QFontDatabase().families(), sl.UI_FONT)

# --- 2) 实际渲染出来的效果 ---
tmp = tempfile.mkdtemp(prefix='latexocr-theme-')
args = sl.build_parser().parse_args(['--no-hotkey', '--outdir', tmp, '--device', 'cpu'])
args.hotkey_display = sl.hotkey_display(args.hotkey)
window = sl.MainWindow(args)
window._model_ready = True          # 模型就绪态，按钮才有正常配色
window._set_busy(False)
window.show()
app.processEvents()
time.sleep(0.4)
app.processEvents()

image = window.grab().toImage()


def color_at(widget, offset):
    """取控件内某点（控件坐标）在窗口截图里的颜色。"""
    spot = widget.mapTo(window, offset)
    return QColor(image.pixel(spot.x(), spot.y())).name().lower()


def left_edge(widget):
    """控件左侧靠里的点，避开文字。"""
    return color_at(widget, QPoint(6, max(6, widget.rect().center().y())))


status = window.statusBar().geometry()
for name, got, want in (
        ('窗口底色', QColor(image.pixel(8, 8)).name().lower(), sl.COLOR_BG),
        ('主按钮', left_edge(window.snip_button), sl.COLOR_ACCENT),
        ('次要按钮', left_edge(window.clip_button), sl.COLOR_CARD),
        ('结果输入框', left_edge(window.result_edit), sl.COLOR_CARD),
        ('历史列表', left_edge(window.history), sl.COLOR_CARD),
        ('状态栏', QColor(image.pixel(status.left() + 6, status.center().y())).name().lower(),
         sl.COLOR_ACCENT_BG)):
    check(name, got == want.lower(), '%s (期望 %s)' % (got, want))

check('界面字体生效', window.hint.font().family() == sl.UI_FONT,
      '%s %spt' % (window.hint.font().family(), window.hint.font().pointSize()))
check('代码框保持等宽', window.result_edit.font().family() == 'Consolas',
      window.result_edit.font().family())

shot = os.path.join(tmp, 'ui.png')
window.grab().save(shot)
size = os.path.getsize(shot) if os.path.exists(shot) else 0
check('窗口可截图导出', size > 5000, '%d bytes' % size)

# 顺便把效果图刷新到 docs/（README 引用它）
preview = os.path.join(ROOT, 'docs', 'ui-preview.png')
try:
    os.makedirs(os.path.dirname(preview), exist_ok=True)
    window.grab().save(preview)
    updated = os.path.getsize(preview)
except OSError as exc:                                       # noqa: BLE001
    updated = 0
    print('（效果图未更新：%s）' % exc)
check('效果图 docs/ui-preview.png', updated > 5000, '%d bytes' % updated)

# --- 3) 控件不能被压扁（压扁 → 文字显示不全，曾出现过） ---
for name, widget in (('采样温度', window.temp_spin), ('采样次数', window.samples_spin),
                     ('主行裁剪', window.trim_box), ('输出格式', window.format_box)):
    hint = widget.minimumSizeHint()
    text_width = max(widget.fontMetrics().horizontalAdvance(t)
                     for t in ([widget.text()] if hasattr(widget, 'text')
                               else [widget.itemText(i) for i in range(widget.count())]))
    check('控件未被压扁：' + name,
          widget.height() >= hint.height() and widget.width() >= hint.width(),
          '%dx%d 需求 %dx%d' % (widget.width(), widget.height(), hint.width(), hint.height()))
    check('文字放得下：' + name, widget.contentsRect().width() >= text_width,
          '内容宽 %d / 文字 %d' % (widget.contentsRect().width(), text_width))

check('默认尺寸不需要滚动', not window._scroll.verticalScrollBar().isVisible(),
      '内容高 %d / 视口高 %d' % (window._scroll.widget().height(),
                                window._scroll.viewport().height()))

window.resize(560, 640)                 # 拉小后应改为滚动，而不是把控件压扁
app.processEvents()
time.sleep(0.3)
app.processEvents()
check('小窗口改为滚动', window._scroll.verticalScrollBar().isVisible())
check('小窗口下仍未被压扁', window.trim_box.height() >= window.trim_box.minimumSizeHint().height(),
      '%dx%d' % (window.trim_box.width(), window.trim_box.height()))

window.preview.shutdown()
window.close()
print('\nTHEMEVERIFY', 'PASS' if not problems else 'FAIL -> %s' % problems, flush=True)
