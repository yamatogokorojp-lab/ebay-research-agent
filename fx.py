"""USDJPY public reference quote; explicit timestamp and hard failure instead of silent fabrication."""
import requests
from datetime import datetime,timezone

class FxError(Exception):pass

def usd_jpy_rate():
    try:
        resp=requests.get('https://open.er-api.com/v6/latest/USD',timeout=12)
        resp.raise_for_status()
        data=resp.json()
        rate=float(data['rates']['JPY'])
        if not (50 < rate < 350):raise ValueError('不正なUSD/JPYレート')
        updated=str(data.get('time_last_update_utc','時刻不明'))
        return {'rate':rate,'updated':updated,'source':'open.er-api.com','retrieved':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    except (requests.RequestException,KeyError,TypeError,ValueError) as e:
        raise FxError('USD/JPY自動取得に失敗しました。レートを手入力するか通信を確認してください: '+str(e)) from e
