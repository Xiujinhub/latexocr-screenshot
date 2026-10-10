"""核心精度验证（不含 GUI）：行投票 / 结构清理 / 主行裁剪 / 分辨率提示。

用法（在仓库根目录执行）::

    D:\\Anaconda\\envs\\OCR\\python.exe -u tests\\test_precision.py

全部通过时最后打印 ``COREVERIFY PASS``。
"""
import os
import sys
import tempfile

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import latex_ocr_core as core  # noqa: E402

TARGET = r'X_{1},X_{2}=\mathrm{chunk}(\mathrm{Conv_{1}}{}_{\times 1}(X),2)'
ROW1 = r'{{X_{1},X_{2}=\mathrm{chunk}(\mathrm{Conv_{1}}{}_{\times1}(X),2)}}'
USER_BAD = (r'\begin{array}{c}' + ROW1 +
            r'\\ {{{}_{s\doteq{\mathrm{sexram}}{}_{V}{}_{\star\star}.}}}\end{array}')
problems = []


def check(name, ok, detail=''):
    print('%-34s %s %s' % (name, 'OK  ' if ok else 'FAIL', detail), flush=True)
    if not ok:
        problems.append(name)


def render(path, blocks, figsize=(7, 1.8), dpi=150):
    fig = plt.figure(figsize=figsize, dpi=dpi)
    for latex, y, size in blocks:
        fig.text(0.01, y, '$%s$' % latex, fontsize=size, va='center')
    fig.savefig(path, dpi=dpi, facecolor='white')
    plt.close(fig)
    return Image.open(path)


# 1) 用户报过的串
variants = [USER_BAD,
            r'\begin{array}{c}' + ROW1 + r'\\ {{{}_{}}}\end{array}',
            r'\begin{array}{c}' + ROW1 + r'\\ {{{\mathrm{}}}\;{,}}}\end{array}']
got = core.consensus_latex(variants)
check('复现用户串 -> 只剩正确行', got == ROW1, got[:80])
check('结构打分：单行=0', core.structure_score(ROW1) == 0)
check('结构打分：两行 array > 10', core.structure_score(USER_BAD) > 10)
check('清理：array 去壳', core.clean_latex(USER_BAD).startswith(r'\begin{array}'))

# 2) 抓屏
check('grab_virtual_desktop', core.grab_virtual_desktop().size[0] > 100)
check('grab_region', core.grab_region((100, 100, 300, 200)).size == (300, 200))

# 3) 端到端：含下一行的框选
tmp = tempfile.mkdtemp(prefix='latexocr-core-')
mixed = render(os.path.join(tmp, 'mixed.png'), [(TARGET, 0.78, 24), ('sexram V', 0.15, 18)])
engine = core.LatexOcrEngine(on_progress=lambda m: None)
engine.load()
import time  # noqa: E402

started = time.time()
result = engine.predict(mixed)                        # 默认 samples=3 + trim='auto'
print('   （耗时 %.1fs）' % (time.time() - started), flush=True)
check('含下一行：不输出 array', 'array' not in result, result[:80])
check('含下一行：无编造内容', 'sexram' not in result and 'star' not in result, result[:80])
check('含下一行：开头正确', result.lstrip('{').startswith('X_{1}'), result[:40])

tight = render(os.path.join(tmp, 'tight.png'), [(TARGET, 0.5, 26)], figsize=(7, 1.2))
single = engine.predict(tight)
check('单行公式照常识别', single.lstrip('{').startswith('X_{1},X_{2}='), single[:60])

tiny = render(os.path.join(tmp, 'tiny.png'), [(TARGET, 0.5, 7)], figsize=(1.8, 0.4), dpi=100)
check('小图给出放大提示', bool(core.resolution_hint(tiny)), core.resolution_hint(tiny)[:34])
check('正常大小不提示', not core.resolution_hint(tight))

print('\nCOREVERIFY', 'PASS' if not problems else 'FAIL -> %s' % problems, flush=True)
