"""Contest v2 阶段审核与 R5 Reviewer 编排入口。

该入口属于编排层，不把 Codex 对话 API 塞进薄 ``contest`` CLI。没有配置
外部 adapter 时，dispatch 只会留下 REQUEST_READY，不会伪造任务已经创建。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从仓库根目录或 contest_v2/scripts 直接执行脚本。
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from contest_v2.review_orchestrator import (
    CommandReviewerAdapter,
    check_stage_gate,
    collect,
    dispatch,
    prepare_request,
    prepare_rereview,
)


def _adapter(value: str | None) -> CommandReviewerAdapter | None:
    return CommandReviewerAdapter(value) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contest-review-orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    gate = sub.add_parser("gate", help="检查 R1/R2/R3/R4 是否具备阶段条件")
    gate.add_argument("run_dir", type=Path)
    gate.add_argument("stage", choices=("R1", "R2", "R3", "R4"))

    prepare = sub.add_parser("prepare", help="生成 R5 review_request.json")
    prepare.add_argument("run_dir", type=Path)
    prepare.add_argument("--round", type=int, default=1)
    prepare.add_argument("--parent-request-id")
    prepare.add_argument("--handoff-dir", default="review_handoff_round2")

    dispatch_parser = sub.add_parser("dispatch", help="调用外部 Reviewer adapter 创建任务")
    dispatch_parser.add_argument("run_dir", type=Path)
    dispatch_parser.add_argument("--adapter-command", help="adapter 命令；省略则保持 REQUEST_READY")

    collect_parser = sub.add_parser("collect", help="从外部 Reviewer adapter 回收结果")
    collect_parser.add_argument("run_dir", type=Path)
    collect_parser.add_argument("--adapter-command", required=True)

    rereview = sub.add_parser("rereview", help="为 MAJOR_REVISION 创建全新复审请求")
    rereview.add_argument("run_dir", type=Path)
    rereview.add_argument("--handoff-dir", default="review_handoff_round2")

    args = parser.parse_args(argv)
    if args.command == "gate":
        value = check_stage_gate(args.run_dir, args.stage)
    elif args.command == "prepare":
        value = prepare_request(args.run_dir, round_number=args.round, parent_request_id=args.parent_request_id, handoff_dir=args.handoff_dir)
    elif args.command == "dispatch":
        value = dispatch(args.run_dir, _adapter(args.adapter_command))
    elif args.command == "collect":
        value = collect(args.run_dir, _adapter(args.adapter_command))
    else:
        value = prepare_rereview(args.run_dir, handoff_dir=args.handoff_dir)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
