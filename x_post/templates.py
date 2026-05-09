# templates.py — 60 文型定数（H1〜H20, S1〜S20, F1〜F20）
# 補遺3 遵守: avg/平均/ave を一切含まない
# 釣りビジョン・fishing-v.jp への言及なし

# --- ハイライトセクション (H) ---
H_TEMPLATES = [
    {
        "id": "H1",
        "priority": 1,
        "conds": [
            ("top_kg_max", ">=", 10.0),
            ("season_ratio_top_kg", ">=", 2.0),
        ],
        "text": (
            "本日最大の話題は<b>{top_kg_fish}の{top_kg_max:.2f}kg</b>。{date_label}時点で"
            "{period_label}以降、関東圏での{kg_threshold}kg超え大物記録です。"
            "{top_kg_port}は遠征エリアですが、<b>{top_kg_ship}</b>はこの時期の運航で"
            "近海では狙えないサイズの回遊魚を求める常連層に人気の船宿です。"
            "シーズン（過去5年同旬比）の {season_ratio_top_kg:.1f}倍という記録的な大物実績で、"
            "この時期ならではの好海況が背景にあると見られます。"
        ),
    },
    {
        "id": "H2",
        "priority": 2,
        "conds": [
            ("top_kg_max", ">=", 5.0),
            ("top_kg_max", "<", 10.0),
        ],
        "text": (
            "注目は<b>{top_kg_fish} {top_kg_min:.1f}〜{top_kg_max:.2f}kg</b>。"
            "<b>{top_kg_ship}</b>（{top_kg_port}）が記録した{top_kg_max:.1f}kg級は良型の実績。"
            "{top_kg_port}を主戦場とするこの船宿は{ship_specialty}が看板で、"
            "今期は好海況が観測されています。今後1〜2週間は同サイズの再現性が高いと推察されます。"
        ),
    },
    {
        "id": "H3",
        "priority": 3,
        "conds": [
            ("wow_pct_top_cnt", ">=", 1.5),
            ("top_cnt_max", ">=", 50),
        ],
        "text": (
            "数の好調枠では<b>{top_cnt_fish} {top_cnt_min}〜{top_cnt_max}匹</b>が目を引きます。"
            "{top_cnt_port}・<b>{top_cnt_ship}</b>での記録で、"
            "<span class=\"num\">先週比 {wow_pct_top_cnt_str}</span>の急増。"
            "{season_label}は通常よりも活発な群れ接岸のシグナルが出ています。"
            "明日以降の同港便も期待できます。"
        ),
    },
    {
        "id": "H4",
        "priority": 4,
        "conds": [
            ("season_ratio_top_cm", ">=", 1.5),
        ],
        "text": (
            "サイズ面では<b>{top_cm_fish} {top_cm_min}〜{top_cm_max}cm</b>が目立ちます。"
            "{top_cm_max}cmの良型は過去5年同旬比 {season_ratio_top_cm:.1f}倍のサイズ感。"
            "{top_cm_port}方面でこの傾向が続いており、型狙い派には好機の時期です。"
        ),
    },
    {
        "id": "H5",
        "priority": 5,
        "conds": [
            ("n_fish_species", ">=", 10),
            ("n_records", ">=", 30),
        ],
        "text": (
            "本日は<b>{n_fish_species}魚種</b>と幅広い顔ぶれが揃いました。"
            "シーズン主力の{shoot_main_list}に加え、{rare_appearances}など"
            "普段名前が出にくい魚種も顔を出しており、{season_label}特有の"
            "<b>釣り物ローテーション期</b>に入った感があります。"
            "船宿選びの幅が広がるタイミングです。"
        ),
    },
    {
        "id": "H6",
        "priority": 6,
        "conds": [
            ("rare_fish_present", "==", True),
        ],
        "text": (
            "本日特筆すべきは<b>{rare_fish_name}</b>の出現。"
            "{rare_port}・<b>{rare_ship}</b>で{rare_count}匹の記録があり、"
            "<b>{rare_fish_name}</b>の本格的な接岸シーズン入りの兆しと捉えてよさそうです。"
        ),
    },
    {
        "id": "H7",
        "priority": 7,
        "conds": [
            ("month", "in", [4, 5, 6]),
            ("seasonal_first_len", ">=", 2),
        ],
        "text": (
            "{season_label}の風物詩、<b>{seasonal_first_list}</b>の釣果報告が今週から本格化しています。"
            "本日は{seasonal_focus_fish}が{seasonal_max}匹台に乗り、"
            "海水温の上昇カーブを見るとシーズンのピーク帯に向かう見込みで、"
            "釣行計画の立てやすい時期です。"
        ),
    },
    {
        "id": "H8",
        "priority": 8,
        "conds": [
            ("month", "in", [4, 5]),
            ("season_ratio_kanpachi", ">=", 1.3),
            ("sst_anom", ">=", 1.0),
        ],
        "text": (
            "SST が例年比 +{sst_anom:.1f}℃と高めで、関東では"
            "<b>大型青物期の早期接岸</b>が現実味を帯びてきました。"
            "本日も{large_pelagic_count}件の青物実績があり、{large_pelagic_areas}方面での"
            "目撃情報が増加。来週末以降の便は予約が埋まりやすいため、計画は早めに固めることをお勧めします。"
        ),
    },
    {
        "id": "H9",
        "priority": 9,
        "conds": [
            ("inner_ratio", ">=", 0.7),
        ],
        "text": (
            "本日は<b>釣果の{inner_pct:.0%}が内海（東京湾・相模湾）</b>に集中しました。"
            "外海は海況の影響で出船を絞った船宿が多く、その分内海便には常連が集中。"
            "アジ・シロギス・カワハギの定番魚種で良型・数ともに安定した記録が並びました。"
        ),
    },
    {
        "id": "H10",
        "priority": 10,
        "conds": [
            ("outer_ratio", ">=", 0.5),
            ("total_cancel_rate", "<", 0.3),
        ],
        "text": (
            "内海は{inner_state}でしたが、外海は予報を覆して好海況。"
            "出船した船宿では{outer_top_fish}を中心に好実績が続出しました。"
            "<b>{outer_top_ship}</b>の{outer_top_record}は、外海ならではの記録です。"
        ),
    },
    {
        "id": "H11",
        "priority": 11,
        "conds": [
            ("morning_share", ">=", 0.6),
        ],
        "text": (
            "釣果の{morning_pct:.0%}が朝マズメ〜午前中に集中。"
            "{morning_top_areas}での明け方の好機を捉えた船宿が好成績でした。"
            "本日のような潮回り（{tide_type}）では<b>朝が好機</b>と覚えておくと"
            "予約・出船時間選定の指針になります。"
        ),
    },
    {
        "id": "H12",
        "priority": 12,
        "conds": [
            ("tide_type", "==", "大潮"),
            ("n_records_ratio", ">=", 1.2),
        ],
        "text": (
            "本日は<b>{tide_type}（{moon_phase}）</b>の潮回りで、釣果件数は通常比高め。"
            "{tide_strong_fish_list}など潮の動きに敏感な魚種で特に好実績が出ています。"
            "次の{tide_type}回りも同パターンの再現を狙うなら早めの予約が安心です。"
        ),
    },
    {
        "id": "H13",
        "priority": 13,
        "conds": [
            ("is_weekend_eve", "==", True),
        ],
        "text": (
            "{weekday_jp}の今日は<b>週末釣行の判断材料</b>として注目される一日。"
            "{weekend_focus_areas}の各船宿で安定した数値が出ており、"
            "{weekend_focus_fish}を狙うなら週末が最適と見られます。"
        ),
    },
    {
        "id": "H14",
        "priority": 14,
        "conds": [
            ("weekday", "in", ["tuesday", "wednesday"]),
        ],
        "text": (
            "{weekday_jp}で、各船宿とも比較的空席のある状況。"
            "<b>常連が休む合間の穴場狙い</b>には絶好のタイミングです。"
            "{post_holiday_recommend_fish}は食いが活発化しており、"
            "本日も{n_records}件の釣果が出ています。"
        ),
    },
    {
        "id": "H15",
        "priority": 15,
        "conds": [
            ("rain_yesterday_mm", ">=", 20),
        ],
        "text": (
            "前日の{rain_yesterday_mm}mmの降雨で、本日は湾奥・港湾を中心に"
            "<b>濁り潮</b>が残った状態でのスタート。"
            "{turbid_resilient_fish}は濁りに強く安定釣果を記録。"
            "明日にかけて潮が澄む方向ですので、シロギス・アジ狙いは晴天続きのタイミングを。"
        ),
    },
    {
        "id": "H16",
        "priority": 16,
        "conds": [
            ("wave_inner", "<=", 0.5),
            ("weather_today", "in", ["晴れ", "快晴"]),
        ],
        "text": (
            "本日は内海・外海ともに<b>凪と晴天</b>に恵まれ、好コンディション。"
            "{clear_top_fish}はハリス号数を落とした繊細な仕掛けで好釣果を記録。"
            "フィネス系の釣りに自信のある方には絶好のタイミングです。"
        ),
    },
    {
        "id": "H17",
        "priority": 17,
        "conds": [
            ("max_wind", ">=", 12),
        ],
        "text": (
            "本日は<b>最大{max_wind:.0f}m/sの強風日</b>。"
            "外海便は{strong_wind_cancel}件の欠航となり、内海でも一部船宿が早上がり判断。"
            "それでも出船した便では{strong_wind_top_fish}で記録が出ています。"
        ),
    },
    {
        "id": "H18",
        "priority": 18,
        "conds": [
            ("kuroshio_state", "==", "north_active"),
        ],
        "text": (
            "黒潮蛇行は北上モードで、関東沿岸では<b>SST が例年比 +{sst_anom:.1f}℃</b>高め。"
            "回遊魚（カンパチ・ハマチ・サワラ）の<b>早期接岸</b>が観測されており、"
            "本日も{kuroshio_pelagic_records}件の青物実績が記録されました。"
        ),
    },
    {
        "id": "H19",
        "priority": 19,
        "conds": [
            ("n_records", ">=", 20),
            ("no_special_event", "==", True),
        ],
        "text": (
            "{date_label}は{season_label}としては<b>平年並みの安定したコンディション</b>。"
            "{stable_top_fish}を中心に{n_records}件の釣果が記録され、"
            "各船宿で確実な手応えを感じる釣行が続いています。"
        ),
    },
    {
        "id": "H20",
        "priority": 20,
        "conds": [],  # フォールバック
        "text": (
            "{date_label}は釣果報告が{n_records}件と控えめでした。"
            "それでも出船した船宿からは{minimal_top_fish}の手堅い釣果が報告されており、"
            "明日以降の好転に期待が持てます。"
        ),
    },
]

# --- 海況セクション (S) ---
S_TEMPLATES = [
    {
        "id": "S1",
        "priority": 1,
        "conds": [
            ("wave_inner", "<=", 1.2),
            ("swell_outer", "<=", 1.5),
            ("total_cancel_rate", "<", 0.1),
        ],
        "text": (
            "本日は<b>内海・外海ともに穏やかな海況</b>に恵まれ、"
            "関東圏{n_ships}船宿の出船率は高い好スコア。"
            "<b>内海（東京湾・相模湾）</b>は風{wind_inner_str}、波{wave_inner:.1f}mと凪に近い状態で、"
            "{inner_top_fish}の数釣りに集中できる好条件でした。"
            "<b>外海（外房・銭洲）</b>もうねり{swell_outer:.1f}mと許容範囲内。"
            "{outer_top_fish}の遠征便も予定通り運航しました。"
        ),
    },
    {
        "id": "S2",
        "priority": 2,
        "conds": [
            ("wave_inner", "<=", 1.2),
            ("cancel_rate_outer", ">=", 0.15),
        ],
        "text": (
            "本日の海況は<b>内海と外海で対照的な一日</b>。"
            "<b>内海</b>は風{wind_inner_str}と穏やかで、久比里・松輪・金沢八景の各沖は"
            "朝マズメから夕方まで凪が続きました。"
            "一方<b>外海</b>は中風で、銭洲・神津島方面は<b>{n_cancellations}船が出船中止</b>判断。"
            "来週末は外海狙いの予約は<b>前日午後に船宿への確認</b>が必須です。"
        ),
    },
    {
        "id": "S3",
        "priority": 3,
        "conds": [
            ("cancel_rate_inner", ">=", 0.15),
            ("cancel_rate_outer", "<", 0.1),
        ],
        "text": (
            "本日は珍しく<b>内海荒れ・外海凪</b>という逆転パターン。"
            "東京湾内は強風となり出船を見合わせた船宿が複数。"
            "一方外海は黒潮の流れが安定し、遠征便を選んだ常連は{outer_top_fish}で好実績を記録しました。"
        ),
    },
    {
        "id": "S4",
        "priority": 4,
        "conds": [
            ("total_cancel_rate", ">=", 0.4),
        ],
        "text": (
            "本日は<b>関東一帯が荒天に見舞われた厳しい一日</b>。"
            "{n_cancellations}船宿が欠航となり、出船率は低い水準。"
            "本日の少ない出船便でも{stormy_top_fish}が記録されており、"
            "海況回復後の好機到来の可能性があります。"
        ),
    },
    {
        "id": "S5",
        "priority": 5,
        "conds": [
            ("max_wind", ">=", 12),
        ],
        "text": (
            "本日は<b>最大{max_wind:.0f}m/sの強風日</b>。"
            "{strong_wind_affected_areas}方面で出船判断が割れました。"
            "それでも出船した船では{strong_wind_top_fish}で記録が出ており、"
            "風裏を狙った船宿が結果を出した形です。"
        ),
    },
    {
        "id": "S6",
        "priority": 6,
        "conds": [
            ("wind_inner_max", "<=", 5),
            ("wind_outer_max", "<=", 6),
        ],
        "text": (
            "本日は<b>無風に近い凪の好海況</b>。"
            "海面は静穏な状態で、{calm_main_fish}の数釣り・{calm_target_fish}の繊細な仕掛けでの釣りに"
            "絶好のコンディションでした。明日も同様の好海況が続く予報です。"
        ),
    },
    {
        "id": "S7",
        "priority": 7,
        "conds": [
            ("swell_outer", ">=", 2.0),
        ],
        "text": (
            "外海はうねり{swell_outer:.1f}mと高く、{swell_affected_areas}方面では"
            "釣り辛さが顕著な一日でした。内海は別次元で穏やかで、{inner_top_fish}を狙う便には好機。"
            "明日以降にはうねりが収まる予報ですので、外海狙いの方は明日以降に期待を。"
        ),
    },
    {
        "id": "S8",
        "priority": 8,
        "conds": [
            ("kuroshio_state", "==", "north_active"),
        ],
        "text": (
            "広域の海況としては、<b>黒潮蛇行が北上モード</b>に入り、"
            "SST も例年比<span class=\"num\">+{sst_anom:.1f}℃</span>高め。"
            "回遊魚（カンパチ・ハマチ・サワラ）の早期接岸が期待できる流れで、"
            "今後2〜3週間は同パターンが続く見込みです。"
        ),
    },
    {
        "id": "S9",
        "priority": 9,
        "conds": [
            ("kuroshio_state", "==", "south_active"),
        ],
        "text": (
            "広域では<b>黒潮蛇行が南下モード</b>に転じており、SST は{sst_anom:+.1f}℃で推移。"
            "底物・潮の影響を受けにくい魚種（カワハギ・カサゴ等）には影響が小さいため、"
            "魚種変更も選択肢に入る局面です。"
        ),
    },
    {
        "id": "S10",
        "priority": 10,
        "conds": [
            ("sst_anom", ">=", 1.5),
            ("month", "in", [3, 4, 5]),
        ],
        "text": (
            "関東沿岸の SST は<b>例年比 +{sst_anom:.1f}℃</b>と高めで推移。"
            "春の魚種のシーズン入りが平年より早い見立てとなっています。"
            "釣り物カレンダーは平年通りに固執せず、現状の海況を踏まえた前倒し計画が有効です。"
        ),
    },
    {
        "id": "S11",
        "priority": 11,
        "conds": [
            ("sst_anom", "<=", -1.0),
        ],
        "text": (
            "SST は例年比{sst_anom:+.1f}℃と低めで、春の本格化が遅れている状況。"
            "シロギス・アジ等の数釣り入りもやや後ろ倒し。"
            "気温の推移を見ながら釣り物の切り替えタイミングを慎重に判断したい時期です。"
        ),
    },
    {
        "id": "S12",
        "priority": 12,
        "conds": [
            ("tide_type", "==", "大潮"),
        ],
        "text": (
            "本日は<b>大潮（{moon_phase}）</b>で潮の動きが活発。"
            "{tide_active_fish_list}など潮に敏感な魚種で好実績が出ました。"
            "次の大潮も同パターンの再現を狙うなら早めの予約が安心です。"
        ),
    },
    {
        "id": "S13",
        "priority": 13,
        "conds": [
            ("tide_type", "in", ["小潮", "長潮", "若潮"]),
        ],
        "text": (
            "{tide_type}の本日は潮の動きがゆるやか。"
            "{small_tide_advantageous_fish}など潮の弱い時間帯に活性が上がる魚種で"
            "堅実な釣果が出ました。ゆっくりと探る釣りに向いた一日です。"
        ),
    },
    {
        "id": "S14",
        "priority": 14,
        "conds": [
            ("tide_type", "==", "中潮"),
        ],
        "text": (
            "中潮の本日は標準的な潮回り。"
            "極端なパターンが出にくいぶん{neutral_top_fish}を中心とした安定した釣果が並びました。"
        ),
    },
    {
        "id": "S15",
        "priority": 15,
        "conds": [
            ("morning_share", ">=", 0.5),
            ("high_tide_hour", "<", 10),
        ],
        "text": (
            "本日は<b>朝の上げ潮</b>が最大の好機。"
            "午前中に釣果が集中し、{morning_top_areas}方面では好記録も。"
            "朝マズメに合わせて出船する早朝便を選ぶと、大物・数のチャンスを最大限に活かせます。"
        ),
    },
    {
        "id": "S16",
        "priority": 16,
        "conds": [
            ("morning_share", ">=", 0.5),
            ("low_tide_hour", "<", 10),
        ],
        "text": (
            "本日は朝の下げ潮が好機。干潮に向かう時間帯に活性が上がり、"
            "{down_tide_target_fish}の好実績が出ました。底物狙いの方は要チェックです。"
        ),
    },
    {
        "id": "S17",
        "priority": 17,
        "conds": [
            ("rain_yesterday_mm", ">=", 20),
        ],
        "text": (
            "前日の{rain_yesterday_mm}mmの降雨で、本日は湾奥を中心に<b>濁り潮</b>が残った海況からのスタートでした。"
            "{turbid_resistant_fish}は濁りに強く安定釣果を記録。"
            "明日にかけて澄む方向ですので、シロギス・アジ狙いは晴天続きのタイミングを。"
        ),
    },
    {
        "id": "S18",
        "priority": 18,
        "conds": [
            ("wave_inner", "<=", 0.5),
            ("no_rain_3d", "==", True),
        ],
        "text": (
            "海中の透明度が高い好コンディション。{clear_view_top_fish}は視覚的な警戒心が強くなる傾向ですが、"
            "仕掛けの工夫が功を奏した好記録もありました。透明度の高い日は仕掛けの工夫が結果を分けます。"
        ),
    },
    {
        "id": "S19",
        "priority": 19,
        "conds": [
            ("wind_direction_changes", ">=", 3),
        ],
        "text": (
            "本日は風向が{wind_direction_changes}回変化する不安定な海況でした。"
            "船位取りの判断が結果を分けた一日。明日は海況が安定する予報です。"
        ),
    },
    {
        "id": "S20",
        "priority": 20,
        "conds": [],  # フォールバック（全条件不一致時に必ず選択）
        "text": (
            "{consecutive_calm_days}日連続の安定凪で、各船宿とも余裕を持った運航。"
            "{stable_calm_top_fish}は数日間の好海況で食いが上向き、本日も好実績が出ています。"
            "未経験者・家族連れの釣行にも適した時期です。"
        ),
    },
]

# --- 魚種別釣果報告セクション (F) ---
F_TEMPLATES = [
    {
        "id": "F1",
        "priority": 1,
        "conds": [
            ("mainstream_count", ">=", 3),
            ("opportunistic_count", ">=", 2),
        ],
        "text": (
            "全体感としては、今日は<b>「{mainstream_fish_list}」のシーズン安定組</b>と"
            "<b>「{opportunistic_fish_list}」の単発大物・好機組</b>に分かれる構成でした。"
        ),
    },
    {
        "id": "F2",
        "priority": 2,
        "conds": [
            ("has_aji", "==", True),
            ("aji_cnt_max", ">=", 100),
        ],
        "text": (
            "<b>アジ</b>は{aji_top_areas}エリアで<span class=\"num\">3桁釣果</span>が頻発し、"
            "群れの動きが継続中。<b>{aji_top_ship}の{aji_top_count}匹</b>は今週の全便でも上位の記録です。"
        ),
    },
    {
        "id": "F3",
        "priority": 3,
        "conds": [
            ("has_madai", "==", True),
            ("madai_kg_max", ">=", 2.5),
        ],
        "text": (
            "<b>マダイ</b>は{madai_top_areas}で{madai_cnt_min}〜{madai_cnt_max}匹レンジ。"
            "{madai_kg_max:.1f}kgの大型は<span class=\"highlight\">サイズが明確に上向き</span>な印象。"
        ),
    },
    {
        "id": "F4",
        "priority": 4,
        "conds": [
            ("has_kisu", "==", True),
            ("kisu_cnt_max", ">=", 100),
        ],
        "text": (
            "<b>シロギス</b>は{kisu_top_areas}の浅場で<span class=\"num\">大爆発</span>。"
            "湾奥への河川流入と水温上昇でベイト溜まりが形成された影響と推察されます。"
            "<b>{kisu_top_ship}の{kisu_cnt_max}匹</b>は今期トップ級の記録です。"
        ),
    },
    {
        "id": "F5",
        "priority": 5,
        "conds": [
            ("has_kawahagi", "==", True),
            ("kawahagi_cnt_max", ">=", 8),
        ],
        "text": (
            "<b>カワハギ</b>は{kawahagi_top_areas}で"
            "{kawahagi_cnt_min}〜{kawahagi_cnt_max}匹・{kawahagi_cm_min}〜{kawahagi_cm_max}cm。"
            "底物の繊細な釣りが好きな常連で常に予約が埋まる人気ジャンルで、"
            "本日も複数船宿で安定した釣果が記録されました。"
        ),
    },
    {
        "id": "F6",
        "priority": 6,
        "conds": [
            ("has_tachiuo", "==", True),
            ("tachiuo_cm_max", ">=", 90),
        ],
        "text": (
            "<b>タチウオ</b>は{tachiuo_top_areas}方面で{tachiuo_cnt_min}〜{tachiuo_cnt_max}匹、"
            "サイズは<b>{tachiuo_cm_min}〜{tachiuo_cm_max}cm</b>と大型揃い。"
            "冬の名残のドラゴン級が春の早朝便で出ているパターンです。"
        ),
    },
    {
        "id": "F7",
        "priority": 7,
        "conds": [
            ("has_kanpachi", "==", True),
            ("kanpachi_kg_max", ">=", 5.0),
        ],
        "text": (
            "<b>カンパチ</b>は{kanpachi_top_areas}で1〜{kanpachi_cnt_max}匹レンジ・"
            "<b>{kanpachi_kg_min:.1f}〜{kanpachi_kg_max:.2f}kg</b>。"
            "{kanpachi_top_ship}が大物記録を出した遠征便で、近海では狙えないサイズ帯です。"
        ),
    },
    {
        "id": "F8",
        "priority": 8,
        "conds": [
            ("has_maruika", "==", True),
            ("maruika_cnt_max", ">=", 30),
        ],
        "text": (
            "<b>マルイカ</b>は{maruika_top_areas}で{maruika_cnt_min}〜{maruika_cnt_max}匹。"
            "{maruika_top_ship}が継続的な好実績で、剣崎沖の良型群が継続中です。"
        ),
    },
    {
        "id": "F9",
        "priority": 9,
        "conds": [
            ("has_yariika", "==", True),
            ("yariika_cnt_max", ">=", 15),
        ],
        "text": (
            "<b>ヤリイカ</b>は{yariika_top_areas}方面で{yariika_cnt_min}〜{yariika_cnt_max}匹。"
            "{yariika_top_ship}など継続的に良型が記録されています。"
        ),
    },
    {
        "id": "F10",
        "priority": 10,
        "conds": [
            ("has_fugu", "==", True),
            ("fugu_cnt_max", "<", 15),
        ],
        "text": (
            "<b>フグ</b>は{fugu_top_areas}方面で{fugu_cnt_min}〜{fugu_cnt_max}匹。"
            "少数ながらコンスタントに記録があり、シーズン後半の手堅い狙い目です。"
        ),
    },
    {
        "id": "F11",
        "priority": 11,
        "conds": [
            ("has_surumeika", "==", True),
            ("surumeika_cnt_max", ">=", 5),
        ],
        "text": (
            "<b>スルメイカ</b>は{surumeika_top_areas}方面で{surumeika_cnt_min}〜{surumeika_cnt_max}匹。"
            "ローテーション釣行に組み込みやすい魚種です。"
        ),
    },
    {
        "id": "F12",
        "priority": 12,
        "conds": [
            ("n_fish_species", ">=", 10),
        ],
        "text": (
            "全{n_fish_species}魚種が顔を揃えた幅広い釣果構成。"
            "{multi_fish_main_three}が三本柱として件数を稼ぎ、"
            "{multi_fish_supporting_list}も少数ながら確実に記録されています。"
            "同日に複数魚種を狙えるため、釣行の自由度が高いタイミングと言えます。"
        ),
    },
    {
        "id": "F13",
        "priority": 13,
        "conds": [
            ("n_fish_species", "<=", 3),
        ],
        "text": (
            "本日は{n_fish_species}魚種のみという特殊な構成。"
            "{single_fish_dominant}が記録の大部分を占め、"
            "シーズン的に他魚種が動きにくい時期に入ったのか、海況に偏りがあった可能性があります。"
        ),
    },
    {
        "id": "F14",
        "priority": 14,
        "conds": [
            ("pelagic_share", ">=", 0.5),
        ],
        "text": (
            "本日は<b>青物中心</b>の構成で、{pelagic_top_fish_list}の合計{pelagic_records}件が記録されました。"
            "{pelagic_main_areas}沖でイワシ等のベイト群が発生していると見られ、"
            "ジギング・キャスティング系の予約が埋まりつつあります。"
        ),
    },
    {
        "id": "F15",
        "priority": 15,
        "conds": [
            ("seasonal_stable_share", ">=", 0.8),
        ],
        "text": (
            "本日は<b>{season_label}の主役 {seasonal_stable_list}が中心</b>の安定した構成。"
            "各船宿で確実な手応えを感じる釣行が続いています。"
        ),
    },
    {
        "id": "F16",
        "priority": 16,
        "conds": [
            ("rare_species_count", ">=", 1),
        ],
        "text": (
            "本日は<b>レア種 {rare_species_list}</b>の出現に注目。"
            "この時期の接岸が観測されており、今後の釣果報告にも期待が持てます。"
        ),
    },
    {
        "id": "F17",
        "priority": 17,
        "conds": [
            ("season_ending_share", ">=", 0.5),
        ],
        "text": (
            "本日の構成は{season_ending_main_fish}など<b>旬の終盤を迎える魚種</b>が中心。"
            "サイズ・数ともにやや落ちてきており、魚種ローテーションを検討するタイミングです。"
        ),
    },
    {
        "id": "F18",
        "priority": 18,
        "conds": [
            ("seasonal_first_len", ">=", 2),
        ],
        "text": (
            "{season_label}の新顔として、<b>{seasonal_first_list}</b>の釣果報告が今週から本格化。"
            "夏に向けたシーズンの本番入りが近いことを示しています。"
        ),
    },
    {
        "id": "F19",
        "priority": 19,
        "conds": [
            ("bait_active", "==", True),
        ],
        "text": (
            "{bait_active_areas}方面では<b>ベイト群の活発な動き</b>が観測されており、"
            "{bait_predator_fish}の食いが連動して上向き。本日も好実績が出ました。"
        ),
    },
    {
        "id": "F20",
        "priority": 20,
        "conds": [],  # フォールバック
        "text": (
            "本日は件数こそ控えめでしたが、出船した船宿からは"
            "{minimal_fish_top}の手堅い釣果が記録されました。明日以降の好転に期待です。"
        ),
    },
]

# 補遺3 検証: この定数ファイル内に「平均」「avg」「ave」が含まれないことを確認
# 注意: wave / cave / have 等の単語内 "ave" は誤検出するため \bave\b で語境界チェック
import re as _re
_ALL_TEXT = " ".join(t["text"] for t in H_TEMPLATES + S_TEMPLATES + F_TEMPLATES)
assert "平均" not in _ALL_TEXT, "補遺3 違反: 平均 が含まれています"
assert not _re.search(r"\bavg\b", _ALL_TEXT, _re.IGNORECASE), "補遺3 違反: avg が含まれています"
assert not _re.search(r"\bave\b", _ALL_TEXT, _re.IGNORECASE), "補遺3 違反: ave が含まれています"
assert "釣りビジョン" not in _ALL_TEXT, "データソース言及禁止: 釣りビジョン が含まれています"
assert "fishing-v" not in _ALL_TEXT.lower(), "データソース言及禁止: fishing-v が含まれています"
