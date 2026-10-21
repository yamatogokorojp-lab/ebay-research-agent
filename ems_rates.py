"""User-provided Japan Post EMS weight-band prices; no hardcoded tariffs."""
import csv
import io
import math

class EMSRateError(ValueError):
    pass

def parse_ems_rate_csv(content: bytes):
    if len(content) > 2_000_000:
        raise EMSRateError("料金CSVが大きすぎます")
    for enc in ("utf-8-sig", "cp932"):
        try:
            txt = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise EMSRateError("文字コードが対応外です")
    reader = csv.DictReader(io.StringIO(txt))
    if not reader.fieldnames or not {'max_weight_g','price_jpy'}.issubset(set(reader.fieldnames)):
        raise EMSRateError("max_weight_g と price_jpy 列が必要です")
    vals=[]
    seen=set()
    for row in reader:
        try:
            w=float(row['max_weight_g'])
            p=float(row['price_jpy'])
        except (ValueError, TypeError):
            raise EMSRateError("重量と金額は数値で入力してください")
        if not all(map(math.isfinite,(w,p))) or w<=0 or p<=0 or w>30000 or w in seen:
            raise EMSRateError("重量帯・料金に不正または重複があります")
        vals.append((w,p))
        seen.add(w)
        if len(vals)>500:
            raise EMSRateError("料金帯が多すぎます")
    if not vals:
        raise EMSRateError("料金行がありません")
    return sorted(vals)

def lookup_ems_rate(rates, weight_g):
    if weight_g is None:
        return None
    try:
        w=float(weight_g)
    except (ValueError,TypeError):
        return None
    if not math.isfinite(w) or w<=0:
        return None
    return next((price for max_weight,price in rates if w<=max_weight), None)
