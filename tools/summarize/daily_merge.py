"""Phase 2: merge multi-device logs into a daily report."""

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from common.io import atomic_write as _atomic_write
from common.hugo import run_hugo_update
from common.llm import ChunkTimeoutError, cleanup_chunk_cache as _cleanup_chunk_cache
from common.paths import LOGS_DIR

from .config import _resolve_output_dir, resolve_hugo_site
from .daily_helpers import _parse_date, _DEFAULT_LOGS_DIR, _DEFAULT_REPORTS_DIR, _DEFAULT_CACHE_DIR
from .formatter import generate_markdown, _sort_report_by_importance, save_report, generate_hugo_post
from .remote import _rclone_download_logs, _rclone_download_reports, _rclone_upload
from .summarizer import (MERGE_PROMPT_PREFIX, MERGE_DEVICE_SUMMARY_PREFIX,
                         _call_summarize, _build_summary_prompt, _get_device_label)
from .usage import load_ccusage_for_date, _merge_token_usages


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
        hugo_site = resolve_hugo_site(args.hugo_site)
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
        hugo_site = resolve_hugo_site(args.hugo_site)
        if not hugo_site.exists():
            print(f"[error] Hugo 站点目录不存在: {hugo_site}")
            sys.exit(1)

        generate_hugo_post(markdown, target_date, hugo_site, api=args.api,
                           force=getattr(args, "force", False))

        run_hugo_update(hugo_site)
