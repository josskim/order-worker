# 2026-11-07 KST · 사이트별 확정 카테고리 워커 반영

- 요청: “정리해서 배포해줘”. 인트라넷에서 확정한 실제 카테고리로 등록한다.
- 변경: 실제 분류 수집기/JSON 내보내기, 계정별 확정 경로를 별도 요청에 적용, 누락 경로 차단, 하위 분류 AJAX 대기, 도매꾹 정확한 버튼명 선택 및 대기 중이던 추천/안내창 처리 보완, 사이트 오류의 결과 보존. 신상마켓 브리지는 등록용 계정과 실제 루트/하위 경로를 전달한다.
- 파일: `order_worker/category_catalog.py`, `order_worker/category_selection.py`, `order_worker/sites/product_registration.py`, 오너클랜/온채널/스페셜오퍼/도매꾹 등록 runner, `scripts/sinsang-batch-registration.py`, 수집/내보내기 CLI와 관련 tests.
- 검증: 카테고리 정규화·경로 격리·지연 옵션 및 관련 상품등록 회귀 테스트 통과. 실제 분류 수집을 제외한 상품 저장 요청은 실행하지 않음.
- 최종 커밋 및 워커 반영 결과는 인트라넷 프로젝트 변경 이력에 기록한다.
