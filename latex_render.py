# -*- coding: utf-8 -*-
"""把 LaTeX 渲染成 PNG，供界面预览。

两条路线：

1. **xelatex（首选）**：本机装了 TeX Live 时，用 ``standalone`` 文档类编译成 PDF，
   再用 PyMuPDF 转 PNG。渲染结果与真实排版完全一致，``\\left...\\right``、
   ``\\begin{array}``、``\\begin{cases}`` 等等都能正常显示。
2. **matplotlib mathtext（降级）**：没有 TeX Live 时使用。它只支持 LaTeX 的一个子集，
   所以先调用 :func:`normalize_for_mathtext` 把 TeX 写法规范化
   （例如 ``\\mathcal L`` → ``\\mathcal{L}``、去掉 ``\\left/\\right``、
   ``\\bm`` → ``\\mathbf``），多行的 ``array`` 再拆成多行分别渲染。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile

__all__ = [
    'LatexRenderError', 'engine_name', 'latex_available', 'find_engine',
    'normalize_for_mathtext', 'render_to_png', 'render_cached',
]

#: Windows 下不要弹出控制台窗口（GUI 里每渲染一次都要调一次 xelatex）
_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

#: 依次尝试的导言区：完整版 → 精简版（个别宏包缺失时还能救）
_PREAMBLES = (
    '\\documentclass[border=2pt]{standalone}\n'
    '\\usepackage{amsmath,amssymb,amsfonts,bm,mathtools}\n',
    '\\documentclass[border=2pt]{standalone}\n'
    '\\usepackage{amsmath}\n',
)

#: 正文的两种包裹方式：行内公式 → 原样（用于用户直接粘贴了完整环境的情况）
_BODIES = ('$\\displaystyle %s$', '%s')

_FONT_COMMANDS = ('mathcal', 'mathrm', 'mathbf', 'mathsf', 'mathtt', 'mathit',
                  'mathbb', 'mathfrak', 'mathnormal', 'boldsymbol')


class LatexRenderError(RuntimeError):
    """LaTeX 渲染失败（没装 TeX Live、语法错误、超时等）。"""


def find_engine() -> str:
    """返回可用的 LaTeX 引擎路径，没有则返回空串。"""
    return shutil.which('xelatex') or ''


def latex_available() -> bool:
    """是否可以用真实 LaTeX 渲染。"""
    return bool(find_engine())


def engine_name(prefer_latex: bool = True) -> str:
    """当前实际使用的预览引擎名，用于界面显示。"""
    if prefer_latex and latex_available():
        return 'xelatex（TeX Live）'
    return 'matplotlib mathtext'


def normalize_for_mathtext(latex: str) -> str:
    """把 TeX 写法规范化成 mathtext 能解析的形式。

    mathtext 的坑（实测）：
    * ``\\left``/``\\right`` 不支持 → 直接去掉（括号本身保留）；
    * ``\\mathcal L`` 这种不带花括号的单字符参数不支持 → 补成 ``\\mathcal{L}``；
    * ``\\bm{x}``、``\\underbrace{}`` 不支持 → 换成 ``\\mathbf{x}``、去掉命令保留内容。
    """
    text = latex or ''
    text = re.sub(r'\\left\s*\.', '', text)
    text = re.sub(r'\\right\s*\.', '', text)
    text = re.sub(r'\\(?:left|right)\s*', '', text)
    text = re.sub(r'\\(?:bigl|bigr|Bigl|Bigr|biggl|biggr|Biggl|Biggr|'
                  r'big|Big|bigg|Bigg|middle)\s*', '', text)
    text = re.sub(r'\\(?:displaystyle|textstyle|scriptstyle|limits|nonumber|notag)\s*', '', text)
    text = re.sub(r'\\bm\s*', r'\\mathbf', text)
    text = re.sub(r'\\(?:under|over)brace\b', '', text)
    text = re.sub(r'\\(' + '|'.join(_FONT_COMMANDS) + r')\s+([A-Za-z0-9])',
                  lambda match: '\\%s{%s}' % (match.group(1), match.group(2)), text)
    return text.strip()


def _run_xelatex(engine: str, workdir: str, tex_name: str, timeout: float):
    """在 workdir 里编译 tex_name，返回 (是否成功, 错误摘要)。"""
    try:
        # cwd 切到临时目录、只传文件名：TeX 处理带 ~ 的 8.3 短路径会失败
        proc = subprocess.run(
            [engine, '-interaction=nonstopmode', '-halt-on-error', tex_name],
            cwd=workdir, capture_output=True, text=True, errors='replace',
            timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, 'xelatex 超时（%.0fs）' % timeout
    except OSError as exc:
        return False, 'xelatex 无法启动：%s' % exc
    if proc.returncode == 0:
        return True, ''
    lines = [line.strip() for line in (proc.stdout or '').splitlines()
             if line.startswith('!')]
    return False, '；'.join(lines[:2]) or ('xelatex 退出码 %d' % proc.returncode)


def _pdf_to_png(pdf_path: str, png_path: str, dpi: int) -> None:
    """用 PyMuPDF 把 PDF 第一页转成 PNG。"""
    try:
        import fitz
    except ImportError as exc:                              # pragma: no cover
        raise LatexRenderError('缺少 PyMuPDF，无法转换 PDF：%s' % exc) from exc
    zoom = max(0.5, dpi / 72.0)
    document = fitz.open(pdf_path)
    try:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pixmap.save(png_path)
    finally:
        document.close()


def render_to_png(latex: str, png_path: str, dpi: int = 180,
                  timeout: float = 90.0, engine: str = None) -> str:
    """把一段 LaTeX 渲染成 PNG 文件。

    Args:
        latex: 公式源码（``$`` 可带可不带，会自动剥掉）。
        png_path: 输出 PNG 路径。
        dpi: 渲染分辨率，180 左右在界面上已经足够清晰。
        timeout: 单次编译超时秒数。
        engine: 指定 xelatex 路径；默认自动查找。

    Raises:
        LatexRenderError: 没装 TeX Live、编译失败或超时。
    """
    engine = engine or find_engine()
    if not engine:
        raise LatexRenderError('没有找到 xelatex，无法用 LaTeX 渲染预览')
    body = (latex or '').strip().strip('$').strip()
    if not body:
        raise LatexRenderError('内容为空')

    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    errors = []
    with tempfile.TemporaryDirectory(prefix='latexocr-render-') as workdir:
        for preamble in _PREAMBLES:
            for template in _BODIES:
                with open(os.path.join(workdir, 'preview.tex'), 'w', encoding='utf-8') as handle:
                    handle.write(preamble + '\\begin{document}\n'
                                 + (template % body) + '\n\\end{document}\n')
                ok, message = _run_xelatex(engine, workdir, 'preview.tex', timeout)
                if not ok:
                    errors.append(message)
                    continue
                pdf = os.path.join(workdir, 'preview.pdf')
                if not os.path.exists(pdf):
                    errors.append('未生成 PDF')
                    continue
                _pdf_to_png(pdf, png_path, dpi)
                return png_path
    raise LatexRenderError('LaTeX 编译失败：%s' % (errors[-1] if errors else '未知错误'))


def _prune_cache(cache_dir: str, keep: int = 200) -> None:
    """只在缓存里保留最近 keep 个文件。"""
    try:
        files = [os.path.join(cache_dir, name) for name in os.listdir(cache_dir)
                 if name.startswith('preview-') and name.endswith('.png')]
    except OSError:
        return
    if len(files) <= keep:
        return
    files.sort(key=lambda path: os.path.getmtime(path))
    for path in files[:-keep]:
        try:
            os.remove(path)
        except OSError:
            pass


def render_cached(latex: str, cache_dir: str, dpi: int = 180,
                  timeout: float = 90.0) -> str:
    """带缓存的渲染：同一段 LaTeX 只会真正编译一次。"""
    key = hashlib.sha1(('%d|%s' % (dpi, latex)).encode('utf-8')).hexdigest()[:20]
    target = os.path.join(cache_dir, 'preview-%s.png' % key)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target
    os.makedirs(cache_dir, exist_ok=True)
    staging = target + '.part'
    try:
        render_to_png(latex, staging, dpi=dpi, timeout=timeout)
        os.replace(staging, target)          # 原子替换，避免界面读到半成品
    except Exception:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass
        raise
    _prune_cache(cache_dir)
    return target
