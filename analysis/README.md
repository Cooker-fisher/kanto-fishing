# analysis/ — 分析バージョン管理

> **現行バージョン**: V2（config.json の `active_version` で管理）

---

## バージョン一覧

| バージョン | 期間 | 状態 | 主な変更 |
|-----------|------|------|---------|
| V1 | 〜2026年3月 | アーカイブ（参照専用） | 旧フォーマット・CSV気象データ |
| **V2** | 2026年4月〜 | **現行** | weather_cache.sqlite 導入・51魚種対応 |

---

## フォルダ構成

```
analysis/
├── README.md             ← このファイル
├── config.json           ← ※プロジェクトルートに配置（全員が参照する唯一の真実）
├── analysis_config.py    ← 後工程（crawler.py 等）が results/ を参照するユーティリティ
├── run.py                ← crawl.yml のランチャー（バージョン自動解決）
├── V1/
│   ├── README.md         ← V1 の分析条件・前後工程との契約
│   ├── methods/          ← 旧スクリプト群（参照専用）
│   └── results/          ← 旧分析結果（参照専用）
└── V2/
    ├── README.md         ← V2 の分析条件・前後工程との契約
    ├── methods/          ← 現行スクリプト群（16本）
    │   └── _paths.py     ← パス自動解決（CLAUDE.md を目印）
    └── results/          ← 分析結果出力先
```

---

## バージョン切替ルール

1. プロジェクトルートの `config.json` の `active_version` を変更する
2. `analysis/V{n+1}/methods/` フォルダを作成
3. `_paths.py` を前バージョンからコピー（中身変更不要）
4. 新しいスクリプトを作成（`from _paths import ...` の1行を追加するだけ）
5. `analysis/V{n+1}/README.md` に変更点・前後工程との契約を記述

---

## 後工程（crawler.py 等）からの参照方法

```python
# analysis/analysis_config.py を使う
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from analysis.analysis_config import get_results_dir, get_db_path

results_dir = get_results_dir()        # → analysis/V2/results/
db_path     = get_db_path()            # → analysis/V2/results/analysis.sqlite
```

バージョン切替は `config.json` の1行変更だけ。crawler.py 自体の修正は不要。
