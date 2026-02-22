#!/usr/bin/env python3
"""
SonarQube Workflow Dashboard Generator

SQLite 추적 DB + Google Sheets 데이터를 기반으로 HTML 대시보드를 생성합니다.

Usage:
    python generate_dashboard.py [--no-sheets] [--output PATH] [--open]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# sonar-common/scripts 경로를 sys.path에 추가
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPT_DIR.parent.parent  # sonar-dashboard/scripts/ → sonar-dashboard/ → skills/
_COMMON_SCRIPTS = _SKILLS_DIR / 'sonar-common' / 'scripts'
sys.path.insert(0, str(_COMMON_SCRIPTS))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ── Args ──────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Generate SonarQube Workflow Dashboard')
    parser.add_argument('--no-sheets', action='store_true',
                        help='DB 데이터만으로 생성 (Google Sheets 생략)')
    parser.add_argument('--output', type=str, default=None,
                        help='출력 파일 경로 (기본: reports/dashboard_{timestamp}.html)')
    parser.add_argument('--open', action='store_true',
                        help='생성 후 브라우저에서 열기')
    return parser.parse_args(argv)


# ── Data Gathering ────────────────────────────────────────────

def gather_tracking_data(tracker):
    """SQLite 추적 DB에서 전체 데이터 수집."""
    conn = tracker._get_conn()

    executions = [dict(r) for r in conn.execute(
        "SELECT * FROM issue_executions ORDER BY started_at"
    ).fetchall()]

    transitions = [dict(r) for r in conn.execute(
        "SELECT * FROM state_transitions ORDER BY transitioned_at"
    ).fetchall()]

    errors = [dict(r) for r in conn.execute(
        "SELECT * FROM error_log ORDER BY created_at"
    ).fetchall()]

    phase_metrics = [dict(r) for r in conn.execute(
        "SELECT * FROM v_phase_metrics"
    ).fetchall()]

    return {
        'executions': executions,
        'transitions': transitions,
        'errors': errors,
        'phase_metrics': phase_metrics,
    }


def gather_sheets_data(spreadsheet_id):
    """Google Sheets에서 이슈 메타데이터 수집. 실패 시 빈 dict 반환."""
    try:
        from sheets_client import SheetsClient
        client = SheetsClient(spreadsheet_id)
        issues = client.get_all_issues()
        # SonarQube키 기준 lookup dict
        lookup = {}
        for issue in issues:
            sonar_key = issue.get('SonarQube키', '')
            if sonar_key:
                lookup[sonar_key] = issue
        return lookup
    except Exception as e:
        logger.warning(f"Sheets 데이터 수집 실패 (DB만으로 계속): {e}")
        return {}


# ── Data Merging ──────────────────────────────────────────────

def _ms_to_display(ms):
    """밀리초를 사람이 읽을 수 있는 형태로 변환."""
    if ms is None:
        return '0s'
    s = round(ms / 1000)
    m = s // 60
    sec = s % 60
    if m > 0:
        return f'{m}m {sec}s'
    return f'{sec}s'


def _parse_datetime(dt_str):
    """날짜 문자열을 datetime 객체로 파싱."""
    if not dt_str:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S%z'):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def compute_kpis(tracking_data):
    """KPI 계산."""
    execs = tracking_data['executions']
    errors = tracking_data['errors']

    # 이슈별로 그룹화
    issue_keys = set()
    success_keys = set()
    blocked_keys = set()
    for e in execs:
        issue_keys.add(e['issue_key'])
        if e['status'] == 'success':
            success_keys.add(e['issue_key'])
        elif e['status'] == 'failed':
            blocked_keys.add(e['issue_key'])

    total = len(issue_keys)
    # success = 최종 상태가 success인 이슈 (develop phase 기준)
    develop_success = set()
    develop_failed = set()
    for e in execs:
        if e['phase'] == 'develop' and e['status'] == 'success':
            develop_success.add(e['issue_key'])
        elif e['phase'] == 'develop' and e['status'] == 'failed':
            develop_failed.add(e['issue_key'])

    # develop이 없는 경우 analyze 기준
    if not develop_success and not develop_failed:
        for e in execs:
            if e['status'] == 'success':
                develop_success.add(e['issue_key'])
            elif e['status'] == 'failed':
                develop_failed.add(e['issue_key'])

    success_count = len(develop_success)
    blocked_count = len(develop_failed - develop_success)
    rate = round(success_count / total * 100, 1) if total > 0 else 0

    # 전체 소요 시간 (첫 실행 ~ 마지막 완료)
    all_starts = [_parse_datetime(e['started_at']) for e in execs if e['started_at']]
    all_ends = [_parse_datetime(e['completed_at']) for e in execs if e.get('completed_at')]
    all_starts = [d for d in all_starts if d]
    all_ends = [d for d in all_ends if d]

    if all_starts and all_ends:
        elapsed_sec = (max(all_ends) - min(all_starts)).total_seconds()
        elapsed_min = round(elapsed_sec / 60, 1)
    else:
        elapsed_min = 0

    # 평균 phase 소요 시간
    durations = [e['duration_ms'] for e in execs if e.get('duration_ms') and e['status'] == 'success']
    avg_duration_ms = round(sum(durations) / len(durations)) if durations else 0
    avg_duration_min = round(avg_duration_ms / 60000, 1)

    error_count = len(errors)

    return {
        'total': total,
        'success': success_count,
        'blocked': blocked_count,
        'rate': rate,
        'elapsed_min': elapsed_min,
        'avg_duration_min': avg_duration_min,
        'errors': error_count,
    }


def build_issue_list(tracking_data, sheets_lookup):
    """이슈 목록 구성: DB 실행 데이터 + Sheets 메타데이터 병합."""
    execs = tracking_data['executions']

    # 이슈별로 실행 데이터 그룹화
    issue_map = {}
    for e in execs:
        key = e['issue_key']
        if key not in issue_map:
            issue_map[key] = {
                'key': key,
                'row': e.get('sheet_row'),
                'analyze_ms': 0,
                'develop_ms': 0,
                'status': 'UNKNOWN',
                'analyze_start': None,
                'analyze_end': None,
                'develop_start': None,
                'develop_end': None,
            }
        entry = issue_map[key]
        if e['phase'] == 'analyze' and e['status'] == 'success':
            entry['analyze_ms'] = e.get('duration_ms') or 0
            entry['analyze_start'] = e.get('started_at')
            entry['analyze_end'] = e.get('completed_at')
        elif e['phase'] == 'develop' and e['status'] == 'success':
            entry['develop_ms'] = e.get('duration_ms') or 0
            entry['develop_start'] = e.get('started_at')
            entry['develop_end'] = e.get('completed_at')

    # 최종 상태 결정 (마지막 transition 기준)
    for t in tracking_data['transitions']:
        key = t['issue_key']
        if key in issue_map:
            issue_map[key]['status'] = t['to_status']

    # Sheets 메타데이터 병합
    issues = []
    for key, data in issue_map.items():
        sheet = sheets_lookup.get(key, {})
        data['file'] = sheet.get('파일', 'unknown')
        data['line'] = sheet.get('라인', '')
        data['rule'] = sheet.get('규칙', 'unknown')
        data['severity'] = sheet.get('심각도', 'unknown')
        data['message'] = sheet.get('메시지', '')
        # 파일명만 추출 (경로가 길면)
        if data['file'] != 'unknown' and '/' in data['file']:
            data['file_short'] = data['file'].rsplit('/', 1)[-1]
        else:
            data['file_short'] = data['file']
        data['total_ms'] = data['analyze_ms'] + data['develop_ms']
        issues.append(data)

    # row 기준 정렬
    issues.sort(key=lambda x: (x.get('row') or 9999, x['key']))
    return issues


def compute_executions_timeline(tracking_data):
    """Gantt 차트용 실행 타임라인 데이터."""
    execs = tracking_data['executions']
    timeline = []
    for e in execs:
        if e['status'] not in ('success', 'failed'):
            continue
        start = _parse_datetime(e.get('started_at'))
        end = _parse_datetime(e.get('completed_at'))
        if not start or not end:
            continue
        timeline.append({
            'key': e['issue_key'],
            'row': e.get('sheet_row'),
            'phase': e['phase'],
            'start': e['started_at'],
            'end': e['completed_at'],
            'start_ts': start.timestamp(),
            'end_ts': end.timestamp(),
            'duration_ms': e.get('duration_ms'),
        })
    timeline.sort(key=lambda x: x['start_ts'])
    return timeline


def compute_batches(timeline):
    """실행 간 gap > 60초이면 새 배치로 구분."""
    if not timeline:
        return []

    batches = []
    current_batch = {'items': [], 'start': None, 'end': None}

    for item in timeline:
        if current_batch['end'] is not None:
            gap = item['start_ts'] - current_batch['end']
            if gap > 60:
                batches.append(current_batch)
                current_batch = {'items': [], 'start': None, 'end': None}

        current_batch['items'].append(item)
        if current_batch['start'] is None or item['start_ts'] < current_batch['start']:
            current_batch['start'] = item['start_ts']
        if current_batch['end'] is None or item['end_ts'] > current_batch['end']:
            current_batch['end'] = item['end_ts']

    if current_batch['items']:
        batches.append(current_batch)

    # 배치 요약 정보
    result = []
    for i, batch in enumerate(batches, 1):
        rows = sorted(set(item['row'] for item in batch['items'] if item.get('row')))
        keys = set(item['key'] for item in batch['items'])
        start_dt = datetime.fromtimestamp(batch['start'])
        end_dt = datetime.fromtimestamp(batch['end'])
        # 상태 결정
        all_done = all(
            item['phase'] == 'develop' and item.get('duration_ms')
            for key in keys
            for item in batch['items']
            if item['key'] == key and item['phase'] == 'develop'
        )
        result.append({
            'batch_num': i,
            'rows': rows,
            'row_range': f"Row {min(rows)} ~ {max(rows)}" if rows else "N/A",
            'start': start_dt.strftime('%H:%M'),
            'end': end_dt.strftime('%H:%M'),
            'agent_count': len(keys),
            'status': 'ALL DONE' if all_done else 'IN PROGRESS',
        })
    return result


def compute_file_impact(issues):
    """파일별 이슈 수 및 규칙 목록."""
    file_map = {}
    for issue in issues:
        f = issue.get('file', 'unknown')
        if f not in file_map:
            file_map[f] = {'file': f, 'count': 0, 'rules': set()}
        file_map[f]['count'] += 1
        rule = issue.get('rule', 'unknown')
        if rule != 'unknown':
            file_map[f]['rules'].add(rule)

    result = []
    for f, data in sorted(file_map.items(), key=lambda x: -x[1]['count']):
        result.append({
            'file': data['file'],
            'count': data['count'],
            'rules': sorted(data['rules']),
        })
    return result


def compute_rule_dist(issues):
    """규칙별 이슈 수."""
    rule_map = {}
    for issue in issues:
        rule = issue.get('rule', 'unknown')
        if rule not in rule_map:
            rule_map[rule] = {'rule': rule, 'count': 0, 'message': issue.get('message', '')}
        rule_map[rule]['count'] += 1
    return sorted(rule_map.values(), key=lambda x: -x['count'])


def merge_data(tracking_data, sheets_lookup):
    """모든 데이터를 대시보드용 구조로 병합."""
    kpis = compute_kpis(tracking_data)
    issues = build_issue_list(tracking_data, sheets_lookup)
    timeline = compute_executions_timeline(tracking_data)
    batches = compute_batches(timeline)
    file_impact = compute_file_impact(issues)
    rule_dist = compute_rule_dist(issues)

    # 전이 로그
    transition_log = [{
        'key': t['issue_key'],
        'to': t['to_status'],
        'at': t['transitioned_at'],
    } for t in tracking_data['transitions']]

    # phase metrics 정리
    phase_metrics = []
    for m in tracking_data['phase_metrics']:
        phase_metrics.append({
            'phase': m['phase'],
            'status': m['status'],
            'count': m['execution_count'],
            'avg_ms': m['avg_duration_ms'],
            'min_ms': m['min_duration_ms'],
            'max_ms': m['max_duration_ms'],
            'avg_attempts': m['avg_attempts'],
        })

    # 실행 요약 통계
    total_execs = len(tracking_data['executions'])
    success_execs = sum(1 for e in tracking_data['executions'] if e['status'] == 'success')
    failed_execs = sum(1 for e in tracking_data['executions'] if e['status'] == 'failed')
    total_transitions = len(tracking_data['transitions'])

    # 전체 소요 시간 범위
    all_times = []
    for t in tracking_data['transitions']:
        dt = _parse_datetime(t['transitioned_at'])
        if dt:
            all_times.append(dt)
    for e in tracking_data['executions']:
        dt = _parse_datetime(e.get('started_at'))
        if dt:
            all_times.append(dt)
        dt = _parse_datetime(e.get('completed_at'))
        if dt:
            all_times.append(dt)

    if all_times:
        time_range_start = min(all_times).strftime('%Y-%m-%d %H:%M')
        time_range_end = max(all_times).strftime('%H:%M')
        run_date = f"{time_range_start} ~ {time_range_end}"
    else:
        run_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 담당자
    assignee = os.environ.get('ASSIGNEE_NAME', 'unknown')

    return {
        'kpis': kpis,
        'issues': issues,
        'timeline': timeline,
        'batches': batches,
        'file_impact': file_impact,
        'rule_dist': rule_dist,
        'transition_log': transition_log,
        'phase_metrics': phase_metrics,
        'exec_summary': {
            'total': total_execs,
            'success': success_execs,
            'failed': failed_execs,
            'transitions': total_transitions,
        },
        'run_date': run_date,
        'assignee': assignee,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ── HTML Rendering ────────────────────────────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SonarQube Workflow Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg-primary: #0f172a;
    --bg-secondary: #1e293b;
    --bg-card: #1e293b;
    --bg-card-hover: #263347;
    --border: #334155;
    --text-primary: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent-blue: #3b82f6;
    --accent-cyan: #06b6d4;
    --accent-green: #10b981;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
    --accent-purple: #8b5cf6;
    --accent-pink: #ec4899;
    --gradient-blue: linear-gradient(135deg, #3b82f6, #06b6d4);
    --gradient-green: linear-gradient(135deg, #10b981, #34d399);
    --gradient-purple: linear-gradient(135deg, #8b5cf6, #a78bfa);
    --gradient-amber: linear-gradient(135deg, #f59e0b, #fbbf24);
    --shadow: 0 4px 6px -1px rgba(0,0,0,0.3), 0 2px 4px -2px rgba(0,0,0,0.2);
    --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.4), 0 4px 6px -4px rgba(0,0,0,0.3);
    --radius: 12px;
    --radius-sm: 8px;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
  }

  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }

  .header {
    text-align: center;
    padding: 48px 24px 32px;
    position: relative;
  }
  .header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 300px;
    background: radial-gradient(ellipse at 50% 0%, rgba(59,130,246,0.15) 0%, transparent 70%);
    pointer-events: none;
  }
  .header h1 {
    font-size: 2.5rem;
    font-weight: 800;
    background: var(--gradient-blue);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 8px;
    position: relative;
  }
  .header .subtitle {
    color: var(--text-secondary);
    font-size: 1.1rem;
    position: relative;
  }
  .header .run-date {
    display: inline-block;
    margin-top: 12px;
    padding: 4px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 0.85rem;
    color: var(--text-muted);
    position: relative;
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }
  .kpi-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    position: relative;
    overflow: hidden;
    transition: transform 0.2s, box-shadow 0.2s;
  }
  .kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-lg);
  }
  .kpi-card .kpi-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    margin-bottom: 12px;
  }
  .kpi-card .kpi-value {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1.2;
  }
  .kpi-card .kpi-label {
    font-size: 0.85rem;
    color: var(--text-secondary);
    margin-top: 4px;
  }
  .kpi-card .kpi-bar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
  }

  .section { margin-bottom: 32px; }
  .section-title {
    font-size: 1.3rem;
    font-weight: 700;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section-title .icon {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
  }

  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    box-shadow: var(--shadow);
  }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; }

  @media (max-width: 900px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
  }

  .table-wrapper { overflow-x: auto; }
  table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.875rem;
  }
  thead th {
    background: rgba(59,130,246,0.08);
    color: var(--text-secondary);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    padding: 12px 16px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    white-space: nowrap;
  }
  thead th:first-child { border-radius: var(--radius-sm) 0 0 0; }
  thead th:last-child { border-radius: 0 var(--radius-sm) 0 0; }
  tbody td {
    padding: 12px 16px;
    border-bottom: 1px solid rgba(51,65,85,0.5);
    vertical-align: middle;
  }
  tbody tr { transition: background 0.15s; }
  tbody tr:hover { background: var(--bg-card-hover); }
  tbody tr:last-child td { border-bottom: none; }

  .badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  .badge-success { background: rgba(16,185,129,0.15); color: #34d399; }
  .badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; }
  .badge-amber { background: rgba(245,158,11,0.15); color: #fbbf24; }
  .badge-purple { background: rgba(139,92,246,0.15); color: #a78bfa; }
  .badge-red { background: rgba(239,68,68,0.15); color: #f87171; }
  .badge-cyan { background: rgba(6,182,212,0.15); color: #22d3ee; }
  .badge-pink { background: rgba(236,72,153,0.15); color: #f472b6; }

  .duration-bar-wrapper {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .duration-bar {
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    flex: 1;
    max-width: 120px;
    overflow: hidden;
  }
  .duration-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.6s ease;
  }

  .gantt-container {
    position: relative;
    overflow-x: auto;
    padding: 16px 0;
  }
  .gantt-row {
    display: flex;
    align-items: center;
    margin-bottom: 6px;
    height: 32px;
  }
  .gantt-label {
    width: 80px;
    flex-shrink: 0;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-align: right;
    padding-right: 12px;
  }
  .gantt-track {
    flex: 1;
    position: relative;
    height: 100%;
    background: rgba(51,65,85,0.3);
    border-radius: 4px;
  }
  .gantt-bar {
    position: absolute;
    height: 24px;
    top: 4px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.65rem;
    font-weight: 600;
    color: white;
    min-width: 2px;
    transition: opacity 0.2s;
    cursor: default;
  }
  .gantt-bar:hover { opacity: 0.85; }
  .gantt-bar.analyze { background: var(--gradient-blue); }
  .gantt-bar.develop { background: var(--gradient-green); }
  .gantt-time-label {
    font-size: 0.7rem;
    color: var(--text-muted);
    position: absolute;
  }

  .state-node {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
  }

  .chart-container {
    position: relative;
    width: 100%;
    max-height: 300px;
  }

  .tooltip-text {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .issue-key {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.78rem;
    color: var(--accent-cyan);
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: inline-block;
  }

  .file-path {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.78rem;
    color: var(--text-secondary);
  }

  .stats-row {
    display: flex;
    gap: 32px;
    flex-wrap: wrap;
    margin-top: 16px;
  }
  .stat-item { text-align: center; }
  .stat-item .stat-value { font-size: 1.5rem; font-weight: 700; }
  .stat-item .stat-label { font-size: 0.8rem; color: var(--text-muted); }

  .transition-log {
    max-height: 400px;
    overflow-y: auto;
    font-size: 0.8rem;
  }
  .transition-log::-webkit-scrollbar { width: 6px; }
  .transition-log::-webkit-scrollbar-track { background: transparent; }
  .transition-log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  .log-entry {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid rgba(51,65,85,0.3);
  }
  .log-time {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    color: var(--text-muted);
    white-space: nowrap;
    min-width: 55px;
  }
  .log-issue {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.72rem;
    color: var(--accent-cyan);
    min-width: 70px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .footer {
    text-align: center;
    padding: 32px 0;
    color: var(--text-muted);
    font-size: 0.8rem;
    border-top: 1px solid var(--border);
    margin-top: 48px;
  }

  @keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0.3); }
    50% { box-shadow: 0 0 0 8px rgba(16,185,129,0); }
  }
  .pulse-success { animation: pulse-green 2s infinite; }

  .no-data {
    text-align: center;
    padding: 48px;
    color: var(--text-muted);
    font-size: 1.1rem;
  }
</style>
</head>
<body>

<script>
// ========== INJECTED DATA ==========
const DASHBOARD_DATA = {DASHBOARD_DATA_JSON};

// ========== HELPERS ==========
function msToStr(ms) {
  if (!ms) return '0s';
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? m + 'm ' + sec + 's' : sec + 's';
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

const STATE_COLORS = {
  'ANALYZING': '#3b82f6', 'REVIEW_ANALYSIS': '#8b5cf6',
  'REPORT_CREATED': '#06b6d4', 'JIRA_CREATED': '#06b6d4',
  'DEVELOPING': '#10b981', 'REVIEW_FIX': '#f59e0b',
  'TESTING': '#ec4899', 'DONE': '#10b981', 'BLOCKED': '#ef4444', 'APPROVED': '#10b981'
};

const SEVERITY_BADGE = s => s === 'HIGH' || s === 'CRITICAL' || s === 'BLOCKER' ? 'badge-red' : 'badge-amber';

const BADGE_COLORS = ['badge-blue', 'badge-cyan', 'badge-purple', 'badge-amber', 'badge-pink', 'badge-success', 'badge-red'];
const CHART_COLORS = [
  'rgba(139,92,246,0.8)', 'rgba(245,158,11,0.8)', 'rgba(59,130,246,0.8)',
  'rgba(16,185,129,0.8)', 'rgba(236,72,153,0.8)', 'rgba(6,182,212,0.8)', 'rgba(239,68,68,0.8)'
];
const CHART_BORDERS = [
  'rgba(139,92,246,1)', 'rgba(245,158,11,1)', 'rgba(59,130,246,1)',
  'rgba(16,185,129,1)', 'rgba(236,72,153,1)', 'rgba(6,182,212,1)', 'rgba(239,68,68,1)'
];

const data = DASHBOARD_DATA;
const kpis = data.kpis;
const issues = data.issues;

// ========== RENDER ==========
document.addEventListener('DOMContentLoaded', function() {

  // -- Header --
  document.getElementById('runDate').textContent = data.run_date + ' KST \u2022 Assignee: ' + escapeHtml(data.assignee);

  // -- KPI Values --
  document.getElementById('kpiTotal').textContent = kpis.total;
  document.getElementById('kpiSuccess').textContent = kpis.success;
  const rateEl = document.getElementById('kpiRate');
  rateEl.textContent = kpis.rate + '%';
  if (kpis.rate >= 100) rateEl.style.color = 'var(--accent-green)';
  else if (kpis.rate >= 80) rateEl.style.color = 'var(--accent-amber)';
  else rateEl.style.color = 'var(--accent-red)';
  document.getElementById('kpiElapsed').innerHTML = kpis.elapsed_min + '<span style="font-size:1rem;font-weight:400;">min</span>';
  document.getElementById('kpiAvg').innerHTML = kpis.avg_duration_min + '<span style="font-size:1rem;font-weight:400;">min</span>';
  document.getElementById('kpiErrors').textContent = kpis.errors;

  if (issues.length === 0) {
    document.getElementById('mainContent').innerHTML = '<div class="no-data">No workflow data found. Run /sonar run first.</div>';
    return;
  }

  // -- Rule Distribution Chart --
  const ruleDist = data.rule_dist;
  if (ruleDist.length > 0) {
    new Chart(document.getElementById('ruleChart'), {
      type: 'doughnut',
      data: {
        labels: ruleDist.map(r => r.rule + (r.message ? ' (' + r.message.substring(0, 30) + ')' : '')),
        datasets: [{
          data: ruleDist.map(r => r.count),
          backgroundColor: ruleDist.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
          borderColor: ruleDist.map((_, i) => CHART_BORDERS[i % CHART_BORDERS.length]),
          borderWidth: 2,
          hoverOffset: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 16, font: { size: 12 } } }
        },
        cutout: '60%'
      }
    });
  }

  // -- Phase Duration Chart (stacked bar) --
  if (issues.length > 0) {
    new Chart(document.getElementById('phaseDurationChart'), {
      type: 'bar',
      data: {
        labels: issues.map(d => 'R' + (d.row || '?')),
        datasets: [
          {
            label: 'Analyze',
            data: issues.map(d => Math.round((d.analyze_ms || 0) / 1000)),
            backgroundColor: 'rgba(59,130,246,0.7)',
            borderColor: 'rgba(59,130,246,1)',
            borderWidth: 1, borderRadius: 4,
          },
          {
            label: 'Develop',
            data: issues.map(d => Math.round((d.develop_ms || 0) / 1000)),
            backgroundColor: 'rgba(16,185,129,0.7)',
            borderColor: 'rgba(16,185,129,1)',
            borderWidth: 1, borderRadius: 4,
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: true,
        plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
        scales: {
          x: { stacked: true, ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
          y: { stacked: true, ticks: { color: '#64748b', font: { size: 11 }, callback: v => v + 's' }, grid: { color: 'rgba(51,65,85,0.3)' } }
        }
      }
    });
  }

  // -- Issue Table --
  const tbody = document.getElementById('issueTableBody');
  const maxTotal = Math.max(...issues.map(d => (d.analyze_ms || 0) + (d.develop_ms || 0)), 1);

  issues.forEach(d => {
    const total = (d.analyze_ms || 0) + (d.develop_ms || 0);
    const analyzeP = (d.analyze_ms / maxTotal * 100).toFixed(1);
    const developP = (d.develop_ms / maxTotal * 100).toFixed(1);
    const statusBadge = d.status === 'DONE' || d.status === 'APPROVED' ? 'badge-success' : d.status === 'BLOCKED' ? 'badge-red' : 'badge-blue';
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td style="font-weight:700; color:var(--accent-cyan);">' + (d.row || '-') + '</td>' +
      '<td><span class="badge badge-purple">' + escapeHtml(d.rule) + '</span></td>' +
      '<td><span class="file-path">' + escapeHtml(d.file_short || d.file) + '</span></td>' +
      '<td>' + escapeHtml(String(d.line || '')) + '</td>' +
      '<td><span class="badge ' + SEVERITY_BADGE(d.severity) + '">' + escapeHtml(d.severity) + '</span></td>' +
      '<td><div class="duration-bar-wrapper"><span class="tooltip-text">' + msToStr(d.analyze_ms) + '</span>' +
      '<div class="duration-bar"><div class="duration-bar-fill" style="width:' + analyzeP + '%; background:var(--gradient-blue);"></div></div></div></td>' +
      '<td><div class="duration-bar-wrapper"><span class="tooltip-text">' + msToStr(d.develop_ms) + '</span>' +
      '<div class="duration-bar"><div class="duration-bar-fill" style="width:' + developP + '%; background:var(--gradient-green);"></div></div></div></td>' +
      '<td style="font-weight:600;">' + msToStr(total) + '</td>' +
      '<td><span class="badge ' + statusBadge + '">' + escapeHtml(d.status) + '</span></td>';
    tbody.appendChild(tr);
  });

  // -- Per-issue Duration Chart (horizontal bar) --
  new Chart(document.getElementById('issueDurationChart'), {
    type: 'bar',
    data: {
      labels: issues.map(d => 'Row ' + (d.row || '?') + ' (' + (d.rule || '?') + ')'),
      datasets: [
        {
          label: 'Analyze',
          data: issues.map(d => +((d.analyze_ms || 0) / 60000).toFixed(1)),
          backgroundColor: 'rgba(59,130,246,0.7)',
          borderColor: 'rgba(59,130,246,1)',
          borderWidth: 1, borderRadius: 4,
        },
        {
          label: 'Develop',
          data: issues.map(d => +((d.develop_ms || 0) / 60000).toFixed(1)),
          backgroundColor: 'rgba(16,185,129,0.7)',
          borderColor: 'rgba(16,185,129,1)',
          borderWidth: 1, borderRadius: 4,
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
      scales: {
        x: { stacked: true, ticks: { color: '#64748b', font: { size: 11 }, callback: v => v + 'min' }, grid: { color: 'rgba(51,65,85,0.3)' } },
        y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(51,65,85,0.3)' } }
      }
    }
  });

  // -- Gantt Chart --
  const ganttC = document.getElementById('ganttContainer');
  const timeline = data.timeline;
  if (timeline.length > 0) {
    const globalStartTs = Math.min(...timeline.map(t => t.start_ts));
    const globalEndTs = Math.max(...timeline.map(t => t.end_ts));
    const totalSpan = globalEndTs - globalStartTs || 1;

    // group by row
    const rowSet = [...new Set(timeline.map(t => t.row))].filter(r => r != null).sort((a, b) => a - b);
    rowSet.forEach(row => {
      const rowExecs = timeline.filter(t => t.row === row);
      const ganttRow = document.createElement('div');
      ganttRow.className = 'gantt-row';

      const label = document.createElement('div');
      label.className = 'gantt-label';
      label.textContent = 'Row ' + row;

      const track = document.createElement('div');
      track.className = 'gantt-track';

      rowExecs.forEach(e => {
        const left = ((e.start_ts - globalStartTs) / totalSpan * 100).toFixed(2);
        const width = ((e.end_ts - e.start_ts) / totalSpan * 100).toFixed(2);
        const bar = document.createElement('div');
        bar.className = 'gantt-bar ' + e.phase;
        bar.style.left = left + '%';
        bar.style.width = width + '%';
        bar.title = e.phase + ': ' + e.start + ' ~ ' + e.end;
        if (parseFloat(width) > 4) {
          bar.textContent = msToStr(e.duration_ms);
        }
        track.appendChild(bar);
      });

      ganttRow.appendChild(label);
      ganttRow.appendChild(track);
      ganttC.appendChild(ganttRow);
    });

    // Time axis
    const axisRow = document.createElement('div');
    axisRow.style.cssText = 'display:flex; position:relative; margin-top:4px; height:20px; margin-left:80px;';
    const axisDuration = totalSpan;
    const step = Math.max(Math.round(axisDuration / 300) * 300, 300); // ~5min intervals
    for (let s = 0; s <= axisDuration; s += step) {
      const lbl = document.createElement('div');
      lbl.className = 'gantt-time-label';
      lbl.style.left = (s / axisDuration * 100).toFixed(1) + '%';
      const dt = new Date((globalStartTs + s) * 1000);
      lbl.textContent = dt.getHours() + ':' + String(dt.getMinutes()).padStart(2, '0');
      axisRow.appendChild(lbl);
    }
    ganttC.appendChild(axisRow);
  }

  // -- Phase Metrics Table --
  const pmBody = document.getElementById('phaseMetricsBody');
  data.phase_metrics.filter(m => m.status === 'success').forEach(m => {
    const tr = document.createElement('tr');
    const phaseBadge = m.phase === 'analyze' ? 'badge-blue' : 'badge-success';
    tr.innerHTML =
      '<td><span class="badge ' + phaseBadge + '">' + m.phase.toUpperCase() + '</span></td>' +
      '<td>' + m.count + '</td>' +
      '<td>' + msToStr(m.avg_ms) + '</td>' +
      '<td>' + msToStr(m.min_ms) + '</td>' +
      '<td>' + msToStr(m.max_ms) + '</td>' +
      '<td>' + (m.avg_attempts || '1.0') + '</td>';
    pmBody.appendChild(tr);
  });

  // -- Exec Summary --
  const es = data.exec_summary;
  document.getElementById('execTotal').textContent = es.total;
  document.getElementById('execSuccess').textContent = es.success;
  document.getElementById('execFailed').textContent = es.failed;
  document.getElementById('execTransitions').textContent = es.transitions;

  // -- Transition Log --
  const logDiv = document.getElementById('transitionLog');
  data.transition_log.forEach(t => {
    const color = STATE_COLORS[t.to] || '#64748b';
    const at = t.at || '';
    // extract time portion
    const timePart = at.length > 10 ? at.substring(11, 16) : at;
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML =
      '<span class="log-time">' + escapeHtml(timePart) + '</span>' +
      '<span class="log-issue">' + escapeHtml(t.key.substring(0, 8)) + '...</span>' +
      '<span class="state-node" style="background:' + color + '22; color:' + color + '; border:1px solid ' + color + '44;">' + escapeHtml(t.to) + '</span>';
    logDiv.appendChild(entry);
  });

  // -- File Impact Table --
  const fiBody = document.getElementById('fileImpactBody');
  data.file_impact.forEach(f => {
    const tr = document.createElement('tr');
    const rulesHtml = f.rules.map((r, i) => '<span class="badge ' + BADGE_COLORS[i % BADGE_COLORS.length] + '">' + escapeHtml(r) + '</span>').join(' ');
    tr.innerHTML =
      '<td><span class="file-path">' + escapeHtml(f.file) + '</span></td>' +
      '<td>' + f.count + '</td>' +
      '<td>' + rulesHtml + '</td>';
    fiBody.appendChild(tr);
  });

  // -- Batch Table --
  const batchBody = document.getElementById('batchBody');
  const batchBadges = ['badge-blue', 'badge-cyan', 'badge-purple', 'badge-pink', 'badge-amber', 'badge-success'];
  data.batches.forEach((b, i) => {
    const tr = document.createElement('tr');
    const badgeCls = batchBadges[i % batchBadges.length];
    const statusBadge = b.status === 'ALL DONE' ? 'badge-success' : 'badge-amber';
    tr.innerHTML =
      '<td><span class="badge ' + badgeCls + '">Batch ' + b.batch_num + '</span></td>' +
      '<td>' + escapeHtml(b.row_range) + '</td>' +
      '<td>' + escapeHtml(b.start) + '</td>' +
      '<td>' + escapeHtml(b.end) + '</td>' +
      '<td>' + b.agent_count + '</td>' +
      '<td><span class="badge ' + statusBadge + '">' + escapeHtml(b.status) + '</span></td>';
    batchBody.appendChild(tr);
  });

});
</script>

<div class="header">
  <h1>SonarQube Workflow Dashboard</h1>
  <div class="subtitle">Automated Issue Resolution Report</div>
  <div class="run-date" id="runDate"></div>
</div>

<div class="container" id="mainContent">

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-bar" style="background: var(--gradient-blue);"></div>
      <div class="kpi-icon" style="background: rgba(59,130,246,0.15); color: var(--accent-blue);">&#x1F4CB;</div>
      <div class="kpi-value" id="kpiTotal">0</div>
      <div class="kpi-label">Total Issues</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-bar" style="background: var(--gradient-green);"></div>
      <div class="kpi-icon" style="background: rgba(16,185,129,0.15); color: var(--accent-green);">&#x2705;</div>
      <div class="kpi-value" style="color: var(--accent-green);" id="kpiSuccess">0</div>
      <div class="kpi-label">Successfully Resolved</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-bar" style="background: var(--gradient-green);"></div>
      <div class="kpi-icon" style="background: rgba(16,185,129,0.15); color: var(--accent-green);">&#x1F3AF;</div>
      <div class="kpi-value" id="kpiRate">0%</div>
      <div class="kpi-label">Success Rate</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-bar" style="background: var(--gradient-amber);"></div>
      <div class="kpi-icon" style="background: rgba(245,158,11,0.15); color: var(--accent-amber);">&#x23F1;</div>
      <div class="kpi-value" id="kpiElapsed">0</div>
      <div class="kpi-label">Total Elapsed Time</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-bar" style="background: var(--gradient-purple);"></div>
      <div class="kpi-icon" style="background: rgba(139,92,246,0.15); color: var(--accent-purple);">&#x26A1;</div>
      <div class="kpi-value" id="kpiAvg">0</div>
      <div class="kpi-label">Avg Duration / Phase</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-bar" style="background: linear-gradient(135deg, #ec4899, #f472b6);"></div>
      <div class="kpi-icon" style="background: rgba(236,72,153,0.15); color: var(--accent-pink);">&#x1F504;</div>
      <div class="kpi-value" id="kpiErrors">0</div>
      <div class="kpi-label">Retries / Errors</div>
    </div>
  </div>

  <!-- Charts Row -->
  <div class="section">
    <div class="grid-2">
      <div class="card">
        <div class="section-title">
          <div class="icon" style="background: rgba(139,92,246,0.15); color: var(--accent-purple);">&#x1F4CA;</div>
          Rule Distribution
        </div>
        <div class="chart-container" style="max-height: 260px; display:flex; justify-content:center;">
          <canvas id="ruleChart"></canvas>
        </div>
      </div>
      <div class="card">
        <div class="section-title">
          <div class="icon" style="background: rgba(6,182,212,0.15); color: var(--accent-cyan);">&#x23F3;</div>
          Phase Duration (seconds)
        </div>
        <div class="chart-container" style="max-height: 260px;">
          <canvas id="phaseDurationChart"></canvas>
        </div>
      </div>
    </div>
  </div>

  <!-- Gantt Timeline -->
  <div class="section">
    <div class="card">
      <div class="section-title">
        <div class="icon" style="background: rgba(59,130,246,0.15); color: var(--accent-blue);">&#x1F4C5;</div>
        Execution Timeline (Gantt)
      </div>
      <div style="display:flex; gap:16px; margin-bottom:12px; font-size:0.8rem;">
        <span><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:var(--gradient-blue);vertical-align:middle;margin-right:4px;"></span> Analyze</span>
        <span><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:var(--gradient-green);vertical-align:middle;margin-right:4px;"></span> Develop</span>
      </div>
      <div class="gantt-container" id="ganttContainer"></div>
    </div>
  </div>

  <!-- Issue Detail Table -->
  <div class="section">
    <div class="card">
      <div class="section-title">
        <div class="icon" style="background: rgba(16,185,129,0.15); color: var(--accent-green);">&#x1F4DD;</div>
        Issue Details
      </div>
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Row</th>
              <th>Rule</th>
              <th>File</th>
              <th>Line</th>
              <th>Severity</th>
              <th>Analyze</th>
              <th>Develop</th>
              <th>Total</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="issueTableBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Per-issue duration chart -->
  <div class="section">
    <div class="card">
      <div class="section-title">
        <div class="icon" style="background: rgba(245,158,11,0.15); color: var(--accent-amber);">&#x1F4CA;</div>
        Per-Issue Duration Breakdown
      </div>
      <div class="chart-container" style="max-height: 350px;">
        <canvas id="issueDurationChart"></canvas>
      </div>
    </div>
  </div>

  <!-- State Transitions and Phase Metrics -->
  <div class="section">
    <div class="grid-2">
      <div class="card">
        <div class="section-title">
          <div class="icon" style="background: rgba(245,158,11,0.15); color: var(--accent-amber);">&#x2699;</div>
          Phase Performance Metrics
        </div>
        <table>
          <thead>
            <tr>
              <th>Phase</th>
              <th>Count</th>
              <th>Avg</th>
              <th>Min</th>
              <th>Max</th>
              <th>Attempts</th>
            </tr>
          </thead>
          <tbody id="phaseMetricsBody"></tbody>
        </table>
        <div style="margin-top:20px;">
          <div class="section-title" style="font-size:1rem;">Execution Summary</div>
          <div class="stats-row">
            <div class="stat-item">
              <div class="stat-value" style="color:var(--accent-blue);" id="execTotal">0</div>
              <div class="stat-label">Total Executions</div>
            </div>
            <div class="stat-item">
              <div class="stat-value" style="color:var(--accent-green);" id="execSuccess">0</div>
              <div class="stat-label">Successful</div>
            </div>
            <div class="stat-item">
              <div class="stat-value" style="color:var(--accent-red);" id="execFailed">0</div>
              <div class="stat-label">Failed</div>
            </div>
            <div class="stat-item">
              <div class="stat-value" style="color:var(--accent-purple);" id="execTransitions">0</div>
              <div class="stat-label">State Transitions</div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">
          <div class="icon" style="background: rgba(236,72,153,0.15); color: var(--accent-pink);">&#x1F4DC;</div>
          State Transition Log
        </div>
        <div class="transition-log" id="transitionLog"></div>
      </div>
    </div>
  </div>

  <!-- File Impact -->
  <div class="section">
    <div class="card">
      <div class="section-title">
        <div class="icon" style="background: rgba(6,182,212,0.15); color: var(--accent-cyan);">&#x1F4C1;</div>
        Affected Files Summary
      </div>
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Issues</th>
            <th>Rules</th>
          </tr>
        </thead>
        <tbody id="fileImpactBody"></tbody>
      </table>
    </div>
  </div>

  <!-- Batch Processing -->
  <div class="section">
    <div class="card">
      <div class="section-title">
        <div class="icon" style="background: rgba(139,92,246,0.15); color: var(--accent-purple);">&#x1F680;</div>
        Batch Processing Summary
      </div>
      <table>
        <thead>
          <tr>
            <th>Batch</th>
            <th>Rows</th>
            <th>Started</th>
            <th>Completed</th>
            <th>Agents</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="batchBody"></tbody>
      </table>
    </div>
  </div>

</div>

<div class="footer">
  Generated by SonarQube Dev-Exec Workflow &bull; Claude Code Agent &bull; <script>document.write(DASHBOARD_DATA.generated_at)</script>
</div>

</body>
</html>"""


def render_html(dashboard_data):
    """대시보드 데이터를 HTML로 렌더링."""
    data_json = json.dumps(dashboard_data, ensure_ascii=False, default=str)
    return _HTML_TEMPLATE.replace('{DASHBOARD_DATA_JSON}', data_json)


# ── Main ──────────────────────────────────────────────────────

def main(argv=None):
    args = parse_args(argv)

    # 환경변수 로드
    try:
        from env_loader import load_env, get_env, get_root_dir
        load_env()
        root_dir = get_root_dir()
    except Exception as e:
        logger.warning(f"env_loader 사용 불가, 기본값 사용: {e}")
        if os.environ.get('CLAUDE_PROJECT_DIR'):
            root_dir = Path(os.environ['CLAUDE_PROJECT_DIR'])
        else:
            _candidate = Path(__file__).resolve().parent.parent.parent.parent.parent
            if (_candidate / '.claude').is_dir():
                root_dir = _candidate
            else:
                root_dir = Path.cwd()

    # 추적 DB 연결
    try:
        from tracking_db import get_tracker
        tracker = get_tracker()
    except Exception as e:
        result = {"status": "failed", "error": f"Tracking DB 연결 실패: {e}"}
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # DB 데이터 수집
    tracking_data = gather_tracking_data(tracker)
    if not tracking_data['executions']:
        result = {"status": "failed", "error": "No tracking data found. Run /sonar run first."}
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # Sheets 데이터 수집
    sheets_lookup = {}
    if not args.no_sheets:
        try:
            spreadsheet_id = get_env('SPREADSHEET_ID', required=False)
            if spreadsheet_id:
                sheets_lookup = gather_sheets_data(spreadsheet_id)
            else:
                logger.warning("SPREADSHEET_ID 미설정, DB만으로 계속")
        except Exception as e:
            logger.warning(f"Sheets 데이터 수집 실패 (DB만으로 계속): {e}")

    # 데이터 병합
    dashboard_data = merge_data(tracking_data, sheets_lookup)

    # HTML 렌더링
    html = render_html(dashboard_data)

    # 출력 경로 결정
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        reports_dir = root_dir / 'reports'
        output_path = reports_dir / f'dashboard_{timestamp}.html'

    # 디렉토리 생성
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 파일 쓰기
    output_path.write_text(html, encoding='utf-8')

    # 브라우저 열기
    if args.open:
        try:
            subprocess.run(['open', str(output_path)], check=False,
                           capture_output=True, timeout=5)
        except Exception as e:
            logger.warning(f"브라우저 열기 실패 (파일은 정상 생성): {e}")

    # 결과 출력
    result = {
        "status": "success",
        "output_path": str(output_path),
        "issues_count": len(dashboard_data['issues']),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
