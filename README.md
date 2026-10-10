# 公式截图识别（LaTeX-OCR）

把屏幕上的数学公式框选下来，直接识别成 LaTeX 代码。基于 `pix2tex`，运行在 conda 的
`OCR` 环境（`D:\Anaconda\envs\OCR`，Python 3.9 + torch 1.13.1 CPU + PyQt5）。

## 下载 / 安装

* **直接用**：到 [Releases](https://github.com/Xiujinhub/latexocr-screenshot/releases/latest)
  下载 `LaTeXOCR-Setup-1.0.0.exe` —— 安装包内置 Python 运行时、全部依赖和模型权重，
  Windows 10/11 64 位，**不需要 Python / 联网 / 管理员权限**，装完即可离线识别。
* **改代码 / 从源码跑**：准备好 conda 环境 `OCR`（依赖见下），双击 `run_gui.bat` 即可。


## 文件清单

| 文件 | 说明 |
| --- | --- |
| `screenshot_latex.py` | **主程序**：桌面工具，全局快捷键截图 → 框选 → 识别 → 预览/复制 |
| `latex_ocr_core.py` | 识别引擎 + 环境兼容层（加载模型、预处理、推理） |
| `latex_render.py` | 预览渲染：优先 `xelatex`（TeX Live）+ PyMuPDF，其次 matplotlib mathtext |
| `latex_ocr_cli.py` | 命令行版：图片文件 / 剪贴板 / 屏幕区域 / 自检 / 环境诊断 |
| `run_gui.bat` / `run_cli.bat` | 双击即用的启动脚本（已写好 OCR 环境路径） |
| `tests/test_precision.py` | 精度回归：行投票 / 结构清理 / 主行裁剪判定 / 分辨率提示 |
| `tests/test_gui.py` | GUI 回归：加载 / 模拟截图 / 结果 / 剪贴板 / 历史 / 格式 / 预览 / 遮罩框选 |
| `tests/test_theme.py` | 界面回归：配色是否生效、字体有没有被样式表接管 |
| `packaging/` | 打包脚本（PyInstaller spec + Inno Setup 脚本 + 图标），见 `packaging/README.md` |
| `dist/` | 打包产物：`LaTeXOCR-Setup-1.0.0.exe` 安装包 与 `LaTeXOCR\` 绿色版 |
| `docs/ui-preview.png` | 界面效果图（浅绿主题的实际截图） |
| `output/history.jsonl` | 运行时的历史记录（本次会话有效，**关闭软件时自动清空**） |

## 快速开始

```bat
:: 1) 先自检，确认环境可用（首次会自动下载约 120MB 权重）
run_cli.bat --doctor
run_cli.bat --selfcheck

:: 2) 启动界面工具
run_gui.bat
```

启动后：

1. 按 **Ctrl+Alt+M**（或点“截图识别”）→ 屏幕变暗并冻结；
2. 按住左键拖拽框住公式（可跨显示器），松手即开始识别；`Esc` / 右键取消；
3. 结果出现在文本框里，按当前“输出格式”自动复制到剪贴板；
4. 结果不理想时点“重试”（会自动调高采样温度换一次采样），或手动改文本框内容。

## 界面功能

* **输出格式**：`Raw`（纯 LaTeX）、`LaTeX-$`（`$...$`）、`LaTeX-$$`（`$$...$$`）、
  `Sympy`（转成 sympy 表达式，需要 `latex2sympy2`，已装）。
* **预览**：默认调用本机 TeX Live 的 `xelatex` 渲染，效果和真实排版一致
  （`\left...\right`、`\begin{array}`、`\begin{cases}` 都能显示）；没有 TeX Live 时自动退回
  matplotlib mathtext，并先把 TeX 写法规范化（见下节）。渲染在后台进行，结果按内容缓存。
* **采样温度**：默认 `0.2`。越小越稳定、越大越随机；“重试”会乘 1.5（上限 1.0）。
* **采样次数**：默认 `3`。识别多次后**按行投票**，把随机编造出来的行投票掉（见下节）。
* **主行裁剪**：默认“总是只保留主行”。框选时不小心把上下另一行也框进来时，会自动只识别
  公式那一行（实测这样字符也更准）；矩阵、分段函数等多行公式请选“关闭”。
* **历史记录**：双击条目载入，记录写到 `output/history.jsonl`（最多 200 条）；
  **关闭软件时会自动清空该文件**，所以它只作为本次会话的临时记录，不会越攒越多。
* **不落盘**：默认不再保存框选切片，`output/` 里只留 `history.jsonl`；
  预览渲染的缓存在系统临时目录（`%TEMP%\latexocr-preview`）。
  确实需要留档时加 `--save-captures`，才会把切片存到 `output/captures/`。
* 窗口内快捷键：`Ctrl+Alt+M` 截图、`Ctrl+O` 打开图片、`Ctrl+V` 识别剪贴板。

## 命令行用法

```bat
run_cli.bat formula.png                       :: 识别图片文件（可多个）
run_cli.bat --clipboard                       :: 识别剪贴板里的图片
run_cli.bat --screen                          :: 截取整个屏幕后识别
run_cli.bat --region 100,200,600,120           :: 截取屏幕区域 left,top,width,height
run_cli.bat formula.png --json                :: JSON 输出，便于脚本调用
run_cli.bat --temperature 0.4 formula.png      :: 换采样温度
```

LaTeX 结果输出到 stdout，日志输出到 stderr，因此可以安全地做管道：

```bat
run_cli.bat --clipboard > result.tex
```

退出码：`0` 成功，`1` 失败，`2` 画面里没有公式。

## 为什么要写兼容层（重点）

直接调用 `pix2tex.cli.LatexOCR`（也就是官方的 `latexocr` 命令）在 **这个 OCR 环境里必定失败**，
有两处版本冲突，本项目在 `latex_ocr_core.py` 里都绕开了，**不需要改动你的 conda 环境**：

1. **`torch 1.13.1` 与 `numpy 2.0.2` ABI 不匹配**
   torch 1.13 是用 numpy 1.x 编译的，`torch.from_numpy()` / `torch.as_tensor(ndarray)` 会直接抛
   `RuntimeError: Numpy is not available`。而 `LatexOCR.__call__` 里的
   `test_transform(...)` 依赖 albumentations 的 `ToTensorV2`，内部正是 `torch.from_numpy`。
   → 本项目改用 `torch.frombuffer(memoryview(...))` 构造张量，完全不经过 numpy 桥接。
2. **`transformers 4.57` 的 `tokenizer.decode()` 只接受 `List[int]`**
   pix2tex 传的是 Tensor，会抛
   `TypeError: argument 'ids': 'Tensor' object cannot be converted to 'Sequence'`。
   → 本项目在解码前先 `.tolist()`。

顺带一提：pix2tex 的 `image_resizer.pth` 不能省。实测关掉它（`--no-resize`）后同一张
`x^2+y^2=z^2` 会被识别成一段乱码，因为它负责预测“这张图应该缩放多宽”，必须保留。

### 一致性校验

预处理必须和 pix2tex 训练时一致，否则精度会掉。本项目用
`cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)` + `(x - mean*255)/(std*255)`
（`mean=0.7931`, `std=0.1738`，取自 `pix2tex/dataset/transforms.py`）复刻 albumentations 的
`ToGray + Normalize + ToTensorV2`，并和真实 albumentations 输出做过逐位比对：

| 用例 | 通道序 | 最大绝对误差 |
| --- | --- | --- |
| 随机彩色图 | `COLOR_RGB2GRAY` | **0.000e+00** |
| 随机彩色图 | `COLOR_BGR2GRAY` | 1.06（通道序错了） |
| 黑白文本图 | 两者相同 | 0.000e+00 |

结论：`COLOR_RGB2GRAY` 与 albumentations 完全一致，已采用。

## 识别精度：array 外壳 / 编造出来的行

pix2tex 最常见的一类错误是把一行公式识别成：

```latex
\begin{array}{c}{{X_{1},X_{2}=\mathrm{chunk}(\mathrm{Conv_{1}}{}_{\times1}(X),2)}}
\\ {{{}_{s\doteq{\mathrm{sexram}}{}_{V}{}_{\star\star}.}}}\end{array}
```

第一行其实是对的，问题在于它多出一行编造内容，还被套了 `array` 外壳。根因是**框选里带进了
公式上/下的另一行文字**（实测复现：把 `sexram V` 这类文字放进框选，输出立刻变成上面这种形态），
模型会把它们当成多行公式，并对多出来的垂直空间“填空”。

现在有三道处理，都在 `latex_ocr_core.py` 里：

1. **结构清理**（始终生效，零风险）：丢掉只有 `{}`、`\,`、`\mathrm{}` 之类的装饰行，
   单行结果自动脱掉 `array` 外壳，去掉行尾多余的 `\\`。
2. **按行投票**（默认 `--samples 3`，第一次用贪心解码，后两次温度采样）：
   真正的公式内容每次几乎都一样，编造出来的行每次都不一样，于是按行多数投票把后者清掉。
3. **只保留主行**（默认 `--trim-lines on`）：按水平投影找出文字带，当某条带与主线之间存在
   **足够大的空白**（`gap >= 1.3 × 较高那条带的高度`）且主线明显更高时，才判定“这是另一行”，
   裁掉后再识别。

第 3 条是关键——**实测把公式和另一行一起喂给模型，字符精度也会下降**（模型要来“解释”多出来的
垂直空间）。裁掉之后模型的输入宽度上限（672px）全都花在公式上，字符反而更准。

### 用你自己那两张真实截图做的实测

（你当时那两次框选曾保存在 `output/captures/`，后来按你的要求清掉了；下面是用它们做验证的记录）

| 选区 | 与真实公式的相似度 | 结果 |
| --- | --- | --- |
| 整张（含下一行残影，就是你报的那次） | **0.99** | 干净单行 |
| 上面也多带一点 | **0.99** | 干净单行 |
| 只到公式下沿 | 0.91 | 干净单行 |
| 另一张公式（`EX∈ℝ^{H×W×C}𝔅`） | **1.00** | 干净单行 |
| 同样输入但 `--trim-lines off` | 0.51 ~ 0.92 | 出现 `array` + 编造行 |

你报的那次，现在的结果是：

```latex
X_{1},X_{2}=\mathrm{chunk}(\mathrm{Conv}_{1\times1}(X),2)
```

已经没有任何 `array` 外壳，也没有编造出来的第二行。

### 三种主行裁剪模式怎么选

| 模式 | 行为 | 建议 |
| --- | --- | --- |
| `on`（默认） | 检测到明显分离的另一行时，只识别主行 | 日常截图；实测最准也最快 |
| `auto` | 先识别原图，只有结果不干净时才补跑主行 | 想对比两种结果时 |
| `off` | 原样识别 | 矩阵、`cases` 分段函数等多行公式 |

行间距小的多行结构（矩阵、带上下限的积分、分式）**不会**被误裁：裁剪需要空白达到
“较高文字带高度的 1.3 倍”以上，且主线要明显更高。7 组回归（单行/分式/噪点/两行贴很近/
两行等高/远处另一行/小字在上）都验证过判定符合预期。

### 还有一类错误：字符级

`\mathrm{chunk}`、`\operatorname{xxx}` 这类长命令是 pix2tex 权重的弱项（实测会把
`chunk` 读成 `cluplk`）。这类错误**不是预处理能解决的**，因为模型的输入宽度上限是 672 像素。
真正有效的办法在源头：

* 先把页面放大（PDF 里 `Ctrl+=`，网页里 `Ctrl+滚动`）再截图，让公式本身有更多真实像素；
* 界面会在公式太小时直接在状态栏提示：“公式高度只有 N 像素，先把页面放大再截图会明显更准”；
* 识别完对着预览核一眼长命令，必要时手动改一下文本框（改完预览和复制都会同步）。

## 预览渲染（MathType 能编译、但预览不出来）

之前预览用的是 matplotlib 的 mathtext，它只实现 LaTeX 的一个子集，所以像

```latex
{\mathcal L}_{D}=1-\exp\left(-\frac{\sqrt{W_{2}^{2}}}{C}\right)
```

这种完全合法的公式会卡在两处：`\left(`/`\right)` 不支持；`\mathcal L`（命令后不带花括号）
也不支持。现在做了两层：

**首选：真实 LaTeX 渲染**（本机装了 TeX Live 就自动启用）

* 用 `standalone` 文档类 + `xelatex` 编译成 PDF，再用 PyMuPDF 转 PNG；
* `\left...\right`、`\begin{array}`、`\begin{cases}`、`\substack` 等等统统正常；
* 渲染在后台线程里做，并带 350ms 防抖，不挡界面；结果按内容哈希缓存到 `output/preview/`，
  同一条公式第二次显示是瞬时的（首次约 1.5 秒）；
* 编译失败时把 xelatex 的报错摘要显示在预览下方，不影响识别结果和复制；
* 界面「预览引擎」一栏会写明当前用的是哪种渲染方式。

**降级：matplotlib mathtext**（没装 TeX Live 时）

先经过 `latex_render.normalize_for_mathtext()` 规范化：

| TeX 写法 | 规范化成 mathtext 能接受的形式 |
| --- | --- |
| `\left( ... \right)` | `( ... )`（去掉这两个命令，括号保留） |
| `\mathcal L` | `\mathcal{L}`（补上花括号） |
| `\bm{x}` | `\mathbf{x}` |
| `\underbrace{x+y}_{z}` | `{x+y}_{z}` |
| `\displaystyle` / `\bigl` / `\middle` / `\limits` | 直接去掉 |
| `\begin{array}{c}a\\b\end{array}` | 按行拆开，逐行分别绘制 |

实测上面那条公式在 mathtext 下规范化后也能正常预览，`array` 这类多行结果会按行显示。

相关参数：`--preview-engine {auto,latex,mathtext}`（默认 auto，有 TeX Live 就用它）、
`--preview-dpi`（默认 180）、`--no-preview`。

## 打包 / 分发给别人

已经打好的成品（在 `dist\` 下）：

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `LaTeXOCR-Setup-1.0.0.exe` | 344 MB | **安装包**：双击安装，免管理员，自动建开始菜单/桌面快捷方式与卸载项 |
| `LaTeXOCR\` | 971 MB | **免安装绿色版**：整个目录拷到哪都能跑，双击 `LaTeXOCR.exe` 即用 |

干净电脑上的要求只有一条：**Windows 10 / 11 64 位**。
不需要 Python、不需要 conda、**不需要联网**、不需要 VC++ 运行库、不需要管理员权限。
模型权重（`weights.pth` 102 MB + `image_resizer.pth` 19 MB）已经内置，装好就能离线识别。

安装位置 `%LOCALAPPDATA%\Programs\LaTeXOCR`；运行时数据写
`%LOCALAPPDATA%\LaTeXOCR\history.jsonl`（关闭软件时清空）。
开始菜单里除了主程序，还有一个 **“检查环境（自检）”**，双击就能确认这台机器能不能用。

**唯一没打包的是 TeX Live**（几个 GB，不适合内置）：没装也能正常用，
公式预览会自动退回 matplotlib 渲染（`\left \right`、`\mathcal`、`array` 都已做等价处理）；
装了 `xelatex` 则自动改用真实 LaTeX 渲染。

重新打包 / 改版本号 / 详细原理见 [`packaging/README.md`](packaging/README.md)，
一键打包脚本是 `packaging\build_installer.bat`。

### 实测验证

| 项目 | 结果 |
| --- | --- |
| 打包结果自检（`latexocr-cli.exe --selfcheck`） | **PASS**，相似度 1.00，模型加载 1.7s |
| 模拟干净电脑（PATH 只留 `C:\Windows\system32`） | **PASS**，识别正常，无网络请求 |
| 安装包静默安装 → 自检 → 卸载 | 安装退出码 0、自检 **PASS**、卸载后目录/快捷方式/数据目录全部清干净 |
| 绿色版 GUI | 正常运行，快捷框选后成功识别并写入历史 |
| exe 版本信息 | `公式截图识别 (LaTeX-OCR)` 1.0.0 + 自绘图标 |

小提示：PyInstaller 打出来的 exe 偶尔会被杀毒软件误报，加到白名单即可；
首次启动比源码运行略慢（要解压/加载约 1 GB 依赖），之后就正常了。

## 界面（浅绿主题）

整体是浅绿 + 白卡片、圆角、单色强调的极简风格，效果图见 `docs/ui-preview.png`：

* 配色集中在 `screenshot_latex.py` 顶部，想换颜色只改这几个常量即可：
  `COLOR_BG`（窗口底）、`COLOR_CARD`（卡片/输入框）、`COLOR_BORDER`（边框）、
  `COLOR_ACCENT`（主色，默认 `#4aa678`）、`COLOR_TEXT` / `COLOR_MUTED`（文字）；
* 所有样式写在 `THEME`（一份 QSS）里，只负责颜色 / 边框 / 圆角 / 间距；
* “截图识别”是主按钮（实心绿），其余是描边按钮；分节标题用绿色小字，信息层级一眼能看清；
* 设置区压成 **3 行**（采样温度＋采样次数同一行、主行裁剪一行、窗口置顶＋预览引擎一行），
  模型状态挪到状态栏右侧；
* 内容放在**滚动区**里：窗口拉小时滚动，而不是把控件压扁——压扁会让“采样温度”这类控件的
  文字显示不全（这个问题已修，`tests/test_theme.py` 里有“控件未被压扁 / 文字放得下”的断言守着）；
* 遮罩框选的选框与尺寸标签同样用主题绿。

**一个坑**：QSS 里千万别写 `font-family` —— 它会盖掉 `setFont()`，被样式表 polish 过的
控件会退回系统默认字体，中文直接变成宋体。字体统一走 `QFont`（`UI_FONT` / `UI_FONT_SIZE`），
等宽的 LaTeX 框由 `setFont(Consolas)` 指定；`tests/test_theme.py` 会把这条规则和各种配色
都验一遍，防止以后改样式改坏。

启动方式不变：

```bat
run_gui.bat
```



## 实测记录

在本机 OCR 环境跑通的结果（CPU 推理）：

```
run_cli.bat --doctor     # numpy_bridge=False，自动走兼容路径；权重已就绪
run_cli.bat --selfcheck  # [PASS] x^{2}+y^{2}=z^{2} 一致，单张约 0.3~3s
run_cli.bat formula.png  # x^{2}+y^{2}=z^{2}，exit=0
```

精度相关的两套回归（`tests/test_precision.py` / `tests/test_gui.py` / `tests/test_theme.py`，
共 69 项断言全部通过）：

```
复现用户串 -> 只剩正确行        OK   {{X_{1},X_{2}=\mathrm{chunk}(\mathrm{Conv_{1}}{}_{\times1}(X),2)}}
含下一行：不输出 array          OK   {{X_{1},\,X_{2}=\mathrm{churk}(...)}}
含下一行：无编造内容            OK
单行公式照常识别               OK
小图给出放大提示               OK
裁剪判定（7 组：单行/分式/噪点/贴很近/等高/远处另一行/小字在上）  OK
GUI：加载/截图/结果/剪贴板/历史/格式/采样次数/主行裁剪/遮罩框选    OK
预览：xelatex 渲染 \left/\mathcal/multi-row array 等              OK
界面：浅绿配色 #f3faf5 / 主按钮 #4aa678 / 状态栏 #e8f5ee          OK
界面：字体 Microsoft YaHei UI 9pt，LaTeX 框保持 Consolas 等宽      OK
界面：采样温度/次数/主行裁剪 控件 29px 高、文字放得下、不被压扁     OK
文件：默认不写截图切片；关闭后 history.jsonl 清空、output 只剩它    OK
```

性能参考（CPU）：单张公式 3 次采样约 1.5~6s（公式越大越慢）；把“采样次数”设为 1 可降到约 1/3。


## 常见问题

**Q：按了快捷键没反应？**
别的软件占用了该快捷键。换一个，例如
`run_gui.bat --hotkey "<ctrl>+<shift>+s"`；窗口内的 `Ctrl+Alt+M` 始终可用。

**Q：提示“截屏失败”？**
少数受限会话（远程桌面、无桌面权限的进程）里 PIL 抓屏会报
`OSError: screen grab failed`。程序会自动退回 Qt 的 `QScreen.grabWindow` 逐屏合成，
两条路径都失败才会报错。

**Q：识别结果多出一行乱码 / 被套了 `\begin{array}`？**
默认的“只保留主行 + 按行投票”已经会自动处理（实测你报的那次已从 0.51 提到 0.99）。
如果还想更保险：把框选收窄到公式那一行，或把“主行裁剪”设成“总是”。

**Q：预览显示不出来 / 说“mathtext 不支持”？**
先看界面「预览引擎」那一栏：正常应该显示 `xelatex（TeX Live）`。如果是 mathtext，
说明没找到 `xelatex`（TeX Live 没装或不在 PATH 里）。本机装了 TeX Live，
现在这类公式（`\left...\right`、`\begin{array}` 等）都能正常渲染了。

**Q：我的公式本来就是多行的（矩阵、cases）怎么办？**
把“主行裁剪”设为“关闭”（`--trim-lines off`）。默认模式只在检测到“明显分离的另一行”
时才会裁，矩阵/分段函数那种行间距小的结构不会被误裁。

**Q：识别结果不准怎么办？**
① 框选时把符号、上下标、分数线都框进去，四周留一点白边，**别带上下别的行**；
② 公式太小就先把页面放大再截图（界面会提示）；
③ 点“重试”换采样，或把“采样次数”调到 5；
④ 长命令（`\mathrm{...}`、`\operatorname{...}`）是模型弱项，对着预览核一眼，手动改掉即可。

**Q：识别变慢了？**
默认 3 次采样 + 可能的“主行裁剪”重跑，换取更干净的结果。把“采样次数”设成 1、
“主行裁剪”设成“关闭”，速度大约回到原来的 1/3。

**Q：多显示器 / 高 DPI 会不会错位？**
不会。遮罩铺满整个虚拟桌面，并按 `截图宽 ÷ 控件宽` 的比例换算坐标，
200% 缩放下的映射已实测正确（见上表）。

**Q：中文乱码？**
`run_cli.bat` 已设置 UTF-8 控制台；直接用 `python latex_ocr_cli.py` 时，
重定向输出会写成 UTF-8 文件，用支持 UTF-8 的编辑器打开即可。

**Q：想彻底根治版本问题？**
可以把 numpy 降到 1.x：`pip install "numpy<2"`，这样官方 `LatexOCR` 的道路也能用；
但本环境里还装着 opencv 5.0 / paddleocr 等，降级有连带风险，所以本项目默认不动环境。

## 参数速查

`screenshot_latex.py`：`--hotkey`（默认 `<ctrl>+<alt>+m`）、`--temperature`（默认 0.2）、
`--samples`（采样次数，默认 3）、`--trim-lines {on,auto,off}`（主行裁剪，默认 on）、
`--preview-engine {auto,latex,mathtext}`（预览渲染，默认 auto）、`--preview-dpi`（默认 180）、
`--device cpu|cuda`、`--outdir`（history.jsonl 位置）、`--no-preview`、`--save-captures`、
`--no-hotkey`。

`latex_render.py`（预览渲染）：`latex_available()` / `engine_name()` /
`normalize_for_mathtext(tex)` / `render_to_png(tex, png, dpi=)` / `render_cached(tex, cache_dir, dpi=)`。
其中 xelatex 渲染需要 TeX Live（本机已有），PDF→PNG 用 PyMuPDF。

`latex_ocr_cli.py`：`--doctor`、`--selfcheck`、`--clipboard`、`--screen`、
`--region L,T,W,H`、`--temperature`、`--samples`、`--trim-lines`、`--device`、`--json`。

`latex_ocr_core.py`（被两个入口共用）：`LatexOcrEngine(temperature=, device=, samples=,
trim_lines=)`、`engine.predict(image, temperature=, samples=, trim_lines=)`，
以及 `trim_to_main_line` / `consensus_latex` / `clean_latex` / `structure_score` /
`resolution_hint` / `grab_virtual_desktop` / `grab_region` 这些可单独调用的工具函数。

