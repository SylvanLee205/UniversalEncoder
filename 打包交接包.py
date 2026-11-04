#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包交接包（双击即可运行）

把项目里"该给人看的东西"打成一个 zip，放到桌面。
自动排除：视频素材（8.8 GB）、__pycache__、测试临时产物 —— 它们对理解代码零帮助。

用法：
  双击本文件          → 生成 桌面\\UniversalEncoder_交接包_vNN.zip
  传 -r 参数          → 连同归档\\测试素材 一起打包（8.8 GB，很慢，一般不需要）
"""
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"

# 永远排除：可再生物
ALWAYS_SKIP_NAMES = {"__pycache__", ".DS_Store", "_env_cache.json"}
# 默认排除：体积大、对理解代码无帮助
DEFAULT_SKIP_DIRS = {"测试素材"}
# 永远排除的目录名：git 仓库副本、完整备份。
# 2026-11-04 踩坑：桌面上的 UniversalEncoder-repo\ 与本目录同级时，有人把它
# 复制进项目里，交接包一下子从 21 个文件涨到 270 个（5.6 MB），全是 .git 对象，
# 对"接手看懂代码"零帮助 —— 而且仓库内容与根目录程序重复。
ALWAYS_SKIP_DIRS = {".git", "UniversalEncoder-repo", "UniversalEncoder_备份_20261019"}


def should_skip(path: Path, include_media: bool) -> bool:
    if path.name in ALWAYS_SKIP_NAMES:
        return True
    if path.name.startswith("_tmp_v"):
        return True
    # 不要把上一版的交接包再装进来（嵌套 zip），否则每发一版体积就翻一倍。
    if path.suffix.lower() == ".zip" and path.name.startswith("UniversalEncoder_交接包"):
        return True
    for part in path.parts:
        if part in ALWAYS_SKIP_DIRS:
            return True
        if part in DEFAULT_SKIP_DIRS and not include_media:
            return True
    return False


def main() -> int:
    include_media = "-r" in sys.argv or "--include-media" in sys.argv

    version = "vNN"
    for p in HERE.glob("UniversalEncoder_v*.py"):
        version = p.stem.split("_")[-1]
        break

    out = DESKTOP / f"UniversalEncoder_交接包_{version}.zip"
    if out.exists():
        try:
            out.unlink()
        except OSError as e:
            print(f"无法覆盖已存在的包：{e}")
            return 1

    n_files = 0
    total = 0
    skipped = 0
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(HERE.rglob("*")):
                if not p.is_file():
                    continue
                if should_skip(p, include_media):
                    skipped += 1
                    continue
                z.write(p, str(Path(HERE.name) / p.relative_to(HERE)))
                n_files += 1
                total += p.stat().st_size
    except OSError as e:
        print(f"打包失败：{e}")
        return 1

    print("=" * 60)
    print("交接包已生成")
    print("=" * 60)
    print(f"  位置      {out}")
    print(f"  文件数    {n_files}")
    print(f"  原始体积  {total/1024:.0f} KB")
    print(f"  压缩后    {out.stat().st_size/1024:.0f} KB")
    print(f"  排除      {skipped} 个文件/目录"
          f"{'（含 8.8 GB 测试素材）' if not include_media else ''}")
    print()
    print("包里有什么：")
    with zipfile.ZipFile(out) as z:
        for name in sorted(z.namelist()):
            if name.endswith("/"):
                continue
            print(f"  {z.getinfo(name).file_size:>9,}  {name}")
    print()
    print("给接手的人：让他先读包里的 README.md（项目入口索引），")
    print("再读 归档\\文档\\交接_HANDOVER.md 的「⚡ 30 秒速览」。")
    print()
    input("按回车关闭…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
