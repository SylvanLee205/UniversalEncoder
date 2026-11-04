# 更新记录

> 完整实测数据与设计取舍见 `docs/编码参数与问题总结.md`（32 章）；一页速览见 `docs/项目总结.md`。

| 版本 | 变更 |
|---|---|
| v1.0 | 首个可用版本：双硬件平台（QSV / NVENC）自动检测、菜单式参数、批量编码 |
| v3 | NVENC 侧调优（preset / tune / multipass 取舍） |
| v7 | 并发路数实测（1/2/3 路吞吐对比，2 路为拐点） |
| v15 | 每文件运行日志、失败重试（最多 3 次）、失败清单、`b` 逐级返回 |
| v16 | **上限模式改为 ICQ 反解调 Q**（修正 AV1 用 `-q:v` 导致体积膨胀数倍的问题） |
| v23 | 默认 preset 改为 medium(QSV)/p5(NVENC)、默认关闭自动标定、并发默认 2 路 |
| v31 | 默认上限 2.5 Mbps、质量档标签按 NEG 实测更新、修正与反解冲突的 VBR 兜底 |
| v37 | 关闭 Q 缓存（画质优先）；Q32 + 2.5 Mbps 定稿 |
| v39~v46 | 质量档 24~38 + 自定义 Q、上限 1.0~6.0 Mbps、音频 32k~128k、GOP 菜单、质量地板、NVENC QVBR + AQ/lookahead；启动优化到 0.1 秒 |
| v47~v49 | **杜比视界保留**（RPU 注入 + `dvvC` 配置盒移植）；文案统一 |
| v57~v63 | 杜比视界默认改 HLG（实测 DV 保留偏亮/+40%）；修元数据与竖屏旋转；**GOP 实测**（源 0.93~2.15 秒）并改为**自适应（相机 1 秒 / 其余 2 秒）**；默认质量 Q30；加 `-forced_idr`；元数据补写幂等化 |
| v66~v69 | 音频 128/96/64/48（默认 96k）；GOP 菜单 自适应/1/2/3；默认质量 Intel Q30 / NVENC cq36（rigaya +6）；修复 v68「不设 -g」导致的全局卡顿 |
| v70~v76 | 像素率兜底（上限喂不饱则单遍+提示）；【12 高级设置】折叠质量地板/杜比视界；DV 路径按平台取编码器；音频参数精简（保留 vbr 与 -ac）；移除 -forced_idr |
| v79~v81 | **修 faststart 根治**（两处重封装曾把 moov 挪回尾部）；B 帧五档终版（保持默认最优）；跟手定论=编码器决定（QSV 卡/x265 跟手，CTU 无关）；面板显示 faststart 与版本 |
| v82~v84 | **上限失效根治**（v70 的像素率兜底曾直接 return，用户设的上限被静默跳过；7418→2490 kbps 实测）；`.MOV` 源 + Opus 失败修复（临时文件改 .mp4）；`ICQ_CAP_TOLERANCE` 收紧到 1.05 |
| v85 | **【13 输出容器】** MP4（默认）/MKV/MOV/跟随源（MOV 强制 AAC；MKV 不下发 movflags）；**目标已存在 → 跳过**（不再记失败、不再白重试、不删源）；面板显示`质量优先（预估 X < 上限 Y）`；**「承诺-行为」自检 5 条**（上限/地板/GOP/faststart/音频，编完自动跑）；修重试分支误用旧 `result` 变量、参数预览泄漏 `-progress`、重名保护生成 `a.mp4.mp4`；清理死常量 `RULE`/`RULE_HEAVY`；版本号改为 `APP_VERSION` |
| v87 | **纯清理，零功能改动**：删 11 个死函数 + 2 个死变量（含 `describe_encoder_capabilities` / `_probe_encode_segment` 等试编码自检遗留），并迭代清掉连锁暴露的 `RC_MODE` / `RC_MODE_LABELS` / `RC_MODE_AUTO`（`RC_MODE` 是纯写不读）；共删 169 行、改 3 行。验证：死代码归零、AST `global` 扫描无异常、`_selftest_v87.py` 40/40、`_e2e_v87.py` 5 组全流程、**v86/v87 三组参数生成的 ffmpeg 命令逐字节一致**；面板版本号 → v87。详见技术文档第三十二章 |
| v86 | **自检基准改为跟随用户设置**（用户反馈：手选 GOP/音频后仍被提示"与预期不符"）。① `GOP_AUTO` 漏写 `global` → 手选任意 GOP 后自检仍按自适应的 0.8~2.6 秒判定，必然误报；② GOP 自检取消写死区间，改由 `expected_gop_seconds()` 从本次设定推导（并把 `calculate_gop` 的 48~3000 帧夹紧换算回秒）；③ 上限自检判定由 `plan.is_capped` 改为 `plan.cap_kbps`（反解重压后 mode 变 QUALITY，此前会**漏检**大文件）；④ 质量地板导致码率超上限属预期，改列「自检说明」而非「自检未达标」；⑤ 音频 copy 判定与构建端逐字对齐（int 截断 + MOV 不走 copy）；⑥ 面板版本号补刷为 v86。测试：`_selftest_v86.py` 40/40（含 4 条 v85 必败回归用例）、`_e2e_v86.py` 五组全流程（新增"手选 3 秒 GOP"用例） |
| **v88** | **修「N 卡机器上误报 QSV 可用」**（用户反馈：87 版在 NVIDIA 设备上竟检测到 QSV 可用）。根因两层：① ffmpeg 的 `-encoders` 是**编译期**信息，官方 gyan 构建默认 `--enable-libvpl`，任何机器都会列出 `av1_qsv`/`hevc_qsv`；② v87 的 `main()` 走「快速路径」，只要见到 `*_qsv` 就认定 Intel 可用，**一次都没查显卡**，而真正查显卡的 `detect_intel()` 只在快速路径空手时才被调用 —— 两条路都到不了它。修复：新增 `real_gpu_adapters()`（`EnumDisplayDevicesW` 枚举真实适配器，按 PCI VEN 号判厂商 8086/10DE，剔除 GameViewer/IddCx/Parsec 等虚拟显示器，实测 **0.02 秒**，比原 PowerShell CIM 的 0.30 秒快一个数量级）；平台检测收敛为**唯一入口** `detect_platforms()`，判据改为「显卡存在 ∧ ffmpeg 有对应编码器」；`detect_platforms()` 同时返回**已排除平台的原因**，界面用 `×` 行说清「没有 Intel 显卡」还是「有卡但缺 QSV 编码器」；`_platform_cache.json` 键加入显卡指纹（换卡/eGPU 不再复用旧结论）；去掉 `benchmark_concurrency()` 里同样的「编码器列表兜底」；HEVC 也做 3 帧试编码（实测 0.78 秒，进程内缓存只付一次），兜住「有 Intel 卡但 oneVPL 会话起不来（MFX -9）」；`detect_nvenc_hardware()` 在 `nvidia-smi` 缺席时用枚举名兜底世代识别。测试：`_selftest_v88.py` **52/52**（新增 12 条平台检测用例，含纯 N 卡/双显卡/纯 Intel/枚举失败四种形态）、`_e2e_v88.py` 5 组全流程 |
