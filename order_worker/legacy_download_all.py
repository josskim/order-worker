"""
전체 사이트 주문서 자동 가져오기 마스터 스크립트
실행: python download_all.py
결과: 오너클랜 N건 등록, 온채널 M건 등록 ... 형태로 출력
"""
import asyncio
import sys
import json
import os
import requests
import uuid

# sites 폴더를 path에 추가 (절대 경로 사용)
base_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, base_dir)

try:
    import sites
    from sites import ownerclan, onchannel, domeggook, specialoffer, domesin
except Exception as e:
    import traceback
    print(f"PROGRESS: [시스템] 임포트 오류 발생: {str(e)}")
    print(f"PROGRESS: [디버그] {traceback.format_exc()}")
    sys.exit(1)

def format_result(r: dict) -> str:
    site = r.get("site", "?")
    if not r.get("success"):
        err = r.get("error", "알 수 없는 오류")
        return f"[실패] {site}: ({err})"
    inserted = r.get("insertedCount", 0)
    duplicate = r.get("duplicateCount", 0)
    total = r.get("totalRows", 0)
    if total == 0:
        return f"[없음] {site}: 주문 없음"
    return f"[성공] {site}: {inserted}건 등록 (중복 {duplicate}건)"

async def main():
    # 시작 전 doc/excel 폴더 비우기 (이전 잔여 파일 제거)
    try:
        from sites.utils import DOWNLOAD_DIR
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath): os.remove(fpath)
    except: pass

    all_results = []
    print("=" * 50)
    print("[시스템] 전체 사이트 주문서 자동 가져오기 시작")
    print("=" * 50)

    # 1. 오너클랜 / F오너클랜
    print("PROGRESS: [오너클랜] 작업 시작...")
    try:
        results = await ownerclan.run()
        all_results.extend(results)
    except Exception as e:
        all_results.append({"site": "오너클랜", "success": False, "error": str(e)})
        all_results.append({"site": "F오너클랜", "success": False, "error": str(e)})

    # 2. 온채널 / F온채널
    print("PROGRESS: [온채널] 작업 시작...")
    try:
        results = await onchannel.run()
        all_results.extend(results)
    except Exception as e:
        all_results.append({"site": "온채널", "success": False, "error": str(e)})
        all_results.append({"site": "F온채널", "success": False, "error": str(e)})

    # 3. 도매꾹 / F도매꾹
    print("PROGRESS: [도매꾹] 작업 시작...")
    try:
        results = await domeggook.run()
        all_results.extend(results)
    except Exception as e:
        all_results.append({"site": "도매꾹", "success": False, "error": str(e)})
        all_results.append({"site": "F도매꾹", "success": False, "error": str(e)})

    # 4. 스페셜오퍼
    print("PROGRESS: [스페셜오퍼] 작업 시작...")
    try:
        results = await specialoffer.run()
        all_results.extend(results)
    except Exception as e:
        all_results.append({"site": "스페셜오퍼", "success": False, "error": str(e)})

    # 5. 도매의신
    print("PROGRESS: [도매의신] 작업 시작...")
    try:
        results = await domesin.run()
        all_results.extend(results)
    except Exception as e:
        all_results.append({"site": "도매의신", "success": False, "error": str(e)})

    print("\n" + "=" * 50)
    print("[시스템] 전체 결과:")
    print("=" * 50)
    for r in all_results:
        print(format_result(r))

    # 최종 JSON 결과 출력 전 doc/excel 폴더 다시 한번 비우기
    try:
        from sites.utils import DOWNLOAD_DIR
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath): os.remove(fpath)
    except: pass

    # 텔레그램 리포트 발송
    try:
        from sites.utils import send_telegram_message, INTRANET_API
        run_id = str(uuid.uuid4())[:8]

        # 1. 텔레그램 발송
        msg = f"<b>[인트라넷 주문 수집 리포트]</b>\n(ID: {run_id})\n\n"
        for r in all_results:
            msg += format_result(r) + "\n"
        send_telegram_message(msg)

        # 2. DB 로그 기록 (웹 팝업용)
        log_api = INTRANET_API.replace("/run", "") + "/log"
        requests.post(log_api, json={"run_id": run_id, "summary": all_results}, timeout=10)
    except Exception as e:
        print(f"PROGRESS: [로그 기록 실패] {e}")

    # JSON 결과도 출력 (인트라넷 API가 파싱용)
    print("\n__JSON__")
    print(json.dumps(all_results, ensure_ascii=False))

    return all_results

if __name__ == "__main__":
    asyncio.run(main())
