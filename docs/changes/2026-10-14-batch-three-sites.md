# 2026-10-14 KST · 조원/마법바지 일괄등록 실행 및 도매꾹 0/0

- 요청: 인트라넷 상품일괄등록에 조원·마법바지·시스터 실제 등록과 토글 연결. 도매꾹 부피/무게 모두 0.
- 결과: account1/account2 runner가 인접 sinsang 워커의 normal 엔진을 별도 프로세스로 호출. 기존 등록 확인 후 없을 때만 등록하고 후속 로그인 목록 확인 후 성공 반환. 시스터 서버 실행 결과 preResults를 summary에 병합. DB 토글 매핑 jupraha1/jupraha2/sister 추가, 임시저장 토글 제외는 유지.
- 도매꾹/F도매꾹 부피·무게 두 입력 단계 모두 0. 오래된 payload에도 0으로 입력.
- 실제 검증: G127150 두 신상마켓 계정 실제 등록과 별도 로그인 목록 재확인 통과. 대표컷 6장·17,000원·3색 FREE. 도매꾹 두 계정 입력창 0/0 확인(등록 제출 안 함).
- 테스트: mixed runner/preResults·성공/실패/임시저장 토글 매핑·온채널 회귀 총 10개 통과. Python compileall 통과.
- 변경: order_worker/sites/sinsang_registration.py, scripts/sinsang-batch-registration.py, order_worker/sites/product_registration.py, order_worker/sites/domeggook_registration.py, order_worker/database_transport.py, 관련 테스트.
- 적용: 매 작업 새 subprocess이므로 다음 작업부터 실행. SINSANG_WORKER_ROOT로 인접 워커 위치 변경 가능. 최종 커밋/푸시 해시는 인트라넷 이력에 기록.
