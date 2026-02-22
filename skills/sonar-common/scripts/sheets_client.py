#!/usr/bin/env python3
"""
Google Sheets 공통 클라이언트
스프레드시트 읽기/쓰기를 위한 유틸리티 함수 제공
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from env_loader import load_env, get_env, get_credentials_path

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 환경변수 로드
load_env()

# 인증 파일 경로
CREDENTIALS_FILE = str(get_credentials_path())

SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

# 컬럼 인덱스 (0-based)
COL_STATUS = 0
COL_ASSIGNEE = 1
COL_JIRA_KEY = 2
COL_SEVERITY = 3
COL_QUALITY = 4
COL_TYPE = 5
COL_FILE = 6
COL_LINE = 7
COL_MESSAGE = 8
COL_RULE = 9
COL_CLEAN_CODE = 10
COL_SONAR_KEY = 11
COL_CREATED = 12
# 추가 컬럼 (워크플로우용)
COL_LOCK_TS = 13
COL_ATTEMPT_ANALYSIS = 14
COL_ATTEMPT_FIX = 15
COL_REPORT_URL = 16
COL_LAST_ERROR = 17
COL_APPROVED_BY = 18
COL_APPROVED_TS = 19


SEVERITY_ORDER = {'BLOCKER': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}


class SheetsClient:
    def __init__(self, spreadsheet_id: str = None, worksheet_name: str = None):
        if spreadsheet_id is None:
            spreadsheet_id = get_env('SPREADSHEET_ID')
        if not os.path.exists(CREDENTIALS_FILE):
            raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")

        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPES)
        self.client = gspread.authorize(creds)

        try:
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"Spreadsheet not found: {spreadsheet_id}")
            raise

        if worksheet_name:
            self.worksheet = self.spreadsheet.worksheet(worksheet_name)
        else:
            self.worksheet = self.spreadsheet.sheet1

    def get_all_issues(self) -> List[Dict]:
        """모든 이슈를 딕셔너리 리스트로 반환"""
        data = self.worksheet.get_all_values()
        if len(data) < 2:
            return []

        headers = data[0]
        issues = []
        for i, row in enumerate(data[1:], start=2):
            issue = {headers[j]: row[j] if j < len(row) else '' for j in range(len(headers))}
            issue['_row'] = i
            issues.append(issue)
        return issues

    def get_issues_by_status(self, status: str) -> List[Dict]:
        """특정 상태의 이슈 반환"""
        return [i for i in self.get_all_issues() if i.get('상태') == status]

    def get_issues_by_assignee(self, assignee: str) -> List[Dict]:
        """특정 담당자의 이슈 반환"""
        return [i for i in self.get_all_issues() if i.get('담당자') == assignee]

    def get_my_issues(self, assignee: str, statuses: List[str] = None) -> List[Dict]:
        """내 담당 이슈 중 특정 상태만 반환"""
        issues = self.get_issues_by_assignee(assignee)
        if statuses:
            issues = [i for i in issues if i.get('상태') in statuses]
        return issues

    def claim_issues(self, count: int, assignee: str) -> List[Dict]:
        """DEPRECATED: claim 단계가 제거됨. NEW 상태 이슈 N개를 claim"""
        new_issues = self.get_issues_by_status('대기')[:count]

        now = datetime.now().isoformat()
        for issue in new_issues:
            row = issue['_row']
            self.worksheet.update_cell(row, COL_STATUS + 1, 'CLAIMED')
            self.worksheet.update_cell(row, COL_ASSIGNEE + 1, assignee)
            self.worksheet.update_cell(row, COL_LOCK_TS + 1, now)

        return new_issues

    def distribute_issues(self, members: list[str]) -> dict[str, list[dict]]:
        """DEPRECATED: claim 단계가 제거됨. 대기 이슈를 심각도 순 정렬 후 멤버에게 라운드로빈 분배"""
        waiting = self.get_issues_by_status('대기')
        # 심각도 높은 순 정렬
        waiting.sort(key=lambda x: SEVERITY_ORDER.get(x.get('심각도', ''), 99))

        # 라운드로빈 분배
        result = {m: [] for m in members}
        now = datetime.now().isoformat()
        for i, issue in enumerate(waiting):
            member = members[i % len(members)]
            row = issue['_row']
            self.worksheet.update_cell(row, COL_STATUS + 1, 'CLAIMED')
            self.worksheet.update_cell(row, COL_ASSIGNEE + 1, member)
            self.worksheet.update_cell(row, COL_LOCK_TS + 1, now)
            result[member].append(issue)

        return result

    def update_status(self, row: int, status: str):
        """이슈 상태 업데이트"""
        self.worksheet.update_cell(row, COL_STATUS + 1, status)

    def update_jira_key(self, row: int, jira_key: str):
        """Jira 키 업데이트"""
        self.worksheet.update_cell(row, COL_JIRA_KEY + 1, jira_key)

    def update_attempt(self, row: int, attempt_type: str, count: int):
        """시도 횟수 업데이트"""
        if attempt_type == 'analysis':
            self.worksheet.update_cell(row, COL_ATTEMPT_ANALYSIS + 1, str(count))
        elif attempt_type == 'fix':
            self.worksheet.update_cell(row, COL_ATTEMPT_FIX + 1, str(count))

    def update_error(self, row: int, error: str):
        """에러 메시지 업데이트"""
        self.worksheet.update_cell(row, COL_LAST_ERROR + 1, error)

    def update_report_url(self, row: int, url: str):
        """보고서 URL 업데이트"""
        self.worksheet.update_cell(row, COL_REPORT_URL + 1, url)

    def approve_issue(self, row: int, approver: str):
        """이슈 승인"""
        now = datetime.now().isoformat()
        self.worksheet.update_cell(row, COL_STATUS + 1, 'APPROVED')
        self.worksheet.update_cell(row, COL_APPROVED_BY + 1, approver)
        self.worksheet.update_cell(row, COL_APPROVED_TS + 1, now)
