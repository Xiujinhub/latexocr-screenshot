# -*- coding: utf-8 -*-
"""命令行版公式识别：图片文件 / 剪贴板 / 屏幕区域 → LaTeX。

用法示例::

    python latex_ocr_cli.py --doctor                 # 检查环境
    python latex_ocr_cli.py --selfcheck              # 自检（画一个公式再识别回来）
    python latex_ocr_cli.py formula.png              # 识别图片
    python latex_ocr_cli.py --clipboard              # 识别剪贴板里的图片
    python latex_ocr_cli.py --region 100,200,600,120 # 抓屏幕上的一块区域
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
import time

from PIL import Image, ImageGrab

from latex_ocr_core import (DEFAULT_SAMPLES, DEFAULT_TEMPERATURE, EmptyImageError,
                            LatexOcrEngine, LatexOcrError, describe_environment,
                            grab_region, grab_virtual_desktop)

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff')

#: --trim-lines 的三个取值 → 引擎参数
TRIM_VALUES = {'auto': 'auto', 'on': True, 'off': False}


def log(message: str = '') -> None:
    print(message, file=sys.stderr)


def parse_region(text: str):
    """解析 ``left,top,width,height`` 形式的区域参数。"""
    parts = [p.strip() for p in re.split(r'[,，]', text) if p.strip()]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError('区域格式应为 left,top,width,height，例如 100,200,600,120')
    try:
        left, top, width, height = (int(float(p)) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError('区域坐标必须是数字：%r' % text)
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError('区域宽高必须大于 0')
    return left, top, width, height


def grab_screen(region=None) -> Image.Image:
    """截取整屏或指定区域（虚拟桌面坐标，支持多显示器）。"""
    if region is None:
        return grab_virtual_desktop()
    return grab_region(region)


def grab_clipboard() -> Image.Image:
    """读取剪贴板中的图片；若剪贴板里是文件路径则打开第一个图片文件。"""
    try:
        data = ImageGrab.grabclipboard()
    except Exception as exc:
        raise LatexOcrError('读取剪贴板失败：%s' % exc) from exc
    if isinstance(data, Image.Image):
        return data
    if isinstance(data, list) and data:
        for path in data:
            if str(path).lower().endswith(IMAGE_SUFFIXES):
                return Image.open(path)
        raise LatexOcrError('剪贴板里是文件，但不是图片文件')
    raise LatexOcrError('剪贴板里没有图片（请先截图复制）')


def recognize(engine: LatexOcrEngine, image: Image.Image, name: str, as_json: bool) -> int:
    """识别单张图并输出结果，返回进程退出码。"""
    started = time.time()
    try:
        latex = engine.predict(image)
    except EmptyImageError as exc:
        if as_json:
            print(json.dumps({'source': name, 'ok': False, 'error': str(exc)}, ensure_ascii=False))
        else:
            log('[跳过] %s：%s' % (name, exc))
        return 2
    except LatexOcrError as exc:
        if as_json:
            print(json.dumps({'source': name, 'ok': False, 'error': str(exc)}, ensure_ascii=False))
        else:
            log('[失败] %s：%s' % (name, exc))
        return 1
    elapsed = time.time() - started
    if as_json:
        print(json.dumps({'source': name, 'ok': True, 'latex': latex,
                          'seconds': round(elapsed, 2)}, ensure_ascii=False))
    else:
        print(latex)
        log('  <- %s（%.2fs）' % (name, elapsed))
    return 0


def render_formula(latex: str, path: str) -> None:
    """用 matplotlib 的 mathtext 画一个公式图，用于自检。"""
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(6, 1.6), dpi=150)
    figure.text(0.02, 0.5, '$%s$' % latex, fontsize=30, va='center', ha='left')
    figure.savefig(path, dpi=150, facecolor='white')
    plt.close(figure)


def _canonical(text: str) -> str:
    """去掉对比较无意义的装饰，用于自检的宽松比对。"""
    text = text.replace(r'\left', '').replace(r'\right', '')
    text = text.replace('{', '').replace('}', '').replace(' ', '')
    return text.strip()


def selfcheck(engine: LatexOcrEngine) -> int:
    """画两个公式再识别回来，验证整条链路是否正常。"""
    cases = [r'x^{2}+y^{2}=z^{2}', r'\frac{a}{b}=c']
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for index, expected in enumerate(cases, 1):
            png = os.path.join(tmp, 'case%d.png' % index)
            render_formula(expected, png)
            started = time.time()
            actual = engine.predict(Image.open(png))
            elapsed = time.time() - started
            want, got = _canonical(expected), _canonical(actual)
            ratio = difflib.SequenceMatcher(None, want, got).ratio()
            if want == got:
                verdict = 'PASS'
            elif ratio >= 0.7:
                verdict = '近似'
            else:
                verdict = 'FAIL'
                failed += 1
            log('[%s] 期望 %-20s 实际 %-22s 相似度 %.2f 用时 %.2fs'
                % (verdict, expected, actual, ratio, elapsed))
            print(actual)
    if failed:
        log('\n自检未通过：%d/%d 例差异较大，可调整 temperature 后重试。' % (failed, len(cases)))
        return 1
    log('\n自检通过，环境可用。')
    return 0


def print_doctor() -> int:
    info = describe_environment()
    log('=== 公式识别环境自检 ===')
    for key, value in info.items():
        log('%-20s %s' % (key, value))
    if not info['numpy_bridge']:
        log('\n注意：torch.from_numpy 不可用（numpy 与 torch 版本不匹配），'
            '已自动启用 torch.frombuffer 兼容路径，无需处理。')
    if not info['checkpoints_ready']:
        log('\n注意：pix2tex 权重尚未下载，首次识别会自动下载约 120MB。')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='latex_ocr_cli.py',
        description='把公式截图识别为 LaTeX（基于 pix2tex）')
    parser.add_argument('images', nargs='*', help='待识别的图片文件（可多个）')
    parser.add_argument('-c', '--clipboard', action='store_true', help='识别剪贴板里的图片')
    parser.add_argument('-s', '--screen', action='store_true', help='截取整个屏幕后识别')
    parser.add_argument('-r', '--region', type=parse_region, metavar='L,T,W,H',
                        help='截取屏幕指定区域后识别，如 100,200,600,120')
    parser.add_argument('-t', '--temperature', type=float, default=DEFAULT_TEMPERATURE,
                        help='采样温度，越大越随机（默认 %(default)s）')
    parser.add_argument('--samples', type=int, default=DEFAULT_SAMPLES,
                        help='采样次数，多次采样按行投票可去掉编造出来的行（默认 %(default)s，'
                             '设为 1 更快但可能多出杂行）')
    parser.add_argument('--trim-lines', choices=['on', 'auto', 'off'], default='on',
                        help='“只保留主行”策略：on=检测到明显分离的另一行时只识别主行（默认，'
                             '实测最准最快）、auto=先跑原图、结果不干净时才补跑主行、'
                             'off=原样识别（矩阵/分段函数等多行公式用 off）')
    parser.add_argument('-d', '--device', choices=['cpu', 'cuda'], default=None,
                        help='推理设备（默认自动检测）')
    parser.add_argument('--json', action='store_true', help='以 JSON 输出结果')
    parser.add_argument('--doctor', action='store_true', help='只检查环境后退出')
    parser.add_argument('--selfcheck', action='store_true', help='渲染公式并识别，验证链路')
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')   # type: ignore[attr-defined]
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')   # type: ignore[attr-defined]

    args = build_parser().parse_args(argv)
    if args.doctor:
        return print_doctor()

    engine = LatexOcrEngine(temperature=args.temperature, device=args.device,
                            samples=args.samples,
                            trim_lines=TRIM_VALUES[args.trim_lines],
                            on_progress=log)
    try:
        if args.selfcheck:
            return selfcheck(engine)

        jobs = []
        for path in args.images:
            if not os.path.exists(path):
                log('[跳过] 文件不存在：%s' % path)
                continue
            jobs.append(('文件 %s' % path, Image.open(path)))
        if args.region is not None:
            jobs.append(('屏幕区域 %s' % (args.region,), grab_screen(args.region)))
        elif args.screen:
            jobs.append(('整屏', grab_screen()))
        if args.clipboard:
            jobs.append(('剪贴板', grab_clipboard()))
        if not jobs:
            log('未指定输入，改为读取剪贴板…')
            jobs.append(('剪贴板', grab_clipboard()))

        started = time.time()
        engine.load()
        log('模型就绪（加载耗时 %.1fs）' % (time.time() - started))

        code = 0
        for name, image in jobs:
            code = max(code, recognize(engine, image, name, args.json))
        return code
    except LatexOcrError as exc:
        log('[错误] %s' % exc)
        return 1
    except KeyboardInterrupt:
        log('\n已中断')
        return 130


if __name__ == '__main__':
    sys.exit(main())

