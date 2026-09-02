import requests
from bs4 import BeautifulSoup
import datetime
import pytz
import os

def get_taiwan_now():
    """取得台灣當前時間"""
    taiwan_tz = pytz.timezone('Asia/Taipei')
    return datetime.datetime.now(taiwan_tz)

def get_last_trading_day(taiwan_now):
    """取得上一個交易日（跳過週末）"""
    target = taiwan_now.date() - datetime.timedelta(days=1)
    for _ in range(10):
        if target.weekday() < 5:  # 0-4 = 週一至週五
            return target
        target -= datetime.timedelta(days=1)
    return taiwan_now.date() - datetime.timedelta(days=3)

def get_market_data():
    url = 'https://www.taifex.com.tw/cht/3/futDailyMarketReport'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.taifex.com.tw/cht/3/futDailyMarketReport'
    }

    taiwan_now = get_taiwan_now()
    taiwan_date_str = taiwan_now.strftime('%Y/%m/%d')
    print(f"[{taiwan_now.strftime('%Y-%m-%d %H:%M:%S')} 台灣時間] 開始爬取資料")

    # ── 1. 取得日盤資料 (一般交易時段) ──────────────────────────────
    # 日盤資料在 15:00 後才會完整，所以我們抓「上一個交易日」
    day_volume = 0
    day_date_found = None
    try:
        # workflow 在 07:00執行，此時昨日日盤已完整
        target_date = get_last_trading_day(taiwan_now)
        for _ in range(10):
            if target_date.weekday() >= 5:
                target_date -= datetime.timedelta(days=1)
                continue

            date_str = target_date.strftime('%Y/%m/%d')
            print(f"  查詢日盤日期: {date_str}")

            data = {
                'queryType': 2,
                'marketCode': 0,
                'commodity_id': 'TX',
                'queryDate': date_str
            }
            res_day = requests.post(url, data=data, headers=headers, timeout=15)
            res_day.encoding = 'utf-8'
            soup_day = BeautifulSoup(res_day.text, 'html.parser')
            table_day = soup_day.find('table', class_='table_f')

            if table_day:
                rows = table_day.find_all('tr')
                if len(rows) > 1:
                    header = [t.text.strip() for t in rows[0].find_all(['td', 'th'])]
                    # 嘗試多個可能的成交量欄位名稱
                    vol_candidates = ['*一般交易時段成交量', '*成交量', '一般交易時段成交量', '成交量']
                    vol_idx = None
                    for cand in vol_candidates:
                        if cand in header:
                            vol_idx = header.index(cand)
                            break

                    if vol_idx is not None:
                        tds = [td.text.strip() for td in rows[1].find_all(['td', 'th'])]
                        if len(tds) > vol_idx:
                            raw_vol = tds[vol_idx].replace(',', '').strip()
                            print(f"    找到日盤資料，原始值: '{tds[vol_idx]}' → 解析為: {raw_vol}")
                            if raw_vol.isdigit():
                                day_volume = int(raw_vol)
                                day_date_found = date_str
                                break
            target_date -= datetime.timedelta(days=1)

        if day_date_found:
            print(f"  日盤成交量: {day_volume} (日期: {day_date_found})")
        else:
            print(f"  未找到日盤資料")

    except Exception as e:
        print(f"  取得日盤資料失敗: {e}")

    # ── 2. 取得夜盤資料 (盤後交易時段) ──────────────────────────────
    # 夜盤是 15:00 ~ 隔日 05:00，
    # 若在 07:30 執行，今晨 05:00 夜盤已收盤
    # 查詢時傳入「今天」作為日期參數（因為這場夜盤是昨天15:00開盤，今天05:00收盤）
    night_volume = 0
    night_price_change = ""
    night_date_found = None
    try:
        # 夜盤查詢日期 = 今天（抓取已結束的昨夜夜盤）
        night_query_date = taiwan_now.date()
        night_date_str = night_query_date.strftime('%Y/%m/%d')
        print(f"  查詢夜盤日期: {night_date_str}")

        data_night = {
            'queryType': 2,
            'marketCode': 1,  # 夜盤
            'commodity_id': 'TX',
            'queryDate': night_date_str
        }
        res_night = requests.post(url, data=data_night, headers=headers, timeout=15)
        res_night.encoding = 'utf-8'
        soup_night = BeautifulSoup(res_night.text, 'html.parser')
        table_night = soup_night.find('table', class_='table_f')

        if table_night:
            rows = table_night.find_all('tr')
            for row in rows:
                tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                # TX 夜盤資料判斷：依據報價表結構
                # tds[0] 為商品名稱，tds[6] 為漲跌，tds[8] 為成交量
                if len(tds) > 8 and tds[0] == 'TX':
                    raw_vol = tds[8].replace(',', '').strip()
                    if raw_vol.isdigit():
                        night_price_change = tds[6]
                        night_volume = int(raw_vol)
                        night_date_found = night_date_str
                        print(f"  夜盤成交量: {night_volume}, 漲跌: {night_price_change}")
                        break

        if not night_date_found:
            print(f"  未找到夜盤 TX 資料")

    except Exception as e:
        print(f"  取得夜盤資料失敗: {e}")

    # ── 3. 取得三大法人外援夜盤多空淨額 ────────────────────────────
    foreign_net_position = "請手動輸入"
    foreign_date_found = None
    try:
        url_ah = 'https://www.taifex.com.tw/cht/3/futContractsDateAh'
        res_ah = requests.get(url_ah, headers=headers, timeout=15)
        res_ah.encoding = 'utf-8'
        soup_ah = BeautifulSoup(res_ah.text, 'html.parser')
        table_ah = soup_ah.find('table', class_='table_f')

        if table_ah:
            rows = table_ah.find_all('tr')
            # 結構：Row 3=臺股期貨(自營商), Row 4=投信, Row 5=外援 (子列，無商品名稱)
            # 子列格式：身份別, 多方口數, 多方金額, 空方口數, 空方金額, 多空淨額口數, 多空淨額金額
            if len(rows) > 5:
                tds = [td.text.strip().replace(',', '') for td in rows[5].find_all(['td', 'th'])]
                # tds[0] = '外援'（身份別）, tds[5] = 多空淨額口數
                # 用 Unicode codepoint 確認：外援 = U+5916 U+63F4
                if len(tds) >= 6 and tds[0][0] == '外' and tds[0][1] == '資':
                    foreign_net_position = tds[5]
                    if not foreign_net_position.startswith('-') and foreign_net_position != '0':
                        foreign_net_position = '+' + foreign_net_position
                    foreign_date_found = taiwan_date_str
                    print(f"  外援多空淨額: {foreign_net_position} (多方: {tds[1]}, 空方: {tds[3]})")

    except Exception as e:
        print(f"  取得三大法人資料失敗: {e}")

    # ── 4. 資料有效性檢查 ───────────────────────────────────────────
    # 確保至少有一個資料不是 0
    if day_volume == 0 and night_volume == 0:
        print("  [警告] 日盤和夜盤成交量皆為 0，資料可能過舊或抓取失敗")

    print(f"  完成！日期: {taiwan_date_str}")
    return day_volume, night_volume, night_price_change, foreign_net_position

def evaluate(day_volume, night_volume, night_price_change, foreign_net_position):
    if day_volume == 0 and night_volume == 0:
        return 0, "無效數據", None

    total_volume = day_volume + night_volume
    ratio = (night_volume / total_volume) * 100 if total_volume > 0 else 0

    if ratio < 30:
        signal = "夜盤參考價值較低"
    elif 31 <= ratio <= 39:
        signal = "中性看待"
    elif ratio > 40:
        signal = "很強的訊號"
    else:
        signal = "中性看待"

    return ratio, signal, total_volume

def generate_html(day_volume, night_volume, night_price_change, foreign_net_position, ratio, signal, total_volume=None):
    taiwan_tz = pytz.timezone('Asia/Taipei')
    taiwan_now = datetime.datetime.now(taiwan_tz)
    date_str = taiwan_now.strftime("%Y-%m-%d %H:%M:%S 台灣時間")

    # 取得資料日期描述
    last_trading = get_last_trading_day(taiwan_now)
    data_date_str = last_trading.strftime("%Y/%m/%d")

    prompt = f"""請以投資顧問的角度，根據以下數據對今日台股加權指數開盤與走勢進行評估：
1. 台指期夜盤漲跌：{night_price_change}
2. 台指期夜盤成交量：{night_volume} 口
3. 台指期日盤成交量：{day_volume} 口
4. 夜盤量占比：{ratio:.1f}% ({signal})
5. 外援夜盤多空淨額：{foreign_net_position} 口

請參考以下原則：
- 夜盤量占比 <30% 參考價值低，>40% 很強的訊號。
- 綜合研判範例：
  (1) 夜盤上漲，多空淨額為正：上漲力道紮實。
  (2) 夜盤上漲，多空淨額為負：上漲力道不強，盤中或尾盤可能往下走。
  (3) 夜盤下跌，多空淨額為負：外援看跌，開盤可能往下修正。
  (4) 夜盤下跌，多空淨額為正：抄底機會，開盤可能往下修正再反彈。"""

    # 根據訊號決定 badge 類別
    if ratio > 40:
        badge_class = "badge-strong"
        badge_text = "很強的訊號"
    elif ratio >= 30:
        badge_class = "badge-neutral"
        badge_text = "中性看待"
    else:
        badge_class = "badge-weak"
        badge_text = "參考價值低"

    # 根據漲跌決定顏色
    if '▲' in str(night_price_change):
        price_color_class = "red"
    elif '▼' in str(night_price_change):
        price_color_class = "green"
    else:
        price_color_class = ""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>當日加權指數漲跌評估</title>
    <style>
        :root {{
            --bg-color: #f3f4f6;
            --card-bg: #ffffff;
            --text-main: #1f2937;
            --text-muted: #6b7280;
            --primary: #3b82f6;
            --up-color: #ef4444;
            --down-color: #10b981;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            margin: 0;
            color: var(--primary);
        }}
        .header p {{
            color: var(--text-muted);
            margin-top: 5px;
        }}
        .dashboard {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        .card {{
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            text-align: center;
        }}
        .card h3 {{
            margin: 0 0 8px 0;
            font-size: 0.9rem;
            color: var(--text-muted);
            font-weight: 500;
        }}
        .card .value {{
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        .card .badge {{
            font-size: 0.85rem;
            padding: 4px 12px;
            border-radius: 20px;
            display: inline-block;
        }}
        .badge-strong {{ background: #fef3c7; color: #d97706; }}
        .badge-neutral {{ background: #e5e7eb; color: #6b7280; }}
        .badge-weak {{ background: #d1fae5; color: #059669; }}
        .red {{ color: var(--up-color); }}
        .green {{ color: var(--down-color); }}
        .orange {{ color: #f59e0b; }}
        .blue {{ color: var(--primary); }}

        .result-section {{
            background: var(--card-bg);
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            margin-bottom: 30px;
        }}
        .result-section h2 {{
            margin-top: 0;
            border-bottom: 2px solid var(--bg-color);
            padding-bottom: 10px;
        }}
        .prompt-box {{
            background: #1e293b;
            color: #e2e8f0;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            white-space: pre-wrap;
            line-height: 1.5;
            position: relative;
        }}
        .btn {{
            background-color: var(--primary);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 1rem;
            margin-top: 10px;
        }}
        .btn:hover {{
            background-color: #2563eb;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>當日加權指數漲跌評估</h1>
            <p>數據更新時間：{date_str}</p>
        </div>

        <div class="dashboard">
            <div class="card">
                <h3>夜盤漲跌</h3>
                <div class="value {price_color_class}">{night_price_change if night_price_change else '無資料'}</div>
            </div>
            <div class="card">
                <h3>夜盤量佔比</h3>
                <div class="value blue">{ratio:.1f}%</div>
                <span class="badge {badge_class}">{badge_text}</span>
            </div>
            <div class="card">
                <h3>外援多空淨額</h3>
                <div class="value orange">{foreign_net_position}</div>
            </div>
        </div>

        <div class="result-section">
            <h2>AI 評估提示詞 (Prompt)</h2>
            <p>請將以下提示詞複製，並貼上至 ChatGPT、Gemini 或其他大語言模型中，以獲取今日盤勢解析。</p>
            <div class="prompt-box" id="promptText">{prompt}</div>
            <button class="btn" onclick="copyPrompt()">📋 複製提示詞</button>
        </div>
    </div>

    <script>
        function copyPrompt() {{
            const text = document.getElementById('promptText').innerText;
            navigator.clipboard.writeText(text).then(() => {{
                alert('提示詞已複製！請貼上至大模型中。');
            }});
        }}
    </script>
</body>
</html>"""

    with open('daily_report.html', 'w', encoding='utf-8') as f:
        f.write(html)
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("成功產生 daily_report.html 和 index.html")

if __name__ == "__main__":
    print("=" * 50)
    print("開始爬取期交所資料...")
    print("=" * 50)
    d_vol, n_vol, n_price, f_net = get_market_data()
    print(f"日盤量: {d_vol}, 夜盤量: {n_vol}, 夜盤漲跌: {n_price}")

    ratio, signal, total_vol = evaluate(d_vol, n_vol, n_price, f_net)
    print(f"總成交量: {total_vol} 口, 夜盤佔比: {ratio:.1f}%, 訊號: {signal}")

    generate_html(d_vol, n_vol, n_price, f_net, ratio, signal, total_vol)
    print("=" * 50)
