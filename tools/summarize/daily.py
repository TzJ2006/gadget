"""Pipeline orchestration commands for the daily summarization workflow.

Provides subcommand entry points: export, export_past, merge, legacy, deploy,
and config (show/init).  Extracted from daily_summary.py.
"""

import getpass
import json
import logging
import platform
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from common.io import atomic_write as _atomic_write
from common.hugo import run_hugo_update
from common.llm import ChunkTimeoutError, cleanup_chunk_cache as _cleanup_chunk_cache
from common.paths import LOGS_DIR, REPORTS_DIR, CACHE_DIR
from common.site_staging import resolve_site_content_dir, write_site_content

from .config import _load_config, _resolve_output_dir, _get_device_name, _CONFIG_PATH, _REPO_CONFIG_PATH, _cached_config
from .remote import _rclone_upload, _rclone_upload_dir, _rclone_download_logs, _rclone_download_reports, _find_rclone
from .parsers import (discover_all_dates, parse_claude_code, parse_codex,
                      parse_chatgpt_export, parse_generic, collect_conversations)
from .usage import (fetch_ccusage,
                    load_ccusage_for_date, _merge_token_usages, _refresh_usage_snapshots)
from .summarizer import (SUMMARY_PROMPT, MERGE_PROMPT_PREFIX, MERGE_DEVICE_SUMMARY_PREFIX,
                         _call_summarize, format_conversations, chunk_conversations,
                         _build_summary_prompt, _call_single_summarize, _get_device_label)
from .formatter import (generate_markdown, _sort_report_by_importance, save_report,
                        generate_hugo_post, _DEFAULT_REPORTS_DIR)

# ─── Default directories ────────────────────────────────────────────
_DEFAULT_LOGS_DIR = LOGS_DIR / "summarize"
_DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"
_DEFAULT_CACHE_DIR = CACHE_DIR / "summarize"


# ─── Helpers ─────────────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> date:
    """解析日期字符串，None 时返回今天。"""
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            print(f"[error] 日期格式无效: {date_str}，请使用 YYYY-MM-DD")
            sys.exit(1)
    return date.today()


# ─── 5. 子命令入口 ─────────────────────────────────────────────────

def cmd_export(args):
    """Phase 1: 本地导出对话 log（可选单设备 AI 总结）。"""
    target_date = _parse_date(args.date)
    print(f"[info] 目标日期: {target_date.isoformat()}")

    # 提前计算输出路径，即使没有会话也可以刷新 usage 快照
    logs_dir = _resolve_output_dir(args.output, "SUMMARIZE_LOGS_DIR",
                                   "logs_dir", _DEFAULT_LOGS_DIR)
    logs_dir.mkdir(parents=True, exist_ok=True)

    conversations = collect_conversations(target_date, args.chatgpt, args.generic)

    if not conversations:
        print(f"[warn] {target_date.isoformat()} 没有找到任何对话记录")
        if not getattr(args, '_skip_ccusage', False):
            _refresh_usage_snapshots(logs_dir)
        return False

    total_msgs = sum(len(c["messages"]) for c in conversations)
    print(f"[info] 共 {len(conversations)} 个会话，{total_msgs} 条消息")

    # 设备信息
    device_name = _get_device_name()
    device_info = {
        "device_name": device_name,
        "hostname": platform.node(),
        "platform": sys.platform,
        "username": getpass.getuser(),
    }

    out_path = logs_dir / f"{target_date.isoformat()}_{device_name}.json"

    # 读取已有文件的 merged 设备列表
    existing_data = None
    existing_merged_devices = []
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            existing_merged_devices = existing_data.get("_merged_devices", [])
        except (OSError, json.JSONDecodeError):
            pass

    # 从已有文件恢复 per-device summaries
    device_summaries = {}
    if existing_data is not None:
        old_ds = existing_data.get("device_summary")
        if isinstance(old_ds, dict):
            # 新格式：{device_name: summary_dict, ...}
            # 过滤掉含 parse_error 等非设备 key（安全起见检查 value 类型）
            for k, v in old_ds.items():
                if isinstance(v, dict):
                    device_summaries[k] = v

    # 可选：单设备 AI 总结（已 summarize 的设备跳过 API 调用）
    if args.summarize:
        if device_name in existing_merged_devices:
            print(f"[info] 设备 {device_name} 已 summarize，跳过 API 调用")
        else:
            try:
                summary_result = _call_summarize(args.api, conversations, target_date,
                                                 timeout=args.timeout)
            except ChunkTimeoutError as e:
                print(f"[warn] {e}")
                summary_result = None
            if summary_result:
                _sort_report_by_importance(summary_result)
                device_summaries[device_name] = summary_result

    # Token 用量统计已迁移至独立 per-source usage 文件，不再内嵌到 log 中
    # 见 _refresh_usage_snapshots() / fetch_source_usage()

    # 构造 export log
    export_data = {
        "version": 1,
        "date": target_date.isoformat(),
        "device": device_info,
        "conversations": conversations,
        "device_summary": device_summaries if device_summaries else None,
        "token_usage": None,
    }

    # 更新已合并设备列表
    merged_devices = list(existing_merged_devices)
    if args.summarize and device_name not in merged_devices:
        merged_devices.append(device_name)
    export_data["_merged_devices"] = merged_devices

    # 末尾设备标识（tail 时快速可见）
    if merged_devices:
        export_data["_source_device"] = (
            f"merged <{', '.join(merged_devices)}>"
        )
    else:
        export_data["_source_device"] = (
            f"{device_name} ({sys.platform}, "
            f"{getpass.getuser()}@{platform.node()}) "
            f"| summarized: false"
        )

    # 若已有同名 log 文件，合并对话（按 source+project+timestamp 去重）
    if existing_data is not None:
        old_convs = existing_data.get("conversations", [])
        seen = {(c.get("source"), c.get("project"), c.get("timestamp"))
                for c in conversations}
        merged = list(conversations)
        added = 0
        for c in old_convs:
            key = (c.get("source"), c.get("project"), c.get("timestamp"))
            if key not in seen:
                merged.append(c)
                seen.add(key)
                added += 1
        export_data["conversations"] = merged
        print(f"[info] 检测到已有 log，合并: 新 {len(conversations)} + 旧增量 {added} = {len(merged)} 个会话")

    # auto-finalize: 非今天 + 无新增对话 → 标记 finalized，避免后续重复扫描
    if existing_data is not None:
        old_count = len(existing_data.get("conversations", []))
        new_count = len(export_data["conversations"])
        if target_date != date.today() and new_count == old_count:
            export_data["_finalized"] = True
            print(f"[info] 对话数量无变化 ({old_count})，标记为 finalized")
        else:
            export_data["_finalized"] = False
    else:
        # 首次导出非今天的日期，直接 finalize
        if target_date != date.today():
            export_data["_finalized"] = True

    _atomic_write(out_path, json.dumps(export_data, ensure_ascii=False, indent=2))
    finalized = export_data.get("_finalized", False)
    print(f"[ok] 对话 log 已导出: {out_path}" + (" (finalized)" if finalized else ""))

    # 批量导出时跳过逐文件上传，由 cmd_export_past 末尾一次性批量上传整个目录
    if not getattr(args, '_skip_upload', False):
        _rclone_upload(out_path, subdirectory="logs")

    # 刷新全量 ccusage / codex_usage 快照（批量导出时由 cmd_export_past 统一调用，跳过此处）
    if not getattr(args, '_skip_ccusage', False):
        _refresh_usage_snapshots(logs_dir)

    return True


def cmd_export_past(args):
    """导出所有过去未导出的日期的对话 log。"""
    device_name = _get_device_name()
    logs_dir = _resolve_output_dir(getattr(args, "output", None),
                                   "SUMMARIZE_LOGS_DIR", "logs_dir",
                                   _DEFAULT_LOGS_DIR)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 发现所有存在对话的日期
    print("[info] 扫描所有对话日期...")
    all_dates = discover_all_dates()
    if not all_dates:
        print("[warn] 未发现任何对话记录")
        return

    # 找出已导出的日期及其 finalized 状态
    exported_dates = {}  # date -> finalized (bool)
    for log_file in logs_dir.glob(f"*_{device_name}.json"):
        # 文件名格式: YYYY-MM-DD_device.json
        date_part = log_file.stem.rsplit(f"_{device_name}", 1)[0]
        try:
            d = date.fromisoformat(date_part)
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                exported_dates[d] = data.get("_finalized", False)
            except (OSError, json.JSONDecodeError):
                exported_dates[d] = False
        except ValueError:
            continue

    force = getattr(args, "force", False)
    new_dates = sorted(all_dates - set(exported_dates.keys()))
    stale_dates_set = {d for d, fin in exported_dates.items()
                       if not fin and d in all_dates}
    finalized_count = sum(1 for fin in exported_dates.values() if fin)

    if force:
        pending_dates = sorted(all_dates)
    else:
        pending_dates = sorted(set(new_dates) | stale_dates_set)

    if not pending_dates:
        print(f"[info] 所有 {len(all_dates)} 个日期均已导出且 finalized，无需操作")
        return

    if force:
        print(f"[info] --force 模式：强制重新导出全部 {len(pending_dates)} 个日期")
    else:
        print(f"[info] 共 {len(all_dates)} 个日期有对话，"
              f"已 finalized {finalized_count} 个，"
              f"待更新 {len(stale_dates_set)} 个，"
              f"新增 {len(new_dates)} 个")

    # 逐日期调用 cmd_export（跳过每日 ccusage 调用 + 逐文件上传，最后统一处理）
    args._skip_ccusage = True
    args._skip_upload = True
    exported_count = 0
    skipped_empty_count = 0
    for i, d in enumerate(pending_dates, 1):
        print(f"\n{'='*60}")
        label = "更新" if d in stale_dates_set else "导出"
        print(f"[info] ({i}/{len(pending_dates)}) {label} {d.isoformat()}")
        print(f"{'='*60}")
        args.date = d.isoformat()
        if cmd_export(args):
            exported_count += 1
        else:
            skipped_empty_count += 1

    # 批量导出完成后，统一刷新一次 ccusage / codex_usage 快照
    _refresh_usage_snapshots(logs_dir)

    # 一次性批量上传整个 logs 目录（幂等，比逐文件快且稳）
    _rclone_upload_dir(logs_dir, subdirectory="logs")

    print(f"\n[ok] 批量导出完成，共处理 {len(pending_dates)} 个日期，"
          f"成功导出 {exported_count} 个，空会话跳过 {skipped_empty_count} 个")


def _merge_single_date(d: str, base_cmd: list[str], date_files: dict[str, list[Path]],
                       chunk_timeout: int, log_dir: Path) -> tuple[str, bool, str]:
    """Worker: merge a single date in a subprocess, logging output to file.

    Returns (date, success, log_path).
    """
    total_size = sum(p.stat().st_size for p in date_files.get(d, []))
    est_chunks = max(1, total_size // 150000 + 1)
    proc_timeout = chunk_timeout * (est_chunks + 1) + 60

    log_file = log_dir / f"merge_{d}.log"
    cmd = base_cmd + ["--date", d]
    try:
        with open(log_file, "w", encoding="utf-8") as flog:
            flog.write(f"[cmd] {' '.join(cmd)}\n")
            flog.write(f"[info] ~{total_size // 1024}KB, ~{est_chunks} chunks, "
                       f"timeout={proc_timeout}s\n\n")
            result = subprocess.run(cmd, timeout=proc_timeout,
                                    stdout=flog, stderr=subprocess.STDOUT)
        return (d, result.returncode == 0, str(log_file))
    except subprocess.TimeoutExpired:
        with open(log_file, "a", encoding="utf-8") as flog:
            flog.write(f"\n[error] 处理超时 ({proc_timeout}s)\n")
        return (d, False, str(log_file))
    except Exception as exc:
        with open(log_file, "a", encoding="utf-8") as flog:
            flog.write(f"\n[error] {exc}\n")
        return (d, False, str(log_file))


def _cmd_merge_sync_all(args):
    """--sync-all: 下载所有 log + reports，按日期分组，并行 spawn 子进程处理。"""
    local_logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR",
                                         "logs_dir", _DEFAULT_LOGS_DIR)
    synced = _rclone_download_logs(None, local_logs_dir)
    if not synced:
        print("[warn] 未同步到任何 log 文件")
        sys.exit(0)

    # 同步远端 reports（已 finalized 的报告可直接复用，无需重新 merge）
    reports_dir = _resolve_output_dir(args.output, "SUMMARIZE_REPORTS_DIR",
                                      "reports_dir", _DEFAULT_REPORTS_DIR)
    _rclone_download_reports(reports_dir)

    # 按日期分组（文件名格式: YYYY-MM-DD_device.json）
    date_files: dict[str, list[Path]] = {}
    for p in synced:
        stem = p.stem
        if len(stem) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", stem[:10]):
            date_files.setdefault(stem[:10], []).append(p)

    if not date_files:
        print("[warn] 无法从文件名中提取日期")
        sys.exit(0)

    dates_sorted = sorted(date_files.keys())
    print(f"[info] 共发现 {len(dates_sorted)} 天的 log: {', '.join(dates_sorted)}")

    # --before：只处理早于该日期的数据（ISO 日期串可直接字典序比较），
    # 用于排除当天未完成的记录（auto 会传 --before <today>）。
    before = getattr(args, "before", None)
    if before:
        skipped = [d for d in dates_sorted if d >= before]
        dates_sorted = [d for d in dates_sorted if d < before]
        if skipped:
            print(f"[info] --before {before}: 跳过 {len(skipped)} 天 (>= {before}): {', '.join(skipped)}")
        if not dates_sorted:
            print(f"[info] --before {before}: 没有早于该日期的待处理 log")
            return

    # 跳过已 finalized 的报告（未 finalized 的重新处理）
    force = getattr(args, "force", False)
    dates_to_process = []
    for d in dates_sorted:
        report_json = reports_dir / f"{d}.json"
        if report_json.exists() and not force:
            try:
                with open(report_json, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("_finalized", False):
                    print(f"[info] 跳过 {d}（报告已 finalized）")
                    continue
                else:
                    print(f"[info] {d} 报告存在但未 finalized，重新处理")
            except (OSError, json.JSONDecodeError):
                print(f"[info] {d} 报告存在但无法读取，重新处理")
        dates_to_process.append(d)

    if not dates_to_process:
        print("[info] 所有日期均已 finalized，无需处理（使用 --force 强制重新生成）")
        return

    workers = max(1, int(getattr(args, "workers", 1) or 1))
    workers = min(workers, len(dates_to_process))
    print(f"[info] 需处理 {len(dates_to_process)} 天: {', '.join(dates_to_process)}")
    print(f"[info] 使用 {workers} 个 worker 并行处理")

    chunk_timeout = args.timeout

    # 子进程 log 输出目录
    log_dir = LOGS_DIR / "summarize" / "merge_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 构建子进程参数
    base_cmd = [sys.executable, "-m", "summarize.cli",
                "merge", "--sync", "--timeout", str(chunk_timeout)]
    if args.api:
        base_cmd += ["--api", args.api]
    if args.output:
        base_cmd += ["--output", args.output]
    if getattr(args, "no_cache", False):
        base_cmd += ["--no-cache"]
    if getattr(args, "force", False):
        base_cmd += ["--force"]

    ok, fail = 0, 0
    results: dict[str, bool] = {}

    if workers <= 1:
        # 顺序处理（保持原有行为）
        iter_dates = dates_to_process
        if tqdm is not None:
            iter_dates = tqdm(dates_to_process, desc="Merging", unit="day")
        for d in iter_dates:
            _, success, log_path = _merge_single_date(
                d, base_cmd, date_files, chunk_timeout, log_dir)
            results[d] = success
            status = "✓" if success else "✗"
            if tqdm is not None:
                iter_dates.set_postfix_str(f"{d} {status}")
            else:
                print(f"  {status} {d}  (log: {log_path})")
            if success:
                ok += 1
            else:
                fail += 1
    else:
        # 并行处理
        pbar = None
        if tqdm is not None:
            pbar = tqdm(total=len(dates_to_process), desc="Merging", unit="day")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_merge_single_date, d, base_cmd,
                                date_files, chunk_timeout, log_dir): d
                for d in dates_to_process
            }
            for future in as_completed(futures):
                d, success, log_path = future.result()
                results[d] = success
                status = "✓" if success else "✗"
                if pbar is not None:
                    pbar.update(1)
                    pbar.set_postfix_str(f"{d} {status}")
                else:
                    print(f"  {status} {d}  (log: {log_path})")
                if success:
                    ok += 1
                else:
                    fail += 1

        if pbar is not None:
            pbar.close()

    # 打印汇总
    print(f"\n[ok] sync-all 完成: 成功 {ok}, 失败 {fail}, 共 {len(dates_to_process)} 天")
    print(f"[info] 子进程日志目录: {log_dir}")
    if fail > 0:
        failed_dates = [d for d, s in results.items() if not s]
        print(f"[warn] 失败日期: {', '.join(failed_dates)}")
        print(f"[info] 查看日志: cat {log_dir}/merge_<date>.log")

    # 全部处理完成后统一部署
    if args.deploy and ok > 0:
        print(f"\n[info] 开始批量部署 {ok} 天的报告...")
        hugo_site = Path(args.hugo_site)
        if not hugo_site.exists():
            print(f"[error] Hugo 站点目录不存在: {hugo_site}")
            return
        for d in dates_to_process:
            report_md = reports_dir / f"{d}.md"
            if report_md.exists():
                try:
                    file_date = date.fromisoformat(d)
                    generate_hugo_post(report_md.read_text(encoding="utf-8"), file_date,
                                       hugo_site, force=getattr(args, "force", False))
                except Exception as e:
                    print(f"[warn] 部署 {d} 失败: {e}")
        run_hugo_update(hugo_site)


def cmd_merge(args):
    """Phase 2: 合并多设备 log 文件，生成最终汇总日报。"""
    # --sync-all 或 --sync 无 --date: 全量同步，每天单独处理
    if args.sync_all or (args.sync and not args.date):
        return _cmd_merge_sync_all(args)

    log_files = list(args.log_files)

    # --sync: 从远端下载 log 文件（此处必有 --date）
    if args.sync:
        sync_date = _parse_date(args.date)
        local_logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR",
                                             "logs_dir", _DEFAULT_LOGS_DIR)
        synced = _rclone_download_logs(sync_date, local_logs_dir)

        # 合并 CLI 指定的文件和同步下载的文件（按 resolved path 去重）
        seen_paths = {Path(f).resolve() for f in log_files}
        for p in synced:
            if p.resolve() not in seen_paths:
                log_files.append(str(p))
                seen_paths.add(p.resolve())

    if not log_files:
        print("[error] 无 log 文件可合并。请指定文件路径或使用 --sync 从远端下载")
        sys.exit(1)

    # 读取所有 log 文件
    all_conversations = []
    device_summaries = []
    device_token_usages = []
    inferred_date = None
    all_sources_finalized = True

    for filepath in log_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                log_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] 读取 {filepath} 失败: {e}, 跳过")
            continue

        device = log_data.get("device", {})
        log_date = log_data.get("date")
        device_label = device.get("device_name") or device.get("hostname", "unknown")
        print(f"[info] 加载 log: {filepath} (设备: {device_label})")

        # 跟踪源 log 的 finalized 状态
        if not log_data.get("_finalized", True):
            all_sources_finalized = False

        if inferred_date is None and log_date:
            inferred_date = log_date

        # 为每个 conversation 添加 device 来源信息
        for conv in log_data.get("conversations", []):
            conv["device"] = device
            all_conversations.append(conv)

        # 收集已有的 device_summary（兼容新旧格式）
        ds = log_data.get("device_summary")
        if ds:
            if "_merged_devices" in log_data:
                # 新格式: {device_name: summary_dict, ...}
                for dev_name, summary in ds.items():
                    if isinstance(summary, dict) and summary.get("parse_error"):
                        # JSON 解析失败，保留原始文本供 merge LLM 理解
                        device_summaries.append({
                            "device": dev_name,
                            "summary": None,
                            "raw_text": summary.get("raw_response", ""),
                        })
                    elif isinstance(summary, dict):
                        device_summaries.append({
                            "device": dev_name,
                            "summary": summary,
                        })
            else:
                # 旧格式: flat summary dict
                if ds.get("parse_error"):
                    device_summaries.append({
                        "device": device_label,
                        "summary": None,
                        "raw_text": ds.get("raw_response", ""),
                    })
                else:
                    device_summaries.append({
                        "device": device_label,
                        "summary": ds,
                    })

        # 收集 token_usage
        tu = log_data.get("token_usage")
        if tu:
            device_token_usages.append({
                "device": device_label,
                "device_name": device_label,
                "usage": tu,
            })

    if not all_conversations:
        print("[warn] 没有找到任何对话记录")
        sys.exit(0)

    # 确定目标日期
    target_date = _parse_date(args.date) if args.date else (
        date.fromisoformat(inferred_date) if inferred_date else date.today()
    )

    total_msgs = sum(len(c["messages"]) for c in all_conversations)
    print(f"[info] 目标日期: {target_date.isoformat()}")
    print(f"[info] 共 {len(all_conversations)} 个会话，{total_msgs} 条消息，来自 {len(log_files)} 个 log 文件")

    # 检查已有报告是否已 finalized → 跳过（除非 --force 或 --no-cache）
    force = getattr(args, 'force', False)
    output_dir = _resolve_output_dir(args.output, "SUMMARIZE_REPORTS_DIR",
                                     "reports_dir", _DEFAULT_REPORTS_DIR)
    if not force and not getattr(args, "no_cache", False):
        existing_report_path = output_dir / f"{target_date.isoformat()}.json"
        if existing_report_path.exists():
            try:
                with open(existing_report_path, "r", encoding="utf-8") as f:
                    existing_report = json.load(f)
                if existing_report.get("_finalized", False):
                    print(f"[info] {target_date} 报告已 finalized，跳过（使用 --force 强制重新生成）")
                    return
            except (OSError, json.JSONDecodeError):
                pass

    # 构建 merge prompt 上下文
    extra_context = ""
    if device_summaries:
        extra_context = MERGE_DEVICE_SUMMARY_PREFIX
        for ds in device_summaries:
            extra_context += f"\n--- Device {ds['device']} preliminary summary ---\n"
            if ds.get("summary") is not None:
                extra_context += json.dumps(ds["summary"], ensure_ascii=False, indent=2)
            else:
                # JSON 解析失败的原始文本，让 merge LLM 直接理解
                extra_context += ("(Note: the following is the raw LLM response that failed JSON parsing. "
                                  "Please extract useful information from it.)\n")
                extra_context += ds.get("raw_text", "")
            extra_context += "\n"
        extra_context += "\n--- Full conversation logs below ---\n\n"

    device_labels = sorted(set(_get_device_label(c) for c in all_conversations))
    summary_prompt = _build_summary_prompt(device_labels if len(device_labels) > 1 else None)
    prompt_prefix = MERGE_PROMPT_PREFIX + summary_prompt

    # AI 总结缓存：避免重复调用 API
    logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR",
                                   "logs_dir", _DEFAULT_LOGS_DIR)
    cache_dir = _DEFAULT_CACHE_DIR
    cache_path = cache_dir / f"{target_date.isoformat()}.json"

    use_cache = not getattr(args, "no_cache", False)
    chunk_cache_dir = (_DEFAULT_CACHE_DIR / "chunks" / target_date.isoformat()) if use_cache else None

    if use_cache and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            print(f"[info] 使用已缓存的 AI 总结: {cache_path}")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] 缓存读取失败: {e}，重新调用 API")
            report = None
    else:
        report = None

    if report is None:
        # 调 API 生成总结
        try:
            report = _call_summarize(args.api, all_conversations, target_date,
                                     prompt_prefix=prompt_prefix, extra_context=extra_context,
                                     timeout=args.timeout,
                                     chunk_cache_dir=chunk_cache_dir)
        except ChunkTimeoutError as e:
            print(f"[error] {e}")
            sys.exit(1)

        # 保存缓存
        try:
            _atomic_write(cache_path, json.dumps(report, ensure_ascii=False, indent=2))
            print(f"[info] AI 总结已缓存: {cache_path}")
        except OSError as e:
            print(f"[warn] 缓存写入失败: {e}")

        # 最终报告缓存成功后，清理 chunk 缓存
        if chunk_cache_dir:
            _cleanup_chunk_cache(chunk_cache_dir)

    _sort_report_by_importance(report)

    # 合并多设备 token 用量，按来源分组（优先独立快照，旧 log 内嵌数据兜底）
    standalone_usages = load_ccusage_for_date(logs_dir, target_date)

    by_source_inputs = {}
    for u in standalone_usages:
        by_source_inputs.setdefault(u.get("_source", "unknown"), []).append(u)

    standalone_claude_devices = {
        u["device_name"] for u in by_source_inputs.get("claude_code", [])}
    for inline in device_token_usages:
        dev = inline.get("device_name", inline.get("device", "unknown"))
        if dev not in standalone_claude_devices:
            by_source_inputs.setdefault("claude_code", []).append(inline)

    token_usage_by_source = {
        source: _merge_token_usages(items)
        for source, items in by_source_inputs.items() if items
    }
    if token_usage_by_source:
        report["token_usage_by_source"] = token_usage_by_source
        # backward-compat aliases consumed by formatter/charts/weekly/monthly
        if "claude_code" in token_usage_by_source:
            report["token_usage"] = token_usage_by_source["claude_code"]
        if "codex" in token_usage_by_source:
            report["codex_token_usage"] = token_usage_by_source["codex"]

    # auto-finalize: 非今天的日期直接 finalize（过去的日期不会再有新对话）
    # 注：之前要求 all_sources_finalized，但源 log 的 finalized 状态取决于各设备
    # 是否重新 export，不应阻塞报告 finalization
    if target_date < date.today():
        report["_finalized"] = True
        if not all_sources_finalized:
            print(f"[info] 日期已过，报告标记为 finalized（部分源 log 未 finalized，不影响报告）")
        else:
            print(f"[info] 日期已过且所有源 log 均 finalized，报告标记为 finalized")
    else:
        report["_finalized"] = False

    # 生成并保存报告（usage 卡片直接内嵌在 Markdown 中，无需图表文件）
    markdown = generate_markdown(report, target_date)
    save_report(report, markdown, target_date, output_dir)

    _rclone_upload(output_dir / f"{target_date.isoformat()}.md",
                   output_dir / f"{target_date.isoformat()}.json",
                   subdirectory="reports")

    # Hugo 部署
    if args.deploy:
        hugo_site = Path(args.hugo_site)
        if not hugo_site.exists():
            print(f"[error] Hugo 站点目录不存在: {hugo_site}")
            sys.exit(1)

        generate_hugo_post(markdown, target_date, hugo_site, api=args.api,
                           force=getattr(args, "force", False))

        run_hugo_update(hugo_site)


def cmd_legacy(args):
    """兼容旧用法：单机一步完成（等同于 export --summarize 的效果）。"""
    target_date = _parse_date(args.date)
    print(f"[info] 目标日期: {target_date.isoformat()}")

    conversations = collect_conversations(target_date, args.chatgpt, args.generic)

    if not conversations:
        print(f"[warn] {target_date.isoformat()} 没有找到任何对话记录")
        sys.exit(0)

    total_msgs = sum(len(c["messages"]) for c in conversations)
    print(f"[info] 共 {len(conversations)} 个会话，{total_msgs} 条消息")

    # 调用 AI 总结
    logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR", "logs_dir",
                                   _DEFAULT_LOGS_DIR)
    use_cache = not getattr(args, "no_cache", False)
    chunk_cache_dir = (_DEFAULT_CACHE_DIR / "chunks" / target_date.isoformat()) if use_cache else None

    try:
        report = _call_summarize(args.api, conversations, target_date,
                                 timeout=args.timeout,
                                 chunk_cache_dir=chunk_cache_dir)
    except ChunkTimeoutError as e:
        print(f"[error] {e}")
        sys.exit(1)

    # chunk 缓存在总结完成后清理
    if chunk_cache_dir:
        _cleanup_chunk_cache(chunk_cache_dir)

    _sort_report_by_importance(report)

    # Token 用量统计：优先独立 per-source 快照，兜底调用 fetch_ccusage（Claude Code）
    standalone_usages = load_ccusage_for_date(logs_dir, target_date)
    by_source_inputs = {}
    for u in standalone_usages:
        by_source_inputs.setdefault(u.get("_source", "unknown"), []).append(u)

    if not by_source_inputs.get("claude_code"):
        fetched = fetch_ccusage(target_date)
        if fetched:
            by_source_inputs.setdefault("claude_code", []).append(
                {"device_name": _get_device_name(), "usage": fetched})

    token_usage_by_source = {
        s: _merge_token_usages(items)
        for s, items in by_source_inputs.items() if items}
    if token_usage_by_source:
        report["token_usage_by_source"] = token_usage_by_source
        if "claude_code" in token_usage_by_source:
            report["token_usage"] = token_usage_by_source["claude_code"]
        if "codex" in token_usage_by_source:
            report["codex_token_usage"] = token_usage_by_source["codex"]

    # 生成并保存报告
    output_dir = _resolve_output_dir(args.output, "SUMMARIZE_REPORTS_DIR",
                                     "reports_dir", _DEFAULT_REPORTS_DIR)
    markdown = generate_markdown(report, target_date)
    save_report(report, markdown, target_date, output_dir)

    _rclone_upload(output_dir / f"{target_date.isoformat()}.md",
                   output_dir / f"{target_date.isoformat()}.json",
                   subdirectory="reports")


def cmd_deploy(args):
    """批量部署报告到 Hugo bugJournal（默认只部署尚未上线的报告）。"""
    from io import StringIO
    from common.translation import count_translation_chunks

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    reports_dir = _resolve_output_dir(getattr(args, 'reports_dir', None),
                                      "SUMMARIZE_REPORTS_DIR",
                                      "reports_dir", _DEFAULT_REPORTS_DIR)
    hugo_site = Path(args.hugo_site)

    if not hugo_site.exists():
        print(f"[error] Hugo 站点目录不存在: {hugo_site}", file=sys.stderr)
        sys.exit(1)

    if not reports_dir.exists():
        print(f"[error] 报告目录不存在: {reports_dir}", file=sys.stderr)
        sys.exit(1)

    # Collect target markdown files
    if args.date:
        target_date = _parse_date(args.date)
        md_files = [reports_dir / f"{target_date.isoformat()}.md"]
        md_files = [f for f in md_files if f.exists()]
        if not md_files:
            print(f"[warn] 未找到 {target_date.isoformat()} 的报告", file=sys.stderr)
            sys.exit(0)
    else:
        md_files = sorted(reports_dir.glob("*.md"))
        if not md_files:
            print("[warn] 报告目录中没有 .md 文件", file=sys.stderr)
            sys.exit(0)

    # Determine which reports are already deployed to Hugo
    hugo_content_dir = resolve_site_content_dir(hugo_site, "bugJournal", "daily")
    deployed_dates: set[str] = set()
    if hugo_content_dir.exists():
        for p in hugo_content_dir.glob("*.md"):
            try:
                date.fromisoformat(p.stem)
                deployed_dates.add(p.stem)
            except ValueError:
                pass

    # Filter: only deploy reports not yet on the website (unless --force)
    force = getattr(args, 'force', False)
    to_deploy = []
    skipped = 0
    non_date_skipped = 0
    for md_file in md_files:
        try:
            file_date = date.fromisoformat(md_file.stem)
        except ValueError:
            non_date_skipped += 1
            continue
        if not force and md_file.stem in deployed_dates:
            skipped += 1
            continue
        to_deploy.append((md_file, file_date))

    if not to_deploy:
        # 已 staged ≠ 已发布：仍要跑一次 Hugo 构建 + push，确保站点是最新的
        print("[ok] 所有报告均已 staged，直接运行 Hugo 构建/发布")
        run_hugo_update(hugo_site)
        return

    # Set up log file
    log_dir = _DEFAULT_REPORTS_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "deploy.log"
    log_file = open(log_path, "w", encoding="utf-8")

    def log(msg: str) -> None:
        log_file.write(msg + "\n")
        log_file.flush()

    # Pre-calculate total translation chunks for tqdm
    total_chunks = 0
    for md_file, _ in to_deploy:
        content = md_file.read_text(encoding="utf-8")
        total_chunks += count_translation_chunks(content)

    log(f"[info] 报告总数: {len(md_files)}, 跳过非日期: {non_date_skipped}, "
        f"已部署: {skipped}, 待部署: {len(to_deploy)}, 翻译块: {total_chunks}")
    print(f"Deploying {len(to_deploy)} reports, {total_chunks} chunks (log: {log_path})")

    errors: list[str] = []
    pbar = tqdm(total=total_chunks, desc="Translating", unit="chunk") if tqdm else None

    for md_file, file_date in to_deploy:
        buf = StringIO()
        try:
            markdown_body = md_file.read_text(encoding="utf-8")
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                generate_hugo_post(markdown_body, file_date, hugo_site, pbar=pbar,
                                   force=force,
                                   overwrite_human=getattr(args, "overwrite_human", False))
            finally:
                sys.stdout = old_stdout
            log(buf.getvalue().rstrip())
        except Exception as e:
            log(buf.getvalue().rstrip())
            msg = f"[error] {file_date.isoformat()}: {e}"
            log(msg)
            print(msg, file=sys.stderr)
            errors.append(msg)

    if pbar:
        pbar.close()

    log_file.close()

    if errors:
        print(f"\n{len(errors)} errors (see {log_path}):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    else:
        print(f"Done. {len(to_deploy)} reports deployed.")

    run_hugo_update(hugo_site)


def cmd_config(args):
    """查看或初始化配置文件。"""
    if args.init:
        _config_init()
    else:
        # 默认 --show
        _config_show()


def _config_show():
    """显示当前配置。"""
    print(f"配置文件路径: {_CONFIG_PATH}")
    if _CONFIG_PATH.exists():
        cfg = _load_config()
        print(f"配置内容:")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    else:
        print("(配置文件不存在，使用默认值)")

    print()
    print("当前生效路径:")
    print(f"  device_name:  {_get_device_name()}")
    logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR",
                                   "logs_dir", _DEFAULT_LOGS_DIR)
    reports_dir = _resolve_output_dir(None, "SUMMARIZE_REPORTS_DIR",
                                      "reports_dir", _DEFAULT_REPORTS_DIR)
    print(f"  logs_dir:     {logs_dir}")
    print(f"  reports_dir:  {reports_dir}")

    cfg = _load_config()
    remote = cfg.get("rclone_remote")
    if remote:
        rclone_bin = _find_rclone()
        status = f"已找到: {rclone_bin}" if rclone_bin else "未找到"
        print(f"  rclone:       {remote} ({status})")
        print(f"    logs:       {remote}/logs/")
        print(f"    reports:    {remote}/reports/")
    else:
        print(f"  rclone:       (未配置)")
    rclone_path = cfg.get("rclone_path")
    if rclone_path:
        print(f"  rclone_path:  {rclone_path}")


def _config_init():
    """交互式创建配置文件（写入仓库内 tools/summarize/config.json）。"""
    print(f"配置文件路径: {_REPO_CONFIG_PATH}")
    if _REPO_CONFIG_PATH.exists():
        overwrite = input("配置文件已存在，是否覆盖？[y/N] ").strip().lower()
        if overwrite != "y":
            print("取消")
            return

    cfg = {}

    # device_name
    default_name = platform.node() or "unknown"
    name = input(f"设备别名 (device_name) [{default_name}]: ").strip()
    cfg["device_name"] = name or default_name

    # logs_dir
    logs = input("logs 输出目录 (留空使用默认 outputs/logs/summarize/): ").strip()
    if logs:
        cfg["logs_dir"] = logs

    # reports_dir
    reports = input("reports 输出目录 (留空使用默认 outputs/reports/summarize/): ").strip()
    if reports:
        cfg["reports_dir"] = reports

    # rclone_remote
    rclone = input("rclone 远端路径 (如 <remote名>:<目录>，留空跳过): ").strip()
    if rclone:
        cfg["rclone_remote"] = rclone

    # rclone_path（仅在设了 remote 且 PATH 中没有 rclone 时询问）
    if rclone and not shutil.which("rclone"):
        rclone_path = input("rclone 二进制路径 (如 ~/.local/bin/rclone，留空跳过): ").strip()
        if rclone_path:
            cfg["rclone_path"] = rclone_path

    # ── 行为默认值（供 auto / daily / weekly / monthly 作为 flag 默认）──
    api = input("默认 API (ollama/anthropic/openai/claude_cli) [ollama]: ").strip()
    if api:
        cfg["default_api"] = api

    model = input("本地模型名 (OLLAMA_MODEL，如 qwen3.6-sum，留空跳过): ").strip()
    if model:
        cfg["model"] = model

    reasoning = input("推理力度 (reasoning_effort，本地思考模型填 none，留空跳过): ").strip()
    if reasoning:
        cfg["reasoning_effort"] = reasoning

    deploy = input("auto 是否默认部署到 Hugo？[y/N] ").strip().lower()
    if deploy == "y":
        cfg["deploy"] = True

    hugo_site = input("Hugo 站点根目录 (deploy 用，留空使用默认): ").strip()
    if hugo_site:
        cfg["hugo_site"] = hugo_site

    workers = input("daily merge --sync-all 并行 worker 数 (留空使用默认 1): ").strip()
    if workers.isdigit():
        cfg["workers"] = int(workers)

    # 写入
    _atomic_write(_REPO_CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))
    print(f"\n[ok] 配置已保存: {_REPO_CONFIG_PATH}")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
