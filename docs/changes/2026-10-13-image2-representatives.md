# 2026-10-13 KST · 대표이미지 보호 및 임시저장 토글 제외

- 요청: 인트라넷 일괄등록 대표이미지는 사이즈표를 제외한 image2 대표컷 사용. 임시저장 완료를 등록 토글로 표시하지 않음.
- 결과: 온채널 업로드 전 image2 저장경로·1000 파일명을 검사해 과거 대기 요청에 섞인 image1 대표컷 업로드 방지. 작업 결과의 draftSaved/alreadyDraft를 DB 토글 활성화 대상에서 제외.
- 부가 복구: 저장 성공 이후 사이트의 늦은 이동이 목록 GET과 충돌하는 경우, 읽기 전용 GET만 1회 재시도. 저장 요청 자체는 재실행하지 않음.
- 실검증: CH5531839/CH5531840 기존 임시저장에 올바른 대표컷 각각 4개로 수정. 원본 image2 파일과 내려받은 온채널 이미지가 모두 일치. 상세 6장, 블랙/FREE 옵션, 공급가 15,000원 보존 확인.
- 검증: tests/test_database_transport.py, tests/test_onchannel_registration.py, tests/test_product_registration.py 총 9개 통과.
- 변경 파일: order_worker/sites/onchannel_registration.py, order_worker/database_transport.py, tests/test_onchannel_registration.py, tests/test_database_transport.py.
- 최종 커밋/푸시 결과는 인트라넷 이력에 기록. 다음 작업의 새 subprocess부터 적용.
