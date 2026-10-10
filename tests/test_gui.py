"""GUI 全链路验证（模型加载 / 模拟截图 / 结果 / 剪贴板 / 历史 / 格式 / 遮罩框选）。

用法（在仓库根目录执行）::

    D:\\Anaconda\\envs\\OCR\\python.exe -u tests\\test_gui.py

全部通过时最后打印 ``GUIVERIFY PASS``。
"""
import os
import sys
import tempfile
import time

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screenshot_latex as sl  # noqa: E402

TARGET = r'x^{2}+y^{2}=z^{2}'
#: 用户反馈过“MathType 能编译但预览不出来”的那条（\left...\right + \mathcal L）
USER_LATEX = r'{\mathcal L}_{D}=1-\exp\left(-\frac{\sqrt{W_{2}^{2}}}{C}\right)'
problems = []
done = False


def check(name, ok, detail=''):
    print('%-32s %s %s' % (name, 'OK  ' if ok else 'FAIL', detail), flush=True)
    if not ok:
        problems.append(name)


def wait_for_preview(window, timeout=60.0):
    """等待预览的后台渲染结束。"""
    started = time.time()
    while time.time() - started < timeout:
        QApplication.processEvents()
        if window.preview.last_ok is not None:
            return True
        time.sleep(0.05)
    return False


tmp = tempfile.mkdtemp(prefix='latexocr-gui-')
outdir = os.path.join(tmp, 'out')            # 只让程序往这里写 history.jsonl
png = os.path.join(tmp, 'formula.png')
fig = plt.figure(figsize=(6, 1.4), dpi=150)
fig.text(0.02, 0.5, '$%s$' % TARGET, fontsize=30, va='center')
fig.savefig(png, dpi=150, facecolor='white')
plt.close(fig)
image = Image.open(png)

args = sl.build_parser().parse_args(['--no-hotkey', '--outdir', outdir, '--device', 'cpu'])
args.hotkey_display = sl.hotkey_display(args.hotkey)
check('hotkey_display', args.hotkey_display == 'Ctrl+Alt+M', args.hotkey_display)
check('主行裁剪默认=总是', sl.trim_index(sl.TRIM_VALUES[args.trim_lines]) == 0)
check('主行裁剪值映射', (sl.TRIM_VALUES['on'], sl.TRIM_VALUES['auto'],
                        sl.TRIM_VALUES['off']) == (True, 'auto', False))

app = QApplication([sys.argv[0]])
window = sl.MainWindow(args)
check('模型加载前按钮禁用', not window.snip_button.isEnabled())
check('采样次数默认 3', window.samples_spin.value() == 3)
check('主行裁剪下拉默认推荐项', window.trim_box.currentIndex() == 0)
check('引擎初始裁剪模式', window.engine.trim_lines is True)


def after_model():
    check('模型加载完成', window._model_ready, window.model_label.text())
    if not window._model_ready:
        app.quit()
        return
    check('就绪后按钮可用', window.snip_button.isEnabled())
    window.on_captured(image)


def after_recognize():
    global done
    if done:
        return
    done = True
    text = window.result_edit.toPlainText()
    check('识别结果', text == TARGET, repr(text))
    check('自动复制', QApplication.clipboard().text() == '$%s$' % TARGET)
    check('历史记录', window.history.count() == 1 and os.path.exists(window.history_file))
    check('不往 output 写截图', window._last_capture_path == ''
          and not os.path.exists(window.capture_dir),
          window._last_capture_path or '无切片文件')
    window.format_box.setCurrentText('Raw')
    check('格式切换', window.formatted_edit.toPlainText() == TARGET)
    window.samples_spin.setValue(1)
    check('采样次数联动', window.engine.samples == 1)
    window.trim_box.setCurrentIndex(2)
    check('主行裁剪联动(关闭)', window.engine.trim_lines is False)
    window.trim_box.setCurrentIndex(1)
    check('主行裁剪联动(自动)', window.engine.trim_lines == 'auto')
    window.trim_box.setCurrentIndex(0)
    check('主行裁剪联动(总是)', window.engine.trim_lines is True)
    check('状态栏含采样次数', '次采样' in window.statusBar().currentMessage(),
          window.statusBar().currentMessage()[:60])

    # --- 预览：用户那条“MathType 能编译但预览不出来”的公式 ---
    check('预览引擎', window.preview.engine_name().startswith('xelatex'),
          window.preview.engine_name())
    wait_for_preview(window)               # 预览是异步 + 防抖渲染的，等它完成
    check('识别后预览成功', window.preview.last_ok is True, window.preview.last_error or '')
    window.preview.show_latex(USER_LATEX)
    wait_for_preview(window)
    check('预览用户公式(含 \\left/\\mathcal)', window.preview.last_ok is True,
          window.preview.last_error or '')
    window.preview.show_latex(r'\begin{array}{c}a+b\\c+d\end{array}')
    wait_for_preview(window)
    check('预览多行 array', window.preview.last_ok is True, window.preview.last_error or '')

    # --- 预览降级路径（mathtext） ---
    fallback = sl.LatexPreview(enabled=True, engine='mathtext', cache_dir=tmp, dpi=180)
    check('mathtext 引擎名', fallback.engine_name().startswith('matplotlib'),
          fallback.engine_name())
    fallback._draw_mathtext(USER_LATEX)
    check('mathtext 渲染用户公式', fallback.last_ok is True, fallback.last_error or '')
    fallback._draw_mathtext(r'\begin{array}{c}a+b\\c+d\end{array}')
    check('mathtext 渲染多行 array', fallback.last_ok is True, fallback.last_error or '')
    fallback.shutdown()

    finish()


def finish():
    selector = sl.RegionSelector()
    started = selector.start()
    check('遮罩抓屏', started and selector._shot is not None, str(selector._shot.size))
    captured = []
    selector.captured.connect(captured.append)
    selector.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(300, 200),
                                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    selector.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(700, 320),
                                        Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    selector.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(700, 320),
                                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    check('框选裁剪', bool(captured) and captured[0].size == (413, 133),
          str(captured[0].size if captured else None))
    check('遮罩收起', selector.isHidden())

    # --- 关闭软件后 history.jsonl 应被清空 ---
    history_file = window.history_file
    before = os.path.getsize(history_file) if os.path.exists(history_file) else 0
    check('关闭前 history 有内容', before > 0, '%d bytes' % before)
    window.close()
    app.processEvents()
    after = os.path.getsize(history_file) if os.path.exists(history_file) else 0
    check('关闭后 history.jsonl 已清空', os.path.exists(history_file) and after == 0,
          '%d bytes' % after)
    check('关闭后不残留 captures 目录', not os.path.exists(window.capture_dir))
    outputs = sorted(os.listdir(window.outdir)) if os.path.isdir(window.outdir) else []
    check('output 里只剩 history.jsonl', outputs == ['history.jsonl'], str(outputs))

    print('\nGUIVERIFY', 'PASS' if not problems else 'FAIL -> %s' % problems, flush=True)
    app.quit()


window.signals.model_loaded.connect(lambda ok, err: QTimer.singleShot(200, after_model))
window.signals.recognized.connect(lambda *a: QTimer.singleShot(300, after_recognize))
window.signals.recognize_failed.connect(
    lambda msg: (check('识别流程', False, msg), app.quit()))
QTimer.singleShot(600000, app.quit)
app.exec_()
