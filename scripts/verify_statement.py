# -*- coding: utf-8 -*-
"""验证生成的九江对账单(任意年度): 内容回读 / 几何 / 网格像素 / 首页静态区对比
用法: verify_statement.py <csv> <orig.pdf> <out.pdf>"""
import csv, re, sys
from pathlib import Path
import pymupdf

FONT = r'C:\Windows\Fonts\STSONG.TTF'
fm = pymupdf.Font(fontfile=FONT)
CSV_PATH, ORIG, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])

def money(v): return f'{v:,.2f}'
def pf(s): return float((s or '0').replace(',', ''))
def fmt_amount(raw):
    raw = raw.strip()
    if not raw: return ''
    neg = raw.startswith('-')
    return ('-' if neg else '+') + money(abs(pf(raw)))

with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
    rd = list(csv.reader(f))
hidx = next(i for i, r in enumerate(rd) if r and r[0].strip() == '交易时间')
head = [h.strip() for h in rd[hidx]]
crows = [dict(zip(head, [c.strip() for c in r])) for r in rd[hidx+1:] if r and r[0].strip()]

exp_vals = set(); exp_dates = set()
for r in crows:
    exp_vals |= {fmt_amount(r['交易金额']), r['币种'], money(pf(r['余额']))}
    if r['收入']: exp_vals.add(money(pf(r['收入'])))
    if r['支出']: exp_vals.add(money(pf(r['支出'])))
    exp_dates.add(r['交易时间'][:10])

ok = True
def check(cond, msg):
    global ok
    print(('PASS' if cond else 'FAIL'), msg)
    if not cond: ok = False

doc = pymupdf.open(OUT)
spans = []
for pno in range(doc.page_count):
    for b in doc[pno].get_text('dict')['blocks']:
        if b['type'] != 0: continue
        for l in b['lines']:
            for s in l['spans']:
                if s['text'].strip():
                    spans.append((pno, s['origin'][1], s['origin'][0], s['text'], s['size']))
dates = {t for _,_,_,t,_ in spans if re.fullmatch(r'\d{4}-\d{2}-\d{2}', t)}
times = {t for _,_,_,t,_ in spans if re.fullmatch(r'\d{2}:\d{2}:\d{2}', t)}
vals = {t for _,_,_,t,_ in spans}
missing = [v for v in sorted(exp_vals) if v not in vals]
check(dates == exp_dates, f'日期集合一致 ({len(dates)})')
check(len(times) == len({r['交易时间'][11:19] for r in crows}), f'时间数一致 ({len(times)})')
check(not missing, f'金额/币种值齐全 (缺 {missing[:5]})')

sp1 = sorted((y, x, t, sz) for pno, y, x, t, sz in spans if pno == 0)
fd = next((y, x, t) for y, x, t, _ in sp1 if re.fullmatch(r'\d{4}-\d{2}-\d{2}', t))
check(abs(fd[0] - 158.3) < 0.3, f'首页首行基线≈158.3 (实际 {fd[0]:.1f})')
r0 = crows[0]
for t, want in [(fmt_amount(r0['交易金额']), 138.6),
                (money(pf(r0['收入'])) if r0['收入'] else '', 190.9),
                (money(pf(r0['支出'])) if r0['支出'] else '', 243.2),
                (money(pf(r0['余额'])), 295.5)]:
    if not t: continue
    hit = next((x + fm.text_length(t, sz) for y, x, s, sz in sp1
                if 157.5 <= y <= 160.5 and s == t), None)
    check(hit is not None and abs(hit - want) < 0.3, f'首行 {t} 右缘={want} (实际 {hit})')

def hlines(p):
    zoom = 2.0
    pix = p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height; smp = pix.samples
    out, run = [], None
    for y in range(h):
        row = smp[y*w:(y+1)*w]
        isl = sum(1 for b in row if b < 128) > 0.8*w
        if isl and run is None: run = y
        elif not isl and run is not None:
            out.append((run + y - 1)/2/zoom); run = None
    if run is not None: out.append((run + h - 1)/2/zoom)
    return out

def vlines(p):
    zoom = 2.0
    pix = p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height; smp = pix.samples
    colx = [x/zoom for x in range(w) if sum(1 for i in range(h) if smp[i*w+x] < 128) > 0.5*h]
    res, run = [], None
    for x in colx:
        if run is None or x - run[1] > 1.5: run = [x, x]; res.append(run)
        else: run[1] = x
    return [round((a+b)/2, 1) for a, b in res]

for pno in range(doc.page_count):
    hl = hlines(doc[pno])
    if pno == 0:
        check(abs(hl[0]-133.8) < 1.0 and abs(hl[1]-146.8) < 1.0, '首页表头带位置一致')
        dd = [round(hl[i+1]-hl[i], 1) for i in range(1, len(hl)-1)]
        check(dd and min(dd) >= 29.5, f'首页行距正常 (min {min(dd) if dd else "-"})')
    else:
        check(abs(hl[0]-35.8) < 1.0, '续页起始位置一致')
vl = vlines(doc[0])
check(len(vl) >= 11, f'列分隔线齐全 ({len(vl)})')

odoc = pymupdf.open(ORIG)
zo = 3.0
pa = odoc[0].get_pixmap(matrix=pymupdf.Matrix(zo, zo), colorspace=pymupdf.csGRAY)
pb = doc[0].get_pixmap(matrix=pymupdf.Matrix(zo, zo), colorspace=pymupdf.csGRAY)
a, b, aw = pa.samples, pb.samples, pa.width
def diff(x0, x1, y0, y1):
    n = d = 0
    for y in range(int(y0*zo), int(y1*zo)):
        for x in range(int(x0*zo), int(x1*zo)):
            n += 1
            if abs(a[y*aw+x] - b[y*aw+x]) > 25: d += 1
    return d/n
dl, dbg, dt, dh = diff(41, 159, 37, 67), diff(36, 559, 60, 75), diff(30, 559, 30, 133.8), diff(30, 559, 133.8, 147.5)
print(f'logo={dl:.4f} 背景={dbg:.4f} 顶部={dt:.4f} 表头={dh:.4f}')
check(dl == 0.0, 'logo 像素一致')
check(dbg < 0.005, '纯背景一致')
check(dt < 0.12 and dh < 0.30, '静态区结构一致(余为字体差异)')

print()
print('OVERALL:', 'OK' if ok else 'FAILED')
doc.close(); odoc.close()
