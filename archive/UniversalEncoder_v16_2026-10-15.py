# -*- coding: utf-8 -*-

"""
视频批量归档 / 编码工具
- Intel QSV AV1 / HEVC
- Q30 / Q32 / Q34 / Q36
- 平台对应硬件解码优先，失败自动回退 CPU 解码 + 对应硬件编码
- 并发路数按显卡 NVENC 引擎数量自动决定（见下方 v2/v3 说明）
- 当前目录 / 递归扫描
- 安全 output 模式 / 原地事务式替换模式
- ffprobe 编码判断与输出验证
- 实时 3 路进度显示
- 完成后详细压缩统计

要求：
1. Windows
2. ffmpeg.exe / ffprobe.exe 已加入 PATH
3. Intel Arc / Intel QSV 或 NVIDIA NVENC 驱动正常


============================================================
v2/v3 改动说明（同目录下的原版 UniversalEncoder.py 未做任何改动）
============================================================
测试环境：RTX 2060 Laptop（驱动 595.97）+ AMD R7 4800H + ffmpeg N-121464。
素材：1290x2796 @60fps HEVC 15 Mbps 的 iPhone 录屏，取 10 秒样片同段对比，
画质用 libvmaf（n_subsample=2），比较时都把码率固定在约 1.8 Mbps。

1) MAX_WORKERS 3 → 1
   瓶颈是单块 NVENC（编码时 utilization.encoder = 99%，SM 只有 11%，CPU 空闲）。
   实测总吞吐（p4+hq+qres+la32，10 秒片段）：
       1 路 2.94x | 2 路合计 3.17x | 3 路 3.20x | 4 路 3.29x | 6 路 3.37x
   并发只多约 15% 的总吞吐，却把每个文件的速度切成 1/N。驱动本身允许
   8 个并发会话（实测 8 路全部成功），所以不是"会话数限制"，是硬件只有一块。

2) NVENC 默认参数（固定 1.8 Mbps 上限，同码率比画质）
   preset / 单路速度 / VMAF：
       p1 4.01x 52.69 | p3 4.11x 52.69（与 p1 逐字节相同）
       p4 3.31x 53.60 | p5 2.66x 54.15 | p6 1.52x 54.88 | p7 1.38x 54.90
   → p6 之后完全平坦（p6→p7 仅 +0.02），所以默认取拐点前的 p5。
   -tune uhq        : 0.607x / 53.85  → 比 hq 慢 2.3 倍且画质更低，已移除
   -multipass fullres: 1.18x / 54.89  → 白慢 11% 且无收益，改为 qres
   -multipass qres   : 1.31x / 55.20  → 几乎免费还 +0.30，保留
   -rc-lookahead 32  : 1.32x / 55.13  → 几乎免费 +0.23，保留
   spatial+temporal AQ: 1.37x / 51.09 → 明显负收益（p4 上 49.90），默认关闭
   原版默认组合（p7+uhq+fullres+la32+AQ）实测 0.54x / 54.03，
   属于"最慢、体积最大、画质也不是最好"的那一档。

3) 选择编码器后立刻做一次 3 帧试编码
   Turing（RTX 20 系）的 ffmpeg 会列出 av1_nvenc，但这张卡没有 AV1 编码单元
   （实测报 "No capable devices found"）。原版要跑到批处理中途才整批失败，
   v2 在开始前就给出明确原因。

4) 提醒：真正的画质杠杆是码率，不是 preset
   实测 RD 曲线（p7+hq+qres+la32，CQ26 为目标）：
       实际上限 1011k→40.4 | 1331k→47.5 | 1802k→55.5 | 2123k→59.3
                2899k→65.9 | 3596k→69.3 | 4111k→71.1 | 5332k→74.7
   preset 从 p4 提到 p7 只值 +1.2 分，而码率翻倍值 +6~10 分。
   另外：脚本里"上限 1.5 Mbps"因为 maxrate = 上限 × 1.2，实际产出约 1.8 Mbps。
   想更清楚就选 3000（约 3.6 Mbps，VMAF ≈ 69）。
============================================================


------------------------------------------------------------
v3 追加：按 NVENC 世代自动选参数，并在本机实测标定
------------------------------------------------------------
"最佳性价比参数"随 NVENC 世代变化，同一个开关在不同卡上的收益完全不同：

  本机实测（RTX 2060 Laptop / Turing / NVENC 第 7 代，1290x2796@60 录屏，
  固定 1.8 Mbps 上限，10 秒样片，libvmaf）：
      p7 + hq + qres + la32     1.31x   VMAF 55.20   ← 实测最优
      p7 + uhq                  0.61x   VMAF 53.85   ← 慢 2.3 倍而且更差
      p7 + spatial/temporal AQ  1.37x   VMAF 51.09   ← 明显负收益
      p4 + hq                   3.31x   VMAF 53.60   ← 只低 1.6 分，快 2.5 倍

  公开横向评测（Pascal→Blackwell，含 RTX 5070 Ti，见 arXiv:2605.01187）：
      UHQ 在 HEVC 上平均省 11~13% BD-rate、AV1 上省 16~19%；
      但吞吐代价按世代递减：Ampere -56%、Ada -26%、Blackwell -18%。
      → UHQ 在 50 系上更划算，在 20/30 系（同为第 7 代编码器）上很亏；
        而且它的收益随内容变化（低运动量素材上可能反而变差）。

结论：不写死。v3 的做法是
  1) 用 nvidia-smi 识别显卡 → NVENC 世代（Turing / Ampere / Ada / Blackwell）
     与编码引擎数量（来源：NVIDIA 官方 Video Encode and Decode Support Matrix）；
  2) 并发路数 = 编码引擎数量（单引擎卡并发只会把每个文件拖慢，多引擎卡才值得并发）；
  3) 首次运行时，用**你自己的素材 + 你自己的码率设置**把各候选档位各编一小段，
     实测速度与画质，选出性价比最高的一档（规则：在最快与最好之间，选
     "画质不低于最好档 NVENC_QUALITY_TOLERANCE 分"里最快的那一档）；
  4) 结果缓存到脚本目录的 _nvenc_calibration.json，键 = 显卡|编码器|编码|模式|码率|分辨率|帧率。
     想重新标定就删掉那个 json，或把 NVENC_AUTO_CALIBRATE 设为 False 永远用世代默认值。
  5) 挑选规则：先找画质最好的档位，再在"画质不低于它 NVENC_QUALITY_TOLERANCE 分"
     （默认 1.5 分，速度优先）的档位里挑最快的。不服就设 NVENC_FORCE_PROFILE 手动锁定，
     或把容差调小（0.5 = 明显偏向慢档）。

多引擎卡（RTX 5090=3、5080/5070Ti=2、4080/4090/4070Ti=2）还会多一个候选：
-split_encode_mode forced（SFE，把一个画面拆给多个 NVENC，单任务就能吃满全部引擎）。
"""

from __future__ import annotations

import concurrent.futures
import glob
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ============================================================
# 全局配置
# ============================================================

# 实测（单 NVENC 引擎，例如 RTX 2060）：并发只增加约 15% 的总吞吐，
# 却让每个文件的编码速度变成 1/N。设为 1 时单文件最快出结果，整批总时间几乎不变。
# 只有多编码引擎的平台（多张 NVENC / Intel QSV 与独显并存）才值得调大。
# 并发路数：默认 2 路；想让它自己实测选最优，把 AUTO_WORKERS 改成 True。
# 实测参考（都能用 --concurrency-test 复现）：
#   Intel Arc A380：1路 2.18x | 2路 合计3.82x(+75%) 单文件1.92x |
#                   3路 3.96x(+81%) 1.48x | 4路 3.99x(+83%) 1.01x
#   RTX 2060 Laptop：1路 2.18x | 2路 合计2.58x(+18%) 单文件1.30x |
#                   3路 2.60x(+19%) 0.87x | 4路 2.68x(+23%) 0.68x
# → 两边都是「2 路拿走大部分吞吐收益」；N 卡继续加路数收益极小、单文件速度掉得快。
MAX_WORKERS = 2
RETRY_FAILED_FILES = True        # 批次跑完后，失败文件是否串行重试（偶发失败多半能过）
MAX_FILE_ATTEMPTS = 3            # 单个文件最多尝试几次（含首次）：首次 + 2 次重试。
                                 # 3 次都不行就直接报错、不再重试，避免拖累整批。
RETRY_PAUSE_SECONDS = 3.0        # 重试前的等待，给驱动/会话一点恢复时间
RUN_LOG_NAME = "_encode_run.log"  # 批次运行日志（成功/失败都写，便于事后分析）
DEFAULT_WORKERS = 2
AUTO_WORKERS = True             # 默认自适应：首次运行实测并发收益（约 10~20 秒）并缓存；
                                # 想固定路数就改成 False，那时用 DEFAULT_WORKERS
WORKERS_CACHE_FILE = Path(__file__).resolve().parent / "_workers.json"
WORKERS_CACHE_VERSION = 1

# 归档视频格式
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".m4v",
    ".avi",
    ".ts",
    ".webm",
    ".flv",
}

# 安全模式输出目录名
OUTPUT_DIR_NAME = "output"

# 临时文件标记
TEMP_MARKER = ".temp."

# FFmpeg 进度里的 out_time 多久不前进就判定卡死。
# 注意：不能用“有没有输出行”判断——ffmpeg 即使一帧都没编出来，也会持续
# 输出 -progress 行，那样看门狗永远不会触发（旧版正是这样挂死的）。
PROGRESS_TIMEOUT = 180

# ------------------------------------------------------------
# 码率控制模式
# ------------------------------------------------------------
# quality：只按质量值编码（QSV 质量模式 / NVENC CQ），不限制体积
# capped ：所有视频都按码率上限编码
# auto   ：先用质量模式采样估算码率，超过上限的文件才改用上限模式（推荐）
RC_MODE_QUALITY = "quality"
RC_MODE_CAPPED = "capped"
RC_MODE_AUTO = "auto"

# 当前运行使用的模式与上限（由 main() 设置，编码线程只读）
RC_MODE = RC_MODE_AUTO
VIDEO_BITRATE_CAP_KBPS: Optional[int] = None

# ------------------------------------------------------------
# ffmpeg / ffprobe 可执行文件
# ------------------------------------------------------------
# 留空 = 用 PATH 里的 ffmpeg/ffprobe。
#
# 为什么需要这个开关（跨 8 个构建实测结论）：
#   Intel QSV 的 ICQ 质量模式（官方推荐、同画质更省码率）能不能启用，
#   取决于 **ffmpeg 构建**，而不是驱动：
#     ✅ 可用（-global_quality:v 30 → 日志 RateControlMethod: ICQ）：
#        ffmpeg 9.0.2 发布版、9.0 分支(n9.0.2-22)、8.0 发布版、
#        以及 2025-04 ~ 2025-10 的各个 git 构建
#     ❌ 不可用（参数根本传不到编码器，落到 "Using CQP by default"）：
#        2026-10 的 master 构建（N-127054、gyan 2026-10-01 full）
#   两者用的是同一个 oneVPL 运行时（日志都是
#   "Use Intel(R) oneVPL to create MFX session ... version 1.1"），
#   所以换驱动解决不了这件事；master 上同一构建里 -g/-bf/-b:v/-q:v/私有选项
#   都正常送达，只有 global_quality 送不到。
# 实测效率（1290x2796 60fps 录屏，同 VMAF 87.2）：ICQ 约 2531 kbps，
# 而 CQP 需要 q26 才能到同画质（2660 kbps），即 ICQ 同画质省约 5%。
FFMPEG_BIN: Optional[str] = None
FFPROBE_BIN: Optional[str] = None

# 找 ffmpeg 的顺序（简单、可预期）：
#   1) PATH 里的 ffmpeg / ffprobe
#   2) 程序自己所在目录、以及当前目录（含其下 ffmpeg*/bin/ 这种解压布局）
# 程序改名不影响：只看目录，不看程序文件名。
_SCRIPT_DIR = Path(__file__).resolve().parent
_LOCAL_FFMPEG_GLOBS = [
    "ffmpeg.exe",
    str(Path("ffmpeg*") / "bin" / "ffmpeg.exe"),
    str(Path("ffmpeg*") / "*" / "bin" / "ffmpeg.exe"),
]

# 质量模式标签（由启动探测填入，用于界面显示）
QUALITY_MODE_LABEL: dict[str, str] = {}


def ffmpeg_exe() -> str:
    return FFMPEG_BIN or "ffmpeg"


def ffprobe_exe() -> str:
    return FFPROBE_BIN or "ffprobe"


def _local_ffmpeg_candidates() -> list[str]:
    """程序目录 / 当前目录里的 ffmpeg（含 ffmpeg*/bin 这种解压布局）。"""
    found: list[str] = []
    for base in (_SCRIPT_DIR, Path.cwd().resolve()):
        for pattern in _LOCAL_FFMPEG_GLOBS:
            for hit in sorted(glob.glob(str(base / pattern))):
                if hit not in found:
                    found.append(hit)
    return found


def locate_ffmpeg_if_missing() -> Optional[str]:
    """PATH 里没有 ffmpeg 时，在程序目录 / 当前目录里找。"""
    for cand in _local_ffmpeg_candidates():
        try:
            cp = run_command([cand, "-version"], timeout=15)
        except Exception:
            continue
        if cp.returncode == 0 and "ffmpeg version" in (cp.stdout or ""):
            return cand
    return None

def sibling_ffprobe(ffmpeg_path: str) -> str:
    p = Path(ffmpeg_path)
    cand = p.with_name("ffprobe.exe" if p.suffix.lower() == ".exe" else "ffprobe")
    return str(cand) if cand.exists() else (FFPROBE_BIN or "ffprobe")


# ------------------------------------------------------------
# 质量档位
# ------------------------------------------------------------
# Intel QSV：档位就是质量值本身（1~51，越小越好），菜单直接显示实际参数。
# NVIDIA NVENC：CQ 与 QSV 不是同一标尺；而且 AV1 的 CQ 范围是 0~255，
# HEVC 是 0~51，因此两个编码器必须分开给档位。
INTEL_VIDEO_QUALITY_LEVELS = [26, 28, 30, 32, 34]
NVIDIA_HEVC_QUALITY_LEVELS = [18, 20, 22, 24, 26, 28, 30]
NVIDIA_AV1_QUALITY_LEVELS = [24, 28, 32, 36, 40, 44, 48]

# 默认质量档位：各编码器标尺不同，必须分开给
#   Intel QSV      QP 1~51   → 30 是"均衡"
#   NVENC HEVC     CQ 0~51   → 26 是"均衡 / 推荐"
#   NVENC AV1      CQ 0~255  → 40 是"均衡 / 推荐"
DEFAULT_VIDEO_QUALITY = 30


def default_quality(platform_key: str, codec_key: str) -> int:
    if platform_key == "intel":
        return 30
    return 40 if codec_key == "av1" else 26

# 视频码率上限候选（kbps）——不限制 / 1.0 / 1.5 / 2.0 / 3.0 / 自定义
# 默认 1.5 Mbps：录屏类素材按观感与体积的折中
#
# 实测 RD 曲线（1290x2796@60 录屏，p7+hq+qres+lookahead32，10 秒样片 VMAF）：
#   实际码率 1011k→40.4 | 1331k→47.5 | 1802k→55.5 | 2123k→59.3
#            2899k→65.9 | 3596k→69.3 | 4111k→71.1 | 5332k→74.7
# 注意：maxrate = 上限 × BITRATE_PEAK_RATIO(1.2)，所以选"上限 1.5 Mbps"
# 实际产出约 1.8 Mbps。这个素材是 3.6 MP@60 且文字边缘多，VMAF 想上 90
# 需要的码率比源码率还高，所以这里只能按"体积优先"取值；在意画质选 3000。
VIDEO_BITRATE_CAP_PRESETS = [None, 1000, 1500, 2000, 3000]
DEFAULT_VIDEO_BITRATE_CAP = 1500

# 质量模式下"预计会不会超标"的快速估算：
# 实测 QSV ICQ 的产出码率大约是源视频码率的 1/4 ~ 1/6，这里取 1/5 做判断，
# 不解码、不采样，瞬间得出每个文件走质量模式还是走上限模式。
# 万一估算偏差导致成品真的超了上限，编码完成后会自动用上限模式重编该文件（见 encode_one）。
ICQ_SOURCE_DIVISOR = 5.0

# 峰值码率 = 目标码率 × 该系数。必须略大于 1：
# QSV 在 maxrate == bitrate 时会切到 CBR。
BITRATE_PEAK_RATIO = 1.2

# VBV 缓冲时长（秒）。越大，码率分配越灵活、画质越平稳。
BITRATE_BUFFER_SECONDS = 2.0

# GOP 秒数。归档取向：GOP 越长，单位码率画质越好，但关键帧间隔也越长
# （拖动定位粒度变粗，个别硬件播放器对超长 GOP 不友好）。
# 整片实测（1290x2796 60fps 录屏 55.8s，ICQ q32，全片平均码率）：
#   4.2s=2008 kbps  8.3s=1926(-4.1%)  16.7s=1882(-6.3%)  33s=1857(-7.5%)  50s=1862(-7.3%)
#   720p 素材：4.2s=435 → 16.7s=426（-2.1%）
# 取 8 秒：拿到约一半收益（-4.1%），同时保持拖动定位体验。
# 想更省体积可以调到 15~30；想更利落可以调到 4~5（代价就是上面那几个百分点）。
GOP_SECONDS = 8.0

# 音频质量完全独立于视频质量。
# 使用 Opus VBR，实际平均码率会因内容而略有波动。默认 64k。
AUDIO_BITRATES = {
    96: "96k",
    64: "64k",
    48: "48k",
    40: "40k",
}
DEFAULT_AUDIO_BITRATE = 64

# 源音频已经是 Opus 时是否直接复制：源码率 ≤ 目标 × 该系数就复制。
# 理由：Opus→Opus 是有损再编码，为了省几 kbps 而损失一代音质不划算。
AUDIO_COPY_TOLERANCE = 1.25

# ============================================================
# 编码器配置
# ============================================================

# 统一编码器配置。平台之间只统一“质量档位”的操作体验，底层参数分别使用
# Intel QSV / NVIDIA NVENC 原生控制方式，避免把两套编码器的参数硬套在一起。
#
# decode_chain：解码回退链，按顺序尝试，第一个成功的就用它。
#   实测教训：QSV 解码设备会因为驱动/会话问题整个不可用
#   （Error creating a MFX session: -9），此时 d3d11va 仍然可用，
#   而 d3d11va 解码 + QSV 编码的速度与 QSV 零拷贝解码基本相同。
#   旧版只有“QSV 硬解 → CPU 解码”两级，一旦 QSV 解码失效就直接掉到 CPU。
ENCODER_PROFILES = {
    "intel": {
        "name": "Intel QSV",
        "decode_chain": [
            ("QSV 零拷贝硬解", ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]),
            ("D3D11VA 硬解", ["-hwaccel", "d3d11va"]),
            ("CPU 解码", []),
        ],
        "encoders": {
            "av1": "av1_qsv",
            "hevc": "hevc_qsv",
        },
        "settings": {
            "preset": "veryslow",
            "extbrc": 1,
        },
    },
    "nvidia": {
        "name": "NVIDIA NVENC",
        "decode_chain": [
            ("CUDA 零拷贝硬解", ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]),
            ("D3D11VA 硬解", ["-hwaccel", "d3d11va"]),
            ("CPU 解码", []),
        ],
        "encoders": {
            "av1": "av1_nvenc",
            "hevc": "hevc_nvenc",
        },
        "settings": {
            # ---- 以下取值全部由实测决定（RTX 2060 Laptop / 1290x2796@60 录屏 /
            #      固定 1.8 Mbps 上限 / 10 秒样片 / libvmaf） ----
            # 同码率下的单路速度与 VMAF：
            #   p1 4.01x 52.69 | p3 4.11x 52.69 | p4 3.31x 53.60
            #   p5 2.66x 54.15 | p6 1.52x 54.88 | p7 1.38x 54.90
            # p6 之后基本平坦（p6→p7 只有 +0.02），所以取拐点前的 p5。
            "preset": "p5",
            "rc": "vbr",
            # +0.23 VMAF，速度几乎不变（1.38x → 1.32x），保留。
            "lookahead": 32,
            "bf": 4,
            # fullres 白慢 11% 且 VMAF 不动（54.89 vs 54.90）；qres 反而 +0.30
            # （55.20）且几乎不花时间。改 qres，想关就填 "off"。
            "multipass": "qres",
            # 实测 AQ 是负收益：p7 下 54.90 → 51.09，p4 下 53.60 → 49.90。关闭。
            "spatial_aq": 0,
            "temporal_aq": 0,
            "aq_strength": 8,
            "b_ref_mode": "middle",
            # 实测 uhq 慢 2.3 倍且 VMAF 低 1.0 分（53.85 vs 54.90），固定 hq。
            "tune": "hq",
        },
    },
}

# ============================================================
# NVENC 世代识别 + 自动标定（v3）
# ============================================================
# 参数不写死的原因见文件头的 v3 说明。这里只放机制，不放"某张卡该用什么"。
# ------------------------------------------------------------

NVENC_AUTO_CALIBRATE = True      # False = 跳过标定，始终用世代默认参数
NVENC_CALIB_SECONDS = 3.0        # 每个候选档位编码多长的样片
# 画质容差（VMAF 分）。标定规则：先找画质最好的档位，再在所有"画质不低于它这个
# 容差"的档位里挑最快的。1.5 分是"速度优先"的取值——实测在这个码率区间，
# 多花 1.5~2 倍时间往往只能换回 1 分左右（同样的 1 分用码率换需要接近翻倍），
# 不划算。想要画质优先就调小（0.5 会明显偏向慢档）。
NVENC_QUALITY_TOLERANCE = 1.5
# 没有 libvmaf 时退回 SSIM，用单独的容差（SSIM 各档差异远小于 VMAF 分）
NVENC_SSIM_TOLERANCE = 0.004
# 手动锁定档位（None = 让标定自己挑）。可选：p4_fast / p5_balanced / p7_max /
# p7_uhq / p7_uhq_all / p7_uhq_sfe。设了就完全跳过标定。
NVENC_FORCE_PROFILE: Optional[str] = None
NVENC_CALIBRATION_VERSION = 2
NVENC_CALIBRATION_FILE = _SCRIPT_DIR / "_nvenc_calibration.json"
NVENC_CALIBRATED: dict[str, Any] = {}    # 标定选中的参数，build_ffmpeg_command 会合并它
NVENC_HW: dict[str, Any] = {}            # 显卡识别结果

NVENC_GENERATIONS = {
    "turing": "Turing（NVENC 第 7 代）",
    "ampere": "Ampere（NVENC 第 7 代）",
    "ada": "Ada Lovelace（NVENC 第 8 代）",
    "blackwell": "Blackwell（NVENC 第 9 代）",
    "unknown": "未知世代",
}

# 每张卡有几个 NVENC 引擎（决定并发是否有意义、以及能不能用 SFE）。
# 依据：NVIDIA 官方 Video Encode and Decode Support Matrix 的 Total # of NVENC 列。
NVENC_MULTI_ENGINE_HINTS = [
    (re.compile(r"RTX\s*50\s*90", re.I), 3),        # 5090 / 5090 Laptop
    (re.compile(r"RTX\s*50\s*80", re.I), 2),        # 5080 / 5080 Laptop
    (re.compile(r"RTX\s*50\s*70\s*Ti", re.I), 2),  # 5070 Ti / 5070 Ti Laptop
    (re.compile(r"RTX\s*PRO\s*(?:6000|5000|4000)", re.I), 3),
    (re.compile(r"RTX\s*40\s*90", re.I), 2),
    (re.compile(r"RTX\s*40\s*80", re.I), 2),
    (re.compile(r"RTX\s*40\s*70\s*Ti", re.I), 2),
    (re.compile(r"RTX\s*A\d{4}", re.I), 2),
]


def detect_nvenc_hardware() -> dict[str, Any]:
    """识别 GPU 名称 / NVENC 世代 / 编码引擎数量；识别不出来时返回 unknown + 1 引擎。"""
    hw: dict[str, Any] = {
        "gpu": "",
        "driver": "",
        "generation": "unknown",
        "generation_name": NVENC_GENERATIONS["unknown"],
        "engines": 1,
    }

    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            cp = run_command([smi, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             timeout=8)
            rows = [x.strip() for x in (cp.stdout or "").splitlines() if x.strip()]
            if rows:
                parts = [p.strip() for p in rows[0].split(",")]
                hw["gpu"] = parts[0]
                if len(parts) > 1:
                    hw["driver"] = parts[1]
        except Exception:
            pass

    name = str(hw["gpu"])
    if re.search(r"RTX\s*50\s*\d0|RTX\s*PRO\s*\d+\s*Blackwell", name, re.I):
        gen = "blackwell"
    elif re.search(r"RTX\s*40\s*\d0", name, re.I):
        gen = "ada"
    elif re.search(r"RTX\s*30\s*\d0|RTX\s*20\s*50", name, re.I):
        gen = "ampere"          # 注意：RTX 2050 属于 Ampere
    elif re.search(r"RTX\s*20\s*\d0|GTX\s*16\s*\d0|TITAN\s*RTX", name, re.I):
        gen = "turing"
    else:
        gen = "unknown"

    hw["generation"] = gen
    hw["generation_name"] = NVENC_GENERATIONS.get(gen, NVENC_GENERATIONS["unknown"])

    engines = 1
    for pattern, count in NVENC_MULTI_ENGINE_HINTS:
        if pattern.search(name):
            engines = count
            break
    hw["engines"] = engines
    return hw


def nvenc_default_settings() -> dict[str, Any]:
    """世代默认参数：标定被关闭或标定失败时使用。"""
    return dict(ENCODER_PROFILES["nvidia"]["settings"])


def nvenc_candidates(hw: Optional[dict] = None) -> list[tuple[str, dict[str, Any], str]]:
    """候选参数集（标定会在这几档里实测挑选）。返回 (名字, settings, 说明)。"""
    hw = hw or NVENC_HW or {"engines": 1}
    base = {
        "rc": "vbr",
        "bf": 4,
        "b_ref_mode": "middle",
        "lookahead": 32,
        "multipass": "qres",
        "spatial_aq": 0,
        "temporal_aq": 0,
    }
    p4 = {**base, "preset": "p4", "tune": "hq"}
    p5 = {**base, "preset": "p5", "tune": "hq"}
    p7 = {**base, "preset": "p7", "tune": "hq"}
    uhq = {**p7, "tune": "uhq"}

    out: list[tuple[str, dict[str, Any], str]] = [
        ("p4_fast", p4, "最快档"),
        ("p5_balanced", p5, "实测拐点前（世代默认）"),
        ("p7_max", p7, "同码率下 HQ 画质最好"),
    ]

    # UHQ 系只在 Ada/Blackwell 上实测：20/30 系（Turing/Ampere）上 UHQ 更慢且画质更差，
    # 实测已证实是负收益，直接不参与标定（省掉两次无效试编）。
    generation = str(hw.get("generation") or "unknown")
    if generation in ("ada", "blackwell", "unknown"):
        out.append(("p7_uhq", uhq, "UHQ：Ada/Blackwell 上省码率，20/30 系负收益（已按世代裁剪）"))
        if int(hw.get("engines", 1)) > 1:
            out.append((
                "p7_uhq_sfe",
                {**uhq, "split_encode_mode": "forced"},
                "多引擎卡：SFE 让单个任务用满全部 NVENC",
            ))
    return out


# 不进候选表、但可以用 NVENC_FORCE_PROFILE 手动指定的档位。
# p7_uhq_all（UHQ+fullres+AQ）实测明显负收益：AQ 在同码率下 VMAF 反而低 ~4 分，
# 且比 fullres +11% 时间无收益，所以默认不参与标定，只留作手动选项。
NVENC_EXTRA_PROFILES: dict[str, dict[str, Any]] = {
    "p7_uhq_all": {
        "rc": "vbr", "bf": 4, "b_ref_mode": "middle", "lookahead": 32,
        "preset": "p7", "tune": "uhq", "multipass": "fullres",
        "spatial_aq": 1, "temporal_aq": 1, "aq_strength": 8,
    },
}


_LIBVMAF_OK: Optional[bool] = None


def _libvmaf_available() -> bool:
    global _LIBVMAF_OK
    if _LIBVMAF_OK is None:
        try:
            cp = run_command([ffmpeg_exe(), "-hide_banner", "-filters"], timeout=30)
            _LIBVMAF_OK = "libvmaf" in ((cp.stdout or "") + (cp.stderr or ""))
        except Exception:
            _LIBVMAF_OK = False
    return bool(_LIBVMAF_OK)


def measure_quality(encoded: Path, source: Path, start: float, seconds: float) -> tuple[str, float]:
    """返回 (指标名, 数值)。优先 VMAF，本机 ffmpeg 没有 libvmaf 时退回 SSIM。"""
    use_vmaf = _libvmaf_available()
    if use_vmaf:
        graph = (
            "[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];"
            "[a][b]libvmaf=n_threads=%d:n_subsample=2" % max(2, os.cpu_count() or 4)
        )
    else:
        graph = "[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]ssim"

    args = [
        ffmpeg_exe(), "-hide_banner",
        "-i", str(encoded),
        "-ss", "%.3f" % start, "-t", "%.3f" % seconds, "-i", str(source),
        "-lavfi", graph, "-f", "null", "-",
    ]
    try:
        cp = run_command(args, timeout=1800)
    except Exception:
        return "", 0.0

    text = (cp.stderr or "") + "\n" + (cp.stdout or "")
    if use_vmaf:
        m = re.search(r"VMAF score:\s*([0-9.]+)", text)
        return ("VMAF", float(m.group(1))) if m else ("", 0.0)
    m = re.search(r"All:\s*([0-9.]+)", text)
    return ("SSIM", float(m.group(1))) if m else ("", 0.0)


def _calibration_key(hw: dict, encoder: str, codec_key: str, plan: "EncodePlan", info: "MediaInfo") -> str:
    mode = plan.mode if plan else RC_MODE_QUALITY
    cap = int(plan.cap_kbps or 0) if plan else 0
    return "|".join([
        "v%d" % NVENC_CALIBRATION_VERSION,
        str(hw.get("gpu", "")),
        str(hw.get("driver", "")),          # 换驱动可能改变档位结论，纳入 key
        encoder,
        codec_key,
        mode,
        str(cap),
        "%dx%d" % (info.width, info.height),
        "%d" % round(info.fps or 0),
    ])


def _calibration_core_key(hw: dict, encoder: str, codec_key: str, plan: "EncodePlan") -> str:
    """不含分辨率/帧率的"核心 key"。

    档位选择几乎不随分辨率变化（变的只是实测速度），所以分辨率/帧率不同时
    沿用同一份标定结果，避免混合素材（1080p60 + 720p30 + …）反复标定。
    """
    mode = plan.mode if plan else RC_MODE_QUALITY
    cap = int(plan.cap_kbps or 0) if plan else 0
    return "|".join([
        "c%d" % NVENC_CALIBRATION_VERSION,
        str(hw.get("gpu", "")),
        str(hw.get("driver", "")),
        encoder,
        codec_key,
        mode,
        str(cap),
    ])


def _load_calibration(path: Optional[Path] = None) -> Optional[dict]:
    target = path or NVENC_CALIBRATION_FILE
    try:
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _save_calibration(payload: dict, path: Optional[Path] = None) -> None:
    target = path or NVENC_CALIBRATION_FILE
    try:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _run_calibration_encode(
    source: Path,
    info: "MediaInfo",
    platform_key: str,
    codec_key: str,
    video_quality: int,
    plan: "EncodePlan",
    settings: dict,
    start: float,
    seconds: float,
    slot: Optional[dict] = None,
) -> Optional[dict]:
    """按给定 settings 编一小段，返回 {out, speed, fps, wall}；失败返回 None。

    slot = 要临时套用的"参数槽"（NVENC 用 NVENC_CALIBRATED，QSV 用 QSV_CALIBRATED），
    build_ffmpeg_command 会读它，所以试编和正式编码走同一条参数通路。
    """
    slot = NVENC_CALIBRATED if slot is None else slot
    saved = dict(slot)
    slot.clear()
    slot.update(settings)

    out_path = Path(tempfile.gettempdir()) / ("ue_calib_%d.mp4" % os.getpid())
    progress = Path(tempfile.gettempdir()) / ("ue_calib_%d.progress" % os.getpid())
    try:
        for f in (out_path, progress):
            try:
                f.unlink()
            except Exception:
                pass

        cmd = build_ffmpeg_command(
            source=source,
            output=out_path,
            info=info,
            platform_key=platform_key,
            codec_key=codec_key,
            video_quality=video_quality,
            audio_quality=DEFAULT_AUDIO_BITRATE,
            decode_args=decode_args_for(platform_key),
            plan=plan,
            video_only=True,
        )

        i = cmd.index("-i")
        cmd = cmd[:i] + ["-ss", "%.3f" % start, "-t", "%.3f" % seconds] + cmd[i:]
        p = cmd.index("-progress")
        cmd[p + 1] = str(progress)
        cmd[-1] = str(out_path)

        t0 = time.monotonic()
        cp = run_command(cmd, timeout=1800)
        wall = time.monotonic() - t0

        if cp.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
            return None

        fps = 0.0
        try:
            for line in progress.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("fps="):
                    fps = safe_float(line.split("=", 1)[1], 0.0)
        except Exception:
            pass

        # 速度一律按"样片时长 / 实测耗时"算平均速度。
        # 进度文件里的 fps= 只是最后一次采样的瞬时值（往往只覆盖最后零点几秒），
        # 噪点极大，会出现"显示比另一档快、实际却更慢"的假象——显示和决策必须同一指标。
        speed = (seconds / wall) if wall > 0 else 0.0

        return {"out": out_path, "speed": speed, "fps": fps, "wall": wall}
    except Exception:
        return None
    finally:
        slot.clear()
        slot.update(saved)


def calibrate_nvenc(
    source: Path,
    info: "MediaInfo",
    platform_key: str,
    codec_key: str,
    video_quality: int,
    plan: Optional["EncodePlan"] = None,
) -> Optional[dict]:
    """在本机 + 本次素材上实测各候选档位，选出性价比最高的一档并缓存。"""
    hw = NVENC_HW or detect_nvenc_hardware()
    encoder = encoder_name(platform_key, codec_key)
    plan = plan or EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality)

    # 手动锁定档位：跳过标定
    if NVENC_FORCE_PROFILE:
        force_pool = list(nvenc_candidates(hw)) + [
            (n, st, "手动档位（默认不参与标定）") for n, st in NVENC_EXTRA_PROFILES.items()
        ]
        for name, settings, _note in force_pool:
            if name == NVENC_FORCE_PROFILE:
                NVENC_CALIBRATED.clear()
                NVENC_CALIBRATED.update(settings)
                ui_hint("NVENC 标定：按 NVENC_FORCE_PROFILE 强制使用 %s（跳过实测）" % name)
                return settings
        ui_warn("NVENC_FORCE_PROFILE=%s 不是有效档位，改为自动标定。" % NVENC_FORCE_PROFILE)

    key = _calibration_key(hw, encoder, codec_key, plan, info)
    core = _calibration_core_key(hw, encoder, codec_key, plan)

    cached = _load_calibration()
    if cached and cached.get("settings"):
        exact = cached.get("key") == key
        same_core = cached.get("core") == core
        if exact or same_core:
            NVENC_CALIBRATED.clear()
            NVENC_CALIBRATED.update(cached["settings"])
            why = "完全匹配" if exact else "同显卡/编码器/模式（本次分辨率不同，沿用）"
            ui_hint("NVENC 标定：沿用上次结果 %s（%s %.2f；%s）"
                    % (cached.get("chosen", "?"), cached.get("metric", ""),
                       float(cached.get("quality") or 0), why))
            return cached["settings"]

    seconds = max(1.0, min(float(NVENC_CALIB_SECONDS), info.duration - 1.0 if info.duration else float(NVENC_CALIB_SECONDS)))
    start = max(0.0, min(info.duration - seconds - 0.05, info.duration * 0.35)) if info.duration else 0.0

    ui_section("NVENC 自动标定（首次运行，约 %d 档 × %g 秒样片；结果会缓存）"
               % (len(nvenc_candidates(hw)), seconds))
    ui_kv("显卡", "%s | %s | %d 个 NVENC 引擎"
          % (hw.get("gpu") or "未知", hw.get("generation_name") or "未知", int(hw.get("engines", 1))))
    ui_kv("样片", "%s 的 %s 起 %.1f 秒 | %s"
          % (source.name, format_duration(start), seconds, plan_label(plan)))

    rows: list[dict[str, Any]] = []
    for name, settings, note in nvenc_candidates(hw):
        res = _run_calibration_encode(
            source=source, info=info, platform_key=platform_key, codec_key=codec_key,
            video_quality=video_quality, plan=plan, settings=settings,
            start=start, seconds=seconds,
        )
        if res is None:
            ui_warn("%-12s 该档位在本机/本素材上编不出来，已跳过" % name)
            continue
        metric, value = measure_quality(res["out"], source, start, seconds)
        try:
            res["out"].unlink()
        except Exception:
            pass
        rows.append({
            "name": name, "note": note, "settings": settings,
            "speed": res["speed"], "fps": res["fps"], "wall": res["wall"],
            "metric": metric or "n/a", "quality": value,
        })
        print("   %-12s %6.2fx  %6.1f fps  %s %7.2f   %s"
              % (name, res["speed"], res["fps"], (metric or "-"), value, dim(note)),
              flush=True)

    if not rows:
        ui_warn("标定失败（所有候选都编不出来），改用世代默认参数。")
        NVENC_CALIBRATED.clear()
        NVENC_CALIBRATED.update(nvenc_default_settings())
        return None

    metric_name = rows[0]["metric"]
    if metric_name == "VMAF":
        tolerance = NVENC_QUALITY_TOLERANCE
    else:
        # 退回 SSIM 时用更宽的带：SSIM 在固定码率下各档只差 0.001~0.006，
        # 沿用 1.5 分 VMAF 那种"紧带"会只剩最慢档合格。
        tolerance = NVENC_SSIM_TOLERANCE
        ui_warn("本机 ffmpeg 没有 libvmaf，用 SSIM 代替（容差放宽到 %.4f）" % tolerance)
    best = max(rows, key=lambda r: r["quality"])
    eligible = [r for r in rows if r["quality"] >= best["quality"] - tolerance]
    # 先找最快档，再把"耗时在最快档 105% 以内"的档位放在一起，从中挑画质最好的。
    # 这 5% 是测量噪声容限：避免为零点几秒的抖动牺牲明显更高的画质。
    fastest = min(eligible, key=lambda r: r["wall"])
    near = [r for r in eligible if r["wall"] <= fastest["wall"] * 1.05]
    pick = max(near, key=lambda r: r["quality"])

    NVENC_CALIBRATED.clear()
    NVENC_CALIBRATED.update(pick["settings"])

    gap = best["quality"] - pick["quality"]
    speedup = (best["wall"] / pick["wall"]) if pick["wall"] > 0 else 1.0
    ui_ok("选中 %s：%s %.2f（比最好档 %s 低 %.2f，在容差 %.2f 内，但快 %.1f 倍）"
          % (pick["name"], metric_name, pick["quality"], best["name"], gap, tolerance, speedup))

    _save_calibration({
        "key": key,
        "core": core,
        "chosen": pick["name"],
        "settings": pick["settings"],
        "metric": metric_name,
        "quality": pick["quality"],
        "tolerance": tolerance,
        "gpu": hw.get("gpu", ""),
        "generation": hw.get("generation", ""),
        "engines": int(hw.get("engines", 1)),
        "rows": rows,
    })
    ui_hint("标定结果已缓存到 %s（删掉即可重新标定）" % NVENC_CALIBRATION_FILE.name)
    return pick["settings"]



# ============================================================
# 并发收益实测（命令行：python <本脚本> --concurrency-test）
# ------------------------------------------------------------
# 做法：取当前目录第一个视频，同一片段（默认 10 秒）分别用 1/2/3/4 路并行编码，
# 量【合计吞吐】与【单文件速度】。并发值不值、值几路，看"合计吞吐"的增量：
#   NVIDIA 单引擎卡实测：并发只多约 15% 总吞吐，却把单文件速度切成 1/N；
#   Intel QSV 实测 3 路仍有明显总吞吐收益。这里用你自己的机器再验一次。
# ============================================================
BENCH_SEGMENT_SECONDS = 10.0
BENCH_MAX_WORKERS = 4
BENCH_MIN_GAIN = 0.10          # 合计吞吐相对上一档至少 +10% 才继续加路数


def _bench_encode(cmd: list[str], out_path: Path, start: float, seconds: float) -> float:
    """跑一次编码，返回耗时（秒）；失败返回 -1。"""
    cmd = list(cmd)
    i = cmd.index("-i")
    cmd = cmd[:i] + ["-ss", "%.3f" % start, "-t", "%.3f" % seconds] + cmd[i:]
    cmd[-1] = str(out_path)
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception:
        pass
    t0 = time.monotonic()
    try:
        cp = run_command(cmd, timeout=3600)
    except Exception:
        return -1.0
    wall = time.monotonic() - t0
    if cp.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
        return -1.0
    return wall


def _workers_key(platform_key: str, encoder: str) -> str:
    """并发缓存的 key：平台+编码器+硬件（N 卡带显卡与驱动，Intel 带 ffmpeg 版本）。"""
    if platform_key == "nvidia":
        hw = NVENC_HW or detect_nvenc_hardware()
        return "w%d|nvidia|%s|%s|%s" % (WORKERS_CACHE_VERSION, encoder,
                                        hw.get("gpu", ""), hw.get("driver", ""))
    return "w%d|intel|%s|%s" % (WORKERS_CACHE_VERSION, encoder, _ffmpeg_version_line())


def measure_workers(source: Path, info: "MediaInfo", platform_key: str, codec_key: str,
                    plan: Optional["EncodePlan"] = None,
                    max_workers: int = 3, seconds: float = 6.0) -> int:
    """短测 1..max_workers 路，返回建议路数（失败返回 0）。

    规则与 --concurrency-test 一致：合计吞吐相对上一档增益 < BENCH_MIN_GAIN 就停。
    """
    if plan is None:
        cap = DEFAULT_VIDEO_BITRATE_CAP or 1500
        plan = EncodePlan(mode=RC_MODE_CAPPED, quality=DEFAULT_VIDEO_QUALITY, cap_kbps=cap)
    seconds = min(seconds, max(2.0, info.duration - 1.0))
    start = max(0.0, min(info.duration - seconds - 0.05, info.duration * 0.35))
    template = build_ffmpeg_command(
        source=source, output=Path(tempfile.gettempdir()) / "ue_w.mp4", info=info,
        platform_key=platform_key, codec_key=codec_key, video_quality=DEFAULT_VIDEO_QUALITY,
        audio_quality=DEFAULT_AUDIO_BITRATE, decode_args=decode_args_for(platform_key),
        plan=plan, video_only=True,
    )

    best_n, best_throughput = 1, 0.0
    for n in range(1, max_workers + 1):
        outs = [Path(tempfile.gettempdir()) / ("ue_w_%d_%d.mp4" % (n, k)) for k in range(n)]
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            walls = list(pool.map(lambda k: _bench_encode(template, outs[k], start, seconds),
                                  range(n)))
        wall = time.monotonic() - t0
        for out in outs:
            try:
                out.unlink()
            except Exception:
                pass
        if any(w < 0 for w in walls) or wall <= 0:
            break
        throughput = (n * seconds) / wall
        print("   %d 路：合计吞吐 %5.2fx" % (n, throughput), flush=True)
        if n == 1:
            best_n, best_throughput = 1, throughput
        elif throughput >= best_throughput * (1.0 + BENCH_MIN_GAIN):
            best_n, best_throughput = n, throughput
        else:
            # 再加一路的收益已经不够看，后面不必再测（省时间）
            print("   %d 路：增益不足 %.0f%%，停止往上测" % (n, BENCH_MIN_GAIN * 100),
                  flush=True)
            break
    return best_n if best_throughput > 0 else 0


def resolve_workers(source: Path, info: "MediaInfo", platform_key: str, codec_key: str,
                    plan: Optional["EncodePlan"] = None) -> int:
    """决定并发路数：AUTO_WORKERS=False 用默认值；True 则实测并缓存。"""
    if not AUTO_WORKERS:
        ui_hint("并发 %d 路（已关闭自适应；脚本顶部 AUTO_WORKERS 可改回 True）"
                % int(DEFAULT_WORKERS))
        return max(1, int(DEFAULT_WORKERS))

    key = _workers_key(platform_key, encoder_name(platform_key, codec_key))
    cached = _load_calibration(WORKERS_CACHE_FILE)
    if cached and cached.get("key") == key and cached.get("workers"):
        ui_hint("并发自适应：%d 路（沿用上次实测缓存 %s；换显卡/驱动/ffmpeg 会自动重测）"
                % (int(cached["workers"]), WORKERS_CACHE_FILE.name))
        return max(1, int(cached["workers"]))

    ui_section("并发自适应实测（首次运行，约 20~30 秒；结果会缓存）")
    picked = measure_workers(source, info, platform_key, codec_key, plan)
    if not picked:
        ui_warn("并发实测失败，改用默认 %d 路" % DEFAULT_WORKERS)
        return max(1, int(DEFAULT_WORKERS))
    _save_calibration({"key": key, "workers": picked}, WORKERS_CACHE_FILE)
    ui_ok("并发自适应：%d 路（本机实测；已缓存到 %s，删掉即可重测）"
          % (picked, WORKERS_CACHE_FILE.name))
    return picked


def benchmark_concurrency(root: Path) -> int:
    """实测本机并发收益，返回建议的并发路数。"""
    ui_banner("并发收益实测")

    try:
        check_tools()          # 必须先跑：平台检测依赖这里填好的编码器列表
    except Exception as e:
        print(f"环境检查失败：{e}")
        return 1

    videos = scan_videos(root, recursive=False)
    if not videos:
        print("当前目录没有视频，无法测试。请把脚本和至少一个视频放在同一目录再跑。")
        return 1

    source = videos[0]
    try:
        info = get_media_info(source)
    except Exception as e:
        print(f"读取 {source.name} 失败：{e}")
        return 1

    detected = detect_platforms()
    if "nvidia" in detected:
        platform_key = "nvidia"
    elif "intel" in detected:
        platform_key = "intel"
    else:
        print("没有检测到可用的硬件编码平台。")
        return 1
    codec_key = "hevc"
    encoder = encoder_name(platform_key, codec_key)
    prepare_encoder_capabilities(encoder)
    DECODE_TIER[platform_key] = 0
    if platform_key == "nvidia":
        NVENC_HW.update(detect_nvenc_hardware())
        NVENC_CALIBRATED.update(nvenc_default_settings())

    # 用"最贴近实际"的参数：超大素材走上限模式
    cap = DEFAULT_VIDEO_BITRATE_CAP or 1500
    plan = EncodePlan(mode=RC_MODE_CAPPED, quality=DEFAULT_VIDEO_QUALITY, cap_kbps=cap)

    seconds = min(BENCH_SEGMENT_SECONDS, max(2.0, info.duration - 1.0))
    start = max(0.0, min(info.duration - seconds - 0.05, info.duration * 0.35))

    ui_kv("平台 / 编码器", f"{ENCODER_PROFILES[platform_key]['name']} / {encoder}")
    ui_kv("素材", f"{source.name}  {info.width}x{info.height} {info.fps:.2f}fps")
    ui_kv("片段", f"{format_duration(start)} 起 {seconds:g} 秒 | {plan_label(plan)} {cap} kbps")
    print()

    template = build_ffmpeg_command(
        source=source, output=Path(tempfile.gettempdir()) / "ue_bench.mp4", info=info,
        platform_key=platform_key, codec_key=codec_key, video_quality=DEFAULT_VIDEO_QUALITY,
        audio_quality=DEFAULT_AUDIO_BITRATE, decode_args=decode_args_for(platform_key),
        plan=plan, video_only=True,
    )

    rows: list[tuple[int, float, float, float]] = []      # (n, wall, 合计吞吐, 单文件速度)
    best_n, best_throughput = 1, 0.0
    for n in range(1, BENCH_MAX_WORKERS + 1):
        outs = [Path(tempfile.gettempdir()) / f"ue_bench_{n}_{k}.mp4" for k in range(n)]
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            walls = list(pool.map(
                lambda k: _bench_encode(template, outs[k], start, seconds), range(n)))
        wall = time.monotonic() - t0
        for out in outs:
            try:
                out.unlink()
            except Exception:
                pass
        if any(w < 0 for w in walls):
            print(f"  {n} 路：有任务失败，停止测试。")
            break
        throughput = (n * seconds) / wall if wall > 0 else 0.0
        per_file = sum(seconds / w for w in walls) / n if walls else 0.0
        rows.append((n, wall, throughput, per_file))
        print("   %d 路：总耗时 %6.1fs   合计吞吐 %5.2fx   单文件 %5.2fx"
              % (n, wall, throughput, per_file), flush=True)
        if n == 1:
            best_n, best_throughput = 1, throughput
        elif throughput >= best_throughput * (1.0 + BENCH_MIN_GAIN):
            best_n, best_throughput = n, throughput

    if not rows:
        print("测试没有成功跑出结果。")
        return 1

    base = rows[0][2] or 1.0
    print()
    ui_rule()
    print("   路数   总耗时    合计吞吐   相对 1 路   单文件速度")
    for n, wall, throughput, per_file in rows:
        print("   %2d 路  %6.1fs   %6.2fx    %+6.0f%%     %5.2fx"
              % (n, wall, throughput, (throughput / base - 1) * 100, per_file))
    ui_rule()
    ui_ok("建议 MAX_WORKERS = %d（合计吞吐 %.2fx；再往上每加一路的增益不足 %.0f%%）"
          % (best_n, best_throughput, BENCH_MIN_GAIN * 100))
    ui_hint("想固定下来：脚本顶部 INTEL_MAX_WORKERS（Intel）或 N 卡分支里的 min(3, engines) 改成这个数。")
    return 0


# ============================================================
# QSV 自动标定（与 NVENC 同一套机制，只是候选集不同）
# ------------------------------------------------------------
# 实测（1290x2796@60 录屏 20 秒，只变 preset，同码率比画质）：
#   ffmpeg 的 7 个 preset 名实际只映射成 3 个 TargetUsage：
#     veryfast / faster        → TU=7   3.28~3.42x
#     fast / medium / slow     → TU=4   3.15~3.29x
#     slower / veryslow        → TU=1   2.20~2.38x
#   capped 1500k：TU7 81.83 | TU4 82.55 | TU1 82.76
#   ICQ Q30   ：TU7 86.53 | TU4 86.73 | TU1 86.79
# 结论：TU4 用 0.21 VMAF（ICQ 下仅 0.06）换 1.44 倍速度，非常划算；TU7 再快但掉 0.93。
# 所以容差取 0.30 → 自动落到 TU4。想恢复"最慢最好"把 QSV_QUALITY_TOLERANCE 改成 0.05。
# ============================================================
QSV_AUTO_CALIBRATE = True
QSV_CALIB_SECONDS = 3.0
QSV_QUALITY_TOLERANCE = 0.30
QSV_FORCE_PROFILE: Optional[str] = None       # tu1_veryslow / tu4_balanced / tu7_fast
QSV_CALIBRATION_VERSION = 2
QSV_CALIBRATION_FILE = _SCRIPT_DIR / "_qsv_calibration.json"
QSV_CALIBRATED: dict[str, Any] = {}           # 标定选中的参数，build_ffmpeg_command 会合并它


def qsv_candidates() -> list[tuple[str, dict[str, Any], str]]:
    """QSV 候选档位。preset 名只是入口，真正区分的是 TargetUsage。"""
    return [
        ("tu1_veryslow", {"preset": "veryslow"}, "TU=1 最慢、同码率画质最好"),
        ("tu4_balanced", {"preset": "medium"}, "TU=4 画质仅低 ~0.2，速度快 ~1.44 倍"),
        ("tu7_fast", {"preset": "faster"}, "TU=7 最快，画质低 ~0.9"),
    ]


def _qsv_calibration_core_key(encoder: str, codec_key: str, plan: "EncodePlan") -> str:
    """核心 key：含 ffmpeg 版本（ICQ/CQP 行为随构建变化）+ 编码器/编码/模式/上限。"""
    mode = plan.mode if plan else RC_MODE_QUALITY
    cap = int(plan.cap_kbps or 0) if plan else 0
    return "|".join([
        "q%d" % QSV_CALIBRATION_VERSION,
        _ffmpeg_version_line(),
        encoder,
        codec_key,
        mode,
        str(cap),
    ])


def _qsv_calibration_key(encoder: str, codec_key: str, plan: "EncodePlan", info: "MediaInfo") -> str:
    return _qsv_calibration_core_key(encoder, codec_key, plan) + "|%dx%d|%d" % (
        info.width, info.height, round(info.fps or 0))


def calibrate_qsv(
    source: Path,
    info: "MediaInfo",
    platform_key: str,
    codec_key: str,
    video_quality: int,
    plan: Optional["EncodePlan"] = None,
) -> Optional[dict]:
    """在真实素材上实测 QSV 各 preset，选"画质在容差内最快"的一档并缓存。"""
    encoder = encoder_name(platform_key, codec_key)
    plan = plan or EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality)
    profiles = qsv_candidates()

    if QSV_FORCE_PROFILE:
        for name, settings, _note in profiles:
            if name == QSV_FORCE_PROFILE:
                QSV_CALIBRATED.clear()
                QSV_CALIBRATED.update(settings)
                ui_hint("QSV 标定：按 QSV_FORCE_PROFILE 强制使用 %s（跳过实测）" % name)
                return settings
        ui_warn("QSV_FORCE_PROFILE=%s 不是有效档位，改为自动标定。" % QSV_FORCE_PROFILE)

    key = _qsv_calibration_key(encoder, codec_key, plan, info)
    core = _qsv_calibration_core_key(encoder, codec_key, plan)

    cached = _load_calibration(QSV_CALIBRATION_FILE)
    if cached and cached.get("settings"):
        exact = cached.get("key") == key
        same_core = cached.get("core") == core
        if exact or same_core:
            QSV_CALIBRATED.clear()
            QSV_CALIBRATED.update(cached["settings"])
            why = "完全匹配" if exact else "同 ffmpeg/编码器/模式（本次分辨率不同，沿用）"
            ui_hint("QSV 标定：沿用上次结果 %s（%s %.2f；%s）"
                    % (cached.get("chosen", "?"), cached.get("metric", ""),
                       float(cached.get("quality") or 0), why))
            return cached["settings"]

    seconds = max(1.0, min(float(QSV_CALIB_SECONDS),
                           info.duration - 1.0 if info.duration else float(QSV_CALIB_SECONDS)))
    start = max(0.0, min(info.duration - seconds - 0.05, info.duration * 0.35)) if info.duration else 0.0

    ui_section("QSV 自动标定（首次运行，%d 档 × %g 秒样片；结果会缓存）"
               % (len(profiles), seconds))
    ui_kv("ffmpeg", _ffmpeg_version_line()[:60] or "未知")
    ui_kv("样片", "%s 的 %s 起 %.1f 秒 | %s"
          % (source.name, format_duration(start), seconds, plan_label(plan)))

    rows: list[dict[str, Any]] = []
    for name, settings, note in profiles:
        res = _run_calibration_encode(
            source=source, info=info, platform_key=platform_key, codec_key=codec_key,
            video_quality=video_quality, plan=plan, settings=settings,
            start=start, seconds=seconds, slot=QSV_CALIBRATED,
        )
        if res is None:
            ui_warn("%-14s 该档位在本机/本素材上编不出来，已跳过" % name)
            continue
        metric, value = measure_quality(res["out"], source, start, seconds)
        try:
            res["out"].unlink()
        except Exception:
            pass
        rows.append({"name": name, "note": note, "settings": settings,
                     "speed": res["speed"], "fps": res["fps"], "wall": res["wall"],
                     "metric": metric or "n/a", "quality": value})
        print("   %-14s %6.2fx  %6.1f fps  %s %7.2f   %s"
              % (name, res["speed"], res["fps"], (metric or "-"), value, dim(note)), flush=True)

    if not rows:
        ui_warn("QSV 标定失败（所有候选都编不出来），改用默认 preset。")
        QSV_CALIBRATED.clear()
        return None

    metric_name = rows[0]["metric"]
    if metric_name == "VMAF":
        tolerance = QSV_QUALITY_TOLERANCE
    else:
        tolerance = NVENC_SSIM_TOLERANCE
        ui_warn("本机 ffmpeg 没有 libvmaf，用 SSIM 代替（容差 %.4f）" % tolerance)
    best = max(rows, key=lambda r: r["quality"])
    eligible = [r for r in rows if r["quality"] >= best["quality"] - tolerance]
    # 先找最快档，再把"耗时在最快档 105% 以内"的档位放在一起，从中挑画质最好的。
    # 这 5% 是测量噪声容限：避免为零点几秒的抖动牺牲明显更高的画质。
    fastest = min(eligible, key=lambda r: r["wall"])
    near = [r for r in eligible if r["wall"] <= fastest["wall"] * 1.05]
    pick = max(near, key=lambda r: r["quality"])

    QSV_CALIBRATED.clear()
    QSV_CALIBRATED.update(pick["settings"])

    gap = best["quality"] - pick["quality"]
    speedup = (best["wall"] / pick["wall"]) if pick["wall"] > 0 else 1.0
    ui_ok("选中 %s：%s %.2f（比最好档 %s 低 %.2f，在容差 %.2f 内，但快 %.2f 倍）"
          % (pick["name"], metric_name, pick["quality"], best["name"], gap, tolerance, speedup))

    _save_calibration({
        "key": key, "core": core, "chosen": pick["name"], "settings": pick["settings"],
        "metric": metric_name, "quality": pick["quality"], "tolerance": tolerance,
        "rows": rows,
    }, QSV_CALIBRATION_FILE)
    ui_hint("标定结果已缓存到 %s（删掉即可重新标定）" % QSV_CALIBRATION_FILE.name)
    return pick["settings"]


# 质量档位文案。三个编码器的标尺完全不同，必须分开描述：
#   Intel QSV（QP 1~51）、NVENC HEVC（CQ 0~51）、NVENC AV1（CQ 0~255）。
QUALITY_LABELS_INTEL = {
    26: "极高质量 / 文件最大",
    28: "高质量",
    30: "均衡",
    32: "高压缩",
    34: "极高压缩 / 文件最小",
}
QUALITY_LABELS_NVENC_HEVC = {
    18: "接近无损 / 很大",
    20: "极高质量",
    22: "高质量",
    24: "较高质量",
    26: "均衡 / 推荐",
    28: "高压缩",
    30: "极限压缩",
}
QUALITY_LABELS_NVENC_AV1 = {
    24: "接近无损 / 很大",
    28: "极高质量",
    32: "高质量",
    36: "较高质量",
    40: "均衡 / 推荐",
    44: "高压缩",
    48: "极限压缩",
}
RC_MODE_LABELS = {
    RC_MODE_QUALITY: "质量优先（只看画质，不看体积）",
    RC_MODE_CAPPED: "全部限码率（体积可控，复杂画面会被牺牲）",
    RC_MODE_AUTO: "自动兜底（按文件采样判断，推荐）",
}


def quality_levels(platform_key: str, codec_key: str) -> list[int]:
    """返回该平台 + 该编码器真正可用的质量档位。

    NVENC 的 AV1 与 HEVC 用不同的 CQ 标尺（0~255 与 0~51），绝不能共用一列数字。
    """
    if platform_key == "nvidia":
        return NVIDIA_AV1_QUALITY_LEVELS if codec_key == "av1" else NVIDIA_HEVC_QUALITY_LEVELS
    return INTEL_VIDEO_QUALITY_LEVELS


def quality_label(platform_key: str, codec_key: str, value: int) -> str:
    if platform_key == "nvidia":
        table = QUALITY_LABELS_NVENC_AV1 if codec_key == "av1" else QUALITY_LABELS_NVENC_HEVC
    else:
        table = QUALITY_LABELS_INTEL
    return table.get(value, "自定义")


def rc_mode_label(mode: str) -> str:
    return RC_MODE_LABELS.get(mode, mode)




def encoder_name(platform_key: str, codec_key: str) -> str:
    return ENCODER_PROFILES[platform_key]["encoders"][codec_key]


def calculate_gop(fps: float, seconds: float = GOP_SECONDS) -> int:
    """按源视频帧率动态设置 GOP。

    归档取向（不是直播/低延迟）：更长的 GOP 给编码器更多跨帧预测空间。
    本机实测（1080p50，HEVC 质量模式 q32）：GOP 5 秒 → 10 秒，同画质下
    码率降低约 7%（1683 → 1554 kbps）。异常帧率时给保守值。
    """
    if fps <= 0:
        return int(round(25 * seconds))
    gop = int(round(fps * seconds))
    return max(48, min(3000, gop))


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MediaInfo:
    path: Path
    duration: float = 0.0
    size: int = 0
    format_name: str = ""

    video_codec: str = "unknown"
    video_bitrate: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    pix_fmt: str = ""
    profile: str = ""
    video_bitrate_estimated: bool = False

    audio_codec: str = "none"
    audio_bitrate: int = 0
    sample_rate: int = 0
    channels: int = 0
    channel_layout: str = ""

    @property
    def total_bitrate(self) -> int:
        if self.duration > 0 and self.size > 0:
            return int(self.size * 8 / self.duration)
        return 0

    @property
    def is_10bit(self) -> bool:
        pf = (self.pix_fmt or "").lower()
        if "10" in pf or "12" in pf:
            return True
        try:
            # bits_per_raw_sample 并未存入 dataclass，因此主要依靠 pix_fmt。
            return int(self.profile.lower().replace("bit", "")) >= 10
        except Exception:
            return False


@dataclass
class TaskState:
    index: int
    source: Path
    output: Path
    status: str = "queued"

    duration: float = 0.0
    out_time: float = 0.0
    speed: float = 0.0
    fps: float = 0.0
    percent: float = 0.0

    start_time: float = 0.0
    end_time: float = 0.0

    original_size: int = 0
    output_size: int = 0

    message: str = ""
    error: str = ""
    summary: str = ""


@dataclass
class Result:
    index: int
    source: Path
    output: Path
    status: str
    message: str = ""
    original_info: Optional[MediaInfo] = None
    output_info: Optional[MediaInfo] = None
    elapsed: float = 0.0
    avg_speed: float = 0.0
    error: str = ""
    plan: Optional["EncodePlan"] = None
    vmaf: Optional[float] = None
    decoder_label: str = ""


@dataclass
class EncoderCapabilities:
    encoder: str
    options: set[str] = field(default_factory=set)
    help_text: str = ""

    def has(self, option: str) -> bool:
        return option in self.options

    def supports_value(self, option: str, value: str) -> bool:
        """尽量从 encoder help 判断枚举值；无法确认时不武断否定。"""
        text = self.help_text.lower()
        option = option.lstrip("-").lower()
        value = value.lower()
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.search(rf"\-{re.escape(option)}(?:\s|$)", line):
                window = "\n".join(lines[i:i + 5])
                if value in window:
                    return True
        return value in text if option in ("tune", "multipass", "b_ref_mode") else True


# ============================================================
# 全局状态
# ============================================================

STATE_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()

TASK_STATES: dict[int, TaskState] = {}

STOP_REQUESTED = False



def format_bytes(value: int | float) -> str:
    value = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def format_duration(seconds: float) -> str:
    if not seconds or seconds < 0:
        return "00:00:00"

    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_bitrate(bits_per_second: int | float) -> str:
    if not bits_per_second:
        return "N/A"

    kbps = bits_per_second / 1000
    if kbps < 1000:
        return f"{kbps:.0f} kb/s"

    return f"{kbps / 1000:.2f} Mb/s"


def video_bitrate_text(info: "MediaInfo") -> str:
    text = format_bitrate(info.video_bitrate)
    return f"≈{text}" if info.video_bitrate_estimated and text != "N/A" else text


def format_percent(value: float) -> str:
    return f"{max(0.0, min(100.0, value)):.1f}%"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_ratio(value: Any) -> float:
    if not value:
        return 0.0
    try:
        if isinstance(value, str) and "/" in value:
            a, b = value.split("/", 1)
            b = float(b)
            return float(a) / b if b else 0.0
        return float(value)
    except Exception:
        return 0.0


def quote_for_display(path: Path) -> str:
    return str(path)


# ============================================================
# FFmpeg / FFprobe
# ============================================================

def run_command(
    args: list[str],
    timeout: Optional[int] = None,
    capture_output: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def check_tools() -> None:
    """检查 FFmpeg/FFprobe，并一次性缓存 FFmpeg 已编译的编码器列表。

    这里刻意不使用 `ffmpeg -h encoder=...` 做启动阶段的平台检测。
    某些 Windows / NVIDIA 环境下该调用可能明显变慢；平台探测应该尽量轻量。
    """
    global AVAILABLE_ENCODERS, FFMPEG_BIN, FFPROBE_BIN

    # PATH 里没有 ffmpeg 时自动兜底（改完 PATH 后旧终端进程仍拿旧 PATH 的情况很常见）
    if not FFMPEG_BIN and not shutil.which("ffmpeg"):
        found = locate_ffmpeg_if_missing()
        if found:
            FFMPEG_BIN = found
            FFPROBE_BIN = sibling_ffprobe(found)
            print(f"PATH 里没有 ffmpeg，已自动改用：{FFMPEG_BIN}")

    for tool, resolved in (("ffmpeg", ffmpeg_exe()), ("ffprobe", ffprobe_exe())):
        if os.path.isabs(resolved) or os.sep in resolved:
            if not Path(resolved).exists():
                raise RuntimeError(f"找不到指定的 {tool}：{resolved}")
            continue
        path = shutil.which(resolved)
        if not path:
            raise RuntimeError(
                f"找不到 {tool}.exe，请确认 FFmpeg 已安装并加入 PATH，"
                f"或在本脚本顶部设置 FFMPEG_BIN / FFPROBE_BIN。"
            )

    # 这三行是诊断信息：整行压暗，避免和真正要看的设置抢注意力
    try:
        cp = run_command([ffmpeg_exe(), "-version"], timeout=10)
        first_line = cp.stdout.splitlines()[0] if cp.stdout else "unknown"
        print(dim(f"   ffmpeg   {first_line}"))
    except Exception as e:
        print(dim(f"   ffmpeg   检测失败：{e}"))

    try:
        cp = run_command([ffprobe_exe(), "-version"], timeout=10)
        first_line = cp.stdout.splitlines()[0] if cp.stdout else "unknown"
        print(dim(f"   ffprobe  {first_line}"))
    except Exception as e:
        print(dim(f"   ffprobe  检测失败：{e}"))

    try:
        cp = run_command([ffmpeg_exe(), "-hide_banner", "-encoders"], timeout=15)
        if cp.returncode == 0:
            for line in (cp.stdout or "").splitlines():
                # 典型格式：" V..... av1_nvenc ..."
                parts = line.split()
                if len(parts) >= 2 and not line.lstrip().startswith("-"):
                    name = parts[1]
                    if name.endswith(("_qsv", "_nvenc")):
                        AVAILABLE_ENCODERS.add(name)
        print(dim(f"   硬件编码器 {', '.join(sorted(AVAILABLE_ENCODERS)) or '未发现 QSV/NVENC'}"))
    except Exception as e:
        print(dim(f"   编码器列表 检测失败：{e}"))


# ============================================================
# 平台检测 / 终端颜色
# ============================================================

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[92m",
    "red": "\033[91m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "white": "\033[97m",
}

USE_COLOR = bool(getattr(sys.stdout, "isatty", lambda: False)()) or bool(
    os.environ.get("FORCE_COLOR")
)
AVAILABLE_ENCODERS: set[str] = set()
ENCODER_CAPABILITIES: dict[str, EncoderCapabilities] = {}


def color(text: str, name: str, *, bold: bool = False) -> str:
    if not USE_COLOR:
        return text
    prefix = ANSI.get(name, "")
    if bold:
        prefix += ANSI["bold"]
    return f"{prefix}{text}{ANSI['reset']}"


def dim(text: str) -> str:
    return color(text, "dim")


# ------------------------------------------------------------
# 统一的界面层级：标题=青色，提示=黄色，成功=绿色，错误=红色，
# 次要信息=暗色。所有界面都走这几个函数，避免"满屏白字"。
# ------------------------------------------------------------

RULE = "─" * 84
RULE_HEAVY = "═" * 84


def term_width(default: int = 100) -> int:
    """终端可见宽度（列）。用于避免长行折行把界面搅乱。"""
    try:
        return max(60, shutil.get_terminal_size((default, 24)).columns)
    except Exception:
        return default


def fit(text: str, width: int) -> str:
    """按显示宽度截断（超长加省略号）。只用于纯文本片段。"""
    if width <= 1:
        return ""
    return text if len(text) <= width else text[: width - 1] + "…"


def ui_gap(count: int = 3) -> None:
    """模块之间的间隔（模块内部只用 1 行空行，模块之间用 3 行区分层次）。"""
    for _ in range(max(1, count)):
        print()


def disp_width(text: str) -> int:
    """显示宽度：中日韩字符按 2 列算（用于居中，避免名字偏左）。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def ui_banner(text: str) -> None:
    """程序标题：最醒目的一行，工具名居中夹在等号中间。"""
    w = min(74, term_width() - 2)
    inner = f" {text} "
    pad = max(3, (w - disp_width(inner)) // 2)
    line = "=" * pad + inner + "=" * max(3, w - pad - disp_width(inner))
    print(color(line, "cyan", bold=True))


def ui_rule(width: Optional[int] = None, *, bright: bool = False) -> None:
    """模块内分隔线：整行等号。"""
    w = min(74, term_width() - 2) if width is None else width
    line = "=" * max(20, w)
    print(color(line, "cyan", bold=True) if bright else dim(color(line, "cyan")))


def ui_module_line(name: str) -> str:
    """模块标题行：=== 模块名 ====…（后面的等号拉到行尾）。

    标题里若带换行（例如"【3. xxx】\n当前目标编码：…"），这里只取第一行，
    否则等号会跑到第二行去。副标题由 ui_menu / ui_title 单独打印。
    """
    first = name.splitlines()[0] if name.splitlines() else name
    w = min(74, term_width() - 2)
    head = f"=== {first} "
    return head + "=" * max(3, w - disp_width(head))


def ui_title(text: str) -> None:
    """大模块标题：=== 模块名 ====…（品红加粗，和程序标题区分开）。"""
    ui_gap(3)
    lines = text.splitlines() or [text]
    print(color(ui_module_line(lines[0]), "magenta", bold=True))
    for extra in lines[1:]:
        print(f"   {dim(extra)}")
    print()


def ui_section(text: str) -> None:
    """小节标题（左侧色块）。"""
    print()
    print(color(f"▌ {text}", "cyan", bold=True))


def ui_kv(name: str, value: str, *, value_color: str = "white", bold_value: bool = False) -> None:
    """参数行：名称暗、数值亮。"""
    print(f"  {dim(name)}  {color(value, value_color, bold=bold_value)}")


def ui_ok(text: str) -> None:
    print(color(f"  ✓ {text}", "green"))


def ui_warn(text: str) -> None:
    print(color(f"  ! {text}", "yellow"))


def ui_err(text: str) -> None:
    print(color(f"  × {text}", "red"))


def ui_hint(text: str) -> None:
    print(f"  {dim(text)}")


def ui_file(name: str) -> None:
    print(color(f"  {name}", "white", bold=True))


class BackRequested(Exception):
    """用户在任何一步输入 b/返回，要求退回重选。"""


def _is_back(text: str) -> bool:
    return text.strip().lower() in {"b", "back", "返回", "重选", "r"}


def ui_option(key: str, name: str, desc: str = "", is_default: bool = False) -> str:
    """统一的选项行。

    规则（整份界面统一）：
      * 主信息（选项名）亮色；默认项整行绿色加粗，并在名字后缀「（默认）」
      * 说明文字一律作为副信息（暗色），默认项的说明也不标绿，否则太花
      * 默认项行尾只放一个箭头 ←，用来"一眼看到当前选的是哪个"
    """
    if is_default and "默认" not in name:
        name = f"{name}（默认）"
    if is_default:
        line = f"   {color(f'[{key}]', 'green')} {color(name, 'green', bold=True)}"
    else:
        line = f"   {color(f'[{key}]', 'cyan')} {color(name, 'white')}"
    if desc:
        line += f"   {dim(desc)}"
    if is_default:
        line += f"  {color('←', 'green', bold=True)}"
    return line


def ui_prompt(default_label: Optional[str]) -> str:
    """统一提问格式：请选择（默认 xxx）："""
    return f"请选择（默认 {default_label}）：" if default_label else "请选择："


def ui_menu(
    title: str,
    options: list[tuple],
    default: Optional[str] = None,
    default_label: Optional[str] = None,
) -> str:
    """统一菜单：模块边界用实线，标题紧跟选项（一个有主的块），提示单独放。

        ──────────────────────────────
        ▌ 【4. 扫描范围】
           [1] 仅当前文件夹（默认）  ←
           [2] 当前文件夹 + 所有子文件夹

           （输入 b 可返回重选）
        请选择（默认 仅当前文件夹）：

    options 支持 (key, name) 或 (key, name, desc)；desc 作为副信息暗色显示。
    任何一步输入 b（或 back/返回）都会退回重选。
    """
    ui_gap(3)                      # 模块之间的间隔比模块内部大一档
    title_lines = title.splitlines() or [title]
    print(color(ui_module_line(title_lines[0]), "magenta", bold=True))
    for extra in title_lines[1:]:
        print(f"   {dim(extra)}")
    print()                        # 标题与选项之间留空行，避免看成同一行
    for opt in options:
        key, name = opt[0], opt[1]
        desc = opt[2] if len(opt) > 2 else ""
        print(ui_option(key, name, desc, is_default=(default == key)))
    print()
    print(f"   {dim('（输入 b 可返回重选）')}")
    while True:
        value = input(color(ui_prompt(default_label or default), "yellow")).strip()
        if _is_back(value):
            raise BackRequested()
        if not value and default:
            return default
        if value in {o[0] for o in options}:
            return value
        ui_warn("输入无效，请重新选择。")


class StatusBoard:
    """底部固定状态区：普通日志向上滚动，状态区数字原地更新。

    这样既有"可以往上滑看历史"，又不会把进度追加成一堆行。
    仅在真终端（能控制光标）里原地更新；输出被重定向到文件/管道时自动退化为
    只打印"开始"行，保持日志干净。
    """

    def __init__(self) -> None:
        self._content: list[str] = []
        self._visible = False

    @property
    def _can_redraw(self) -> bool:
        # 只有真终端才做光标移动：重定向到文件/管道时（例如 tee、计划任务日志）
        # 退化为只打印普通行，避免把控制序列写进日志。
        return bool(getattr(sys.stdout, "isatty", lambda: False)())

    def _erase(self) -> None:
        if self._visible and self._content:
            sys.stdout.write("\033[%dA\033[J" % len(self._content))
            sys.stdout.flush()
        self._visible = False

    def _redraw(self) -> None:
        if self._content and self._can_redraw:
            sys.stdout.write("\n".join(self._content) + "\n")
            sys.stdout.flush()
            self._visible = True

    def log(self, text: str = "") -> None:
        """在状态区上方追加一行普通日志。"""
        with PRINT_LOCK:
            self._erase()
            print(text, flush=True)
            self._redraw()

    def update(self, lines: list[str]) -> None:
        """原地刷新状态区内容。"""
        with PRINT_LOCK:
            self._erase()
            self._content = list(lines)
            self._redraw()

    def close(self) -> None:
        with PRINT_LOCK:
            self._erase()
            self._content = []


def detect_nvidia() -> tuple[bool, str]:
    """快速检测 NVIDIA：nvidia-smi + FFmpeg NVENC 编译支持。"""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, "未找到 nvidia-smi"

    try:
        cp = run_command(
            [smi, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            timeout=5,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            lines = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
            nvenc = [x for x in ("av1_nvenc", "hevc_nvenc") if x in AVAILABLE_ENCODERS]
            if nvenc:
                return True, f"{'; '.join(lines)} | FFmpeg: {', '.join(nvenc)}"
            return False, f"发现 NVIDIA GPU，但当前 FFmpeg 没有 NVENC encoder：{'; '.join(lines)}"
        return False, (cp.stderr or "nvidia-smi 无可用 GPU").strip()
    except Exception as e:
        return False, str(e)


def detect_intel() -> tuple[bool, str]:
    """快速检测 Intel QSV。启动阶段不做 QSV 初始化测试，避免误把慢启动变成常态。"""
    names: list[str] = []

    if os.name == "nt":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            try:
                cp = run_command(
                    [
                        ps, "-NoProfile", "-NonInteractive", "-Command",
                        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                    ],
                    timeout=5,
                )
                if cp.returncode == 0:
                    names = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
            except Exception:
                pass

    intel_names = [n for n in names if "intel" in n.lower()]
    qsv = [x for x in ("av1_qsv", "hevc_qsv") if x in AVAILABLE_ENCODERS]

    if intel_names and qsv:
        return True, f"{'; '.join(intel_names)} | FFmpeg: {', '.join(qsv)}"
    if intel_names:
        return False, f"发现 Intel GPU，但当前 FFmpeg 没有 QSV encoder：{'; '.join(intel_names)}"
    return False, "未检测到可用 Intel QSV 平台"


def detect_platforms() -> dict[str, str]:
    # 并行检测，避免 PowerShell/CIM 与 nvidia-smi 的启动时间串行叠加。
    # 启动阶段只做“存在性 + FFmpeg encoder”检查，不初始化真正的编码会话。
    result: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        nf = pool.submit(detect_nvidia)
        inf = pool.submit(detect_intel)
        nvidia_ok, nvidia_detail = nf.result()
        intel_ok, intel_detail = inf.result()
    if intel_ok:
        result["intel"] = intel_detail
    if nvidia_ok:
        result["nvidia"] = nvidia_detail
    return result


def choose_platform(detected: dict[str, str]) -> str:
    ui_gap(3)
    print(color(ui_module_line("【1. 硬件编码平台】"), "magenta", bold=True))
    print()
    print(f"   {dim('正在自动检测 Intel QSV / NVIDIA NVENC……')}")

    if detected:
        for key, detail in detected.items():
            label = ENCODER_PROFILES[key]["name"]
            print(color(f"   √ {label}：{detail}", "green"))
    else:
        print(color("   ! 未能自动确认可用的 Intel / NVIDIA 硬件编码平台。", "yellow"))

    if len(detected) == 1:
        key = next(iter(detected))
        print(f"   {dim('自动选择')} {color(ENCODER_PROFILES[key]['name'], 'white', bold=True)}")
        return key

    if not detected:
        manual = ask_choice(
            "【手动选择平台】",
            [("1", "Intel QSV"), ("2", "NVIDIA NVENC")],
            default="1",
        )
        return "intel" if manual == "1" else "nvidia"

    options: list[tuple[str, str]] = []
    if "intel" in detected:
        options.append(("1", "Intel QSV"))
    if "nvidia" in detected:
        options.append(("2", "NVIDIA NVENC"))
    options.append(("3", "手动选择平台（即使自动检测失败也可继续）"))

    choice = ask_choice("检测到多个平台，请选择本次使用的平台：", options, default="1", default_label="Intel QSV")
    if choice == "1" and "intel" in detected:
        return "intel"
    if choice == "2" and "nvidia" in detected:
        return "nvidia"

    manual = ask_choice(
        "【手动选择平台】",
        [("1", "Intel QSV"), ("2", "NVIDIA NVENC")],
        default="1",
    )
    return "intel" if manual == "1" else "nvidia"

def ffprobe_json(path: Path) -> dict[str, Any]:
    args = [
        ffprobe_exe(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    cp = run_command(args, timeout=60)

    if cp.returncode != 0:
        raise RuntimeError(
            f"ffprobe 失败：{path}\n{cp.stderr[-3000:]}"
        )

    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ffprobe 输出不是有效 JSON：{path}\n{e}"
        )


def get_media_info(path: Path) -> MediaInfo:
    data = ffprobe_json(path)

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (s for s in streams if s.get("codec_type") == "audio"),
        None,
    )

    if not video:
        raise RuntimeError(f"没有找到视频流：{path}")

    info = MediaInfo(path=path)
    info.size = path.stat().st_size
    info.format_name = str(fmt.get("format_name", ""))

    info.duration = safe_float(
        video.get("duration")
        or fmt.get("duration"),
        0.0,
    )

    info.video_codec = str(video.get("codec_name", "unknown"))
    info.video_bitrate = safe_int(video.get("bit_rate"))
    info.width = safe_int(video.get("width"))
    info.height = safe_int(video.get("height"))
    info.fps = parse_ratio(video.get("avg_frame_rate"))
    if info.fps <= 0:
        info.fps = parse_ratio(video.get("r_frame_rate"))

    info.pix_fmt = str(video.get("pix_fmt", ""))
    info.profile = str(video.get("profile", ""))

    if audio:
        info.audio_codec = str(audio.get("codec_name", "unknown"))
        info.audio_bitrate = safe_int(audio.get("bit_rate"))
        info.sample_rate = safe_int(audio.get("sample_rate"))
        info.channels = safe_int(audio.get("channels"))
        info.channel_layout = str(audio.get("channel_layout", ""))

    # MKV / TS 等容器的视频流通常没有 bit_rate 字段，显示 N/A 没有参考价值。
    # 这里用「容器总码率 - 音频码率」估算，并标记为估算值（显示时带 ≈）。
    if info.video_bitrate <= 0:
        total_bps = safe_int(fmt.get("bit_rate"))
        if total_bps <= 0 and info.duration > 0 and info.size > 0:
            total_bps = int(info.size * 8 / info.duration)
        if total_bps > 0:
            info.video_bitrate = max(0, total_bps - info.audio_bitrate)
            info.video_bitrate_estimated = info.video_bitrate > 0

    return info


def get_encoder_help(encoder: str) -> str:
    try:
        cp = run_command(
            [ffmpeg_exe(), "-hide_banner", "-h", f"encoder={encoder}"],
            timeout=30,
        )
        return (cp.stdout or "") + "\n" + (cp.stderr or "")
    except Exception:
        return ""


def parse_encoder_capabilities(encoder: str, help_text: str) -> EncoderCapabilities:
    options: set[str] = set()
    for line in help_text.splitlines():
        # FFmpeg encoder help 常见形式：
        #   -preset            <string>     E..V....... Encoding preset
        #   -bf                <int>        E..V....... ...
        match = re.match(r"^\s+-([A-Za-z0-9_-]+)(?:\s|$)", line)
        if match:
            options.add(match.group(1))
    return EncoderCapabilities(encoder=encoder, options=options, help_text=help_text)


def prepare_encoder_capabilities(encoder: str) -> EncoderCapabilities:
    """目标编码器选定后才调用一次 ffmpeg -h encoder=...。"""
    if encoder in ENCODER_CAPABILITIES:
        return ENCODER_CAPABILITIES[encoder]
    help_text = get_encoder_help(encoder)
    caps = parse_encoder_capabilities(encoder, help_text)
    ENCODER_CAPABILITIES[encoder] = caps
    return caps


def verify_encoder_available(encoder: str) -> tuple[bool, str]:
    """确认目标编码器真的能在这台机器上初始化，返回 (是否可用, 说明)。

    "FFmpeg 编进了这个编码器" 不等于 "这台机器能跑"：例如 Turing（RTX 20 系）的
    ffmpeg 会列出 av1_nvenc，但芯片里没有 AV1 编码单元（实测报
    "No capable devices found"），原版要走到批处理中途才整批失败。
    这里用 3 帧 lavfi 画面做一次真实初始化，代价约 0.3 秒。
    """
    if encoder not in AVAILABLE_ENCODERS:
        return False, f"当前 FFmpeg 的编码器列表里没有 {encoder}"

    try:
        cp = run_command(
            [
                ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30",
                "-frames:v", "3", "-c:v", encoder, "-f", "null", "-",
            ],
            timeout=120,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"试编码异常：{e}"

    if cp.returncode != 0:
        lines = [x.strip() for x in (cp.stderr or "").splitlines() if x.strip()]
        # ffmpeg 的最后一行往往只是 "Nothing was written into output file" 这类
        # 由输出封装器报的通用信息，真正的原因在提到该编码器的那一行里。
        picked = next(
            (x for x in lines if encoder.split("_")[0] in x.lower()), None
        )
        if picked is None:
            picked = lines[0] if lines else f"试编码返回码 {cp.returncode}"
        return False, picked

    return True, "编码器已通过 3 帧试编码"


def describe_encoder_capabilities(platform_key: str, codec_key: str) -> list[str]:
    encoder = encoder_name(platform_key, codec_key)
    caps = ENCODER_CAPABILITIES.get(encoder)
    if not caps:
        return ["未读取 encoder help，运行时将按失败自动回退。"]

    lines: list[str] = []
    if platform_key == "nvidia":
        if caps.has("tune") and caps.supports_value("tune", "uhq"):
            lines.append("Tune：UHQ（当前 FFmpeg/硬件支持）")
        elif caps.has("tune"):
            lines.append("Tune：HQ（UHQ 不可用，自动降级）")
        else:
            lines.append("Tune：不使用（encoder 不支持 tune）")
        lines.append(
            "Multipass：fullres" if caps.has("multipass") and caps.supports_value("multipass", "fullres")
            else "Multipass：自动省略（当前 encoder 不支持 fullres）"
        )
        if caps.has("b_ref_mode"):
            lines.append("B-ref：middle（当前 encoder 支持）")
        else:
            lines.append("B-ref：自动关闭（当前 encoder 不支持 b_ref_mode）")
    else:
        lines.append("Preset：veryslow（QSV TargetUsage=1，最慢但画质最好）")
        lines.append(f"GOP：按每个文件的帧率取 {GOP_SECONDS:g} 秒（整片实测：GOP 越长同画质越省，"
                     f"这里取画质与拖动定位的折中）")
        if codec_key == "av1":
            lines.append("AV1：无 -bf / -scenario / -rdo 等 HEVC 专属选项，参数集更小")
            lines.append("AV1 的质量模式依赖 ICQ 是否可用（见上方速率控制方式）")
        else:
            lines.append("上限模式会附加 -extbrc 1（实测同码率画质更稳，最差画面更好）")
        lines.append("不使用 look-ahead：质量模式下无效，上限模式下会崩（驱动缺陷）")
    return lines


# ============================================================
# 扫描
# ============================================================

def is_video_file(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in VIDEO_EXTENSIONS
        and TEMP_MARKER.lower() not in path.name.lower()
    )


def _run_log(line: str) -> None:
    """把一行追加到批次日志（终端被关掉/滚走也能事后查）。失败不抛异常。"""
    try:
        with open(Path.cwd() / RUN_LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except Exception:
        pass


def _log_result(result, tag: str = "") -> None:
    """单个文件的结果写进日志：成功写体积变化，失败写原因（最多 8 行）。"""
    stamp = time.strftime("%H:%M:%S")
    if result.status == "failed":
        _run_log(f"[{stamp}] [{result.index:03d}] 失败 {tag} {result.source}")
        for ln in (result.error or "").splitlines()[:8]:
            _run_log("            " + ln)
    else:
        o = getattr(result, "original_info", None)
        n = getattr(result, "output_info", None)
        extra = ""
        if o is not None and n is not None:
            try:
                pct = (1 - n.size / o.size) * 100 if o.size else 0.0
                extra = f"  {format_bytes(o.size)} -> {format_bytes(n.size)} ({-pct:+.1f}%)"
            except Exception:
                extra = ""
        el = getattr(result, "elapsed", 0) or 0
        _run_log(f"[{stamp}] [{result.index:03d}] 成功 {tag} {result.source}"
                 f" -> {result.output}{extra}  耗时 {format_duration(el)}")


_QUIZ_ANSWERS: dict[int, Any] = {}
_QUIZ_STEP = 1


def _ask(step: int, start_step: int, fn, *args, **kwargs):
    """问卷里的一个菜单。

    - 正常前进：照常提问并记住答案；
    - 按 b 返回后（step < start_step）：直接返回上次的答案，不再重复提问。

    因此"返回上一级"只重新问你要改的那一项，更早的选择保留。
    """
    global _QUIZ_STEP
    _QUIZ_STEP = step
    if step < start_step and step in _QUIZ_ANSWERS:
        return _QUIZ_ANSWERS[step]
    value = fn(*args, **kwargs)
    _QUIZ_ANSWERS[step] = value
    return value


ICQ_CAP_MODE = True             # 上限模式 = ICQ + 按需调 Q（False 则退回旧的 VBR 硬封）
ICQ_CAP_MAX_REFITS = 2           # 最多反解几次（每次 = 重压一遍全片）
ICQ_CAP_TOLERANCE = 1.02         # 实测码率超过天花板 ×1.02 才算超标
ICQ_SLOPE = {"hevc": 0.125, "av1": 0.140}   # ln(码率) 对 Q 的斜率（实测标定）


def measure_video_kbps(path: Path, duration: float = 0.0) -> float:
    """量成品里视频流的平均码率（kbps）；取不到 stream bit_rate 就用体积/时长。"""
    try:
        cp = run_command([ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=bit_rate",
                          "-show_entries", "format=duration,size",
                          "-of", "json", str(path)], timeout=60)
        data = json.loads(cp.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        br = safe_float(st.get("bit_rate"), 0.0)
        if br > 0:
            return br / 1000.0
        fmt = data.get("format") or {}
        dur = safe_float(fmt.get("duration"), 0.0) or duration
        size = safe_float(fmt.get("size"), 0.0) or (
            path.stat().st_size if path.exists() else 0)
        return (size * 8 / dur / 1000.0) if dur > 0 else 0.0
    except Exception:
        return 0.0


def refit_quality(quality: int, measured_kbps: float, cap_kbps: int, codec_key: str) -> int:
    """按 ln(码率) 对 Q 近似线性反解新 Q：Q2 = ceil(Q + ln(实测/天花板)/SLOPE)。

    ceil 是刻意的：宁可略低于天花板，也绝不超。夹在 1~51（QSV 的有效区间）。
    """
    import math
    slope = ICQ_SLOPE.get(codec_key, 0.125)
    if measured_kbps <= 0 or cap_kbps <= 0 or slope <= 0:
        return quality
    delta = math.log(measured_kbps / float(cap_kbps)) / slope
    return max(1, min(51, quality + max(1, int(math.ceil(delta)))))


def _encode_iterative(worker, base_args, plan, duration, cap_kbps, codec_key):
    """先按当前 Q 压一遍；实测码率超天花板就反解 Q 重压（最多 ICQ_CAP_MAX_REFITS 次）。"""
    result = worker(*base_args, plan)
    if not cap_kbps or result.status == "failed":
        return result
    for step in range(ICQ_CAP_MAX_REFITS):
        kbps = measure_video_kbps(result.output, duration)
        if kbps <= 0 or kbps <= cap_kbps * ICQ_CAP_TOLERANCE:
            break
        new_q = refit_quality(plan.quality, kbps, cap_kbps, codec_key)
        if new_q <= plan.quality:
            break
        _run_log("[%s] 超标重压：实测 %d kbps > 上限 %d kbps，Q %d → Q %d"
                 % (time.strftime("%H:%M:%S"), int(kbps), int(cap_kbps),
                    plan.quality, new_q))
        _notice = ("[超标重压] 实测 %d kbps 超过上限 %d kbps，Q %d → %d（重新压一遍）"
                   % (int(kbps), int(cap_kbps), plan.quality, new_q))
        print("   " + dim(_notice), flush=True)
        retry_plan = EncodePlan(mode=RC_MODE_QUALITY, quality=new_q)
        retry_plan.cap_kbps = cap_kbps
        retry_plan.predicted_kbps = plan.predicted_kbps
        res2 = worker(*base_args, retry_plan)
        if res2.status == "failed":
            _run_log("    （第 %d 次重压失败，保留上一版产物）" % (step + 1))
            break
        plan.quality = new_q          # 回写，让日志/汇总显示实际使用的 Q
        result = res2
    return result


def _safe_media_info(path: Path):
    """给并行调用用：失败时把异常当返回值带回来，不打断整批。"""
    try:
        return get_media_info(path)
    except Exception as e:  # noqa: BLE001
        return e


_FFMPEG_VERSION_CACHE: Optional[str] = None


def _ffmpeg_version_line() -> str:
    """取 ffmpeg 版本首行（带缓存），用于判断是不是 master 快照。"""
    global _FFMPEG_VERSION_CACHE
    if _FFMPEG_VERSION_CACHE is None:
        try:
            cp = run_command([ffmpeg_exe(), "-version"], timeout=10)
            _FFMPEG_VERSION_CACHE = (cp.stdout or "").splitlines()[0] if cp.stdout else ""
        except Exception:
            _FFMPEG_VERSION_CACHE = ""
    return _FFMPEG_VERSION_CACHE


def _is_master_snapshot() -> bool:
    """版本号形如 "ffmpeg version N-127054-g9d3f0f2c58-…" = master 快照。

    FFmpeg 的命名约定：master 快照用大写 N-<提交数>-g<hash>，
    发行分支用小写 n<版本>（如 n9.0.2-22-g46d8f462ee）。已知只有 master 快照
    会静默丢掉 -global_quality（ICQ 失效），所以只对它做试编码确认。
    """
    return bool(re.search(r"version\s+N-\d+-g", _ffmpeg_version_line()))


def scan_videos(root: Path, recursive: bool) -> list[Path]:
    videos: list[Path] = []

    if not recursive:
        for item in root.iterdir():
            if is_video_file(item):
                videos.append(item)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            # 排除所有名为 output 的目录，防止重复扫描生成物
            dirnames[:] = [
                d for d in dirnames
                if d.lower() != OUTPUT_DIR_NAME.lower()
            ]

            current = Path(dirpath)

            for filename in filenames:
                path = current / filename
                if is_video_file(path):
                    videos.append(path)

    videos.sort(key=lambda p: str(p).lower())
    return videos


def get_output_path(
    source: Path,
    root: Path,
    recursive: bool,
) -> Path:
    if not recursive:
        output_dir = root / OUTPUT_DIR_NAME
    else:
        # 每个源目录各自拥有 output，避免不同子目录中的同名文件互相覆盖
        output_dir = source.parent / OUTPUT_DIR_NAME

    output_dir.mkdir(parents=True, exist_ok=True)

    # 统一输出为 MP4。
    # 使用原 stem，方便归档后直观看到对应关系。
    return output_dir / f"{source.stem}.mp4"


def get_temp_path(source_or_output: Path) -> Path:
    # 保留完整原文件名（含扩展名），a.mkv 与 a.mp4 的临时文件不会重名。
    return source_or_output.with_name(
        source_or_output.name + TEMP_MARKER + "mp4"
    )


# ============================================================
# 输入 / 菜单
# ============================================================

def ask_choice(
    title: str,
    options: list[tuple],
    default: Optional[str] = None,
    default_label: Optional[str] = None,
) -> str:
    return ui_menu(title, options, default, default_label)



def ask_video_quality(platform_key: str, codec_key: str) -> int:
    platform = ENCODER_PROFILES[platform_key]
    encoder = encoder_name(platform_key, codec_key)
    qualities = quality_levels(platform_key, codec_key)
    knob = "global_quality" if EFFECTIVE_QUALITY_KNOB.get(platform_key) == "global_quality" else "q:v"

    ui_gap(3)
    print(color(ui_module_line(f"【6. 视频编码质量】{platform['name']} / {codec_key.upper()} / {encoder}"), "magenta", bold=True))
    print()

    default_value = default_quality(platform_key, codec_key)
    default_index = (qualities.index(default_value) + 1
                     if default_value in qualities else 1)
    default_value = qualities[default_index - 1]
    prefix = "Q" if platform_key == "intel" else "CQ"
    for idx, q in enumerate(qualities, 1):
        name = f"{prefix}{q}　{quality_label(platform_key, codec_key, q)}"
        print(ui_option(str(idx), name, is_default=(idx == default_index)))

    default_label = f"{prefix}{default_value} {quality_label(platform_key, codec_key, default_value)}"
    print()
    print(f"   {dim('（输入 b 可返回重选）')}")
    while True:
        value = input(color(ui_prompt(default_label), "yellow")).strip()
        if _is_back(value):
            raise BackRequested()
        if not value:
            return default_value
        if value.isdigit() and 1 <= int(value) <= len(qualities):
            return qualities[int(value) - 1]
        ui_warn(f"输入无效，请输入 1-{len(qualities)}。")


def format_cap(kbps: int) -> str:
    return f"{kbps / 1000:g} Mbps" if kbps >= 1000 else f"{kbps} kbps"


def bitrate_label() -> str:
    cap = VIDEO_BITRATE_CAP_KBPS
    if RC_MODE == RC_MODE_QUALITY or not cap:
        return "  |  质量优先（不限体积）"
    if RC_MODE == RC_MODE_AUTO:
        return f"  |  自动兜底 {format_cap(cap)}"
    return f"  |  上限 {format_cap(cap)}"


def cap_pair(cap_kbps: int) -> tuple[int, int]:
    """返回 (maxrate, bufsize)。"""
    maxrate = int(round(cap_kbps * BITRATE_PEAK_RATIO))
    bufsize = int(round(maxrate * BITRATE_BUFFER_SECONDS))
    return maxrate, bufsize


def parse_bitrate_input(text: str) -> Optional[int]:
    """解析自定义码率：'2.5' / '2.5m' = Mbps；'800k' = kbps。"""
    t = text.strip().lower().replace("bps", "").replace(" ", "")
    if not t:
        return None
    try:
        if t.endswith("k"):
            kbps = float(t[:-1])
        elif t.endswith("m"):
            kbps = float(t[:-1]) * 1000
        else:
            kbps = float(t) * 1000
    except ValueError:
        return None
    kbps_int = int(round(kbps))
    return kbps_int if 100 <= kbps_int <= 100000 else None


def ask_video_bitrate_cap() -> Optional[int]:
    ui_gap(3)
    print(color(ui_module_line("【7. 视频码率上限】"), "magenta", bold=True))
    print()
    ui_hint("画质由质量档位主导，码率上限只做天花板：")
    ui_hint("没超的素材按质量档位自然偏低，超了的被压到上限以内。")
    print()

    presets = VIDEO_BITRATE_CAP_PRESETS
    rows = [
        ("1", "不限制", "仅质量档位"),
        ("2", "1.0 Mbps", ""),
        ("3", "1.5 Mbps", ""),
        ("4", "2.0 Mbps", ""),
        ("5", "3.0 Mbps", ""),
    ]
    for key, text, desc in rows:
        print(ui_option(key, text, desc, is_default=(text == "1.5 Mbps")))
    print(f"   {color('[6]', 'cyan')} {color('自定义', 'white')}   "
          f"{dim('如 2.5 或 2.5m = Mbps；800k = kbps')}")
    print()
    print(f"   {dim('（输入 b 可返回重选）')}")

    default_index = presets.index(DEFAULT_VIDEO_BITRATE_CAP) + 1
    while True:
        value = input(color(ui_prompt("1.5 Mbps"), "yellow")).strip()
        if _is_back(value):
            raise BackRequested()
        if not value:
            return presets[default_index - 1]
        if value.isdigit() and 1 <= int(value) <= len(presets):
            return presets[int(value) - 1]
        if value == "6":
            while True:
                custom = input(color("请输入目标码率（b 返回）：", "yellow")).strip()
                if _is_back(custom):
                    raise BackRequested()
                parsed = parse_bitrate_input(custom)
                if parsed is not None:
                    return parsed
                ui_warn("输入无效，范围 100 kbps ~ 100 Mbps。")
        ui_warn("输入无效，请输入 1-6。")


def ask_audio_quality() -> int:
    ui_gap(3)
    print(color(ui_module_line("【8. 音频编码质量】"), "magenta", bold=True))
    print()
    ui_hint("数字越靠前 = 音质越高；数字越靠后 = 文件越小。")
    ui_hint("编码器：Opus VBR / compression_level 10 / frame_duration 60 ms")
    print()

    labels = {
        96: "高质量",
        64: "推荐",
        48: "均衡",
        40: "高压缩 / 极限省空间",
    }
    bitrates = sorted(AUDIO_BITRATES, reverse=True)
    for idx, bitrate in enumerate(bitrates, 1):
        print(ui_option(str(idx), f"{bitrate}k", labels.get(bitrate, ""),
                        is_default=(bitrate == DEFAULT_AUDIO_BITRATE)))
    print()
    print(f"   {dim('（输入 b 可返回重选）')}")

    while True:
        value = input(color(ui_prompt(f"{DEFAULT_AUDIO_BITRATE}k"), "yellow")).strip()
        if _is_back(value):
            raise BackRequested()
        if not value:
            return DEFAULT_AUDIO_BITRATE
        if value.isdigit() and 1 <= int(value) <= len(bitrates):
            return bitrates[int(value) - 1]
        ui_warn(f"输入无效，请输入 1-{len(bitrates)}。")


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"

    while True:
        value = input(color(f"{prompt} {suffix}：", "yellow")).strip().lower()

        if _is_back(value):
            raise BackRequested()

        if not value:
            return default

        if value in ("y", "yes", "1", "是"):
            return True

        if value in ("n", "no", "0", "否"):
            return False

        print("请输入 Y 或 N。")


# ============================================================
# 显示媒体信息
# ============================================================

def print_media_info(info: MediaInfo, prefix: str = "") -> None:
    print(f"{prefix}文件：{info.path.name}")
    print(f"{prefix}大小：{format_bytes(info.size)}")
    print(f"{prefix}时长：{format_duration(info.duration)}")
    print(f"{prefix}视频：{info.video_codec} "
          f"{info.width}x{info.height} "
          f"{info.fps:.3f} fps "
          f"{video_bitrate_text(info)}")
    print(f"{prefix}像素格式：{info.pix_fmt or 'N/A'}")

    if info.audio_codec != "none":
        channels = info.channels or 2
        layout = info.channel_layout or f"{channels}ch"
        print(f"{prefix}音频：{info.audio_codec} "
              f"{format_bitrate(info.audio_bitrate)} "
              f"{info.sample_rate or 'N/A'} Hz "
              f"{layout}")
    else:
        print(f"{prefix}音频：无")


# ============================================================
# 音频参数
# ============================================================

def output_audio_channels(info: MediaInfo) -> int:
    """
    用户要求：
    mono -> mono
    stereo -> stereo
    >2ch -> stereo

    缺失 / 非法 channels 时安全默认 stereo。
    """
    try:
        channels = int(info.channels or 2)
    except (TypeError, ValueError):
        channels = 2

    if channels <= 1:
        return 1

    if channels == 2:
        return 2

    return 2


# ============================================================
# 编码计划 / 能力实测
# ============================================================

# 通用 AVCodecContext 选项：它们不会出现在 `ffmpeg -h encoder=...` 的私有选项表里，
# 旧版用 caps.has() 判断，导致 -global_quality / -bf / -g 永远不下发。
GENERIC_VIDEO_OPTIONS = {"g", "bf", "q:v", "global_quality"}

# 质量控件候选。哪个真正生效由 detect_quality_knob() 在本机实测决定：
# 本机（Arc A380 / 32.0.101.9033 / ffmpeg git-2026-09-26）实测 -q:v 生效，
# -global_quality 无论给 30 还是 45 还是 30*118 都与"不给"逐字节相同（完全无效）。
QUALITY_KNOBS = {
    "intel": ["q:v", "global_quality"],
    "nvidia": ["cq"],
}

EFFECTIVE_QUALITY_KNOB: dict[str, Optional[str]] = {}
DECODE_TIER: dict[str, int] = {}
QUALITY_KNOB_NOTE: dict[str, str] = {}


@dataclass
class EncodePlan:
    """单个视频的编码计划（自动模式下每个文件可能不同）。"""

    mode: str = RC_MODE_QUALITY
    quality: int = 32
    cap_kbps: Optional[int] = None
    predicted_kbps: Optional[int] = None
    note: str = ""

    @property
    def is_capped(self) -> bool:
        return self.mode == RC_MODE_CAPPED and bool(self.cap_kbps)


def plan_label(plan: EncodePlan) -> str:
    if plan.is_capped:
        return f"上限 {format_cap(plan.cap_kbps or 0)}"
    return "质量优先"


def predicted_size_text(plan: EncodePlan, duration: float) -> str:
    kbps = plan.predicted_kbps
    if not kbps or duration <= 0:
        return ""
    return format_bytes(kbps * 1000 / 8 * duration)


def quality_option_args(
    platform_key: str,
    quality: int,
    disabled_features: Optional[set[str]] = None,
) -> list[str]:
    """把质量值翻译成当前平台实测生效的参数。

    注意：ICQ 必须写成 **-global_quality:v**（限定视频流）。
    实测（ffmpeg 2025-04-23）：不限定作用域时 -global_quality 会同时作用到
    音频流，libopus 直接报 "Quality-based encoding not supported" 并以 -22 退出，
    整片编码失败；加上 :v 后视频仍是 ICQ，音频正常。
    """
    disabled_features = disabled_features or set()
    if platform_key == "nvidia":
        return ["-cq", str(quality)]
    knob = EFFECTIVE_QUALITY_KNOB.get(platform_key)
    if knob is None:
        knob = QUALITY_KNOBS["intel"][0]
    if platform_key == "intel" and "global_quality" not in (disabled_features or set()):
        # v16：Intel 一律走 ICQ（-global_quality:v）。
        # 实测：-q:v 在 av1_qsv 上是 0~255 的 AV1 QP，给 30 约等于无损
        # （4543 kbps vs ICQ 1069 kbps，4 倍膨胀）；hevc_qsv 上 -q:v 是 CQP，
        # 同画质也不如 ICQ（Q30：CQP 631k/VMAF 75.1，ICQ 1124k/VMAF 81.1）。
        return ["-global_quality:v", str(quality)]
    if knob == "global_quality":
        return ["-global_quality:v", str(quality)]
    return ["-q:v", str(quality)]


def _probe_encode_size(
    source: Path,
    decode_args: list[str],
    encoder: str,
    quality_args: list[str],
    seconds: float = 1.0,
) -> Optional[int]:
    """试编码一小段，返回输出字节数；失败返回 None。"""
    out = Path(tempfile.gettempdir()) / f"dsh_probe_{os.getpid()}.mp4"
    try:
        if out.exists():
            out.unlink()
        cmd = (
            [ffmpeg_exe(), "-hide_banner", "-y", "-loglevel", "error"]
            + decode_args
            + ["-ss", "1", "-t", str(seconds), "-i", str(source),
               "-map", "0:v:0", "-c:v", encoder, "-an", str(out)]
        )
        cmd = cmd[: cmd.index("-map")] + quality_args + cmd[cmd.index("-map"):]
        cp = run_command(cmd, timeout=120)
        if cp.returncode != 0 or not out.exists():
            return None
        return out.stat().st_size
    except Exception:
        return None
    finally:
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass


def detect_decode_tier(platform_key: str, source: Path, encoder: str) -> int:
    """实测解码回退链，返回可用层级索引（0 最优）。

    实测背景：QSV 解码设备可能整体不可用（Error creating a MFX session: -9），
    而 d3d11va 仍然可用且速度几乎相同。旧版只有"硬解/CPU"两级。
    """
    chain = ENCODER_PROFILES[platform_key]["decode_chain"]
    for idx, (label, args) in enumerate(chain):
        if _probe_encode_size(source, args, encoder, [], seconds=0.4) is not None:
            DECODE_TIER[platform_key] = idx
            return idx
    DECODE_TIER[platform_key] = len(chain) - 1
    return len(chain) - 1


def decode_args_for(platform_key: str) -> list[str]:
    chain = ENCODER_PROFILES[platform_key]["decode_chain"]
    idx = min(DECODE_TIER.get(platform_key, 0), len(chain) - 1)
    return chain[idx][1]


def decode_label_for(platform_key: str) -> str:
    chain = ENCODER_PROFILES[platform_key]["decode_chain"]
    idx = min(DECODE_TIER.get(platform_key, 0), len(chain) - 1)
    return chain[idx][0]


def probe_rate_control_method(
    encoder: str,
    extra_args: list[str],
    exe: Optional[str] = None,
    sample: Optional[Path] = None,
) -> Optional[str]:
    """读 ffmpeg verbose 日志里的 RateControlMethod（CQP / ICQ / VBR / CBR / QVBR）。

    这是判断"质量参数到底有没有生效"最可靠的方法：ffmpeg 会把真正下发给
    驱动的 TargetUsage 与 RateControlMethod 打出来。
    """
    exe = exe or ffmpeg_exe()
    src = sample
    if src is None:
        return None
    args = [exe, "-hide_banner", "-v", "verbose", "-y", "-t", "1",
            "-i", str(src), "-map", "0:v:0", "-c:v", encoder] + extra_args + \
           ["-an", str(Path(tempfile.gettempdir()) / f"dsh_rcm_{os.getpid()}.mp4")]
    try:
        cp = run_command(args, timeout=180)
    except Exception:
        return None
    # 注意：ffmpeg 的日志走 stderr，这里必须两边都找
    text = (cp.stderr or "") + "\n" + (cp.stdout or "")
    m = re.search(r"TargetUsage:\s*\d+;\s*RateControlMethod:\s*(\w+)", text)
    if m:
        return m.group(1).upper()
    m = re.search(r"RateControlMethod:\s*(\w+)", text)
    return m.group(1).upper() if m else None


def _sample_for_probe(source: Path) -> Path:
    """质量/速率探测用的样本：直接编一小段源文件即可。"""
    return source

def detect_quality_knob(
    platform_key: str,
    codec_key: str,
    source: Path,
    info: MediaInfo,
    audio_quality: int = 48,
) -> Optional[str]:
    """实测哪个质量参数真正生效，并尽量优先使用 ICQ（官方推荐、同画质更省码率）。

    判据顺序：
      1. 读 verbose 日志里的 RateControlMethod，能拿到 ICQ 就用它；
      2. 拿不到就退回"输出大小是否明显变化"的启发式；
      3. 全都不行则报警告。
    """
    encoder = encoder_name(platform_key, codec_key)
    if platform_key == "nvidia":
        EFFECTIVE_QUALITY_KNOB[platform_key] = QUALITY_KNOBS["nvidia"][0]
        QUALITY_KNOB_NOTE[platform_key] = "NVENC CQ（-cq N）"
        QUALITY_MODE_LABEL[platform_key] = "CQ"
        return EFFECTIVE_QUALITY_KNOB[platform_key]

    levels = quality_levels(platform_key, codec_key)
    test_quality = max(levels)
    decode_args = decode_args_for(platform_key)

    # ---- 1. 先用 verbose 日志判定速率控制方式 ----
    rcm_default = probe_rate_control_method(encoder, [], sample=source)
    rcm_gq = probe_rate_control_method(encoder, ["-global_quality:v", str(test_quality)], sample=source)
    rcm_qv = probe_rate_control_method(encoder, ["-q:v", str(test_quality)], sample=source)
    rcm_info = f"默认={rcm_default or '?'} -global_quality={rcm_gq or '?'} -q:v={rcm_qv or '?'}"

    if rcm_gq == "ICQ":
        EFFECTIVE_QUALITY_KNOB[platform_key] = "global_quality"
        QUALITY_MODE_LABEL[platform_key] = "ICQ"
        QUALITY_KNOB_NOTE[platform_key] = f"-global_quality 生效，速率控制 = ICQ（好于 CQP）"
        return EFFECTIVE_QUALITY_KNOB[platform_key]

    # ---- 2. 退回"输出大小是否变化"的启发式 ----
    baseline = _probe_encode_size(source, decode_args, encoder, [])
    if baseline is not None:
        for knob in QUALITY_KNOBS["intel"]:
            size = _probe_encode_size(source, decode_args, encoder, [f"-{knob}", str(test_quality)])
            if size is not None and baseline > 0 and abs(size - baseline) / baseline > 0.05:
                EFFECTIVE_QUALITY_KNOB[platform_key] = knob
                label = "ICQ" if (knob == "global_quality" and rcm_gq == "ICQ") else (
                    rcm_qv or "CQP" if knob == "q:v" else "ICQ")
                QUALITY_MODE_LABEL[platform_key] = label
                QUALITY_KNOB_NOTE[platform_key] = (
                    f"-{knob} 生效（速率控制 = {label}；{rcm_info}）"
                )
                return knob

    # ---- 3. 都不行 ----
    EFFECTIVE_QUALITY_KNOB[platform_key] = QUALITY_KNOBS["intel"][0]
    QUALITY_MODE_LABEL[platform_key] = rcm_qv or "CQP"
    QUALITY_KNOB_NOTE[platform_key] = (
        f"警告：质量参数实测都不生效（{rcm_info}），"
        f"建议改用上限模式或换一个支持 ICQ 的 ffmpeg"
    )
    return EFFECTIVE_QUALITY_KNOB[platform_key]



def _probe_encode_segment(
    source: Path,
    decode_args: list[str],
    encoder: str,
    quality_args: list[str],
    start: float,
    seconds: float,
) -> Optional[int]:
    out = Path(tempfile.gettempdir()) / f"dsh_probe_seg_{os.getpid()}.mp4"
    try:
        if out.exists():
            out.unlink()
        cmd = (
            [ffmpeg_exe(), "-hide_banner", "-y", "-loglevel", "error"]
            + decode_args
            + ["-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(source),
               "-map", "0:v:0", "-c:v", encoder, "-an", str(out)]
        )
        cmd = cmd[: cmd.index("-map")] + quality_args + cmd[cmd.index("-map"):]
        cp = run_command(cmd, timeout=300)
        if cp.returncode != 0 or not out.exists() or out.stat().st_size < 1024:
            return None
        return out.stat().st_size
    except Exception:
        return None
    finally:
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass




def cleanup_stale_temps(directories: list[Path], max_age_seconds: float = 3600.0) -> int:
    """清理上次异常中断留下的 *.temp.* 文件。返回清理数量。

    只清理超过 max_age_seconds 的旧文件，避免误删另一个正在运行的实例的临时文件。
    """
    removed = 0
    seen: set[str] = set()
    now = time.time()
    for directory in directories:
        try:
            if not directory.exists():
                continue
            for item in directory.iterdir():
                if not item.is_file():
                    continue
                name = item.name.lower()
                key = str(item).lower()
                if TEMP_MARKER.lower() not in name or key in seen:
                    continue
                seen.add(key)
                try:
                    if now - item.stat().st_mtime < max_age_seconds:
                        continue
                    item.unlink()
                    removed += 1
                except Exception:
                    pass
        except Exception:
            continue
    return removed


# ============================================================
# FFmpeg 命令
# ============================================================

def build_ffmpeg_command(
    source: Path,
    output: Path,
    info: MediaInfo,
    platform_key: str,
    codec_key: str,
    video_quality: int,
    audio_quality: int,
    decode_args: list[str],
    plan: Optional[EncodePlan] = None,
    disabled_features: Optional[set[str]] = None,
    video_only: bool = False,
) -> list[str]:
    """生成 ffmpeg 命令行。

    参数设计原则（均为本机实测结论）：
      * 质量模式 = 质量值主导，不设任何码率参数。实测 -q:v 生效，
        -global_quality 在本驱动上完全无效（由 detect_quality_knob 实测决定用哪个）。
      * 上限模式 = 平均码率 + 峰值天花板 + extbrc。实测 extbrc 让最差画面
        VMAF 从 53.6 提升到 64.2（同码率），因此上限模式必须带它。
      * 不使用 -look_ahead_depth：质量模式下它是空操作，上限模式下与 -b:v
        组合在本驱动会直接崩（Invalid FrameType:0.）或挂死。
      * -g 用 10 秒：实测比默认 GOP 省约 9% 码率，画质几乎不变。
    """
    disabled_features = disabled_features or set()
    plan = plan or EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality)
    platform = ENCODER_PROFILES[platform_key]
    encoder = encoder_name(platform_key, codec_key)
    caps = ENCODER_CAPABILITIES.get(encoder, EncoderCapabilities(encoder))
    audio_bitrate = AUDIO_BITRATES[audio_quality]
    gop = calculate_gop(info.fps)

    args = [ffmpeg_exe(), "-hide_banner", "-y", "-loglevel", "warning"]
    args += decode_args
    args += [
        "-i", str(source),
        "-map", "0:v:0",
    ]
    if not video_only:
        # 预检时只映射视频：避免"音频被编码两次"的观感，也省一点时间
        args += ["-map", "0:a?"]
    args += [
        "-map_chapters", "0",
        "-c:v", encoder,
    ]

    def add_if_supported(
        option: str,
        *values: str,
        feature: Optional[str] = None,
        generic: bool = False,
    ) -> None:
        if feature and feature in disabled_features:
            return
        if generic or option in GENERIC_VIDEO_OPTIONS or caps.has(option):
            args.extend([f"-{option}", *values])

    if platform_key == "intel":
        settings = dict(platform["settings"])
        # v5：QSV 标定选中的参数叠加在默认值之上（原来这里直接引用模块级 dict，
        # 一旦被就地修改会污染全局，改成拷贝）
        if QSV_CALIBRATED:
            settings.update(QSV_CALIBRATED)
        add_if_supported("preset", settings["preset"])

        if plan.is_capped and not ICQ_CAP_MODE:
            # 旧路径：VBR 硬封（只用于需要"封峰值带宽"的场合）
            maxrate, bufsize = cap_pair(int(plan.cap_kbps or 0))
            args += [
                "-b:v", f"{plan.cap_kbps}k",
                "-maxrate", f"{maxrate}k",
                "-bufsize", f"{bufsize}k",
            ]
            add_if_supported("extbrc", str(settings["extbrc"]), feature="extbrc")
        else:
            # v16：上限模式也走纯 ICQ（命令里不留任何码率参数），
            # 超标由 _encode_iterative 反解 Q 解决。
            args += quality_option_args(platform_key, plan.quality or video_quality, disabled_features)

        add_if_supported("g", str(gop), generic=True)

        if codec_key == "hevc" and info.is_10bit and caps.has("profile"):
            args += ["-profile:v", "main10"]

        args += ["-tag:v", "av01" if codec_key == "av1" else "hvc1"]

    else:
        settings = dict(platform["settings"])
        # v3：标定选中的参数叠加在世代默认值之上
        if NVENC_CALIBRATED:
            settings.update(NVENC_CALIBRATED)
        add_if_supported("preset", settings["preset"])

        # 实测：-tune uhq 比 hq 慢 2.3 倍（0.607x vs 1.38x），同码率下 VMAF
        # 反而更低（53.85 vs 54.90）。默认固定 hq；想试 uhq 改 settings["tune"]。
        tune = str(settings.get("tune") or "hq")
        if tune == "uhq" and ("tune_uhq" in disabled_features
                              or not caps.supports_value("tune", "uhq")):
            tune = "hq"
        if "tune" not in disabled_features:
            add_if_supported("tune", tune, feature="tune")

        add_if_supported("rc", settings["rc"])
        add_if_supported("cq", str(video_quality))
        # NVENC：CQ 模式下平均码率必须为 0，天花板只由 maxrate 表达
        # （nvenc.c 会把 avg bitrate/VBV 清零，只保留 maxBitRate，CQ 目标不受影响）。
        args += ["-b:v", "0"]
        if plan.is_capped and plan.cap_kbps:
            maxrate, bufsize = cap_pair(int(plan.cap_kbps))
            args += ["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"]

        # 多引擎卡（RTX 5090=3 / 5080=2 / 5070Ti=2 / 4080=2…）：
        # SFE 把一个画面拆给多个 NVENC，单个任务就能吃满全部引擎。
        # 单引擎卡上这个参数无效，所以只在标定选中时才下发。
        if settings.get("split_encode_mode") and caps.has("split_encode_mode"):
            add_if_supported("split_encode_mode", str(settings["split_encode_mode"]),
                             feature="split_encode")

        # 实测：fullres 比不开 multipass 还慢 11%，VMAF 无变化（54.89 vs 54.90）；
        # qres 反而 +0.30 VMAF（55.20）且几乎不花时间。默认 qres。
        multipass_mode = str(settings.get("multipass") or "")
        if (
            multipass_mode
            and multipass_mode not in ("off", "none", "0")
            and "multipass" not in disabled_features
            and caps.has("multipass")
            and caps.supports_value("multipass", multipass_mode)
        ):
            args += ["-multipass", multipass_mode]

        add_if_supported("rc-lookahead", str(settings["lookahead"]), feature="lookahead")
        # 实测 AQ 是负收益：固定 1.8 Mbps 下 spatial+temporal AQ 让 VMAF 从
        # 54.90 掉到 51.09（p7），p4 上从 53.60 掉到 49.90。默认关闭。
        if settings.get("spatial_aq"):
            add_if_supported("spatial-aq", "1", feature="spatial_aq")
        if settings.get("temporal_aq"):
            add_if_supported("temporal-aq", "1", feature="temporal_aq")
        if settings.get("spatial_aq") or settings.get("temporal_aq"):
            add_if_supported("aq-strength", str(settings["aq_strength"]), feature="aq_strength")
        add_if_supported("bf", str(settings["bf"]), feature="bf", generic=True)
        add_if_supported("g", str(gop), generic=True)

        if "b_ref" not in disabled_features and caps.has("b_ref_mode") and caps.supports_value("b_ref_mode", "middle"):
            args += ["-b_ref_mode", settings["b_ref_mode"]]

        if info.is_10bit and caps.has("profile"):
            args += ["-profile:v", "main10", "-pix_fmt", "p010le"]

        args += ["-tag:v", "hvc1" if codec_key == "hevc" else "av01"]

    if info.audio_codec != "none" and not video_only:
        source_audio_kbps = int(info.audio_bitrate / 1000) if info.audio_bitrate else 0
        if (
            info.audio_codec.lower() == "opus"
            and 0 < source_audio_kbps <= int(audio_quality * AUDIO_COPY_TOLERANCE)
        ):
            # 已经是 Opus 且码率不高：直接复制，避免二次有损
            args += ["-c:a", "copy"]
        else:
            # 注意：这些音频参数必须加 :a 作用域。
            # -compression_level 同时是 hevc_qsv/av1_qsv 的私有选项（等于 TargetUsage），
            # 不限定作用域时会污染视频编码器：实测 -preset veryslow 被改成 7（veryfast），
            # 同画质码率反而更高，并打印 "Invalid compression level: valid range is 0-7"。
            args += [
                "-c:a", "libopus",
                "-b:a", audio_bitrate,
                "-vbr:a", "on",
                "-compression_level:a", "10",
                "-frame_duration:a", "60",
                "-application:a", "audio",
                "-ac", str(output_audio_channels(info)),
            ]

    args += [
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(output),
    ]
    return args


# ============================================================
# FFmpeg 进度解析
# ============================================================

def parse_time_to_seconds(value: str) -> float:
    # FFmpeg -progress 的 out_time 通常是 HH:MM:SS.microseconds
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return 0.0


def stop_process(process: subprocess.Popen, grace: float = 5.0) -> None:
    """尽量让 ffmpeg 自己退出。

    硬杀（kill）一个正在使用 QSV 的 ffmpeg 会让驱动里的 MFX 会话泄漏，
    之后所有 -hwaccel qsv 都会失败（Error creating a MFX session: -9），
    必须先 terminate 给它清理会话的机会，超时才 kill。
    """
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=grace)
            return
        except Exception:
            pass
        process.kill()
        try:
            process.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass


def update_task_state(index: int, **kwargs: Any) -> None:
    with STATE_LOCK:
        state = TASK_STATES.get(index)
        if not state:
            return

        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)


def run_ffmpeg(
    index: int,
    source: Path,
    output: Path,
    info: MediaInfo,
    platform_key: str,
    codec_key: str,
    video_quality: int,
    audio_quality: int,
    plan: Optional[EncodePlan] = None,
    disabled_features: Optional[set[str]] = None,
    retried_for_cap: bool = False,
) -> tuple[bool, float, str]:
    """按解码回退链编码。

    三类失败要分清楚（这是旧版最大的坑）：
      1. 参数不被支持  → 精准关掉那一个可选参数重试；
      2. 解码设备不可用 → 换下一个解码层级（QSV → D3D11VA → CPU）；
      3. 编码器侧错误   → 直接失败。换解码路径毫无意义，只会把一次快速报错
        变成"CPU 解码 0.x 倍速"的长期挂死。
    """
    start = time.monotonic()
    platform_name = ENCODER_PROFILES[platform_key]["name"]
    encoder = encoder_name(platform_key, codec_key)
    chain = ENCODER_PROFILES[platform_key]["decode_chain"]

    # 只对“可选优化”做降级，不对核心编码器/目标 codec 做静默改变。
    fallback_features = [
        "b_ref",
        "multipass",
        "temporal_aq",
        "spatial_aq",
        "aq_strength",
        "lookahead",
        "bf",
        "tune",
    ] if platform_key == "nvidia" else [
        "extbrc",
    ]

    disabled: set[str] = set()
    decode_index = min(DECODE_TIER.get(platform_key, 0), len(chain) - 1)
    attempt = 0
    max_attempts = 4

    while decode_index < len(chain) and attempt < max_attempts:
        attempt += 1
        decode_label, decode_args = chain[decode_index]

        if output.exists():
            try:
                output.unlink()
            except Exception:
                pass

        cmd = build_ffmpeg_command(
            source=source,
            output=output,
            info=info,
            platform_key=platform_key,
            codec_key=codec_key,
            video_quality=video_quality,
            audio_quality=audio_quality,
            decode_args=decode_args,
            plan=plan,
            disabled_features=disabled,
        )

        decode_text = f"{decode_label} + {encoder}"
        if plan is not None:
            decode_text += f" | {plan_label(plan)}"
        if disabled:
            decode_text += " | 已降级：" + ", ".join(sorted(disabled))

        update_task_state(index, status="encoding", start_time=time.time(), message=decode_text)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            return False, time.monotonic() - start, f"无法启动 FFmpeg：{e}"

        stderr_lines: list[str] = []

        def read_stderr() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    if len(stderr_lines) > 120:
                        del stderr_lines[:-120]

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        # stdout（-progress 输出）放到独立线程里读取，主循环用带超时的队列等待。
        # 这样即使 FFmpeg 卡死、完全不输出，也能按 PROGRESS_TIMEOUT 判定并终止；
        # Ctrl+C 也能在 1 秒内被响应。
        stdout_queue: "queue.Queue[Optional[str]]" = queue.Queue()

        def read_stdout() -> None:
            try:
                if process.stdout is not None:
                    for raw_line in process.stdout:
                        stdout_queue.put(raw_line)
            except Exception:
                pass
            finally:
                stdout_queue.put(None)

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stdout_thread.start()

        try:
            last_out_time = -1.0
            last_advance = time.monotonic()
            warned_stall = False
            while True:
                if STOP_REQUESTED:
                    stop_process(process)
                    return False, time.monotonic() - start, "用户中断。"

                try:
                    raw = stdout_queue.get(timeout=1.0)
                except queue.Empty:
                    # 没有新进度行：先看进程是否已退出（EOF 信号只发一次，
                    # 不能只依赖 raw is None 判断结束）
                    if process.poll() is not None:
                        break
                    stalled = time.monotonic() - last_advance
                    if stalled > PROGRESS_TIMEOUT:
                        stop_process(process, grace=10.0)
                        return (
                            False,
                            time.monotonic() - start,
                            f"FFmpeg 已 {int(stalled)} 秒没有任何编码进度（out_time 不前进），"
                            f"判定为卡死并终止。多半是参数/驱动组合问题。",
                        )
                    if stalled > PROGRESS_TIMEOUT * 0.4 and not warned_stall:
                        warned_stall = True
                        update_task_state(
                            index,
                            message=f"{decode_text} | 警告：进度停滞 {int(stalled)} 秒",
                        )
                    continue

                if raw is None:
                    # stdout 已关闭 = ffmpeg 已经输出完毕，通常紧接着退出。
                    # 这里显式等它退出，避免"编码早就完成却一直挂着"。
                    try:
                        process.wait(timeout=10)
                        break
                    except subprocess.TimeoutExpired:
                        stalled = time.monotonic() - last_advance
                        if stalled > PROGRESS_TIMEOUT:
                            stop_process(process, grace=10.0)
                            return (
                                False,
                                time.monotonic() - start,
                                f"FFmpeg 输出已结束但进程 {int(stalled)} 秒没有退出，已终止。",
                            )
                        continue

                line = raw.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key == "out_time":
                        out_time = parse_time_to_seconds(value)
                        if out_time > last_out_time + 0.001:
                            last_out_time = out_time
                            last_advance = time.monotonic()
                        duration = info.duration
                        percent = (out_time / duration * 100) if duration > 0 else 0
                        update_task_state(index, out_time=out_time, percent=percent)
                    elif key == "speed":
                        try:
                            update_task_state(index, speed=float(value.rstrip("x")))
                        except Exception:
                            pass
                    elif key == "fps":
                        try:
                            update_task_state(index, fps=float(value))
                        except Exception:
                            pass
                    elif key == "total_size":
                        try:
                            update_task_state(index, output_size=int(value))
                        except Exception:
                            pass

            return_code = process.wait(timeout=30)
            stderr_thread.join(timeout=2)
            elapsed = time.monotonic() - start

            if return_code == 0:
                # ---- 上限兜底 ----
                # 逐文件计划是"瞬间估算"出来的（不解码、不采样）。万一估算偏了，
                # 质量模式的成品真的超过上限，就在这里用上限模式重编一次该文件。
                # 只有少数被估错的文件会多花一次编码时间，正常文件不受影响。
                if (
                    plan is not None
                    and not plan.is_capped
                    and VIDEO_BITRATE_CAP_KBPS
                    and not retried_for_cap
                ):
                    measured = None
                    try:
                        probe_info = get_media_info(output)
                        measured = probe_info.video_bitrate
                    except Exception:
                        probe_info = None
                    if measured and measured / 1000 > VIDEO_BITRATE_CAP_KBPS * 1.05:
                        retried_for_cap = True
                        update_task_state(
                            index,
                            message=(f"实测 {int(measured / 1000)} kbps 超过上限，"
                                     f"正在按上限 {VIDEO_BITRATE_CAP_KBPS} kbps 重编……"),
                        )
                        capped_plan = EncodePlan(
                            mode=RC_MODE_CAPPED,
                            quality=plan.quality,
                            cap_kbps=VIDEO_BITRATE_CAP_KBPS,
                        )
                        retry_ok, retry_elapsed, retry_error = run_ffmpeg(
                            index=index,
                            source=source,
                            output=output,
                            info=info,
                            platform_key=platform_key,
                            codec_key=codec_key,
                            video_quality=video_quality,
                            audio_quality=audio_quality,
                            plan=capped_plan,
                            disabled_features=disabled,
                            retried_for_cap=True,
                        )
                        return retry_ok, elapsed + retry_elapsed, retry_error
                return True, elapsed, ""

            error_text = "\n".join(stderr_lines[-30:])
            lowered = error_text.lower()

            # 明确属于“高级可选参数不被当前 FFmpeg/驱动接受”的错误才自动降级。
            # 普通输入损坏、磁盘不足、驱动崩溃等硬错误不会被吞掉。
            unsupported_markers = (
                "option .* not found",
                "unrecognized option",
                "invalid argument",
                "error setting option",
                "value out of range",
                "undefined constant",
                "not supported",
                "cannot set",
            )
            looks_like_option_error = any(
                re.search(marker, lowered) for marker in unsupported_markers
            )

            # 上面的 “Invalid FrameType:0.” 这类错误来自编码器本身，而不是解码器。
            # 换解码路径不会改变编码器参数，所以不能靠“回退 CPU 解码”来重试：
            # 那只会把一次快速报错变成永久的 ≈0x 挂起。
            qsv_frame_type_bug = "invalid frametype" in lowered
            encoder_side_error = qsv_frame_type_bug or any(
                marker in lowered for marker in (
                    "error submitting video frame",
                    "error encoding a frame",
                )
            )

            # 解码设备不可用：这才是唯一值得换解码层级的情况。
            decode_side_error = any(
                marker in lowered for marker in (
                    "no device available for decoder",
                    "hardware device setup failed",
                    "error creating a mfx session",
                    "device creation failed",
                    "failed to initialise",
                    "no capable devices found",
                    "cannot load nvcuda",
                    "impossible to convert between the formats",
                )
            )
            # 零拷贝格式不匹配：编码器不接受硬件帧，换成系统内存帧能解决。
            surface_format_error = (
                not qsv_frame_type_bug
                and "error submitting video frame" in lowered
                and "-hwaccel_output_format" in decode_args
            )

            if looks_like_option_error or encoder_side_error:
                # 优先根据 FFmpeg 报错中出现的 option 名称精准降级；
                # 无法定位时不要盲目关闭一串参数，避免把真正的输入/驱动错误吞掉。
                feature_aliases = {
                    "b_ref": ("b_ref_mode", "b-ref", "b ref"),
                    "multipass": ("multipass", "fullres"),
                    "temporal_aq": ("temporal-aq", "temporal aq"),
                    "spatial_aq": ("spatial-aq", "spatial aq"),
                    "aq_strength": ("aq-strength", "aq strength"),
                    "lookahead": ("rc-lookahead", "look_ahead_depth", "lookahead"),
                    "bf": ("-bf", "bframes", "b-frames"),
                    "tune": ("-tune", "tune", "uhq"),
                    "adaptive_i": ("adaptive_i",),
                    "adaptive_b": ("adaptive_b",),
                    "b_strategy": ("b_strategy",),
                    "extbrc": ("extbrc",),
                }
                matched_feature = None
                for candidate in fallback_features:
                    if candidate in disabled:
                        continue
                    aliases = feature_aliases.get(candidate, (candidate,))
                    if any(alias in lowered for alias in aliases):
                        matched_feature = candidate
                        break

                # 已知的 “Invalid FrameType:0.” 只与驱动/参数组合有关。
                # 上限模式里 extbrc 是明确有益的（实测同码率把最差画面 VMAF
                # 从 53.6 提到 64.2），所以只在真的报这个错时才降级它。
                if matched_feature is None and qsv_frame_type_bug:
                    for candidate in ("extbrc",):
                        if candidate in fallback_features and candidate not in disabled:
                            matched_feature = candidate
                            break

                if matched_feature is not None:
                    disabled.add(matched_feature)
                    update_task_state(
                        index,
                        message=f"当前 FFmpeg/驱动拒绝参数，自动降级：{matched_feature}，重新尝试",
                    )
                    continue

            # Invalid FrameType 虽然报在编码器上，但实测是"偶发"的：
            # 同一文件换一层解码（QSV 零拷贝 → d3d11va）再跑往往就过了
            # （2026-10-06 实测：重跑时同文件用 d3d11va 正常产出）。
            # 只给它一次机会（decode_index == 0 时），避免在同一文件上把耗时翻几倍。
            frame_type_fallback = (qsv_frame_type_bug and decode_index == 0 and len(chain) > 1)

            # 换解码层级：解码侧失败、零拷贝格式不匹配，以及上面那次偶发回退。
            if ((decode_side_error or surface_format_error or frame_type_fallback)
                    and decode_index + 1 < len(chain)):
                decode_index += 1
                DECODE_TIER[platform_key] = decode_index
                update_task_state(
                    index,
                    message=f"{decode_label} 不可用，改用 {chain[decode_index][0]} 重新开始",
                )
                continue

            hint = ""
            if decode_side_error:
                hint = "（硬件解码设备都不可用，通常是显卡驱动状态问题，重启可恢复）"
            elif encoder_side_error:
                hint = ("（编码器侧错误：已尝试过的解码层级都失败，直接失败以避免 0x 挂死；"
                        "此类错误常为偶发，重跑本文件多半能过）")
            return False, elapsed, f"FFmpeg 返回码 {return_code}{hint}\n{error_text[-6000:]}"

        except Exception as e:
            stop_process(process)
            stderr_thread.join(timeout=1)
            return False, time.monotonic() - start, f"FFmpeg 运行异常：{e}"

    return False, time.monotonic() - start, "所有编码尝试均失败。"


# ============================================================
# 输出验证
# ============================================================

def validate_output(
    source_info: MediaInfo,
    output: Path,
    target_codec: str,
) -> tuple[bool, Optional[MediaInfo], str]:
    if not output.exists():
        return False, None, "输出文件不存在。"

    try:
        size = output.stat().st_size
    except Exception as e:
        return False, None, f"无法读取输出文件大小：{e}"

    if size <= 0:
        return False, None, "输出文件大小为 0。"

    try:
        output_info = get_media_info(output)
    except Exception as e:
        return False, None, f"输出 ffprobe 失败：{e}"

    expected_codec = target_codec.lower()

    if output_info.video_codec.lower() != expected_codec:
        return (
            False,
            output_info,
            f"输出视频编码不是目标编码："
            f"{output_info.video_codec} != {expected_codec}",
        )

    if output_info.duration <= 0:
        return False, output_info, "输出视频没有有效时长。"

    # 安全检查：输出时长应接近源文件。
    # 允许少量时间戳 / 容器差异。
    if source_info.duration > 0:
        ratio = output_info.duration / source_info.duration

        if ratio < 0.95 or ratio > 1.05:
            return (
                False,
                output_info,
                f"输出时长异常："
                f"{format_duration(output_info.duration)} "
                f"/ 源文件 {format_duration(source_info.duration)}",
            )

    return True, output_info, "ffprobe 输出验证通过。"


# ============================================================
# 压缩统计
# ============================================================

def make_completion_report(
    source_info: MediaInfo,
    output_info: MediaInfo,
    elapsed: float,
    avg_speed: float,
    plan: Optional[EncodePlan] = None,
    platform_key: str = "intel",
    codec_key: str = "hevc",
    decoder_label: str = "",
    vmaf: Optional[float] = None,
) -> str:
    old_size = source_info.size
    new_size = output_info.size

    if old_size > 0:
        size_reduction = (1 - new_size / old_size) * 100
        output_percent = new_size / old_size * 100
        compression_ratio = old_size / new_size if new_size else 0
    else:
        size_reduction = 0
        output_percent = 0
        compression_ratio = 0

    old_total = source_info.total_bitrate
    new_total = output_info.total_bitrate
    bitrate_reduction = (1 - new_total / old_total) * 100 if old_total > 0 else 0

    def stream_text(info: MediaInfo) -> tuple[str, str]:
        video = (
            f"{info.video_codec} | {info.width}x{info.height} | "
            f"{info.fps:.3f} fps | {info.pix_fmt or 'N/A'} | "
            f"{video_bitrate_text(info)}"
        )
        if info.audio_codec != "none":
            channels = info.channels or 2
            layout = info.channel_layout or f"{channels}ch"
            audio = (
                f"{info.audio_codec} | {format_bitrate(info.audio_bitrate)} | "
                f"{info.sample_rate or 'N/A'} Hz | {layout}"
            )
        else:
            audio = "无"
        return video, audio

    old_video, old_audio = stream_text(source_info)
    new_video, new_audio = stream_text(output_info)

    lines = [
        f"原文件：{format_bytes(old_size)}",
        f"新文件：{format_bytes(new_size)}",
        f"体积降低：{size_reduction:.2f}%",
        f"新文件为原文件：{output_percent:.2f}%",
        f"压缩倍率：{compression_ratio:.2f}×",
        f"原时长：{format_duration(source_info.duration)}",
        f"新时长：{format_duration(output_info.duration)}",
        f"原总码率：{format_bitrate(old_total)}",
        f"新总码率：{format_bitrate(new_total)}",
        f"码率降低：{bitrate_reduction:.2f}%",
        "",
        f"原视频：{old_video}",
        f"新视频：{new_video}",
        f"原音频：{old_audio}",
        f"新音频：{new_audio}",
        "",
        f"编码耗时：{format_duration(elapsed)}",
        f"平均速度：{avg_speed:.2f}x" if avg_speed > 0 else "平均速度：N/A",
        "",
        f"编码模式：{plan_label(plan) if plan else '质量优先'}"
        + (f"（质量值 {plan.quality}）" if plan else ""),
        f"编码器：{encoder_name(platform_key, codec_key)}"
        + (f" | 速率控制：{QUALITY_MODE_LABEL.get(platform_key, '')}" if platform_key == "intel" else "")
        + (f" | 解码：{decoder_label}" if decoder_label else ""),
        "√ FFmpeg 成功",
        "√ ffprobe 输出验证通过",
    ]
    if plan is not None and plan.is_capped and plan.cap_kbps:
        actual_kbps = (output_info.video_bitrate or 0) / 1000
        maxrate = plan.cap_kbps * BITRATE_PEAK_RATIO
        over = actual_kbps > maxrate * 1.02
        lines.insert(
            len(lines) - 3,
            f"码率上限：{format_cap(plan.cap_kbps)}（峰值 {format_cap(int(maxrate))}）"
            f" | 实际视频码率：{video_bitrate_text(output_info)}"
            + ("   ⚠ 超过峰值天花板，建议提高上限" if over else "   ✓ 在上限范围内"),
        )
    if plan is not None and not plan.is_capped and plan.predicted_kbps:
        lines.insert(
            len(lines) - 3,
            f"采样预估码率：{format_bitrate(plan.predicted_kbps * 1000)} | "
            f"实际视频码率：{video_bitrate_text(output_info)}",
        )
    if vmaf is not None:
        lines.insert(
            len(lines) - 3,
            f"质量校验：VMAF 平均 {vmaf:.2f}（抽样，越高越接近原片；>90 一般肉眼难辨）",
        )
    return "\n".join(lines)


# ============================================================
# 单任务
# ============================================================

def encode_one(
    index: int,
    source: Path,
    output: Path,
    platform_key: str,
    codec_key: str,
    video_quality: int,
    audio_quality: int,
    plan: Optional[EncodePlan] = None,
) -> Result:
    start = time.monotonic()

    update_task_state(
        index,
        status="probing",
        message="正在读取媒体信息",
    )

    try:
        source_info = get_media_info(source)
    except Exception as e:
        update_task_state(
            index,
            status="failed",
            error=str(e),
            message="ffprobe 输入失败",
        )
        return Result(
            index=index,
            source=source,
            output=output,
            status="failed",
            error=str(e),
        )

    update_task_state(
        index,
        duration=source_info.duration,
        original_size=source_info.size,
    )

    # 编码到临时文件，永远不直接覆盖正式输出。
    temp_output = get_temp_path(output)

    try:
        if temp_output.exists():
            temp_output.unlink()
    except Exception:
        pass

    ok, elapsed, error = run_ffmpeg(
        index=index,
        source=source,
        output=temp_output,
        info=source_info,
        platform_key=platform_key,
        codec_key=codec_key,
        video_quality=video_quality,
        audio_quality=audio_quality,
        plan=plan,
    )

    if not ok:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=error,
            message="FFmpeg 编码失败",
        )

        return Result(
            index=index,
            source=source,
            output=output,
            status="failed",
            original_info=source_info,
            elapsed=elapsed,
            error=error,
        )

    target_codec = codec_key

    valid, output_info, validation_message = validate_output(
        source_info=source_info,
        output=temp_output,
        target_codec=target_codec,
    )

    if not valid or output_info is None:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=validation_message,
            message="输出验证失败",
        )

        return Result(
            index=index,
            source=source,
            output=output,
            status="failed",
            original_info=source_info,
            elapsed=elapsed,
            error=validation_message,
        )

    # 质量校验统一放到"所有编码结束之后"串行执行（见主流程的 QC 阶段），
    # 这里不再做：VMAF 是纯 CPU 计算，放在并发编码里会明显拖慢编码。
    vmaf = None

    # 只有验证通过后才正式发布输出。
    try:
        if output.exists():
            output.unlink()

        os.replace(temp_output, output)
    except Exception as e:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=f"发布输出文件失败：{e}",
            message="输出发布失败",
        )

        return Result(
            index=index,
            source=source,
            output=output,
            status="failed",
            original_info=source_info,
            output_info=output_info,
            elapsed=elapsed,
            error=f"发布输出文件失败：{e}",
        )

    avg_speed = (
        source_info.duration / elapsed
        if elapsed > 0 and source_info.duration > 0
        else 0
    )

    update_task_state(
        index,
        status="completed",
        percent=100.0,
        out_time=output_info.duration,
        output_size=output_info.size,
        speed=avg_speed,
        message="完成",
        summary=(
            f"{format_bytes(source_info.size)} → {format_bytes(output_info.size)}"
        ),
    )

    return Result(
        index=index,
        source=source,
        output=output,
        status="success",
        message=make_completion_report(
            source_info=source_info,
            output_info=output_info,
            elapsed=elapsed,
            avg_speed=avg_speed,
            plan=plan,
            platform_key=platform_key,
            codec_key=codec_key,
            decoder_label=decode_label_for(platform_key),
            vmaf=vmaf,
        ),
        original_info=source_info,
        output_info=output_info,
        elapsed=elapsed,
        avg_speed=avg_speed,
        plan=plan,
        vmaf=vmaf,
        decoder_label=decode_label_for(platform_key),
    )


# ============================================================
# 原地替换模式
# ============================================================

def encode_one_in_place(
    index: int,
    source: Path,
    platform_key: str,
    codec_key: str,
    video_quality: int,
    audio_quality: int,
    plan: Optional[EncodePlan] = None,
) -> Result:
    start = time.monotonic()

    update_task_state(
        index,
        status="probing",
        message="正在读取媒体信息",
    )

    try:
        source_info = get_media_info(source)
    except Exception as e:
        update_task_state(
            index,
            status="failed",
            error=str(e),
            message="ffprobe 输入失败",
        )
        return Result(
            index=index,
            source=source,
            output=source,
            status="failed",
            error=str(e),
        )

    update_task_state(
        index,
        duration=source_info.duration,
        original_size=source_info.size,
    )

    temp_output = source.with_name(
        source.stem + TEMP_MARKER + source.suffix.lstrip(".")
    )

    # 强制保证临时文件不是扫描范围中的正常视频。
    if temp_output.exists():
        try:
            temp_output.unlink()
        except Exception as e:
            return Result(
                index=index,
                source=source,
                output=source,
                status="failed",
                error=f"无法删除旧临时文件：{e}",
            )

    ok, elapsed, error = run_ffmpeg(
        index=index,
        source=source,
        output=temp_output,
        info=source_info,
        platform_key=platform_key,
        codec_key=codec_key,
        video_quality=video_quality,
        audio_quality=audio_quality,
        plan=plan,
    )

    if not ok:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=error,
            message="FFmpeg 编码失败，原文件保持不变",
        )

        return Result(
            index=index,
            source=source,
            output=source,
            status="failed",
            original_info=source_info,
            elapsed=elapsed,
            error=error,
        )

    target_codec = codec_key

    valid, output_info, validation_message = validate_output(
        source_info=source_info,
        output=temp_output,
        target_codec=target_codec,
    )

    if not valid or output_info is None:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=validation_message,
            message="输出验证失败，原文件保持不变",
        )

        return Result(
            index=index,
            source=source,
            output=source,
            status="failed",
            original_info=source_info,
            elapsed=elapsed,
            error=validation_message,
        )

    # 质量校验同样延后到统一 QC 阶段（原地替换模式下会保留备份供其比对）
    vmaf = None

    # 到这里才允许替换原文件。
    # 输出容器固定为 MP4：a.mkv 编码后变为 a.mp4（原来会保留 .mkv 扩展名但内容是 MP4）。
    final_path = source.with_suffix(".mp4")
    try:
        if final_path != source and final_path.exists():
            raise RuntimeError(f"目标文件已存在，拒绝覆盖：{final_path.name}")

        backup_temp = source.with_name(
            source.stem + TEMP_MARKER + "original" + source.suffix
        )

        if backup_temp.exists():
            backup_temp.unlink()

        # 先把原文件临时改名，再把验证通过的新文件放到原路径。
        # 如果第二步失败，尝试恢复原文件。
        os.replace(source, backup_temp)

        try:
            os.replace(temp_output, final_path)
        except Exception:
            os.replace(backup_temp, source)
            raise

        # 新文件已经成功成为正式原路径后，再删除旧文件。
        try:
            backup_temp.unlink()
        except Exception:
            # 删除失败不会让编码结果失效，但留下备份文件以便人工处理。
            pass

    except Exception as e:
        try:
            if temp_output.exists():
                temp_output.unlink()
        except Exception:
            pass

        update_task_state(
            index,
            status="failed",
            error=f"原地替换失败：{e}",
            message="原地替换失败，请检查临时文件",
        )

        return Result(
            index=index,
            source=source,
            output=source,
            status="failed",
            original_info=source_info,
            output_info=output_info,
            elapsed=elapsed,
            error=f"原地替换失败：{e}",
        )

    avg_speed = (
        source_info.duration / elapsed
        if elapsed > 0 and source_info.duration > 0
        else 0
    )

    update_task_state(
        index,
        status="completed",
        percent=100.0,
        out_time=output_info.duration,
        output_size=output_info.size,
        speed=avg_speed,
        message="完成并已安全替换原文件",
        summary=(
            f"{format_bytes(source_info.size)} → {format_bytes(output_info.size)}"
        ),
    )

    return Result(
        index=index,
        source=source,
        output=final_path,
        status="success",
        message=make_completion_report(
            source_info=source_info,
            output_info=output_info,
            elapsed=elapsed,
            avg_speed=avg_speed,
            plan=plan,
            platform_key=platform_key,
            codec_key=codec_key,
            decoder_label=decode_label_for(platform_key),
            vmaf=vmaf,
        ),
        original_info=source_info,
        output_info=output_info,
        elapsed=elapsed,
        avg_speed=avg_speed,
        plan=plan,
        vmaf=vmaf,
        decoder_label=decode_label_for(platform_key),
    )


# ============================================================
# 实时进度 UI
# ============================================================

def progress_bar(percent: float, width: int = 28) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(width * percent / 100)
    return "█" * filled + "-" * (width - filled)


# 已经打印过"开始"行的任务号
_PROGRESS_ANNOUNCED: set[int] = set()
# 全局状态区（编码阶段使用）
STATUS_BOARD = StatusBoard()


def render_progress(
    platform_key: str,
    codec_key: str,
    video_quality: int,
    audio_quality: int,
    recursive: bool,
    output_mode: str,
    total: int,
    completed: int,
    failed: int,
    skipped_target: int,
    skipped_output: int,
    queue_count: int,
    session_start: float = 0.0,
    plans: Optional[dict[int, EncodePlan]] = None,
) -> None:
    """进度显示：日志向上滚动 + 底部状态区原地更新数字（不追加行）。

    旧实现要么整屏刷新（滚不回历史），要么每个 25% 追加一行（刷屏、且短视频没有进度）。
    现在用"底部固定状态区"：每个正在编码的文件一行，含进度条/百分比/速度/剩余时间，
    数字原地变化；完成信息统一放到最后的"编码完成"模块里。
    """
    plans = plans or {}

    with STATE_LOCK:
        states = sorted(TASK_STATES.values(), key=lambda x: x.index)

    active = [s for s in states if s.status in ("encoding", "probing")]
    elapsed_all = time.time() - session_start if session_start else 0.0

    # 文件清单已在"编码开始"模块里列出，这里不再重复打印开始行，
    # 只保留底部状态区（原地更新数字），避免同一份信息出现两遍。
    # 状态区自带一条虚线边界（随状态区一起重绘），
    # 这样"编码清单"和"编码中"永远不会挤在一起。
    rule_width = max(20, min(74, term_width() - 2))
    lines: list[str] = [
        "", "", "",                              # 与上方"编码清单"隔开 3 行
        color(ui_module_line("编码中"), "magenta", bold=True),   # 与"编码开始"同级
    ]
    head = (f"   {color(f'完成 {completed}/{total}', 'green' if completed else 'white')}"
            f"   {color(f'失败 {failed}', 'red' if failed else 'white')}"
            f"   {dim(f'已用 {format_duration(elapsed_all)}')}")
    lines.append(head)

    if not active:
        lines.append("")
        lines.append(f"   {dim('等待调度……')}")
    else:
        # 宽度自适应：状态区是"原地重绘"，一旦折行，光标上移行数就会算错、
        # 界面会糊成一团。所以这里按终端宽度算好每行长度。
        name_w = max(14, min(44, term_width() - 58))
        for pos, state in enumerate(active):
            if pos:
                lines.append("")          # 不同文件之间空一行，便于分辨
            percent = state.percent if state.duration > 0 else 0.0
            bar = progress_bar(percent, 16)
            speed = f"{state.speed:>6.2f}x" if state.speed > 0 else "     —"
            eta = ""
            if percent > 1 and state.start_time:
                used = time.time() - state.start_time
                if used > 3:
                    eta = f"剩余 {format_duration(used * (100.0 - percent) / percent)}"
            name = fit(state.source.name, name_w)
            lines.append(
                f"   {color(f'[{state.index:03d}]', 'blue')} {color(f'{name:<{name_w}}', 'white')} "
                f"{color(bar, 'cyan')} "
                f"{color(f'{percent:5.1f}%', 'white', bold=True)}  "
                f"{dim(f'{speed}   {eta}')}"
            )

    STATUS_BOARD.update(lines)

def handle_sigint(signum: int, frame: Any) -> None:
    global STOP_REQUESTED

    if STOP_REQUESTED:
        print("\n再次收到 Ctrl+C，强制退出。")
        os._exit(130)

    STOP_REQUESTED = True
    print(
        "\n\n收到 Ctrl+C：停止提交新任务，并等待当前 FFmpeg 尽量安全退出……"
    )


# ============================================================
# 主流程
# ============================================================

def pause(message: str = "\n按 Enter 退出……") -> None:
    """等待回车；非交互场景（输入被重定向/管道读完）不抛异常。

    没有这个兜底时，用 < in.txt 或从计划任务运行时，最后一次 input() 会抛
    EOFError，被外层 except 捕获后又调用一次 input()，最终以退出码 1 结束，
    让人误以为程序出错。
    """
    try:
        input(message)
    except EOFError:
        pass


def ensure_console_on_windows() -> None:
    """若 .py 被 Windows 关联到 pythonw.exe，双击时没有控制台；自动改用 python.exe 新开控制台。"""
    if os.name != "nt":
        return
    exe = Path(sys.executable).name.lower()
    if exe != "pythonw.exe":
        return
    console_python = Path(sys.executable).with_name("python.exe")
    if not console_python.exists():
        return
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(
        [str(console_python), str(Path(__file__).resolve())],
        creationflags=creationflags,
    )
    raise SystemExit(0)


detected_cache: list = [None]


def main(start_step: int = 1) -> int:
    global STOP_REQUESTED, VIDEO_BITRATE_CAP_KBPS, RC_MODE
    global FFMPEG_BIN, FFPROBE_BIN, MAX_WORKERS

    # 输出编码兜底：
    # Windows 下当 stdout 被重定向到文件/管道时，Python 使用系统 ANSI 代码页
    # （简体中文为 GBK），遇到该代码页无法表示的字符会直接抛 UnicodeEncodeError
    # 并中断脚本。这里只把错误处理放宽为替换，不改变编码本身，
    # 因此重定向日志仍保持本机原生编码，控制台输出也完全不受影响。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

    signal.signal(signal.SIGINT, handle_sigint)

    root = Path.cwd().resolve()

    ui_banner("视频批量归档 / 编码工具")
    print(f"  {dim('当前目录')}  {color(str(root), 'white')}")

    try:
        check_tools()
    except Exception as e:
        print()
        ui_err(f"{e}")
        pause()
        return 1

    # 0. 先确认有视频可编：没有就立刻说清楚，不要让人先答完 8 个菜单
    if not scan_videos(Path.cwd(), recursive=False) and not scan_videos(Path.cwd(), recursive=True):
        ui_gap(3)
        print(f"   {color('这个目录里没有找到视频文件', 'yellow', bold=True)}")
        print(f"   {dim('请把视频放在脚本所在目录（或其子目录），或先 cd 到有视频的目录再运行本脚本。')}")
        print(f"   {dim('支持的格式：' + '、'.join(sorted(VIDEO_EXTENSIONS)))}")
        print()
        pause()
        return 0

    # 1. 自动检测编码平台
    if 1 in _QUIZ_ANSWERS:
        detected = _QUIZ_ANSWERS[1 - 1] if False else detected_cache[0]
    else:
        detected_cache[0] = detect_platforms()
        detected = detected_cache[0]
    platform_key = _ask(1, start_step, choose_platform, detected)
    platform = ENCODER_PROFILES[platform_key]

    # ---- v3：识别 NVENC 世代与编码引擎数量，并据此决定并发路数 ----
    NVENC_HW.clear()
    NVENC_CALIBRATED.clear()
    QSV_CALIBRATED.clear()
    if platform_key == "nvidia":
        NVENC_HW.update(detect_nvenc_hardware())
        engines = max(1, int(NVENC_HW.get("engines", 1)))
        ui_hint("显卡 %s：%s，%d 个 NVENC 引擎"
                % (NVENC_HW.get("gpu") or "未知", NVENC_HW.get("generation_name"), engines))
        if NVENC_HW.get("generation") in ("ada", "blackwell"):
            ui_hint("该世代的 NVENC 支持 AV1 编码，标定会一并实测（AV1 通常比 HEVC 更省码率）")
    else:
        NVENC_HW.update({"gpu": "", "generation": "unknown",
                         "generation_name": "非 NVIDIA", "engines": 1})
        MAX_WORKERS = int(DEFAULT_WORKERS)

    # 2. 目标视频编码
    codec_choice = _ask(2, start_step, ask_choice,
        f"【2. 目标视频编码】平台：{platform['name']}",
        [
            ("1", "HEVC", f"→ {encoder_name(platform_key, 'hevc')}"),
            ("2", "AV1", f"→ {encoder_name(platform_key, 'av1')}"),
        ],
        default="1",
        default_label="HEVC",
    )

    codec_key = "hevc" if codec_choice == "1" else "av1"
    encoder = encoder_name(platform_key, codec_key)

    # 编译支持 ≠ 本机能跑（典型：Turing 卡选了 AV1，芯片里没有 AV1 编码单元）。
    # 但 HEVC/H.264 在所有受支持的硬件上都有，试编码只是白等 0.3~3 秒
    # （N 卡首次初始化 CUDA 更慢），所以只在 AV1 上做真机确认。
    if codec_key == "av1":
        ui_hint(f"正在确认 {encoder} 能否在本机初始化（试编码，约 1 秒）……")
        encoder_ok, encoder_note = verify_encoder_available(encoder)
    else:
        encoder_ok = encoder in AVAILABLE_ENCODERS
        encoder_note = "编码器列表已包含（HEVC 全世代支持，跳过试编码）"
    if not encoder_ok:
        print()
        ui_err(f"{encoder} 在本机无法初始化：{encoder_note}")
        ui_hint("常见原因：FFmpeg 编进了这个编码器，但显卡没有对应的编码单元"
                "（例如 Turing / RTX 20 系没有 AV1 编码器）。")
        ui_hint(f"FFmpeg 报告的硬件编码器：{', '.join(sorted(AVAILABLE_ENCODERS)) or '无'}")
        pause()
        return 1
    ui_hint(f"{encoder}：{encoder_note}")

    print()
    caps = prepare_encoder_capabilities(encoder)
    if not caps.help_text:
        ui_warn(f"无法读取 {encoder} 的参数表；运行时仍会自动尝试并在可选参数失败时降级。")
    else:
        ui_hint(f"已读取 {encoder} 的 {len(caps.options)} 个参数")

    # 3. 是否跳过目标编码（默认重新编码：不跳过）
    skip_target = _ask(3, start_step, ask_choice,
        f"【3. 已是目标编码的视频】\n"
        f"当前目标编码：{codec_key.upper()} / {encoder}",
        [
            ("1", f"跳过已经是 {codec_key.upper()} 的视频"),
            ("2", "重新编码（不跳过）"),
        ],
        default="2",
        default_label="重新编码",
    ) == "1"

    # 3. 扫描范围
    recursive = (
        _ask(4, start_step, ask_choice,
            "【4. 扫描范围】",
            [
                ("1", "仅当前文件夹"),
                ("2", "当前文件夹 + 所有子文件夹"),
            ],
            default="1",
            default_label="仅当前文件夹",
        )
        == "2"
    )

    # 4. 输出模式
    output_mode_choice = _ask(5, start_step, ask_choice,
        "【5. 输出方式】",
        [
            ("1", "安全模式", "原文件保留，输出到 output/"),
            ("2", "原地替换", "编码成功 + ffprobe 验证通过后替换原视频"),
        ],
        default="1",
        default_label="安全模式",
    )

    output_mode = "safe" if output_mode_choice == "1" else "in_place"

    if output_mode == "in_place" and start_step <= 5:
        print()
        print("！！！原地替换模式！！！")
        print("程序不会在编码开始时删除原文件。")
        print("流程为：原文件 → 临时文件 → FFmpeg 成功 → ffprobe 验证 → 替换。")
        print("如果编码或验证失败，原文件保持不变。")
        print("输出容器统一为 MP4：非 .mp4 的原文件（如 .mkv）成功后扩展名会变为 .mp4。")

        if not confirm(
            "确认启用原地替换模式？",
            default=False,
        ):
            print("已取消。")
            return 0

    # 5. 视频质量（默认 Q30）
    video_quality = _ask(6, start_step, ask_video_quality, platform_key, codec_key)

    # 6. 视频码率上限（默认 1.5 Mbps）
    VIDEO_BITRATE_CAP_KBPS = _ask(7, start_step, ask_video_bitrate_cap)
    RC_MODE = RC_MODE_CAPPED if VIDEO_BITRATE_CAP_KBPS else RC_MODE_QUALITY

    # 7. 音频质量（默认 64k）
    audio_quality = _ask(8, start_step, ask_audio_quality)

    # 扫描前先给个提示：后面这几步要花几秒（逐个 ffprobe + 自检试编码），
    # 之前这几步是完全静默的，会让人以为程序卡住而乱按回车。
    ui_gap(3)
    print(f"   {dim('正在扫描视频文件……')}", flush=True)

    videos = scan_videos(root, recursive)

    if not videos:
        print("没有找到符合条件的视频文件。")
        pause()
        return 0

    print(f"   {dim(f'正在读取 {len(videos)} 个视频的信息……')}", flush=True)

    # 并行读取媒体信息：ffprobe 是独立进程，文件多时串行读是主要等待来源。
    # 4 路并发（保持原顺序），每个文件的失败只影响它自己。
    info_results = []
    if len(videos) > 1:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(4, len(videos))) as pool:
            info_results = list(pool.map(_safe_media_info, videos))
    else:
        info_results = [_safe_media_info(v) for v in videos]

    # 逐文件信息先收集起来，"编码开始"模块里一次性展示
    info_lines: list[str] = []
    # 清理上次异常中断（崩溃/断电/强杀）留下的临时文件，避免越积越多
    stale_dirs = {root}
    stale_dirs |= {v.parent for v in videos}
    stale_dirs |= {v.parent / OUTPUT_DIR_NAME for v in videos}
    removed = cleanup_stale_temps(list(stale_dirs))
    if removed:
        info_lines.append(f"   {dim(f'已清理 {removed} 个上次残留的临时文件')}")

    candidates: list[tuple[int, Path, Optional[Path], MediaInfo]] = []

    skipped_target = 0
    skipped_output = 0
    failed_probe = 0

    expected_codec = codec_key
    claimed_outputs: dict[str, Path] = {}  # 安全模式：输出路径 → 占用它的源文件
    plans: dict[int, EncodePlan] = {}

    for number, source in enumerate(videos, start=1):
        info = info_results[number - 1]
        if isinstance(info, Exception):
            failed_probe += 1
            info_lines.append(f"{color(f'[{number:03d}]', 'blue')} "
                              f"{color(source.name, 'white')}   "
                              f"{color(f'ffprobe 读取失败：{info}', 'red')}")
            continue

        output = None
        if output_mode == "safe":
            output = get_output_path(
                source=source,
                root=root,
                recursive=recursive,
            )
            # 同目录下 a.mkv 与 a.mp4 都会输出为 output/a.mp4，必须区分，
            # 否则会互相覆盖或被误判为“输出已存在”。
            owner = claimed_outputs.get(str(output).lower())
            if owner is not None and owner != source:
                output = output.with_name(f"{source.stem}.{source.suffix.lstrip('.')}.mp4")
                info_lines.append(f"   {color(f'! 与 {owner.name} 输出重名，改为：{output.name}', 'yellow')}")
            claimed_outputs[str(output).lower()] = source

        # 文件名亮、其余信息暗（次要信息降级，方便一眼扫过）
        entry = [f"{color(f'[{number:03d}]', 'blue')} {color(source.name, 'white')}"]
        detail = (f"{info.video_codec:<5} {info.width}x{info.height} "
                  f"{info.fps:.2f}fps  {format_bytes(info.size)}")

        # codec_name 判断，而不是文件后缀
        if info.video_codec.lower() == expected_codec and skip_target:
            skipped_target += 1
            detail += f"   → 跳过：已经是 {codec_key.upper()}"
            info_lines.append(entry[0])
            info_lines.append(f"       {dim(detail)}")
            continue

        # 安全模式：已有正式输出则跳过
        if output_mode == "safe" and output is not None:
            if output.exists() and output.stat().st_size > 0:
                skipped_output += 1
                info_lines.append(entry[0])
                info_lines.append(f"       {dim(detail + '   → 跳过：输出已存在')}")
                continue

        candidates.append(
            (number, source, output, info)
        )
        # 就地决定这个文件走质量模式还是上限模式（瞬间估算，不解码不采样）
        plan = EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality)
        if VIDEO_BITRATE_CAP_KBPS:
            estimated = int(info.total_bitrate / 1000 / ICQ_SOURCE_DIVISOR) if info.total_bitrate else 0
            plan.predicted_kbps = estimated
            # 只在"预计会超过上限"时才限码率，否则上限会把小文件撑大
            if not estimated or estimated > VIDEO_BITRATE_CAP_KBPS:
                plan = EncodePlan(mode=RC_MODE_CAPPED, quality=video_quality,
                                  cap_kbps=VIDEO_BITRATE_CAP_KBPS, predicted_kbps=estimated)
        plans[number] = plan
        badge = color(plan_label(plan), "yellow" if plan.is_capped else "green")
        if info_lines:
            info_lines.append("")        # 清单条目之间 1 行
        info_lines.append(entry[0])
        info_lines.append(f"       {dim(detail)}   {badge}")

    if not candidates:
        ui_gap(3)
        print(f"   {dim('共')} {color(str(len(videos)), 'white', bold=True)} {dim('个视频')}"
              f"   {dim('·')}   {color('没有需要编码的视频', 'yellow')}")
        print()
        pause()
        return 0

    # --------------------------------------------------------
    # 静默自检：解码层级 + 质量参数是否真的生效
    # 不打印过程、不额外提问；结论在下面的"编码设置"里一行带过。
    # 用第一个待编码文件做样本（用 videos[0] 可能撞上损坏/无视频流的文件）。
    # --------------------------------------------------------

    # --------------------------------------------------------
    # 不再做"试编码自检"：
    #   * 解码层级：真正编码时若硬件解码不可用，run_ffmpeg 会自动回退下一层，
    #     所以提前试编一次纯属重复劳动（还多花 1~2 秒）。
    #   * 质量参数：已知只有 master 快照（版本号形如 N-127054-gxxxx）才会
    #     静默丢 ICQ；发行分支（n9.0.2-…）不会。这里只对 master 快照做一次
    #     试编码确认，其他构建直接信任，直接省掉这次等待。
    # --------------------------------------------------------

    sample_source = candidates[0][1]
    sample_info = candidates[0][3]
    DECODE_TIER[platform_key] = 0                 # 默认零拷贝硬解，失败时自动回退

    # ---- v8：决定并发路数（默认 2；AUTO_WORKERS=True 时实测并缓存） ----
    # 并发实测用一个"最重"的文件做样本（源码率最高者）：拿轻松的小文件测会得出偏高的
    # 路数，遇到重素材反而拖慢单文件速度；用最重的那个更保守、更接近最坏情况。
    worker_probe = max(candidates, key=lambda c: (c[3].total_bitrate or 0))
    MAX_WORKERS = resolve_workers(
        worker_probe[1], worker_probe[3], platform_key, codec_key,
        plans.get(worker_probe[0]) or EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality),
    )

    # ---- v3：在真实素材上标定 NVENC 参数（每台机器/每种素材只做一次） ----
    if platform_key == "nvidia":
        if NVENC_AUTO_CALIBRATE:
            calibrate_nvenc(
                source=sample_source,
                info=sample_info,
                platform_key=platform_key,
                codec_key=codec_key,
                video_quality=video_quality,
                plan=plans.get(candidates[0][0]) or EncodePlan(mode=RC_MODE_QUALITY,
                                                              quality=video_quality),
            )
        else:
            NVENC_CALIBRATED.clear()
            NVENC_CALIBRATED.update(nvenc_default_settings())

    # ---- v5：Intel QSV 也在真实素材上标定 preset ----
    if platform_key == "intel":
        if QSV_AUTO_CALIBRATE:
            calibrate_qsv(
                source=sample_source,
                info=sample_info,
                platform_key=platform_key,
                codec_key=codec_key,
                video_quality=video_quality,
                plan=plans.get(candidates[0][0]) or EncodePlan(mode=RC_MODE_QUALITY,
                                                               quality=video_quality),
            )
        else:
            QSV_CALIBRATED.clear()

    if platform_key == "intel" and _is_master_snapshot():
        print(f"   {dim('检测到 master 快照构建，确认一下质量参数是否生效（约 1 秒）……')}",
              flush=True)
        detect_quality_knob(platform_key, codec_key, sample_source, sample_info)

    # --------------------------------------------------------
    # 逐文件计划在分类时就已确定（见上面"就地决定"），这里不再重复计算。

    # --------------------------------------------------------
    # 编码信息
    # --------------------------------------------------------

    capped_files = sum(1 for p in plans.values() if p.is_capped)
    quality_files = len(plans) - capped_files
    if platform_key == "intel":
        rate_text = (f"Q{video_quality} 质量模式"
                     + (f" + {format_cap(VIDEO_BITRATE_CAP_KBPS)} 上限" if VIDEO_BITRATE_CAP_KBPS else ""))
    else:
        rate_text = (f"CQ{video_quality}"
                     + (f" + {format_cap(VIDEO_BITRATE_CAP_KBPS)} 上限" if VIDEO_BITRATE_CAP_KBPS else ""))
    mode_label = QUALITY_MODE_LABEL.get(platform_key, "")

    ui_title("编码信息")
    print(f"   {dim('编码设置')}  {color(codec_key.upper(), 'white', bold=True)}"
          f"{dim(' ・ ' + ('Q' if platform_key == 'intel' else 'CQ') + str(video_quality))}"
          f"{dim(' ・ ' + ('上限 ' + format_cap(VIDEO_BITRATE_CAP_KBPS) if VIDEO_BITRATE_CAP_KBPS else '不限码率'))}"
          f"{dim(' ・ 音频 ' + AUDIO_BITRATES[audio_quality])}"
          f"{dim(' ・ ' + decode_label_for(platform_key))}"
          f"{dim(' ・ GOP ' + f'{GOP_SECONDS:g}秒')}"
          f"{dim(' ・ ' + ('安全 output/' if output_mode == 'safe' else '原地替换'))}")
    if capped_files and quality_files:
        print(f"   {dim('本批')}      {len(candidates)} 个文件："
              f"{color(f'{capped_files} 个上限模式', 'yellow')} · "
              f"{color(f'{quality_files} 个质量模式', 'green')}")
    elif capped_files:
        print(f"   {dim('本批')}      {len(candidates)} 个文件：全部上限模式")
    else:
        print(f"   {dim('本批')}      {len(candidates)} 个文件：全部质量模式")

    # ---- 实际会下发的编码参数（可直接复制到 .bat） ----
    first_source, first_output, first_info = candidates[0][1], candidates[0][2], candidates[0][3]

    def _encoder_params(plan_obj) -> tuple[str, str]:
        cmd = build_ffmpeg_command(
            source=first_source,
            output=first_output or first_source,
            info=first_info,
            platform_key=platform_key,
            codec_key=codec_key,
            video_quality=video_quality,
            audio_quality=audio_quality,
            decode_args=[],
            plan=plan_obj,
        )[:-1]                                   # 去掉末尾的输出路径

        def at(token: str) -> Optional[int]:
            return cmd.index(token) if token in cmd else None

        iv, ia, im = at("-c:v"), at("-c:a"), at("-movflags")
        stop = [x for x in (ia, im) if x is not None]
        video = cmd[iv:min(stop)] if iv is not None and stop else (cmd[iv:] if iv is not None else [])
        if ia is None:
            audio = []
        else:
            audio = cmd[ia:im] if im is not None else cmd[ia:]
        return " ".join(str(x) for x in video), " ".join(str(x) for x in audio)

    v_quality, a_text = _encoder_params(EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality))
    print(f"   {dim('参数')}      {dim('质量模式')} {color(v_quality, 'white')}")
    if VIDEO_BITRATE_CAP_KBPS:
        v_capped, _ = _encoder_params(EncodePlan(mode=RC_MODE_CAPPED, quality=video_quality,
                                                cap_kbps=VIDEO_BITRATE_CAP_KBPS))
        print(f"   {dim('')}          {dim('上限模式')} {color(v_capped, 'white')}")
    print(f"   {dim('')}          {dim('音频')}     {color(a_text, 'white')}")

    # 扫描结果 + 逐文件信息（并进本模块，不再单独占一个模块）
    print(f"   {dim('扫描')}      {color(str(len(videos)), 'white', bold=True)} 个视频"
          f"{dim(' ・ 准备编码 ')} {color(str(len(candidates)), 'green', bold=True)}"
          f"{dim(f' ・ 跳过目标 {skipped_target} ・ 跳过已有输出 {skipped_output} ・ 读取失败 {failed_probe}')}")
    print()
    for line in info_lines:
        print(line)

    # --------------------------------------------------------
    # 初始化状态
    # --------------------------------------------------------

    TASK_STATES.clear()

    for number, source, output, info in candidates:
        if output_mode == "safe":
            assert output is not None
            actual_output = output
        else:
            actual_output = source

        TASK_STATES[number] = TaskState(
            index=number,
            source=source,
            output=actual_output,
            duration=info.duration,
            original_size=info.size,
        )

    results: list[Result] = []
    session_start = time.time()

    # --------------------------------------------------------
    # 并发执行
    # --------------------------------------------------------

    future_map: dict[
        concurrent.futures.Future,
        tuple[int, Path, Optional[Path], MediaInfo],
    ] = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS,
        thread_name_prefix="Encoder",
    ) as executor:

        _run_log("=" * 72)
        _run_log("批次开始 %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        _run_log("  平台/编码器 : %s / %s"
                 % (ENCODER_PROFILES[platform_key]["name"], encoder_name(platform_key, codec_key)))
        _run_log("  质量/上限   : Q%s / %s"
                 % (video_quality, ("%d kbps" % VIDEO_BITRATE_CAP_KBPS) if VIDEO_BITRATE_CAP_KBPS else "不限"))
        _run_log("  音频        : %s" % AUDIO_BITRATES[audio_quality])
        _run_log("  输出方式    : %s" % ("原地替换" if output_mode == "in_place" else "安全模式 output/"))
        _run_log("  并发/文件数 : %d / %d" % (MAX_WORKERS, len(candidates)))
        for _n, _s, _o, _i in candidates:
            _run_log("    [%03d] %s" % (_n, _s))
        _run_log("-" * 72)

        for number, source, output, info in candidates:
            if STOP_REQUESTED:
                break

            plan = plans.get(number, EncodePlan(mode=RC_MODE_QUALITY, quality=video_quality))

            if output_mode == "safe":
                assert output is not None

                future = executor.submit(
                    _encode_iterative,
                    encode_one,
                    (number, source, output, platform_key, codec_key,
                     video_quality, audio_quality),
                    plan,
                    info.duration,
                    VIDEO_BITRATE_CAP_KBPS,
                    codec_key,
                )
            else:
                future = executor.submit(
                    _encode_iterative,
                    encode_one_in_place,
                    (number, source, platform_key, codec_key,
                     video_quality, audio_quality),
                    plan,
                    info.duration,
                    VIDEO_BITRATE_CAP_KBPS,
                    codec_key,
                )

            future_map[future] = (
                number,
                source,
                output,
                info,
            )

        total = len(candidates)

        while future_map:
            done, _ = concurrent.futures.wait(
                future_map.keys(),
                timeout=0.5,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            completed_count = 0
            failed_count = 0

            with STATE_LOCK:
                for state in TASK_STATES.values():
                    if state.status == "completed":
                        completed_count += 1
                    elif state.status == "failed":
                        failed_count += 1

            active_or_queued = total - completed_count - failed_count

            render_progress(
                platform_key=platform_key,
                codec_key=codec_key,
                video_quality=video_quality,
                audio_quality=audio_quality,
                recursive=recursive,
                output_mode=output_mode,
                total=total,
                completed=completed_count,
                failed=failed_count,
                skipped_target=skipped_target,
                skipped_output=skipped_output,
                queue_count=max(0, active_or_queued),
                session_start=session_start,
                plans=plans,
            )

            for future in done:
                # 先 pop，再处理异常；避免 future 元数据丢失
                meta = future_map.pop(future)

                try:
                    result = future.result()
                except Exception as e:
                    number, source, output, _info = meta

                    error = f"worker 未处理异常：{e}"

                    update_task_state(
                        number,
                        status="failed",
                        error=error,
                        message="worker 异常",
                    )

                    result = Result(
                        index=number,
                        source=source,
                        output=output or source,
                        status="failed",
                        error=error,
                    )

                results.append(result)
                _log_result(result)

                # 编码过程中的完成信息不再单独打印：统一放到最后的"编码完成"模块，
                # 无人值守时只看那一段就够了。失败要立刻可见，所以单独留一行。
                if result.status == "failed":
                    STATUS_BOARD.log(
                        f"{color('×', 'red')} {color(f'[{result.index:03d}]', 'blue')} "
                        f"{color(result.source.name, 'white')}   "
                        f"{color((result.error or '')[:110], 'red')}"
                    )

    # --------------------------------------------------------
    # 最终汇总
    # --------------------------------------------------------

    results.sort(key=lambda r: r.index)

    success_count = sum(
        1 for r in results if r.status == "success"
    )
    failed_encode_count = sum(
        1 for r in results if r.status == "failed"
    )

    # 收掉状态区，然后输出唯一的"编码完成"模块（含全部统计信息）
    STATUS_BOARD.close()

    # ---- 失败文件自动重试（串行跑，避开并发争抢；偶发失败多半能过）----
    if RETRY_FAILED_FILES and not STOP_REQUESTED:
        retry_targets = [r for r in results if r.status == "failed"]
        if retry_targets:
            ui_gap(3)
            print(color(ui_module_line("失败重试"), "magenta", bold=True))
            print()
            print(f"   {dim('共 %d 个失败文件；每个最多尝试 %d 次（首次 + %d 次重试），全失败就报错、不再重试' % (len(retry_targets), MAX_FILE_ATTEMPTS, MAX_FILE_ATTEMPTS - 1))}")
            _run_log("-" * 72)
            _run_log("失败重试开始 %s（%d 个，最多尝试 %d 次）"
                     % (time.strftime("%H:%M:%S"), len(retry_targets), MAX_FILE_ATTEMPTS))

            recovered = 0
            attempt = 1
            while attempt < MAX_FILE_ATTEMPTS:
                pending = [r for r in results if r.status == "failed"]
                if not pending or STOP_REQUESTED:
                    break
                attempt += 1
                print()
                print(f"   {color(f'第 {attempt} 次尝试', 'white', bold=True)}"
                      f"   {dim(f'（还有 {len(pending)} 个未成功，每次间隔 %.0f 秒）' % RETRY_PAUSE_SECONDS)}")
                _run_log(f"第 {attempt} 次尝试 {time.strftime('%H:%M:%S')}：{len(pending)} 个")
                for old in pending:
                    if STOP_REQUESTED:
                        break
                    plan = plans.get(old.index, EncodePlan(mode=RC_MODE_QUALITY,
                                                           quality=video_quality))
                    print(f"   {color(f'[{old.index:03d}]', 'blue')} {color(old.source.name, 'white')}"
                          f"   {dim('重试中…')}", flush=True)
                    time.sleep(RETRY_PAUSE_SECONDS)
                    try:
                        if output_mode == "safe":
                            new = encode_one(old.index, old.source, old.output, platform_key,
                                             codec_key, video_quality, audio_quality, plan)
                        else:
                            new = encode_one_in_place(old.index, old.source, platform_key,
                                                      codec_key, video_quality, audio_quality, plan)
                    except Exception as e:  # noqa: BLE001
                        new = Result(index=old.index, source=old.source,
                                     output=old.output or old.source, status="failed",
                                     error=f"重试时异常：{e}")
                    _log_result(new, tag=f"[第{attempt}次]")
                    if new.status != "failed":
                        recovered += 1
                        results[results.index(old)] = new
                        print(f"        {color('重试成功', 'green', bold=True)}")
                    else:
                        print(f"        {color(f'仍然失败（已试 {attempt} 次）', 'red')}")

            remaining = [r for r in results if r.status == "failed"]
            _run_log("失败重试结束：恢复 %d，仍失败 %d" % (recovered, len(remaining)))
            print()
            if remaining:
                print(f"   {color('重试结束', 'white', bold=True)}  恢复 "
                      f"{color(str(recovered), 'green', bold=True)} / 仍失败 "
                      f"{color(str(len(remaining)), 'red', bold=True)}"
                      f"   {dim(f'（已尝试 {attempt} 次，以下文件不再重试）')}")
                for r in remaining:
                    print(f"        {color(f'[{r.index:03d}]', 'blue')} "
                          f"{color(r.source.name, 'white')}   "
                          f"{color((r.error or '').splitlines()[0][:90], 'red')}")
            else:
                print(f"   {color('重试结束', 'white', bold=True)}  "
                      f"{color(f'全部恢复（{recovered} 个）', 'green', bold=True)}")

    successes = [
        r for r in results
        if r.status == "success" and r.original_info and r.output_info
    ]
    failed_results = [r for r in results if r.status == "failed"]

    ui_title("编码完成")
    print(f"   {dim('编码器')}  {color(platform['name'], 'white')} {dim('/')} "
          f"{color(encoder, 'white', bold=True)}"
          f"    {color('Q' + str(video_quality), 'white')}"
          f"{dim(' ・ ' + ('上限 ' + format_cap(VIDEO_BITRATE_CAP_KBPS) if VIDEO_BITRATE_CAP_KBPS else '仅质量档位'))}"
          f"{dim(' ・ 音频 ' + AUDIO_BITRATES[audio_quality])}")
    print(f"   {dim('结果')}    {color(f'成功 {success_count}', 'green', bold=True)}"
          f"   {color(f'失败 {failed_encode_count}', 'red' if failed_encode_count else 'white')}"
          f"   {dim(f'跳过目标 {skipped_target}　跳过已有输出 {skipped_output}　读取失败 {failed_probe}')}")

    if successes:
        total_old = total_new = 0
        total_old_dur = 0.0
        total_elapsed = 0.0

        print(f"   {dim('=' * 74)}")
        for pos, r in enumerate(successes):
            o, n = r.original_info, r.output_info
            if pos:
                print()          # 不同文件之间空一行，避免几块挤在一起
            reduction = (1 - n.size / o.size) * 100 if o.size else 0.0
            total_old += o.size
            total_new += n.size
            total_old_dur += o.duration
            total_elapsed += r.elapsed

            red_color = "green" if reduction >= 60 else ("yellow" if reduction < 30 else "white")
            mode_badge = color(plan_label(r.plan or EncodePlan(mode=RC_MODE_QUALITY)),
                               "yellow" if (r.plan and r.plan.is_capped) else "green")
            # 第 1 行：文件名（亮）+ 模式 + 体积变化+百分比（重点）
            print(f"   {color(f'[{r.index:03d}]', 'blue')} "
                  f"{color(r.source.name, 'white', bold=True)}   {mode_badge}")
            speed_note = (f"耗时 {format_duration(r.elapsed)}"
                          + (f"  {r.avg_speed:.2f}x" if r.avg_speed > 0 else ""))
            print(f"        {dim('体积')}  {format_bytes(o.size)} → "
                  f"{color(format_bytes(n.size), 'white', bold=True)}   "
                  f"{color(f'-{reduction:.1f}%', red_color, bold=True)}"
                  f"    {dim(speed_note)}")
            print(f"        {dim('视频')}  {o.video_codec} {o.width}x{o.height} {o.fps:.2f}fps "
                  f"{video_bitrate_text(o)}  →  {n.video_codec} {n.width}x{n.height} "
                  f"{video_bitrate_text(n)}")
            audio_note = (f"{o.audio_codec} {format_bitrate(o.audio_bitrate)}  →  "
                          f"{n.audio_codec} {format_bitrate(n.audio_bitrate)}")
            print(f"        {dim('音频')}  {audio_note}")
            if r.plan and r.plan.is_capped and r.plan.cap_kbps and n.video_bitrate:
                actual_kbps = n.video_bitrate / 1000
                peak_kbps = int(r.plan.cap_kbps * BITRATE_PEAK_RATIO)
                if actual_kbps > peak_kbps * 1.02:
                    warn_note = (f"码率 {actual_kbps:.0f}k 超过峰值上限（{peak_kbps}k）")
                    print(f"        {color(warn_note, 'yellow')}")
                else:
                    print(f"        {dim(f'码率 {actual_kbps:.0f}k，在上限 {r.plan.cap_kbps}k 内')}")

        total_reduction = (1 - total_new / total_old) * 100 if total_old else 0.0
        print(f"   {dim('=' * 74)}")
        print(f"   {dim('合计')}  {format_bytes(total_old)} → "
              f"{color(format_bytes(total_new), 'white', bold=True)}"
              f"   {dim('节省')} {color(format_bytes(max(0, total_old - total_new)), 'green')}"
              f"   {color(f'-{total_reduction:.1f}%', 'green', bold=True)}"
              f"    {dim(f'总时长 {format_duration(total_old_dur)}　总耗时 {format_duration(total_elapsed)}')}")

    if failed_results:
        print()
        print(color("▌ 失败明细", "red", bold=True))
        for result in failed_results:
            print(f"   {color(f'[{result.index:03d}]', 'blue')} "
                  f"{color(result.source.name, 'white')}")
            print(dim("        " + (result.error or "").replace("\n", "\n        ")))

    # 失败清单落盘：终端被误关、滚动丢失时也能查到是哪几个文件失败。
    # 写两个文件：_failed_files.txt（含原因，便于查看）；
    #             _failed_paths.txt（只有路径，一行一个，便于脚本/手工重跑）。
    fail_log = Path.cwd() / "_failed_files.txt"
    fail_paths = Path.cwd() / "_failed_paths.txt"
    try:
        if failed_results:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            detail = [f"# 失败清单（生成于 {stamp}）",
                      f"# 共 {len(failed_results)} 个文件失败",
                      "# 处理办法：修好/重跑这些文件即可（本脚本对偶发失败重跑通常就成功）",
                      ""]
            for r in failed_results:
                detail.append(f"[{r.index:03d}] {r.source}")
                detail.append("      " + (r.error or "").replace("\n", "\n      "))
                detail.append("")
            fail_log.write_text("\n".join(detail), encoding="utf-8")
            fail_paths.write_text(
                "\n".join(str(r.source) for r in failed_results) + "\n", encoding="utf-8")
            print()
            print(f"   {dim(f'失败清单已写入 {fail_log.name} / {fail_paths.name}（{len(failed_results)} 个）')}")
        else:
            # 本次没有失败：清掉上一次留下的清单，避免误以为这次也失败了
            for stale in (fail_log, fail_paths):
                if stale.exists():
                    stale.unlink()
    except Exception:
        pass

    print()
    print(color("  全部任务处理结束。", "cyan", bold=True))

    _run_log("-" * 72)
    _run_log("批次结束 %s  成功 %d / 失败 %d"
             % (time.strftime("%Y-%m-%d %H:%M:%S"), len(successes), len(failed_results)))
    for r in failed_results:
        _run_log("    失败 [%03d] %s" % (r.index, r.source))
    _run_log("=" * 72)
    print(f"   {dim(f'运行日志：{RUN_LOG_NAME}')}")

    pause()
    return 0


if __name__ == "__main__":
    while True:
        try:
            if "--concurrency-test" in sys.argv:
                ensure_console_on_windows()
                sys.exit(benchmark_concurrency(Path.cwd()))
            ensure_console_on_windows()
            sys.exit(main())
        except BackRequested:
            # 任何一步输入 b/返回：回到【上一项】继续选（更早的选择保留）
            _QUIZ_ANSWERS.pop(_QUIZ_STEP, None)      # 丢掉当前这一项的答案，重问它
            back_to = max(1, _QUIZ_STEP - 1)
            ui_gap(3)
            print(f"   {color(f'已返回第 {back_to} 项', 'yellow', bold=True)}"
                  f"   {dim('更早的选择已保留，请从这里继续')}")
            try:
                ensure_console_on_windows()
                sys.exit(main(start_step=back_to))
            except BackRequested:
                continue
            # 遗留的旧注释（已由上面的实现取代）：
            print()
            print(color("  已返回，请重新选择……", "yellow"))
            print()
            continue
        except KeyboardInterrupt:
            print("\n已中断。")
            sys.exit(130)
        except Exception as e:
            print("\n程序发生未处理异常：")
            print(e)
            pause()
            sys.exit(1)
