"""Phase 1: export conversation logs (single date or batch)."""

import getpass
import json
import platform
import sys
from datetime import date

from common.io import atomic_write as _atomic_write
from common.llm import ChunkTimeoutError

from .config import _resolve_output_dir, _get_device_name
from .daily_helpers import _parse_date, _DEFAULT_LOGS_DIR
from .parsers import discover_all_dates, collect_conversations
from .remote import _rclone_upload, _rclone_upload_dir
from .summarizer import _call_summarize
from .formatter import _sort_report_by_importance
from .usage import _refresh_usage_snapshots


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
