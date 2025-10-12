# ===== مكتبات البوت الذكي =====
import requests, pandas as pd, numpy as np, time, io, os, threading, csv, socket
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import BollingerBands
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from plyer import notification
except:
    notification = None

# ===== إعداد التوكن والدردشة =====
TELEGRAM_TOKEN = "8113229531:AAEcjwghzY4Ip7E1_wdURa-HlkRq-yvVBW8"
CHAT_ID = "7485691652"

# ===== إعدادات البوت =====
bot_running = False
log_file = "metals_bot_events.log"
history_file = "signal_history.xlsx"
metals = {"XAU":"الذهب","XAG":"الفضة","XPT":"البلاتين"}
fallback_prices = {"XAU":1950,"XAG":24,"XPT":1000}
adaptive_settings = {symbol: {"rsi_threshold":50,"sl_factor":1.0,"tp_factor":1.0,"regression_window":10} for symbol in metals.keys()}

# ===== وظائف مساعدة =====
def log_event(event):
    with open(log_file,"a",encoding="utf-8") as f:
        f.write(f"{datetime.now()} - {event}\n")
    print(event)

def internet_available():
    try:
        socket.create_connection(("8.8.8.8",53),timeout=3)
        return True
    except:
        return False

def send_telegram(text, chart_bytes=None):
    if not internet_available(): return
    try:
        if chart_bytes:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            requests.post(url, data={"chat_id":CHAT_ID,"caption":text}, files={"photo":chart_bytes}, timeout=10)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id":CHAT_ID,"text":text}, timeout=10)
    except Exception as e:
        log_event(f"Telegram Error: {e}")

def get_metal_price(symbol):
    if not internet_available(): return fallback_prices[symbol]
    url = f"https://www.goldapi.io/api/{symbol}/USD"
    headers = {"x-access-token":"goldapi-4eg3smgjlxxag-io","Content-Type":"application/json"}
    try:
        r = requests.get(url,headers=headers,timeout=10)
        data = r.json()
        return float(data.get("price",fallback_prices[symbol]))
    except:
        return fallback_prices[symbol]

def save_signal(symbol,tf,signal,price,sl,tp):
    now = datetime.now()
    row = [now,symbol,tf,signal,price,sl,tp,"pending"]
    if not os.path.isfile(history_file):
        df = pd.DataFrame([row],columns=["datetime","symbol","timeframe","signal","price","stop_loss","target","result"])
        df.to_excel(history_file,index=False)
    else:
        df = pd.read_excel(history_file)
        df.loc[len(df)] = row
        df.to_excel(history_file,index=False)

def predict_next_price(prices,window=10):
    if len(prices)<2: return prices[-1]
    X = np.array(range(len(prices[-window:]))).reshape(-1,1)
    y = np.array(prices[-window:])
    model = LinearRegression().fit(X,y)
    return model.predict(np.array([[len(prices[-window:])]]))[0]

def analyze_price(price,symbol,history_prices=[]):
    settings = adaptive_settings[symbol]
    df = pd.DataFrame([price]*50,columns=["close"])
    if len(history_prices)>=50: df["close"]=history_prices[-50:]
    df["rsi"]=RSIIndicator(df["close"],14).rsi()
    df["ema20"]=EMAIndicator(df["close"],20).ema_indicator()
    bb=BollingerBands(df["close"],20,1.5)
    df["upper_band"]=bb.bollinger_hband()
    df["lower_band"]=bb.bollinger_lband()
    last_price = df["close"].iloc[-1]
    last_rsi = df["rsi"].iloc[-1]
    predicted = predict_next_price(df["close"].tolist(),settings["regression_window"])
    signal="⚪ انتظار"; order_type=None; sl=last_price; tp=last_price
    if last_price<df["ema20"].iloc[-1] and last_rsi<settings["rsi_threshold"] and predicted>last_price:
        signal="🟢 شراء"; order_type="BUY"; sl=last_price-10*settings["sl_factor"]; tp=predicted+20*settings["tp_factor"]
    elif last_price>df["ema20"].iloc[-1] and last_rsi>settings["rsi_threshold"] and predicted<last_price:
        signal="🔴 بيع"; order_type="SELL"; sl=last_price+10*settings["sl_factor"]; tp=predicted-20*settings["tp_factor"]
    if last_price<df["lower_band"].iloc[-1]: signal+=" | 🔴 كسر الدعم"
    elif last_price>df["upper_band"].iloc[-1]: signal+=" | 🟢 كسر المقاومة"
    return signal,sl,tp,df

def plot_chart(df,name,signal):
    plt.figure(figsize=(6,3))
    plt.plot(df["close"],label=f"سعر {name}",color="gold")
    plt.plot(df["ema20"],label="EMA20",color="green")
    plt.axhline(df["lower_band"].iloc[-1],color="blue",linestyle='-.',label='دعم')
    plt.axhline(df["upper_band"].iloc[-1],color="red",linestyle='-.',label='مقاومة')
    last_price = df["close"].iloc[-1]
    if "شراء" in signal: plt.scatter(len(df["close"])-1,last_price,color='green',marker='^',s=100)
    elif "بيع" in signal: plt.scatter(len(df["close"])-1,last_price,color='red',marker='v',s=100)
    plt.legend(fontsize=6)
    plt.tight_layout()
    buf=io.BytesIO()
    plt.savefig(buf,format="png"); buf.seek(0); plt.close()
    return buf

def monitor_signals():
    global bot_running
    while bot_running:
        if not os.path.isfile(history_file):
            time.sleep(60)
            continue
        df = pd.read_excel(history_file)
        updated=False
        for idx,row in df.iterrows():
            if row['result']=="pending":
                price=get_metal_price(row['symbol'])
                if "شراء" in row['signal']:
                    if price>=row['target']: df.at[idx,'result']="win"; updated=True
                    elif price<=row['stop_loss']: df.at[idx,'result']="loss"; updated=True
                elif "بيع" in row['signal']:
                    if price<=row['target']: df.at[idx,'result']="win"; updated=True
                    elif price>=row['stop_loss']: df.at[idx,'result']="loss"; updated=True
        if updated: df.to_excel(history_file,index=False)
        time.sleep(60)

def adaptive_learning():
    if not os.path.isfile(history_file): return
    df=pd.read_excel(history_file)
    for symbol in metals.keys():
        df_symbol=df[df['symbol']==symbol]
        total=len(df_symbol)
        if total==0: continue
        wins=len(df_symbol[df_symbol['result']=="win"])
        adaptive_settings[symbol]["sl_factor"]=max(0.5,1.0-0.1*(wins/total))
        adaptive_settings[symbol]["tp_factor"]=max(0.5,1.0+0.1*(wins/total))

def run_bot():
    global bot_running
    bot_running=True
    log_event("✅ تشغيل البوت الذكي...")
    threading.Thread(target=monitor_signals,daemon=True).start()
    threading.Thread(target=bot_loop,daemon=True).start()

def bot_loop():
    while bot_running:
        for symbol,name in metals.items():
            price=get_metal_price(symbol)
            signal,sl,tp,df_chart=analyze_price(price,symbol)
            save_signal(symbol,"5m",signal,price,sl,tp)
            chart=plot_chart(df_chart,name,signal)
            send_telegram(f"{name} - {signal}\nسعر: {price}",chart)
        adaptive_learning()
        time.sleep(300) # كل 5 دقائق

# ===== تشغيل البوت مباشرة =====
if __name__=="__main__":
    run_bot()