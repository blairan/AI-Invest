import requests
from bs4 import BeautifulSoup
import datetime
import os

def get_market_data():
    url = 'https://www.taifex.com.tw/cht/3/futDailyMarketReport'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # 1. 取得日盤資料 (一般交易時段) : 往前找前一個交易日
    day_volume = 0
    try:
        target_date = datetime.date.today() - datetime.timedelta(days=1)
        for _ in range(10): # 往前找最多 10 天
            if target_date.weekday() >= 5: # 週末跳過
                target_date -= datetime.timedelta(days=1)
                continue
                
            date_str = target_date.strftime('%Y/%m/%d')
            data = {'queryType': 2, 'marketCode': 0, 'commodity_id': 'TX', 'queryDate': date_str}
            res_day = requests.post(url, data=data, headers=headers, timeout=10)
            soup_day = BeautifulSoup(res_day.text, 'html.parser')
            table_day = soup_day.find('table', class_='table_f')
            
            if table_day:
                rows = table_day.find_all('tr')
                if len(rows) > 1:
                    header = [t.text.strip() for t in rows[0].find_all(['td', 'th'])]
                    try:
                        # queryType=2 指定日期時，欄位名稱可能是 '*一般交易時段成交量' 或 '*成交量'
                        vol_idx = header.index('*一般交易時段成交量') if '*一般交易時段成交量' in header else header.index('*成交量')
                        tds = [td.text.strip() for td in rows[1].find_all(['td', 'th'])]
                        if len(tds) > vol_idx and tds[vol_idx].replace(',', '').isdigit():
                            day_volume = int(tds[vol_idx].replace(',', ''))
                            break
                    except ValueError:
                        pass
            
            # 沒找到資料（可能是國定假日），往前推一天
            target_date -= datetime.timedelta(days=1)
            
    except Exception as e:
        print(f"取得日盤資料失敗: {e}")

    # 2. 取得夜盤資料 (盤後交易時段)
    # queryType=2, marketCode=1, commodity_id=TX
    night_volume = 0
    night_price_change = ""
    try:
        res_night = requests.post(url, data={'queryType': 2, 'marketCode': 1, 'commodity_id': 'TX'}, headers=headers, timeout=10)
        soup_night = BeautifulSoup(res_night.text, 'html.parser')
        table_night = soup_night.find('table', class_='table_f')
        if table_night:
            rows = table_night.find_all('tr')
            for row in rows:
                tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                if len(tds) > 8 and tds[0] == 'TX' and (tds[8].replace(',', '').isdigit()):
                    night_price_change = tds[6]
                    night_volume = int(tds[8].replace(',', ''))
                    break
    except Exception as e:
        print(f"取得夜盤資料失敗: {e}")
        
    # 3. 取得三大法人外資夜盤多空淨額
    foreign_net_position = "請手動輸入"
    try:
        url_ah = 'https://www.taifex.com.tw/cht/3/futContractsDateAh'
        res_ah = requests.get(url_ah, headers=headers, timeout=10)
        soup_ah = BeautifulSoup(res_ah.text, 'html.parser')
        table_ah = soup_ah.find('table', class_='table_f')
        if table_ah:
            rows = table_ah.find_all('tr')
            for i, row in enumerate(rows):
                tds = [td.text.strip().replace(',', '') for td in row.find_all(['td', 'th'])]
                # 尋找臺股期貨且身份別為外資的那一行
                # 臺股期貨自營商通常是第一筆，外資通常在往下兩行
                if len(tds) >= 7 and '外資' in tds[0]:
                    # 確認它的上一層是臺股期貨
                    prev_rows_text = " ".join([td.text for td in rows[i-2].find_all(['td', 'th'])])
                    if '臺股期貨' in prev_rows_text:
                        # 外資行的多空淨額口數通常在索引 5
                        foreign_net_position = tds[5]
                        if not foreign_net_position.startswith('-') and foreign_net_position != '0':
                            foreign_net_position = '+' + foreign_net_position
                        break
    except Exception as e:
        print(f"取得三大法人資料失敗: {e}")
    
    return day_volume, night_volume, night_price_change, foreign_net_position

def evaluate(day_volume, night_volume, night_price_change, foreign_net_position):
    if day_volume == 0 and night_volume == 0:
        return 0, "無效數據"
    
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
        
    return ratio, signal

def generate_html(day_volume, night_volume, night_price_change, foreign_net_position, ratio, signal):
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    prompt = f"""請以投資顧問的角度，根據以下數據對今日台股加權指數開盤與走勢進行評估：
1. 台指期夜盤漲跌：{night_price_change}
2. 台指期夜盤成交量：{night_volume} 口
3. 台指期日盤成交量：{day_volume} 口
4. 夜盤量占比：{ratio:.1f}% ({signal})
5. 外資夜盤多空淨額：{foreign_net_position} 口

請參考以下原則：
- 夜盤量占比 <30% 參考價值低，>40% 很強的訊號。
- 綜合研判範例：
  (1) 夜盤上漲，多空淨額為正：上漲力道紮實。
  (2) 夜盤上漲，多空淨額為負：上漲力道不強，盤中或尾盤可能往下走。
  (3) 夜盤下跌，多空淨額為負：外資看跌，開盤可能往下修正。
  (4) 夜盤下跌，多空淨額為正：抄底機會，開盤可能往下修正再反彈。"""

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
            --up-color: #ef4444; /* 台灣股市紅色為漲 */
            --down-color: #10b981; /* 台灣股市綠色為跌 */
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
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
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
            margin: 0 0 10px 0;
            font-size: 1rem;
            color: var(--text-muted);
        }}
        .card .value {{
            font-size: 1.8rem;
            font-weight: bold;
        }}
        .red {{ color: var(--up-color); }}
        .green {{ color: var(--down-color); }}
        
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
                <div class="value {'red' if '▲' in str(night_price_change) else 'green' if '▼' in str(night_price_change) else ''}">{night_price_change if night_price_change else '無資料'}</div>
            </div>
            <div class="card">
                <h3>夜盤量佔比</h3>
                <div class="value" style="color: {'var(--up-color)' if ratio > 40 else 'var(--text-main)'};">{ratio:.1f}%</div>
                <div style="font-size: 0.9rem; margin-top:5px; color: var(--text-muted);">{signal}</div>
            </div>
            <div class="card">
                <h3>外資多空淨額</h3>
                <div class="value" style="font-size: 1.2rem; color: #f59e0b;">{foreign_net_position}</div>
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
    print("開始爬取期交所資料...")
    d_vol, n_vol, n_price, f_net = get_market_data()
    print(f"日盤量: {d_vol}, 夜盤量: {n_vol}, 夜盤漲跌: {n_price}")
    
    ratio, signal = evaluate(d_vol, n_vol, n_price, f_net)
    print(f"佔比: {ratio:.1f}%, 訊號: {signal}")
    
    generate_html(d_vol, n_vol, n_price, f_net, ratio, signal)
