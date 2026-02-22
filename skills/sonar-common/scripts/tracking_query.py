#!/usr/bin/env python3
"""
SQLite 추적 DB 조회 CLI

Usage:
    python tracking_query.py summary [--issue KEY] [--json]
    python tracking_query.py history ISSUE_KEY [--json]
    python tracking_query.py errors [--limit 20] [--json]
    python tracking_query.py metrics [--json]
    python tracking_query.py recent [--limit 20] [--status S] [--json]
"""

import argparse
import json
import os
import sys
from typing import Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from tracking_db import get_tracker


def _print_table(rows: List[Dict], columns: List[str] = None):
    """간단한 텍스트 테이블 출력."""
    if not rows:
        print("(no data)")
        return
    if columns is None:
        columns = list(rows[0].keys())
    # 컬럼 폭 계산
    widths = {}
    for col in columns:
        widths[col] = max(len(str(col)), max(len(str(r.get(col, ''))) for r in rows))
        widths[col] = min(widths[col], 60)  # 최대 60자
    # 헤더
    header = ' | '.join(str(col).ljust(widths[col])[:widths[col]] for col in columns)
    print(header)
    print('-+-'.join('-' * widths[col] for col in columns))
    # 행
    for row in rows:
        line = ' | '.join(str(row.get(col, '')).ljust(widths[col])[:widths[col]] for col in columns)
        print(line)


def _output(data, as_json: bool):
    """JSON 또는 텍스트로 출력."""
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_summary(args):
    tracker = get_tracker()
    rows = tracker.get_issue_summary(args.issue)
    if args.json:
        _output(rows, True)
    else:
        if not rows:
            print("No execution data found.")
            return
        columns = ['issue_key', 'phase', 'status', 'attempt_number',
                    'started_at', 'duration_ms', 'total_errors']
        _print_table(rows, columns)


def cmd_history(args):
    tracker = get_tracker()
    history = tracker.get_issue_history(args.issue_key)
    if args.json:
        _output(history, True)
    else:
        print(f"=== History for {history['issue_key']} ===\n")

        print("-- Executions --")
        if history['executions']:
            _print_table(history['executions'],
                         ['execution_id', 'phase', 'status', 'attempt_number',
                          'started_at', 'completed_at', 'duration_ms', 'error_message'])
        else:
            print("(none)")

        print("\n-- State Transitions --")
        if history['transitions']:
            _print_table(history['transitions'],
                         ['from_status', 'to_status', 'transitioned_at',
                          'triggered_by', 'notes'])
        else:
            print("(none)")

        print("\n-- Errors --")
        if history['errors']:
            _print_table(history['errors'],
                         ['error_type', 'error_message', 'phase',
                          'attempt_number', 'created_at'])
        else:
            print("(none)")


def cmd_errors(args):
    tracker = get_tracker()
    rows = tracker.get_error_patterns(args.limit)
    if args.json:
        _output(rows, True)
    else:
        if not rows:
            print("No errors recorded.")
            return
        columns = ['error_type', 'phase', 'occurrence_count',
                    'affected_issues', 'last_seen', 'first_seen']
        _print_table(rows, columns)


def cmd_metrics(args):
    tracker = get_tracker()
    rows = tracker.get_phase_metrics()
    if args.json:
        _output(rows, True)
    else:
        if not rows:
            print("No metrics available (no completed executions).")
            return
        columns = ['phase', 'status', 'execution_count',
                    'avg_duration_ms', 'min_duration_ms', 'max_duration_ms', 'avg_attempts']
        _print_table(rows, columns)


def cmd_recent(args):
    tracker = get_tracker()
    rows = tracker.get_recent_executions(args.limit, args.status)
    if args.json:
        _output(rows, True)
    else:
        if not rows:
            print("No recent executions.")
            return
        columns = ['execution_id', 'issue_key', 'phase', 'status',
                    'attempt_number', 'started_at', 'duration_ms']
        _print_table(rows, columns)


def main():
    parser = argparse.ArgumentParser(
        description='SonarQube Tracking DB Query CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # summary
    p_summary = subparsers.add_parser('summary', help='Issue execution summary')
    p_summary.add_argument('--issue', help='Filter by issue key')
    p_summary.add_argument('--json', action='store_true', help='Output as JSON')
    p_summary.set_defaults(func=cmd_summary)

    # history
    p_history = subparsers.add_parser('history', help='Full issue history')
    p_history.add_argument('issue_key', help='Issue key')
    p_history.add_argument('--json', action='store_true', help='Output as JSON')
    p_history.set_defaults(func=cmd_history)

    # errors
    p_errors = subparsers.add_parser('errors', help='Error patterns')
    p_errors.add_argument('--limit', type=int, default=20, help='Max results (default: 20)')
    p_errors.add_argument('--json', action='store_true', help='Output as JSON')
    p_errors.set_defaults(func=cmd_errors)

    # metrics
    p_metrics = subparsers.add_parser('metrics', help='Phase performance metrics')
    p_metrics.add_argument('--json', action='store_true', help='Output as JSON')
    p_metrics.set_defaults(func=cmd_metrics)

    # recent
    p_recent = subparsers.add_parser('recent', help='Recent executions')
    p_recent.add_argument('--limit', type=int, default=20, help='Max results (default: 20)')
    p_recent.add_argument('--status', help='Filter by status')
    p_recent.add_argument('--json', action='store_true', help='Output as JSON')
    p_recent.set_defaults(func=cmd_recent)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
