# 최종 산출물

| 항목 | 값 |
|------|-----|
| Issue Key | {JIRA-KEY 또는 SonarQube키} |
| Worktree | `worktrees/{issue_key}` |
| 브랜치 | `fix/{issue_key}` |
| 상태 | DONE |

---

## 변경 요약

{한 페이지 요약}

## 영향범위

{영향받는 모듈/기능}

## 리스크

{주의사항}

---

## 커밋 메시지 (복사용)

```
fix({모듈}): {한 줄 요약}

{상세 설명}

- {변경사항 1}
- {변경사항 2}

Issue: {JIRA-KEY 또는 SonarQube키}
```

## PR 설명 (복사용)

```markdown
## Summary

{변경 내용 요약}

## Changes

- {변경사항 1}
- {변경사항 2}

## Test Plan

- [ ] {테스트 항목 1}
- [ ] {테스트 항목 2}

## Related

- Issue: {JIRA-KEY 또는 SonarQube키}
- 분석 보고서: `reports/{issue_key}/01_analysis_report.md`
```

---

## 수동 작업 안내

### 1. 변경 사항 확인

```bash
cd worktrees/{issue_key}
git status
git diff
```

### 2. 커밋 생성

```bash
cd worktrees/{issue_key}
git add .
git commit -m "위의 커밋 메시지 붙여넣기"
```

### 3. 푸시 및 PR 생성

```bash
git push -u origin fix/{issue_key}
gh pr create --title "제목" --body "위의 PR 설명 붙여넣기"
```

### 4. Worktree 정리 (PR 머지 후)

```bash
cd {프로젝트_루트}
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/cleanup_worktree.sh -j {issue_key}
```

---

## 관련 링크

- 분석 보고서: `reports/{issue_key}/01_analysis_report.md`
- 수정 보고서: `reports/{issue_key}/04_fix_report.md`
- 테스트 보고서: `reports/{issue_key}/06_test_report.md`

---

## TDD 산출물

- 테스트 파일: `{tests/sonar_tdd/test_{...}.py / N/A}`
- 결과: {BEFORE GREEN → AFTER GREEN / TDD 스킵 (사유)}
- 커밋에 테스트 파일 포함 여부: {Yes / No}

---

> **주의**: 이 문서는 자동 생성되었습니다. 커밋 및 PR 생성은 사용자가 직접 수행해야 합니다.
