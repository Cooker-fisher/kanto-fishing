#!/usr/bin/env python3
"""
気象データ収集スクリプト weather_crawl.py
- 気象庁アメダスから風速・風向・気温を取得
- NOWPHAS（港湾の沿岸波浪情報）から波高・波周期・潮位を取得
  URL: https://nowphas.mlit.go.jp/mapxml/       (波浪 XML)
       https://nowphas.mlit.go.jp/choui_mapxml/ (潮位 XML)
- weather_data/{海域コード}.csv に1時間ごとに追記

[NOWPHAS観測点コード（関東エリア）]
  217 = 第二海堡（東京湾）     wave+tide
  221 = 京浜港横浜（相模湾代替） tideのみ
  222 = 鹿島港（外房代替）     wave+tide
  209 = 茨城港常陸那珂（茨城）  wave+tide

[アメダス観測点IDの確認方法]
  https://www.jma.go.jp/bosai/amedas/const/amedastable.json
"""
import re, json, time, os, csv
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from xml.etree import ElementTree as ET
except ImportError:
    pass

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Safari/537.36"

# ── 海域設定 ───────────────────────────────────────────────────────────
SEA_AREAS = {
    "tokyo_bay": {
        "name":           "東京湾",
        "amedas_ids":     ["46106", "45401"],   # 横浜・館山
        "wave_code":      217,                   # 第二海堡
        "tide_code":      217,                   # 第二海堡
    },
    "sagami_bay": {
        "name":           "相模湾",
        "amedas_ids":     ["46211", "46106"],   # 三浦・横浜
        "wave_code":      None,                  # 観測点なし
        "tide_code":      221,                   # 京浜港横浜（代替）
    },
    "outer_boso": {
        "name":           "外房",
        "amedas_ids":     ["45371", "45148"],   # 勝浦・銚子
        "wave_code":      222,                   # 鹿島港（代替）
        "tide_code":      222,                   # 鹿島港
    },
    "ibaraki": {
        "name":           "茨城沖",
        "amedas_ids":     ["40046", "45148"],   # 大洗・銚子
        "wave_code":      209,                   # 茨城港常陸那珂
        "tide_code":      222,                   # 鹿島港（209に潮位データなしのため代替）
    },
}

CSV_HEADER = ["datetime", "wave_height", "wave_period", "wind_speed",
              "wind_dir", "temp", "tide_level", "area"]

_WIND_DIR_DEG = {
    1: 0, 2: 23, 3: 45, 4: 68, 5: 90, 6: 113, 7: 135, 8: 158,
    9: 180, 10: 203, 11: 225, 12: 248, 13: 270, 14: 293, 15: 315, 16: 338
}


def fetch(url):
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("utf-8", "cp932", "euc-jp"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  fetch error [{url}]: {e}"); return None


# ── 気象庁アメダス ─────────────────────────────────────────────────────

def get_latest_amedas_time():
    txt = fetch("https://www.jma.go.jp/bosai/amedas/data/latest_time.txt")
    if not txt: return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})', txt.strip())
    return "".join(m.groups()) + "00" if m else None

def fetch_amedas_map(time_str):
    url = f"https://www.jma.go.jp/bosai/amedas/data/map/{time_str}.json"
    txt = fetch(url)
    if not txt: return {}
    try: return json.loads(txt)
    except: return {}

def parse_amedas(amedas_data, station_ids):
    wind_speeds, wind_dirs, temps = [], [], []
    for sid in station_ids:
        d = amedas_data.get(sid)
        if not d: continue
        ws = d.get("wind")
        wd = d.get("windDirection")
        tp = d.get("temp")
        if ws and isinstance(ws, list) and ws[0] is not None:
            wind_speeds.append(float(ws[0]))
        if wd and isinstance(wd, list) and wd[0] is not None:
            wind_dirs.append(_WIND_DIR_DEG.get(int(wd[0]), 0))
        if tp and isinstance(tp, list) and tp[0] is not None:
            temps.append(float(tp[0]))
    return {
        "wind_speed": round(sum(wind_speeds) / len(wind_speeds), 1) if wind_speeds else None,
        "wind_dir":   round(sum(wind_dirs)   / len(wind_dirs))      if wind_dirs   else None,
        "temp":       round(sum(temps)        / len(temps), 1)       if temps       else None,
    }


# ── NOWPHAS（波浪・潮位） ─────────────────────────────────────────────
# URL: https://nowphas.mlit.go.jp/mapxml/       → 波浪 XML
#      https://nowphas.mlit.go.jp/choui_mapxml/ → 潮位 XML
# 欠測値 = 99999 → None として扱う

NOWPHAS_WAVE_URL  = "https://nowphas.mlit.go.jp/mapxml/"
NOWPHAS_TIDE_URL  = "https://nowphas.mlit.go.jp/choui_mapxml/"

_nowphas_wave_cache = None
_nowphas_tide_cache = None

def _fetch_nowphas_xml(url):
    txt = fetch(url)
    if not txt: return {}
    result = {}
    try:
        # BOM除去
        if txt.startswith('\ufeff'): txt = txt[1:]
        root = ET.fromstring(txt.encode('utf-8'))
        for mapdata in root.findall('mapdata'):
            code = mapdata.get('code')
            result[code] = mapdata
    except Exception as e:
        print(f"  NOWPHAS XML parse error: {e}")
    return result

def get_nowphas_wave(code):
    """波高(m)・波周期(s)を返す。欠測・観測なしは None。"""
    global _nowphas_wave_cache
    if _nowphas_wave_cache is None:
        _nowphas_wave_cache = _fetch_nowphas_xml(NOWPHAS_WAVE_URL)
        time.sleep(0.8)
    if code is None: return None, None
    mapdata = _nowphas_wave_cache.get(str(code))
    if mapdata is None: return None, None
    def _val(tag):
        el = mapdata.find(tag)
        if el is None or not el.text: return None
        try:
            v = float(el.text)
            return None if v == 99999 else v
        except: return None
    return _val('yugiha'), _val('shiyuki')

def get_nowphas_tide(code):
    """潮位(cm)を返す。欠測・観測なしは None。"""
    global _nowphas_tide_cache
    if _nowphas_tide_cache is None:
        _nowphas_tide_cache = _fetch_nowphas_xml(NOWPHAS_TIDE_URL)
        time.sleep(0.8)
    if code is None: return None
    mapdata = _nowphas_tide_cache.get(str(code))
    if mapdata is None: return None
    el = mapdata.find('choui')
    if el is None or not el.text: return None
    try:
        v = float(el.text)
        return None if v == 99999 else int(v)
    except: return None


# ── CSV保存 ─────────────────────────────────────────────────────────────

def save_csv(area_code, row):
    os.makedirs("weather_data", exist_ok=True)
    path = os.path.join("weather_data", f"{area_code}.csv")
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            w.writeheader()
        w.writerow(row)


# ── メイン ───────────────────────────────────────────────────────────────

def main():
    global _nowphas_wave_cache, _nowphas_tide_cache
    _nowphas_wave_cache = None
    _nowphas_tide_cache = None

    now = datetime.now()
    print(f"=== weather_crawl.py 開始 {now.strftime('%Y/%m/%d %H:%M')} ===")

    # アメダス最新データ取得
    amedas_time = get_latest_amedas_time()
    amedas_data = {}
    if amedas_time:
        print(f"アメダス時刻: {amedas_time}")
        amedas_data = fetch_amedas_map(amedas_time)
        print(f"アメダス観測点数: {len(amedas_data)}")
        time.sleep(0.8)
    else:
        print("アメダス時刻取得失敗")

    # NOWPHAS データ一括取得（全海域共通）
    print("NOWPHAS 波浪データ取得中...")
    _nowphas_wave_cache = _fetch_nowphas_xml(NOWPHAS_WAVE_URL)
    print(f"  観測点数: {len(_nowphas_wave_cache)}")
    time.sleep(0.8)
    print("NOWPHAS 潮位データ取得中...")
    _nowphas_tide_cache = _fetch_nowphas_xml(NOWPHAS_TIDE_URL)
    print(f"  観測点数: {len(_nowphas_tide_cache)}")
    time.sleep(0.8)

    dt_str = now.strftime("%Y/%m/%d %H:%M")

    for area_code, area in SEA_AREAS.items():
        print(f"\n[{area['name']}]")

        amed = parse_amedas(amedas_data, area["amedas_ids"])
        print(f"  風速:{amed['wind_speed']} m/s  風向:{amed['wind_dir']}°  気温:{amed['temp']}℃")

        wave_h, wave_p = get_nowphas_wave(area["wave_code"])
        print(f"  波高:{wave_h} m  波周期:{wave_p} s  (code={area['wave_code']})")

        tide = get_nowphas_tide(area["tide_code"])
        print(f"  潮位:{tide} cm  (code={area['tide_code']})")

        row = {
            "datetime":    dt_str,
            "wave_height": wave_h   if wave_h   is not None else "",
            "wave_period": wave_p   if wave_p   is not None else "",
            "wind_speed":  amed["wind_speed"] if amed["wind_speed"] is not None else "",
            "wind_dir":    amed["wind_dir"]   if amed["wind_dir"]   is not None else "",
            "temp":        amed["temp"]        if amed["temp"]        is not None else "",
            "tide_level":  tide     if tide     is not None else "",
            "area":        area["name"],
        }
        save_csv(area_code, row)
        print(f"  → weather_data/{area_code}.csv 保存済")

    print(f"\n=== 完了 {datetime.now().strftime('%H:%M:%S')} ===")


if __name__ == "__main__":
    main()
