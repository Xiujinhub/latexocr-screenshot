# -*- coding: utf-8 -*-
"""pix2tex 封装：把公式截图识别成 LaTeX。

对外主要入口是 :class:`LatexOcrEngine`。

为什么要单独写这一层，而不是直接用 ``pix2tex.cli.LatexOCR``：

1. **numpy / torch 桥接断裂**
   当前 ``OCR`` 环境是 ``torch 1.13.1`` + ``numpy 2.0.2``。torch 1.13 是用 numpy 1.x
   编译的，``torch.from_numpy()`` / ``torch.as_tensor(ndarray)`` 会直接抛
   ``RuntimeError: Numpy is not available``。pix2tex 的 ``LatexOCR.__call__`` 依赖
   albumentations 的 ``ToTensorV2``（内部就是 ``torch.from_numpy``），所以官方接口在
   这个环境下必然失败。本模块改用 ``torch.frombuffer(memoryview(...))`` 构造张量，
   完全不经过 numpy 桥接。
2. **transformers 版本不兼容**
   ``transformers 4.57`` 的 ``tokenizer.decode()`` 只接受 ``List[int]``，而 pix2tex 传的
   是 Tensor，会抛 ``TypeError: argument 'ids': 'Tensor' object cannot be converted to
   'Sequence'``。本模块在解码前先 ``.tolist()``。

灰度 + 归一化的预处理与 pix2tex 的 ``test_transform`` 逐位一致，校验方法见 README。
"""

from __future__ import annotations

import os

# 打包/离线环境的第一件事：关掉几个库的联网检查与遥测（干净电脑上不该有网络请求）
os.environ.setdefault('NO_ALBUMENTATIONS_UPDATE', '1')      # albumentations 的版本检查
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
os.environ.setdefault('KMP_WARNINGS', '0')

import re
import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np
import torch
from PIL import Image, ImageEnhance, ImageGrab

__all__ = [
    'LatexOcrEngine', 'LatexOcrError', 'EmptyImageError',
    'prepare_image', 'is_blank', 'image_to_tensor', 'token2str',
    'trim_to_main_line', 'resolution_hint', 'split_latex_rows', 'is_empty_row',
    'clean_latex', 'consensus_latex', 'structure_score', 'pick_cleaner',
    'checkpoints_ready', 'ensure_checkpoints', 'describe_environment',
    'grab_virtual_desktop', 'grab_region',
    'DEFAULT_TEMPERATURE', 'DEFAULT_SAMPLES', 'DEFAULT_TRIM_LINES',
]

# ---------------------------------------------------------------------------
# 常量：全部取自 pix2tex 自身，改这里之前请先确认上游是否变化
# ---------------------------------------------------------------------------

#: pix2tex/dataset/transforms.py 里 albumentations Normalize 的 mean/std
NORMALIZE_MEAN = 0.7931
NORMALIZE_STD = 0.1738

#: 小图会被放大到短边至少 100px 并做对比度/锐化增强（对齐 pix2tex 自带 GUI 的做法）
MIN_SIDE = 100
MAX_UPSCALE = 4.0
CONTRAST_FACTOR = 1.5
SHARPNESS_FACTOR = 1.5

#: 官方默认 temperature 为 0.25；数值越大采样越随机
DEFAULT_TEMPERATURE = 0.2

#: 默认采样次数：多次采样后按行投票，可以消掉随机编造出来的行
DEFAULT_SAMPLES = 3

#: 默认的“只保留主行”策略：True = 检测到明显分离的另一行时只识别主行
#: （实测精度最高、也最快）；'auto' = 先跑原图，结果不干净时才补跑主行；
#: False = 原样识别（矩阵、分段函数等多行公式用）。
DEFAULT_TRIM_LINES = True

#: pix2tex cli.py 里 image_resizer 的迭代次数上限
MAX_RESIZE_LOOPS = 10

#: 判断“截图是空的”时的灰度极差阈值
BLANK_RANGE = 8
BLANK_DARK_LEVEL = 245


class LatexOcrError(RuntimeError):
    """识别过程中的可预期错误。"""


class EmptyImageError(LatexOcrError):
    """截图区域里没有可识别的内容（纯色 / 空白）。"""


# ---------------------------------------------------------------------------
# 环境与权重
# ---------------------------------------------------------------------------

def numpy_bridge_available() -> bool:
    """检测 torch 是否能和当前 numpy 互操作（决定是否必须走兼容路径）。"""
    try:
        torch.from_numpy(np.zeros(1, dtype=np.float32))
        return True
    except Exception:
        return False


def pix2tex_model_dir() -> str:
    """返回 pix2tex 内置的 model 目录（权重/配置/分词器都在这里）。"""
    import pix2tex

    return os.path.join(os.path.dirname(os.path.abspath(pix2tex.__file__)), 'model')


def checkpoint_paths():
    """返回 (weights.pth, image_resizer.pth) 的绝对路径。"""
    ckpt_dir = os.path.join(pix2tex_model_dir(), 'checkpoints')
    return (os.path.join(ckpt_dir, 'weights.pth'),
            os.path.join(ckpt_dir, 'image_resizer.pth'))


def checkpoints_ready() -> bool:
    """权重是否已经下载。"""
    return all(os.path.exists(p) for p in checkpoint_paths())


def ensure_checkpoints(progress: Optional[Callable[[str], None]] = None) -> None:
    """权重缺失时下载（约 120MB），失败会抛 LatexOcrError。"""
    if checkpoints_ready():
        return
    notify = progress or (lambda msg: None)
    notify('首次运行需要下载 pix2tex 权重（约 120MB），请保持网络畅通…')
    try:
        from pix2tex.model.checkpoints.get_latest_checkpoint import download_checkpoints

        download_checkpoints()
    except Exception as exc:  # 网络 / 权限问题
        raise LatexOcrError(
            '下载 pix2tex 权重失败：%s\n'
            '可以手动下载以下文件并放到 %s\n'
            '  https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/weights.pth\n'
            '  https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/image_resizer.pth'
            % (exc, os.path.join(pix2tex_model_dir(), 'checkpoints'))
        ) from exc
    if not checkpoints_ready():
        raise LatexOcrError('权重下载后仍未找到文件，请检查 %s' % pix2tex_model_dir())


# ---------------------------------------------------------------------------
# 屏幕捕获
# ---------------------------------------------------------------------------

_QT_APP = None      # 命令行模式下自己创建的 QApplication，需要保持引用


def _ensure_qt_app():
    """确保存在 QApplication（仅供抓屏兜底路径使用）。"""
    global _QT_APP
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        _QT_APP = QApplication([])
        app = _QT_APP
    return app


def _compose_qt_screens():
    """用 Qt 逐屏抓图拼成整个虚拟桌面。

    Returns:
        (PIL.Image, origin_x, origin_y)：拼好的图，以及它左上角对应的虚拟桌面坐标。
    """
    from PyQt5.QtGui import QImage

    app = _ensure_qt_app()
    entries = []
    for screen in app.screens():
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            continue
        geometry = screen.geometry()
        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        width, height = image.width(), image.height()
        raw = image.bits().asstring(image.bytesPerLine() * height)
        shot = Image.frombuffer('RGB', (width, height), raw, 'raw', 'RGB',
                                image.bytesPerLine(), 1).copy()
        entries.append((geometry, shot, width / max(1, geometry.width()),
                        height / max(1, geometry.height())))
    if not entries:
        raise LatexOcrError('无法抓取屏幕：PIL 与 Qt 两条路径都失败')

    scale_x, scale_y = entries[0][2], entries[0][3]
    left = min(item[0].x() for item in entries)
    top = min(item[0].y() for item in entries)
    right = max(item[0].x() + item[0].width() for item in entries)
    bottom = max(item[0].y() + item[0].height() for item in entries)
    canvas = Image.new('RGB', (max(1, int(round((right - left) * scale_x))),
                               max(1, int(round((bottom - top) * scale_y)))), (0, 0, 0))
    for geometry, shot, _dx, _dy in entries:
        canvas.paste(shot, (int(round((geometry.x() - left) * scale_x)),
                            int(round((geometry.y() - top) * scale_y))))
    return canvas, left, top


def grab_virtual_desktop() -> Image.Image:
    """抓取整个虚拟桌面（支持多显示器）。

    优先用 PIL（物理像素、最快）；在部分受限会话里 PIL 会抛
    ``OSError: screen grab failed``，这时自动退回 Qt 逐屏合成。
    """
    try:
        return ImageGrab.grab(all_screens=True)
    except Exception:                                        # noqa: BLE001
        return _compose_qt_screens()[0]


def grab_region(region) -> Image.Image:
    """按虚拟桌面坐标 ``(left, top, width, height)`` 抓取一块区域。"""
    left, top, width, height = (int(v) for v in region)
    try:
        return ImageGrab.grab(bbox=(left, top, left + width, top + height),
                              all_screens=True)
    except Exception:                                        # noqa: BLE001
        full, origin_x, origin_y = _compose_qt_screens()
        box = (max(0, left - origin_x), max(0, top - origin_y),
               min(full.width, left - origin_x + width),
               min(full.height, top - origin_y + height))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise LatexOcrError('区域 %s 不在屏幕范围内' % (region,))
        return full.crop(box)


def describe_environment() -> dict:
    """收集环境信息，供 ``latex_ocr_cli.py --doctor`` 使用。"""
    import platform
    info = {
        'python': platform.python_version(),
        'platform': platform.platform(),
        'numpy': np.__version__,
        'opencv': cv2.__version__,
        'torch': torch.__version__,
        'cuda_available': torch.cuda.is_available(),
        'numpy_bridge': numpy_bridge_available(),
        'model_dir': pix2tex_model_dir(),
        'checkpoints_ready': checkpoints_ready(),
    }
    try:
        import transformers

        info['transformers'] = transformers.__version__
    except Exception:
        info['transformers'] = '未安装'
    try:
        import pix2tex

        info['pix2tex'] = getattr(pix2tex, '__version__', '未知')
    except Exception as exc:
        info['pix2tex'] = '导入失败: %s' % exc
    return info


# ---------------------------------------------------------------------------
# 图像预处理
# ---------------------------------------------------------------------------

def prepare_image(img: Image.Image, min_side: int = MIN_SIDE,
                  enhance: bool = True) -> Image.Image:
    """截图预处理：转 RGB；短边不足时放大，并做对比度/锐化增强。

    增强只在“放大过”的小图上做，行为与 pix2tex 自带 GUI 一致。
    """
    if not isinstance(img, Image.Image):
        raise LatexOcrError('输入必须是 PIL.Image，实际是 %r' % type(img))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    width, height = img.size
    if width <= 0 or height <= 0:
        raise EmptyImageError('截图区域为空')
    if min(width, height) < min_side:
        scale = min(min_side / min(width, height), MAX_UPSCALE)
        new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        img = img.resize(new_size, Image.LANCZOS)
        if enhance:
            img = ImageEnhance.Contrast(img).enhance(CONTRAST_FACTOR)
            img = ImageEnhance.Sharpness(img).enhance(SHARPNESS_FACTOR)
    return img


def is_blank(img: Image.Image, blank_range: int = BLANK_RANGE,
             dark_level: int = BLANK_DARK_LEVEL) -> bool:
    """判断截图是否没有可识别内容。

    pix2tex 的 ``pad()`` 在纯色图上会因为找不到前景连通域而崩溃，这里提前拦截。
    """
    gray = np.asarray(img.convert('L'))
    if gray.size == 0:
        return True
    low, high = int(gray.min()), int(gray.max())
    if high - low < blank_range:      # 纯色
        return True
    return low > dark_level           # 只有极浅的颜色，没有“墨水”


def image_to_tensor(img: Image.Image) -> torch.Tensor:
    """PIL 图 → ``(1, H, W)`` float32 张量。

    等价于 pix2tex ``test_transform`` 的 ``ToGray + Normalize + ToTensorV2``，
    但用 ``torch.frombuffer`` 取代 ``torch.from_numpy``，绕开 numpy 桥接。
    """
    arr = np.asarray(img.convert('RGB'))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)   # 与 alb.ToGray 的 weighted_average 逐位一致
    gray = gray.astype(np.float32)
    gray -= np.float32(NORMALIZE_MEAN * 255.0)     # alb.Normalize: (x - mean*255) / (std*255)
    gray *= np.float32(1.0 / (NORMALIZE_STD * 255.0))
    shape = gray.shape
    flat = torch.frombuffer(memoryview(gray), dtype=torch.float32).clone()
    return flat.view(shape).unsqueeze(0)


def token2str(tokens: torch.Tensor, tokenizer) -> list:
    """Tensor 形式的 token → LaTeX 字符串（对齐 pix2tex.utils.token2str）。"""
    if tokens.ndim == 1:
        tokens = tokens.unsqueeze(0)
    results = []
    for row in tokens:
        text = tokenizer.decode(row.tolist())      # transformers>=4.4x 只接受 List[int]
        text = (''.join(text.split(' '))
                .replace('Ġ', ' ')
                .replace('[EOS]', '')
                .replace('[BOS]', '')
                .replace('[PAD]', '')
                .strip())
        results.append(text)
    return results


# ---------------------------------------------------------------------------
# 去噪与“只保留主行”
# ---------------------------------------------------------------------------

def trim_to_main_line(img: Image.Image, gap_ratio: float = 1.3,
                      height_ratio: float = 1.15, ink_threshold: int = 160,
                      min_band: int = 3):
    """把框选范围内“明显是另外一行”的内容裁掉，只留最主要的一行。

    截图时很容易顺手把公式上面/下面的另一行文字也框进来。pix2tex 会把它们当成一个
    多行公式，输出 ``\\begin{array}...\\end{array}``，并在多余的行里编造符号
    （例如 ``{{{}_{s\\doteq{\\mathrm{sexram}}...}}}``）。

    做法：按水平方向统计墨水得到文字带，当某条带与其它带之间存在**足够大的空白**
    （gap >= gap_ratio × 较高的那条带的高度）且主带明显更高时，才判定为“不同的行”。
    矩阵、分段函数、带上下限的积分等真正的多行公式，行间距都很小，不会被裁。

    Returns:
        (裁剪后的图, 是否发生了裁剪)
    """
    gray = np.asarray(img.convert('L'))
    if gray.size == 0:
        return img, False
    dark = gray.mean() > 127                     # 白底黑字（截图常态）
    ink = (gray < ink_threshold) if dark else (gray > 255 - ink_threshold)
    row_has_ink = ink.any(axis=1)

    bands = []
    start = None
    for index, has_ink in enumerate(row_has_ink):
        if has_ink and start is None:
            start = index
        elif not has_ink and start is not None:
            bands.append((start, index))
            start = None
    if start is not None:
        bands.append((start, len(row_has_ink)))
    bands = [band for band in bands if band[1] - band[0] >= min_band]
    if len(bands) < 2:
        return img, False

    heights = [bottom - top for top, bottom in bands]
    areas = [int(ink[top:bottom].sum()) for top, bottom in bands]
    main = max(range(len(bands)), key=lambda i: (heights[i], areas[i]))

    for index, (top, bottom) in enumerate(bands):
        if index == main:
            continue
        gap = bands[main][0] - bottom if index < main else top - bands[main][1]
        if gap < gap_ratio * max(heights[main], heights[index]):
            return img, False                   # 间距不够大 → 视为同一个多行公式
        if heights[main] < height_ratio * heights[index]:
            return img, False                   # 主带没有明显更高 → 不敢裁
    margin = max(2, int(round(0.15 * heights[main])))
    box = (0, max(0, bands[main][0] - margin), img.width,
           min(img.height, bands[main][1] + margin))
    return img.crop(box), True


def resolution_hint(image: Image.Image, min_height: int = 18,
                    min_width: int = 120, ink_threshold: int = 160) -> str:
    """公式在原始截图里太小就给出提示（返回空串表示无需提示）。

    这是提升识别率最有效的一招：让用户先在 PDF/网页里放大，再截图，模型的输入
    分辨率会真正提高（而不是靠 LANCZOS 插值放大）。
    """
    gray = np.asarray(image.convert('L'))
    if gray.size == 0:
        return ''
    ink = (gray < ink_threshold) if gray.mean() > 127 else (gray > 255 - ink_threshold)
    if not ink.any():
        return ''
    rows = int(ink.any(axis=1).sum())
    cols = int(ink.any(axis=0).sum())
    if rows < min_height:
        return '公式高度只有 %d 像素，先把页面放大（如 Ctrl+=）再截图会明显更准' % rows
    if cols < min_width:
        return '公式宽度只有 %d 像素，先把页面放大再截图会明显更准' % cols
    return ''


# ---------------------------------------------------------------------------
# LaTeX 结果清理与多采样投票
# ---------------------------------------------------------------------------

_ARRAY_RE = re.compile(r'^\\begin\{array\}\{([^}]*)\}(.*)\\end\{array\}$', re.S)
#: 纯排版命令（去掉它们不影响内容判断）。
#: 注意命令名后面要用 (?![a-zA-Z])，不能用 \b —— 否则 \; \, \! 这类标点命令匹配不上。
_FORMAT_ONLY = re.compile(
    r'\\(?:left|right|quad|qquad|thinspace|medspace|thickspace|displaystyle|'
    r'textstyle|scriptstyle|mathrm|mathbf|mathsf|mathtt|mathit|operatorname\*?|'
    r'text|hspace|phantom|vphantom|strut|bigl|bigr|Bigl|Bigr|big|Big|middle|'
    r'limits|nonumber|notag)(?![a-zA-Z])'
    r'|\\[,;:!]')


def split_latex_rows(latex: str):
    """拆分 ``\\begin{array}{spec} r1 \\\\ r2 \\end{array}``。

    Returns:
        (spec, rows)。不是 array 时返回 ``('', [整串])``。
    """
    match = _ARRAY_RE.match(latex.strip())
    if not match:
        return '', [latex.strip()]
    return match.group(1).strip(), [row.strip() for row in match.group(2).split('\\\\')]


def is_empty_row(row: str) -> bool:
    """判断 array 里的某一行是否只是空白装饰（如 ``{{{}}}\\;{,}``）。"""
    text = _FORMAT_ONLY.sub('', row)
    text = re.sub(r'[{}\s~^_&\.\,;:]', '', text)
    return len(text) == 0


def _vote_key(text: str) -> str:
    """投票用的规范化：忽略空白和纯排版差异。"""
    text = _FORMAT_ONLY.sub('', text)
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'[{}]', '', text)
    return text.strip('\\')


def clean_latex(latex: str) -> str:
    """去掉多余空行、单行 array 外壳、行尾多余的 ``\\\\``。"""
    spec, rows = split_latex_rows(latex)
    rows = [row for row in rows if not is_empty_row(row)]
    if not rows:
        return ''
    if len(rows) == 1:
        return rows[0]
    return '\\begin{array}{%s}%s\\end{array}' % (spec or 'c', '\\\\'.join(rows))


def structure_score(latex: str) -> int:
    """给结果“结构干净程度”打分：越小越干净。

    非 array 的单行结果得 0；带 array 外壳或用多行的结果分数更高（每多一行 +1）。
    用于在“原图识别”和“只保留主行后识别”两个候选里挑更干净的那个。
    """
    spec, rows = split_latex_rows(latex)
    rows = [row for row in rows if not is_empty_row(row)]
    if not spec:
        return 0 if len(rows) == 1 else 10 + len(rows)
    return 10 + max(1, len(rows))


def pick_cleaner(outputs):
    """在多个候选结果里选结构最干净的那个（并列时保留靠前的候选）。"""
    outputs = [text for text in outputs if text]
    if not outputs:
        return ''
    best = outputs[0]
    best_score = structure_score(best)
    for text in outputs[1:]:
        score = structure_score(text)
        if score < best_score:
            best, best_score = text, score
    return best


def consensus_latex(results, threshold: int = None) -> str:
    """对多次采样的结果按“行”投票，只保留稳定的行。

    pix2tex 采样有随机性：真正的公式内容几乎每次都一样，而因为画面里多了一行文字、
    噪点而被编造出来的行每次都不一样。按行投票可以把后者清掉。

    Args:
        results: 多次采样得到的 LaTeX 字符串列表。
        threshold: 至少出现几次才保留；默认多数（n=1 时为 1）。
    """
    results = [text for text in results if text and text.strip()]
    if not results:
        return ''
    if len(results) == 1:
        return clean_latex(results[0])

    if threshold is None:
        threshold = max(2, (len(results) + 1) // 2)

    votes = {}
    specs = {}
    for text in results:
        spec, rows = split_latex_rows(text)
        if spec:
            specs[spec] = specs.get(spec, 0) + 1
        for index, row in enumerate(rows):
            if is_empty_row(row):
                continue
            key = _vote_key(row)
            if not key:
                continue
            entry = votes.setdefault(key, {'count': 0, 'order': [], 'text': row})
            entry['count'] += 1
            entry['order'].append(index)

    kept = [entry for entry in votes.values() if entry['count'] >= threshold]
    if not kept:                      # 全都不稳定 → 退回到多数完整结果
        counts = {}
        for text in results:
            key = _vote_key(text)
            counts[key] = (counts.get(key, (0, text))[0] + 1, text)
        return clean_latex(max(counts.values(), key=lambda item: item[0])[1])

    kept.sort(key=lambda entry: (sum(entry['order']) / len(entry['order']), entry['order'][0]))
    if len(kept) == 1:
        return clean_latex(kept[0]['text'])
    spec = max(specs.items(), key=lambda item: item[1])[0] if specs else 'c'
    return '\\begin{array}{%s}%s\\end{array}' % (spec, '\\\\'.join(e['text'] for e in kept))



# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

class LatexOcrEngine:
    """pix2tex 推理引擎（懒加载 + 线程安全）。

    典型用法::

        engine = LatexOcrEngine()
        latex = engine.predict(pil_image)
    """

    def __init__(self, temperature: float = DEFAULT_TEMPERATURE,
                 device: Optional[str] = None,
                 samples: int = DEFAULT_SAMPLES,
                 trim_lines=DEFAULT_TRIM_LINES,
                 on_progress: Optional[Callable[[str], None]] = None):
        self.temperature = float(temperature)
        self.device = device
        self.samples = max(1, int(samples))
        self.trim_lines = DEFAULT_TRIM_LINES if trim_lines is None else trim_lines
        self.load_seconds: Optional[float] = None
        self._on_progress = on_progress or (lambda msg: None)
        self._load_lock = threading.RLock()
        self._predict_lock = threading.Lock()
        self._api = None
        self._args = None
        self._model = None
        self._resizer = None
        self._tokenizer = None

    # -- 状态 ---------------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._model is not None

    def close(self) -> None:
        """释放模型（一般不需要，进程退出即释放）。"""
        with self._load_lock:
            self._model = None
            self._resizer = None
            self._tokenizer = None

    # -- 加载 ---------------------------------------------------------------
    def load(self) -> None:
        """加载权重、图像缩放器和分词器；重复调用是安全的。"""
        with self._load_lock:
            if self._model is not None:
                return
            started = time.time()
            ensure_checkpoints(self._on_progress)
            api = self._import_pix2tex()
            device = self.device or ('cuda' if torch.cuda.is_available() else 'cpu')
            self._on_progress('加载模型（首次约 10~30 秒）…')

            config_file = os.path.join(api['model_dir'], 'settings', 'config.yaml')
            with open(config_file, 'r', encoding='utf-8') as fh:
                params = api['yaml'].load(fh, Loader=api['yaml'].FullLoader)
            args = api['parse_args'](api['Munch'](params))
            args.update({
                'config': 'settings/config.yaml',
                'checkpoint': 'checkpoints/weights.pth',
                'no_cuda': device == 'cpu',
                'no_resize': False,
            })
            args.wandb = False            # get_model() 会 import wandb，本环境没有装
            args.device = device
            args.temperature = self.temperature

            weights, resizer_weights = checkpoint_paths()
            model = api['get_model'](args)
            model.load_state_dict(torch.load(weights, map_location=device))
            model.eval()

            resizer = None
            if os.path.exists(resizer_weights) and not args.no_resize:
                resizer = api['ResNetV2'](
                    layers=[2, 3, 3], num_classes=max(args.max_dimensions) // 32,
                    global_pool='avg', in_chans=1, drop_rate=.05, preact=True,
                    stem_type='same', conv_layer=api['StdConv2dSame']).to(device)
                resizer.load_state_dict(torch.load(resizer_weights, map_location=device))
                resizer.eval()

            tokenizer = api['PreTrainedTokenizerFast'](
                tokenizer_file=os.path.join(api['model_dir'], 'dataset', 'tokenizer.json'))

            self._api = api
            self._args = args
            self._model = model
            self._resizer = resizer
            self._tokenizer = tokenizer
            self.load_seconds = time.time() - started
            self._on_progress('模型加载完成（%.1fs，设备 %s）' % (self.load_seconds, device))

    def _import_pix2tex(self) -> dict:
        """延迟导入 pix2tex 相关模块（导入本身就要好几秒）。"""
        if self._api is not None:
            return self._api
        import yaml
        from munch import Munch
        from timm.models.layers import StdConv2dSame
        from timm.models.resnetv2 import ResNetV2
        from transformers import PreTrainedTokenizerFast

        from pix2tex.cli import minmax_size
        from pix2tex.models import get_model
        from pix2tex.utils import pad, parse_args, post_process

        self._api = {
            'yaml': yaml, 'Munch': Munch,
            'ResNetV2': ResNetV2, 'StdConv2dSame': StdConv2dSame,
            'PreTrainedTokenizerFast': PreTrainedTokenizerFast,
            'pad': pad, 'minmax_size': minmax_size,
            'parse_args': parse_args, 'post_process': post_process,
            'get_model': get_model,
            'model_dir': pix2tex_model_dir(),
        }
        return self._api

    # -- 预处理 -------------------------------------------------------------
    def _tensorize(self, img: Image.Image) -> torch.Tensor:
        """复刻 pix2tex ``LatexOCR.__call__`` 中“pad → 限尺寸 → 预测最佳宽度”的流程。

        返回 ``(1, 1, H, W)`` 张量。
        """
        api = self._api
        args = self._args
        img = api['minmax_size'](api['pad'](img), args.max_dimensions, args.min_dimensions)
        if self._resizer is not None and not args.no_resize:
            base = img.convert('RGB').copy()
            ratio, width, height = 1, base.size[0], base.size[1]
            for _ in range(MAX_RESIZE_LOOPS):
                height = int(height * ratio)
                resample = Image.BILINEAR if ratio > 1 else Image.LANCZOS
                img = api['pad'](api['minmax_size'](
                    base.resize((width, height), resample),
                    args.max_dimensions, args.min_dimensions))
                predicted = self._resizer(
                    image_to_tensor(img)[:1].unsqueeze(0).to(args.device)).argmax(-1).item()
                width = (predicted + 1) * 32
                if width == img.size[0]:
                    break
                ratio = width / img.size[0]
        return image_to_tensor(img)[:1].unsqueeze(0).to(args.device)

    # -- 推理 ---------------------------------------------------------------
    def predict(self, image: Image.Image, temperature: Optional[float] = None,
                samples: Optional[int] = None, trim_lines=None) -> str:
        """识别一张公式图，返回 LaTeX 字符串。

        Args:
            image: 公式截图（PIL.Image，任意模式）。
            temperature: 覆盖默认温度；越大结果越随机。
            samples: 采样次数，多次采样后按行投票（默认取构造时的设置）。
            trim_lines: ``False`` 不裁、``True`` 总是只保留主行、``'auto'`` 两个候选里取更干净的。

        Raises:
            EmptyImageError: 截图是纯色/空白。
            LatexOcrError: 权重下载失败、识别过程异常等。
        """
        self.load()
        with self._predict_lock:
            base = prepare_image(image)
            if is_blank(base):
                raise EmptyImageError('截图里没有找到公式（画面接近纯色）')

            mode = self.trim_lines if trim_lines is None else trim_lines
            count = max(1, int(self.samples if samples is None else samples))
            temp = self.temperature if temperature is None else float(temperature)

            # 主行裁剪从“原图”上做：prepare_image 的放大/增强会改变墨水形状，
            # 实测在原始像素上裁剪再交给 image_resizer 决定缩放比，字符更准。
            trimmed, did_trim = trim_to_main_line(image)
            if mode is True and did_trim:
                candidates = [trimmed]           # 用户明确要求：只识别主要的那一行
            else:
                candidates = [base]              # 原图结果字符更稳，优先用它

            try:
                outputs = [consensus_latex(self._sample_texts(candidate, count, temp))
                           for candidate in candidates]
                # 'auto'：只有原图结果“结构不干净”（多出行/套了 array）时，
                # 才多花一次代价去识别裁好的主行，再挑更干净的那个。
                if mode == 'auto' and did_trim and structure_score(outputs[0]) > 0:
                    outputs.append(consensus_latex(self._sample_texts(trimmed, count, temp)))
            except EmptyImageError:
                raise
            except Exception as exc:
                raise LatexOcrError('识别失败：%s: %s' % (type(exc).__name__, exc)) from exc
            return pick_cleaner(outputs)

    def _sample_texts(self, image: Image.Image, count: int, temperature: float) -> list:
        """对同一张预处理后的图采样若干次，返回原始解码结果。"""
        with torch.no_grad():
            tensor = self._tensorize(image)
            texts = []
            for index in range(count):
                # 第一次用贪心解码，其余用温度采样，兼顾稳定与多样性
                current = 1e-8 if (count > 1 and index == 0) else temperature
                decoded = self._model.generate(tensor, temperature=current)
                texts.append(self._api['post_process'](
                    token2str(decoded, self._tokenizer)[0]))
        return texts

