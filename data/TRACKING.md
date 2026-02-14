# Data Directory

이 디렉토리는 sonar-intake 스킬이 SonarQube API에서 수집한 이슈 데이터를 저장합니다.

## 구조

```
data/
├── {project_key}_{timestamp}/
│   └── all_issues.json          # SonarQube API 원본 응답
├── {project_key}_{timestamp}.csv # CSV 변환 결과
└── TRACKING.md                  # 이 파일
```

## 참고

- `all_issues.json`: SonarQube `/api/issues/search` 응답 전체
- `.csv`: Google Sheets 업로드용 변환 파일
- 추적 DB는 `.claude/data/sonar_tracking.db`에 별도 저장
