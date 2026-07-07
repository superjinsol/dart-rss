#!/usr/bin/env python3
"""
DART 공시 RSS 생성기
담당 기업 공시를 DART Open API로 수집해 RSS XML 파일로 저장
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DART_API_KEY = os.environ.get("DART_API_KEY", "")
OUTPUT_PATH = Path("docs/feed.xml")
STATE_PATH = Path("docs/seen.json")
LOOKBACK_DAYS = 3          # 최근 며칠치 공시 조회
MAX_ITEMS_PER_RUN = 200    # RSS 아이템 최대 개수

# ──────────────────────────────────────────────
# 담당 기업 목록 (종목명 → corp_code는 API로 조회)
# ──────────────────────────────────────────────
TARGET_COMPANIES = [
    # 유통 채널
    "BGF리테일", "BGF", "GS리테일", "GS", "이마트", "신세계",
    "롯데쇼핑", "롯데하이마트", "현대백화점", "현대지에프홀딩스",
    "한화갤러리아", "광주신세계", "신세계인터내셔날",
    "현대홈쇼핑", "NS홈쇼핑", "한섬", "서부T&D",
    # 식품·음료
    "CJ제일제당", "CJ", "CJ씨푸드", "농심", "농심홀딩스",
    "삼양식품", "삼양홀딩스", "삼양사", "오뚜기",
    "대상", "대상홀딩스", "풀무원", "빙그레", "남양유업",
    "매일유업", "매일홀딩스", "하이트진로", "하이트진로홀딩스",
    "롯데칠성음료", "롯데웰푸드", "오리온", "오리온홀딩스",
    "크라운제과", "크라운해태홀딩스", "해태제과식품", "동서",
    # 수산·식자재
    "동원산업", "동원수산", "사조대림", "사조씨푸드",
    "삼립", "샘표식품", "샘표",
    # 담배
    "KT&G",
    # 프랜차이즈·외식
    "교촌에프앤비", "더본코리아", "신세계푸드", "맘스터치앤컴퍼니",
    # 유통 지주·복합
    "롯데지주", "현대그린푸드", "CJ프레시웨이",
    # 호텔·면세·레저·카지노
    "호텔신라", "파라다이스", "아난티", "호텔롯데", "GKL", "강원랜드",
    # 하림 그룹
    "하림", "하림지주",
    # IT·커머스
    "SK스퀘어",
    # 기타
    "한화",
]

# ──────────────────────────────────────────────
# DART corp_code 매핑 (캐시)
# ──────────────────────────────────────────────
def get_corp_code_map() -> dict:
    """DART에서 전체 기업 목록 다운로드 후 corp_name → corp_code 매핑"""
    import zipfile, io

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    resp = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        with z.open("CORPCODE.xml") as f:
            tree = ET.parse(f)

    mapping = {}
    for item in tree.getroot().findall("list"):
        name = item.findtext("corp_name", "").strip()
        code = item.findtext("corp_code", "").strip()
        stock = item.findtext("stock_code", "").strip()
        # 상장사 우선 (stock_code 있는 것), 없으면 비상장도 포함
        if name and code:
            if name not in mapping or stock:  # 상장사가 있으면 덮어씀
                mapping[name] = code
    return mapping


# ──────────────────────────────────────────────
# 공시 조회
# ──────────────────────────────────────────────
def fetch_disclosures(corp_code: str, bgn_de: str) -> list:
    """특정 기업의 최근 공시 목록 조회"""
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "page_count": 40,
        "sort": "date",
        "sort_mth": "desc",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
    except Exception as e:
        print(f"  [오류] {corp_code}: {e}")
    return []


# ──────────────────────────────────────────────
# RSS 생성
# ──────────────────────────────────────────────
def build_rss(items: list) -> str:
    """수집한 공시 목록으로 RSS 2.0 XML 생성"""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "DART 공시 - 담당 기업"
    ET.SubElement(channel, "link").text = "https://dart.fss.or.kr"
    ET.SubElement(channel, "description").text = "블로터 유통산업부 담당 기업 DART 공시 피드"
    ET.SubElement(channel, "language").text = "ko"
    ET.SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    for item in items[:MAX_ITEMS_PER_RUN]:
        entry = ET.SubElement(channel, "item")
        rcept_no = item.get("rcept_no", "")
        corp_name = item.get("corp_name", "")
        report_nm = item.get("report_nm", "")
        rcept_dt = item.get("rcept_dt", "")  # YYYYMMDD

        title_text = f"[{corp_name}] {report_nm}"
        link_text = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

        # 날짜 파싱
        try:
            dt = datetime.strptime(rcept_dt, "%Y%m%d")
            pub_date = dt.strftime("%a, %d %b %Y 09:00:00 +0900")
        except Exception:
            pub_date = ""

        ET.SubElement(entry, "title").text = title_text
        ET.SubElement(entry, "link").text = link_text
        ET.SubElement(entry, "guid").text = rcept_no
        ET.SubElement(entry, "pubDate").text = pub_date
        ET.SubElement(entry, "description").text = (
            f"{corp_name} | {report_nm} | 접수일: {rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"
        )

    # 보기 좋게 indent
    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


# ──────────────────────────────────────────────
# 중복 방지 (seen.json)
# ──────────────────────────────────────────────
def load_seen() -> set:
    if STATE_PATH.exists():
        return set(json.loads(STATE_PATH.read_text()))
    return set()


def save_seen(seen: set):
    STATE_PATH.write_text(json.dumps(sorted(seen)))


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    if not DART_API_KEY:
        raise RuntimeError("DART_API_KEY 환경변수가 없습니다.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("▶ corp_code 매핑 로딩 중...")
    corp_map = get_corp_code_map()

    bgn_de = (datetime.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    seen = load_seen()
    all_items = []

    for corp_name in TARGET_COMPANIES:
        corp_code = corp_map.get(corp_name)
        if not corp_code:
            print(f"  [미매칭] {corp_name}")
            continue

        disclosures = fetch_disclosures(corp_code, bgn_de)
        new_items = [d for d in disclosures if d.get("rcept_no") not in seen]
        print(f"  {corp_name}: {len(new_items)}건 신규")
        all_items.extend(new_items)

    # 최신순 정렬
    all_items.sort(key=lambda x: x.get("rcept_dt", "") + x.get("rcept_no", ""), reverse=True)

    # RSS 저장
    rss_xml = build_rss(all_items)
    OUTPUT_PATH.write_text(rss_xml, encoding="utf-8")
    print(f"\n✅ RSS 저장 완료: {OUTPUT_PATH} ({len(all_items)}건)")

    # seen 업데이트
    new_seen = seen | {d["rcept_no"] for d in all_items if "rcept_no" in d}
    # seen이 너무 커지지 않도록 최근 2000개만 유지
    save_seen(set(sorted(new_seen)[-2000:]))


if __name__ == "__main__":
    main()
