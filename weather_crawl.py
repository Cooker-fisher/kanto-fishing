#!/usr/bin/env python3
"""
気象データ収集スクリプト weather_crawl.py
- 気象庁アメダスから風速・風向・気温を取得
- Open-Meteo Marine APIから波高・波周期・うねり・海面水温を取得
  URL: https://marine-api.open-meteo.com/v1/marine
- NOWPHAS（港湾の沿岸波浪情報）から潮位のみ取得（実測値）
  URL: https://nowphas.mlit.go.jp/choui_mapxml/
- tide736.net APIから満干潮時刻・大潮小潮・月齢を取得
  URL: https://tide736.net/api/get_tide.php?pc={pc}&hc={hc}&yr=...
- weather_data/{海域コード}.csv に1時間ごとに追記

[海域別の座標（Open-Meteo Marine）]
  東京湾:  lat=35.3, lon=139.7
  相模湾:  lat=35.0, lon=139.4
  外房:    lat=35.4, lon=140.6
  茨城沖:  lat=36.2, lon=140.7

[NOWPHAS潮位観測点コード（関東エリア）]
  217 = 第二海堡（東京湾）
  221 = 京浜港横浜（相模湾代替）
  222 = 鹿島港（外房・茨城）

[tide736.net 港コード（関東エリア）]
  pc=13, hc=0001 = 築地（東京湾）
  pc=14, hc=0015 = 諸磯（相模湾）
  pc=12, hc=0005 = 上総勝浦（外房）
  pc=08, hc=0005 = 大洗（茨城）

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
        "name":       "東京湾",
        "lat":        35.3,
        "lon":        139.7,
        "amedas_ids": ["46106", "45401"],   # 横浜・館山
        "tide_code":  217,                   # 第二海堡（NOWPHAS潮位）
        "tide_pc":    13,                    # 都道府県コード: 東京
        "tide_hc":    "0001",               # 港コード: 築地
    },
    "sagami_bay": {
        "name":       "相模湾",
        "lat":        35.0,
        "lon":        139.4,
        "amedas_ids": ["46211", "46106"],   # 三浦・横浜
        "tide_code":  221,                   # 京浜港横浜（NOWPHAS潮位）
        "tide_pc":    14,                    # 都道府県コード: 神奈川
        "tide_hc":    "0015",               # 港コード: 諸磯（三浦半島西岸）
    },
    "outer_boso": {
        "name":       "外房",
        "lat":        35.4,
        "lon":        140.6,
        "amedas_ids": ["45371", "45148"],   # 勝浦・銚子
        "tide_code":  222,                   # 鹿島港（NOWPHAS潮位）
        "tide_pc":    12,                    # 都道府県コード: 千葉
        "tide_hc":    "0005",               # 港コード: 上総勝浦
    },
    "ibaraki": {
        "name":       "茨城沖",
        "lat":        36.2,
        "lon":        140.7,
        "amedas_ids": ["40046", "45148"],   # 大洗・銚子
        "tide_code":  222,                   # 鹿島港（NOWPHAS潮位）
        "tide_pc":    8,                     # 都道府県コード: 茨城
        "tide_hc":    "0005",               # 港コード: 大洗
    },
}

CSV_HEADER = ["datetime", "wave_height", "wave_period", "swell_height",
              "wind_speed", "wind_dir", "temp", "sea_surface_temp",
              "pressure",
              "tide_level",
              "flood1", "flood1_cm", "flood2", "flood2_cm",
              "ebb1", "ebb1_cm", "ebb2", "ebb2_cm",
              "tide_range", "tide_type", "moon_age",
              "area"]

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
    wind_speeds, wind_dirs, temps, pressures = [], [], [], []
    for sid in station_ids:
        d = amedas_data.get(sid)
        if not d: continue
        ws = d.get("wind")
        wd = d.get("windDirection")
        tp = d.get("temp")
        pr = d.get("normalPressure") or d.get("pressure")
        if ws and isinstance(ws, list) and ws[0] is not None:
            wind_speeds.append(float(ws[0]))
        if wd and isinstance(wd, list) and wd[0] is not None:
            wind_dirs.append(_WIND_DIR_DEG.get(int(wd[0]), 0))
        if tp and isinstance(tp, list) and tp[0] is not None:
            temps.append(float(tp[0]))
        if pr and isinstance(pr, list) and pr[0] is not None:
            pressures.append(float(pr[0]))
    return {
        "wind_speed": round(sum(wind_speeds) / len(wind_speeds), 1) if wind_speeds else None,
        "wind_dir":   round(sum(wind_dirs)   / len(wind_dirs))      if wind_dirs   else None,
        "temp":       round(sum(temps)        / len(temps), 1)       if temps       else None,
        "pressure":   round(sum(pressures)    / len(pressures), 1)   if pressures   else None,
    }


# ── Open-Meteo Marine API（波浪・海面水温） ────────────────────────────

def get_marine_data(lat, lon):
    """波高(m)・波周期(s)・うねり波高(m)・海面水温(℃)を返す。"""
    url = (
        f"https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=wave_height,wave_period,swell_wave_height,sea_surface_temperature"
        f"&forecast_days=1&timezone=Asia/Tokyo"
    )
    txt = fetch(url)
    if not txt:
        return None, None, None, None
    try:
        data = json.loads(txt)
        times = data["hourly"]["time"]
        now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
        # 現在時刻のインデックスを探す（なければ直前の時刻を使う）
        idx = 0
        for i, t in enumerate(times):
            if t <= now_str:
                idx = i
        h  = data["hourly"]["wave_height"][idx]
        p  = data["hourly"]["wave_period"][idx]
        sw = data["hourly"]["swell_wave_height"][idx]
        st = data["hourly"]["sea_surface_temperature"][idx]
        def _r(v, n=2): return round(v, n) if v is not None else None
        return _r(h), _r(p), _r(sw), _r(st, 1)
    except Exception as e:
        print(f"  Open-Meteo Marine parse error: {e}")
        return None, None, None, None


# ── tide736.net（満干潮時刻・大潮小潮・月齢） ─────────────────────────

def get_tide_prediction(pc, hc):
    """
    満干潮時刻・潮汐区分（大潮/小潮）・月齢を返す。
    戻り値: dict with flood1/flood1_cm/flood2/flood2_cm/ebb1/ebb1_cm/ebb2/ebb2_cm/
                    tide_range/tide_type/moon_age
    """
    now = datetime.now()
    url = (
        f"https://tide736.net/api/get_tide.php"
        f"?pc={pc}&hc={hc}"
        f"&yr={now.year}&mn={now.month:02d}&dy={now.day:02d}&rg=day"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        date_key = now.strftime("%Y-%m-%d")
        day = data["tide"]["chart"][date_key]

        floods = day.get("flood", [])
        ebbs   = day.get("edd",   [])
        moon   = day.get("moon",  {})

        def _t(lst, i): return lst[i]["time"] if len(lst) > i else ""
        def _c(lst, i): return lst[i]["cm"]   if len(lst) > i else ""

        flood_cms = [f["cm"] for f in floods if f.get("cm") is not None]
        ebb_cms   = [e["cm"] for e in ebbs   if e.get("cm") is not None]
        tide_range = ""
        if flood_cms and ebb_cms:
            tide_range = round(max(flood_cms) - min(ebb_cms), 1)

        return {
            "flood1":    _t(floods, 0), "flood1_cm": _c(floods, 0),
            "flood2":    _t(floods, 1), "flood2_cm": _c(floods, 1),
            "ebb1":      _t(ebbs,   0), "ebb1_cm":   _c(ebbs,   0),
            "ebb2":      _t(ebbs,   1), "ebb2_cm":   _c(ebbs,   1),
            "tide_range": tide_range,
            "tide_type":  moon.get("title", ""),
            "moon_age":   moon.get("age",   ""),
        }
    except Exception as e:
        print(f"  tide736 parse error: {e}")
        return {}


# ── NOWPHAS潮位（実測値のみ） ──────────────────────────────────────────

NOWPHAS_TIDE_URL = "https://nowphas.mlit.go.jp/choui_mapxml/"
_nowphas_tide_cache = None

def _fetch_nowphas_tide_xml():
    txt = fetch(NOWPHAS_TIDE_URL)
    if not txt: return {}
    result = {}
    try:
        if txt.startswith('\ufeff'): txt = txt[1:]
        root = ET.fromstring(txt.encode('utf-8'))
        for mapdata in root.findall('mapdata'):
            code = mapdata.get('code')
            result[code] = mapdata
    except Exception as e:
        print(f"  NOWPHAS XML parse error: {e}")
    return result

def get_nowphas_tide(code):
    """潮位(cm)を返す。欠測・観測なしは None。"""
    global _nowphas_tide_cache
    if _nowphas_tide_cache is None:
        _nowphas_tide_cache = _fetch_nowphas_tide_xml()
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

HISTORY_HEADER = [
    "date", "wave_height", "wave_period", "swell_height",
    "wind_speed", "wind_dir", "temp", "sea_surface_temp",
    "flood1", "flood1_cm", "flood2", "flood2_cm",
    "ebb1", "ebb1_cm", "ebb2", "ebb2_cm",
    "tide_range", "tide_type", "moon_age",
    "area",
]

def save_csv(area_code, row):
    os.makedirs("weather_data", exist_ok=True)
    path = os.path.join("weather_data", f"{area_code}.csv")
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            w.writeheader()
        w.writerow(row)


def save_history_csv(area_code, date_str, row):
    """当日の日次サマリーを {area}_history.csv に追記。既存日付はスキップ。"""
    os.makedirs("weather_data", exist_ok=True)
    path = os.path.join("weather_data", f"{area_code}_history.csv")
    # 既存の日付を確認
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("date") == date_str:
                    return False  # 既存日付はスキップ
    write_header = not os.path.exists(path)
    history_row = {k: row.get(k, "") for k in HISTORY_HEADER}
    history_row["date"] = date_str
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_HEADER)
        if write_header:
            w.writeheader()
        w.writerow(history_row)
    return True


# ── メイン ───────────────────────────────────────────────────────────────

def main():
    global _nowphas_tide_cache
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
        time.sleep(0.5)
    else:
        print("アメダス時刻取得失敗")

    # NOWPHAS潮位データ一括取得
    print("NOWPHAS 潮位データ取得中...")
    _nowphas_tide_cache = _fetch_nowphas_tide_xml()
    print(f"  観測点数: {len(_nowphas_tide_cache)}")
    time.sleep(0.5)

    dt_str = now.strftime("%Y/%m/%d %H:%M")

    for area_code, area in SEA_AREAS.items():
        print(f"\n[{area['name']}]")

        # アメダス（風・気温）
        amed = parse_amedas(amedas_data, area["amedas_ids"])
        print(f"  風速:{amed['wind_speed']} m/s  風向:{amed['wind_dir']}°  気温:{amed['temp']}℃  気圧:{amed.get('pressure')} hPa")

        # Open-Meteo Marine（波浪・海面水温）
        wave_h, wave_p, swell_h, sst = get_marine_data(area["lat"], area["lon"])
        print(f"  波高:{wave_h} m  波周期:{wave_p} s  うねり:{swell_h} m  水温:{sst}℃")
        time.sleep(0.5)

        # NOWPHAS潮位（実測）
        tide = get_nowphas_tide(area["tide_code"])
        print(f"  潮位:{tide} cm  (code={area['tide_code']})")

        # tide736.net（満干潮・大潮小潮・月齢）
        tp = get_tide_prediction(area["tide_pc"], area["tide_hc"])
        print(f"  満潮1:{tp.get('flood1','')} ({tp.get('flood1_cm','')}cm)  "
              f"満潮2:{tp.get('flood2','')} ({tp.get('flood2_cm','')}cm)  "
              f"潮区分:{tp.get('tide_type','')}  月齢:{tp.get('moon_age','')}")
        time.sleep(0.5)

        row = {
            "datetime":         dt_str,
            "wave_height":      wave_h  if wave_h  is not None else "",
            "wave_period":      wave_p  if wave_p  is not None else "",
            "swell_height":     swell_h if swell_h is not None else "",
            "wind_speed":       amed["wind_speed"] if amed["wind_speed"] is not None else "",
            "wind_dir":         amed["wind_dir"]   if amed["wind_dir"]   is not None else "",
            "temp":             amed["temp"]        if amed["temp"]        is not None else "",
            "sea_surface_temp": sst     if sst     is not None else "",
            "pressure":         amed.get("pressure") if amed.get("pressure") is not None else "",
            "tide_level":       tide    if tide    is not None else "",
            "flood1":           tp.get("flood1",    ""),
            "flood1_cm":        tp.get("flood1_cm", ""),
            "flood2":           tp.get("flood2",    ""),
            "flood2_cm":        tp.get("flood2_cm", ""),
            "ebb1":             tp.get("ebb1",      ""),
            "ebb1_cm":          tp.get("ebb1_cm",   ""),
            "ebb2":             tp.get("ebb2",      ""),
            "ebb2_cm":          tp.get("ebb2_cm",   ""),
            "tide_range":       tp.get("tide_range",""),
            "tide_type":        tp.get("tide_type", ""),
            "moon_age":         tp.get("moon_age",  ""),
            "area":             area["name"],
        }
        save_csv(area_code, row)
        date_str = now.strftime("%Y-%m-%d")
        added = save_history_csv(area_code, date_str, row)
        print(f"  → weather_data/{area_code}.csv 保存済{'  / _history.csv 追記済' if added else '  / _history.csv スキップ（既存）'}")

    print(f"\n=== 完了 {datetime.now().strftime('%H:%M:%S')} ===")


if __name__ == "__main__":
    main()
