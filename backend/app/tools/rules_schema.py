"""The editable values of config/strategy_rules.yaml: which agent uses each one, what it means, and its valid range.

The rules screen (api/rules.py, frontend RulesView) is drawn from FIELDS, and every save is checked against them,
so a value the agents cannot use never reaches them. docs/AGENTS.md explains the same values in prose.
"""

import re

# Page features measured by the PDF engine (ToolPDF /v1/profile) that profiler rules can test.
FEATURES = {
    "text_chars": "글자 수",
    "text_area_ratio": "텍스트 면적 비율",
    "images": "이미지 수",
    "image_area_ratio": "이미지 면적 비율",
    "drawings": "벡터 도형 수",
    "tables": "표 수",
    "table_area_ratio": "표 면적 비율",
    "table_text_share": "표 안 글자 비율",
}
LABELS = ["text", "scanned", "table", "diagram", "chart", "image_heavy", "mixed"]
PARSERS = ["pymupdf_text", "pymupdf_tables", "vlm_ocr", "vlm_figures"]

AGENTS = [
    {"key": "intake", "label": "형식 판별", "about": "Office 문서를 PDF로 바꾸는 방법. PDF·이미지는 바꿀 값이 없다."},
    {"key": "profile", "label": "콘텐츠 분석", "about": "쪽마다 특징을 재서 라벨을 붙이는 규칙. 위에서부터 처음 맞는 규칙을 쓴다."},
    {"key": "strategy", "label": "전략 결정", "about": "쪽 라벨별 파서와 청킹 방식을 고르는 기준. 청크 크기는 청킹 탭에 있다."},
    {"key": "parse", "label": "파싱", "about": "추출 묶음 크기, 그림·캡션·표 재추출 기준."},
    {"key": "chunk", "label": "청킹", "about": "청크 크기·겹침·최소 크기. 전략 결정 단계가 이 값으로 계획을 세우고 청킹 단계가 쓴다."},
    {"key": "embed", "label": "임베딩", "about": "바꿀 규칙 값이 없다. 임베딩·VLM·reranker 모델 주소는 config/models.yaml에서 정한다."},
]


def _f(agent, path, label, help, type, **kw):
    return {"agent": agent, "path": path, "label": label, "help": help, "type": type, **kw}


FIELDS = [
    # intake
    _f("intake", ["office", "prefer"], "Office 변환 우선", "libreoffice: 원본 레이아웃에 가장 가깝다(ToolPDF에 LibreOffice가 있을 때). native: ToolPDF 자체 렌더링.",
       "choice", choices=["libreoffice", "native"]),
    _f("intake", ["office", "xlsx"], "엑셀 변환", "native: 시트를 표로 그려 모든 칸이 읽힌다(권장). libreoffice: 넓은 시트가 쪽마다 잘린다.",
       "choice", choices=["native", "libreoffice"]),
    _f("intake", ["office", "xlsx_rows_per_page"], "엑셀 쪽당 행 수", "시트를 이 행 수마다 한 쪽으로 나누고 머리 행을 반복한다.", "int", min=1, max=500),
    _f("intake", ["office", "xlsx_max_rows"], "엑셀 시트당 최대 행 수", "넘으면 잘라내고 근거에 남긴다.", "int", min=1, max=1_000_000),
    # profile
    _f("profile", ["profiler", "rules"], "쪽 분류 규칙", "위에서부터 차례로 보고 조건이 모두 맞는 첫 규칙의 라벨을 붙인다. 조건 min_: 특징 ≥ 값, max_: 특징 ≤ 값.",
       "rule_list"),
    _f("profile", ["profiler", "default", "label"], "어느 규칙에도 안 맞을 때 라벨", "신뢰도 0.4로 붙는다.", "choice", choices=LABELS),
    _f("profile", ["profiler", "vlm_review_below"], "VLM 재판단 기준 신뢰도", "규칙 신뢰도가 이보다 낮은 쪽을 VLM에 다시 묻는다. 0이면 묻지 않는다.",
       "float", min=0, max=1, step=0.05),
    _f("profile", ["profiler", "vlm_review_max_pages"], "VLM 재판단 최대 쪽 수", "신뢰도 낮은 순으로 이 쪽 수까지만 묻는다.", "int", min=0, max=100),
    _f("profile", ["profiler", "batch_pages"], "한 번에 분석할 쪽 수", "ToolPDF에 특징을 요청하는 묶음 크기. 진행 표시 단위다.", "int", min=1, max=200),
    _f("profile", ["strategy", "dominant_ratio"], "문서 성격 기준 비율", "가장 많은 라벨이 이 비율 이상이면 '<라벨>-dominant', 아니면 mixed.",
       "float", min=0, max=1, step=0.05),
    # strategy
    _f("strategy", ["strategy", "parsers"], "쪽 라벨별 파서", "vlm_* 파서는 VLM이 없으면 대체 파서로 바뀐다.", "parser_map"),
    _f("strategy", ["strategy", "fallback"], "대체 파서", "VLM이 없을 때, 그리고 라벨에 파서가 없을 때 쓴다.", "choice", choices=["pymupdf_text", "pymupdf_tables"]),
    _f("strategy", ["strategy", "heading_size_ratio"], "제목 글자 크기 배율", "본문 글자 크기(가장 많이 쓰인 크기)의 이 배 이상을 제목으로 본다.",
       "float", min=1, max=3, step=0.05),
    _f("strategy", ["strategy", "section_min_page_ratio"], "절 단위 청킹 기준", "제목 크기 글자가 있는 쪽이 이 비율 이상이면 절(section) 단위로 나눈다. 아니면 크기 기준(recursive).",
       "float", min=0, max=1, step=0.05),
    # parse
    _f("parse", ["parse", "window_pages"], "추출 묶음 쪽 수", "ToolPDF에 한 번에 추출을 맡기는 쪽 수. 큰 문서의 메모리를 묶는다.", "int", min=1, max=100),
    _f("parse", ["parse", "windows_in_flight"], "동시에 요청할 묶음 수", "ToolPDF의 처리 프로세스 수보다 크게 두면 VLM 호출과 다음 묶음 준비가 겹친다.", "int", min=1, max=64),
    _f("parse", ["parse", "figures", "enrich_native_pages"], "텍스트·표 쪽의 그림도 설명", "끄면 다이어그램·이미지·차트 쪽의 그림만 VLM에 설명시킨다.", "bool"),
    _f("parse", ["parse", "figures", "min_area_ratio"], "그림으로 볼 최소 면적", "이미지·도형 덩어리가 쪽 면적의 이 비율 이상이면 그림 영역으로 본다.",
       "float", min=0, max=1, step=0.01),
    _f("parse", ["parse", "figures", "max_per_page"], "쪽당 최대 그림 수", "큰 것부터 이 개수까지 VLM에 설명시킨다.", "int", min=0, max=20),
    _f("parse", ["parse", "captions", "pattern"], "캡션 패턴(정규식)", "이 패턴으로 시작하는 줄을 캡션으로 보고 가까운 그림·표에 붙인다. 대소문자 구분 없음.", "regex"),
    _f("parse", ["parse", "captions", "max_gap"], "캡션 최대 거리(pt)", "그림·표 위아래 이 거리 안의 캡션만 붙인다.", "float", min=0, max=500, step=1),
    _f("parse", ["parse", "tables", "max_empty_cell_ratio"], "표 재추출 기준 빈 칸 비율", "빈 칸 비율이 이보다 크면(병합 셀, 선 없는 칸) 그 표를 VLM으로 다시 읽는다. 1이면 다시 읽지 않는다.",
       "float", min=0, max=1, step=0.05),
    _f("parse", ["parse", "relabel_chart_min_area"], "차트로 다시 분류할 면적", "다이어그램·이미지 쪽에서 VLM이 차트라고 한 그림이 이 비율 이상이면 쪽 라벨을 chart로 바꾼다.",
       "float", min=0, max=1, step=0.05),
    # chunk (planned by the strategy agent, applied by the chunker)
    _f("chunk", ["strategy", "target_tokens"], "청크 크기(토큰)", "임베딩 모델 토큰 단위. 모델 max_tokens - 16을 넘으면 그 값으로 줄인다.", "int", min=64, max=8192),
    _f("chunk", ["strategy", "overlap_tokens"], "겹침(토큰)", "본문이 크기 때문에 끊길 때 앞 청크 끝을 다음 청크 앞에 반복한다. 청크 크기의 1/4까지.", "int", min=0, max=2048),
    _f("chunk", ["strategy", "min_tokens"], "최소 청크 크기(토큰)", "이보다 짧은 청크를 같은 절의 이웃 청크와 합친다. 0이면 합치지 않는다. 청크 크기의 1/2까지.",
       "int", min=0, max=4096),
]

_BY_PATH = {tuple(f["path"]): f for f in FIELDS}


def get(d: dict, path: list[str]):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _leaves(d, prefix=()):
    """Paths of every value, stopping at fields that hold a whole structure (rule list, parser map)."""
    if prefix in _BY_PATH or not isinstance(d, dict):
        yield prefix
        return
    for k, v in d.items():
        yield from _leaves(v, prefix + (k,))


def _number(f: dict, v, where: str, errors: list[str]) -> None:
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and (f["type"] == "float" or float(v).is_integer())
    if not ok:
        errors.append(f"{where}: {'정수' if f['type'] == 'int' else '숫자'}여야 합니다")
    elif not (f["min"] <= v <= f["max"]):
        errors.append(f"{where}: {f['min']}~{f['max']} 사이여야 합니다 (지금 {v})")


def _rule_list(v, errors: list[str]) -> None:
    if not isinstance(v, list) or not v:
        errors.append("쪽 분류 규칙: 규칙이 하나 이상 있어야 합니다")
        return
    ids = set()
    for i, r in enumerate(v, 1):
        where = f"쪽 분류 규칙 {i}번"
        if not isinstance(r, dict) or set(r) - {"id", "label", "when"}:
            errors.append(f"{where}: id, label, when 만 쓸 수 있습니다")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", rid or ""):
            errors.append(f"{where}: id는 영어 소문자·숫자·_ 로 쓴다 (예: table_dominant)")
        elif rid in ids:
            errors.append(f"{where}: id '{rid}'가 겹칩니다")
        ids.add(rid)
        if r.get("label") not in LABELS:
            errors.append(f"{where}: label은 {', '.join(LABELS)} 중 하나")
        when = r.get("when")
        if not isinstance(when, dict) or not when:
            errors.append(f"{where}: 조건(when)이 하나 이상 있어야 합니다")
            continue
        for key, val in when.items():
            kind, _, feat = key.partition("_")
            if kind not in ("min", "max") or feat not in FEATURES:
                errors.append(f"{where}: 조건 '{key}'를 알 수 없습니다 (min_/max_ + {', '.join(FEATURES)})")
            elif not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0:
                errors.append(f"{where}: 조건 '{key}'의 값은 0 이상의 숫자")


def _bad_text(v) -> bool:
    """Text that cannot be stored as UTF-8 (lone surrogates from a client that mis-decoded Korean)."""
    if isinstance(v, str):
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            return True
        return False
    if isinstance(v, dict):
        return any(_bad_text(k) or _bad_text(x) for k, x in v.items())
    if isinstance(v, list):
        return any(_bad_text(x) for x in v)
    return False


def validate(rules: dict) -> list[str]:
    """Problems with a full rules dict (as the screen sends it); empty when the agents can use it."""
    errors: list[str] = []
    if not isinstance(rules, dict):
        return ["규칙은 객체여야 합니다"]
    if _bad_text(rules):
        return ["깨진 글자가 있습니다(한글 인코딩이 맞지 않는 요청). 화면에서 다시 저장하세요"]
    for leaf in _leaves(rules):
        if leaf not in _BY_PATH and leaf != ("profiler", "default", "id"):
            errors.append(f"{'.'.join(leaf)}: 바꿀 수 없는 항목입니다")
    for f in FIELDS:
        v, where = get(rules, f["path"]), f["label"]
        if v is None:
            errors.append(f"{where}: 값이 없습니다")
        elif f["type"] in ("int", "float"):
            _number(f, v, where, errors)
        elif f["type"] == "bool" and not isinstance(v, bool):
            errors.append(f"{where}: 켬/끔이어야 합니다")
        elif f["type"] == "choice" and v not in f["choices"]:
            errors.append(f"{where}: {', '.join(f['choices'])} 중 하나")
        elif f["type"] == "regex":
            try:
                re.compile(v)
            except (re.error, TypeError) as e:
                errors.append(f"{where}: 정규식 오류 ({e})")
        elif f["type"] == "rule_list":
            _rule_list(v, errors)
        elif f["type"] == "parser_map":
            if not isinstance(v, dict) or set(v) != set(LABELS) or any(p not in PARSERS for p in v.values()):
                errors.append(f"{where}: 라벨 {len(LABELS)}개 모두에 {', '.join(PARSERS)} 중 하나")
    tgt, ov, mn = (get(rules, ["strategy", k]) for k in ("target_tokens", "overlap_tokens", "min_tokens"))
    if all(isinstance(x, int) for x in (tgt, ov, mn)):
        if ov > tgt // 4:
            errors.append(f"겹침: 청크 크기의 1/4({tgt // 4}) 이하여야 합니다")
        if mn > tgt // 2:
            errors.append(f"최소 청크 크기: 청크 크기의 1/2({tgt // 2}) 이하여야 합니다")
    return errors


def diff(base, new):
    """Only what differs from the shipped rules (what the override file stores)."""
    if isinstance(base, dict) and isinstance(new, dict):
        out = {}
        for k, v in new.items():
            if k not in base:
                out[k] = v
            elif (d := diff(base[k], v)) is not None:
                out[k] = d
        return out or None
    return None if base == new else new


def changed_paths(base: dict, new: dict) -> list[list[str]]:
    """Field paths whose value differs from the default, for the screen's "changed" marks."""
    return [f["path"] for f in FIELDS if get(base, f["path"]) != get(new, f["path"])]
