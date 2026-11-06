"""광역시도 경계(GeoJSON) -> 대시보드용 경량 SVG 경로(src/korea_geo.json).

원자료: 통계청(KOSTAT) 센서스용 행정구역경계 2013, southkorea/southkorea-maps 저장소의 단순화 GeoJSON
  https://github.com/southkorea/southkorea-maps (kostat/2013/json/skorea_provinces_geo_simple.json)
시각화(지도 그리기) 용도로만 쓰며, 분석·예측에는 사용하지 않는다.
사용: python scripts/build_geo.py <geojson 경로>
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.regions import canon_assembly  # noqa: E402

LAT0 = 36.0
LABEL_AT = {"경기": (127.42, 37.88), "충남": (126.75, 36.55), "전남": (126.95, 34.82)}
K = math.cos(math.radians(LAT0))


def proj(lon, lat):
    return lon * K, -lat


def area(ring):
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def main(src, out, W=600, eps=0.006, min_area=0.004):
    d = json.load(open(src, encoding="utf-8"))
    polys = {}
    for f in d["features"]:
        code = canon_assembly(f["properties"]["name"])
        g = f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        keep = []
        for p in parts:
            ring = [proj(*pt) for pt in p[0]]
            a = abs(area(ring))
            cx = sum(x for x, _ in ring) / len(ring) / K
            if cx < 125.0:          # 백령도 등 서해 최북단 도서: 지도 폭을 넓혀 생략
                continue
            if code == "제주":       # 제주는 위로 당겨 배치(삽입 지도 관행), 실제 위치와 다름을 범례에 명시
                ring = [(x, y - 0.5) for x, y in ring]
            if cx > 130.2:          # 울릉도·독도: 본토 지도 범위를 크게 넓혀 생략(범례에 명시)
                continue
            if a < min_area and code != "제주":
                continue            # 작은 섬 생략
            keep.append((a, ring))
        keep.sort(key=lambda t: -t[0])
        polys[code] = keep
    xs = [x for v in polys.values() for _, r in v for x, _ in r]
    ys = [y for v in polys.values() for _, r in v for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = (W - 20) / (x1 - x0)
    H = (y1 - y0) * s + 20
    T = lambda x, y: (round((x - x0) * s + 10, 1), round((y - y0) * s + 10, 1))  # noqa: E731
    res = {}
    for code, v in polys.items():
        dstr = []
        for _, ring in v:
            n = len(ring)
            pts = rdp(ring[:n // 2 + 1], eps)[:-1] + rdp(ring[n // 2:] + [ring[0]], eps)  # 닫힌 고리는 반으로 나눠 단순화
            if len(pts) < 4:
                continue
            q = [T(*p) for p in pts]
            dstr.append("M" + " L".join(f"{x},{y}" for x, y in q) + "Z")
        big = v[0][1]
        a = area(big)
        cx = sum((x1_ + x2_) * (x1_ * y2_ - x2_ * y1_) for (x1_, y1_), (x2_, y2_) in zip(big, big[1:] + big[:1])) / (6 * a)
        cy = sum((y1_ + y2_) * (x1_ * y2_ - x2_ * y1_) for (x1_, y1_), (x2_, y2_) in zip(big, big[1:] + big[:1])) / (6 * a)
        if code in LABEL_AT:  # 다른 시도를 감싸는 경기도 등은 무게중심 대신 지정 위치에 이름 표시
            cx, cy = proj(*LABEL_AT[code])
        res[code] = dict(d=" ".join(dstr), c=T(cx, cy))
    out_obj = dict(w=W, h=round(H), source="통계청 센서스용 행정구역경계(2013), southkorea/southkorea-maps", regions=res)
    Path(out).write_text(json.dumps(out_obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{out}: {len(res)} regions, {Path(out).stat().st_size/1024:.0f}KB, {W}x{round(H)}")


if __name__ == "__main__":
    main(sys.argv[1], str(Path(__file__).resolve().parents[1] / "src" / "korea_geo.json"))
