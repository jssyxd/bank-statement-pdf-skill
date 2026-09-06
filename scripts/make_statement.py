# -*- coding: utf-8 -*-
"""
按九江银行对账单原 PDF 排版重建交易明细清单，明细数据取 CSV。
用法: python make_statement.py <明细.csv> <原版.pdf> [输出.pdf]
排版参数由原 PDF 实测(像素网格+文本基线); 字体 = 原版内嵌 STSong(华文宋体 STSONG.TTF, 度量逐字符一致)。
"""
import csv, io, re, sys
from pathlib import Path
import pymupdf
from PIL import Image as PILImage

FONT = r'C:\Windows\Fonts\STSONG.TTF'
PAGE_W, PAGE_H = 595.0, 842.0
COLS = [36.0, 88.3, 140.6, 192.9, 245.2, 297.5, 349.8, 402.1, 454.4, 506.7, 559.0]
CENTER_X = [(COLS[i] + COLS[i+1]) / 2 for i in range(10)]
COL_ALIGN = ['center', 'right', 'right', 'right', 'right', 'center',
             'center', 'center', 'center', 'center']
P1_HEADER_TOP, P1_DATA_TOP = 133.8, 146.8
CONT_DATA_TOP, P1_BOTTOM, CONT_BOTTOM = 35.8, 789.8, 788.8
ROW_LEAD, BASE1_OFF = 9.0, 11.5
WRAP_USABLE, RIGHT_PAD, MIN_SIZE = 49.5, 2.0, 7.0
TITLE_BASE, HEADER_BASE = 57.0, 145.0
INFO_BASES = [83.0, 96.0, 109.0, 122.0]
INFO_XS = [52.5, 312.5]
HEADERS = ['交易时间', '交易金额', '收入', '支出', '余额', '币种',
           '对方账号', '对方户名', '摘要', '交易用途']
FONT_SIZE = 9.0

fm = pymupdf.Font(fontfile=FONT)
def tw(s, size=FONT_SIZE):
    return fm.text_length(s, size)

def money(v):
    return f'{v:,.2f}'

def fmt_amount(raw):
    raw = raw.strip()
    if not raw:
        return ''
    neg = raw.startswith('-')
    return ('-' if neg else '+') + money(abs(float(raw.replace(',', ''))))

def build_subset_font(charset, out_ttf):
    from fontTools.ttLib import TTFont
    from fontTools import subset
    f = TTFont(FONT, fontNumber=0)
    opts = subset.Options(); opts.recalc_bounds = True
    ss = subset.Subsetter(opts)
    ss.populate(text=''.join(sorted(charset)))
    ss.subset(f)
    f.save(out_ttf)
    return out_ttf

# ---------- 输入 ----------
if len(sys.argv) < 3:
    sys.exit('usage: make_statement.py <csv> <src.pdf> [out.pdf]')
CSV_PATH = Path(sys.argv[1])
SRC_PDF = Path(sys.argv[2])
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else CSV_PATH.with_name('明细-替换版.pdf')
workdir = Path(__file__).resolve().parent

with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
    rd = list(csv.reader(f))
kv = {}
hidx = None
for i, r in enumerate(rd):
    if r and r[0].strip() == '交易时间':
        hidx = i
        break
    if r and len(r) >= 4 and r[1].strip() and r[0].strip() not in ('', '九江银行交易明细清单'):
        kv[r[0].strip()] = r[1].strip()
        if r[2].strip():
            kv[r[2].strip()] = r[3].strip()
assert hidx is not None
head = [h.strip() for h in rd[hidx]]
rows = []
for r in rd[hidx+1:]:
    if not r or not r[0].strip():
        continue
    rows.append(dict(zip(head, [c.strip() for c in r])))

def pf(s):
    return float((s or '0').replace(',', ''))

in_rows  = [r for r in rows if r['收入']]
out_rows = [r for r in rows if r['支出']]
sum_in  = sum(pf(r['收入']) for r in in_rows)
sum_out = sum(pf(r['支出']) for r in out_rows)
if (int(kv.get('贷方总笔数', -1)) != len(in_rows) or abs(pf(kv.get('贷方发生总额', '-1')) - sum_in) > 1e-4
        or int(kv.get('借方总笔数', -1)) != len(out_rows) or abs(pf(kv.get('借方发生总额', '-1')) - sum_out) > 1e-4):
    print('!! 警告: CSV 汇总头与明细不一致, 以逐行汇总为准', file=sys.stderr)
print(f'rows={len(rows)} 贷方(收入)={len(in_rows)}笔 {sum_in:,.2f} | 借方(支出)={len(out_rows)}笔 {sum_out:,.2f}')

info = [
    f"查询账号:{kv.get('查询账号', '')}", f"开户银行:{kv.get('开户银行', '')}",
    f"账户名称:{kv.get('账户名称', '')}", f"交易时间范围:{kv.get('交易时间范围', '')}",
    f"借方总笔数:{len(out_rows)}", f"借方发生总额:{money(sum_out)}",
    f"贷方总笔数:{len(in_rows)}", f"贷方发生总额:{money(sum_in)}",
]
INFO_ROWS = [(info[0], info[1]), (info[2], info[3]), (info[4], info[5]), (info[6], info[7])]

# ---------- 模板校验 ----------
def probe_geom(page):
    zoom = 2.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    smp = pix.samples
    hl, run = [], None
    for y in range(h):
        row = smp[y*w:(y+1)*w]
        isl = sum(1 for b in row if b < 128) > 0.8*w
        if isl and run is None: run = y
        elif not isl and run is not None:
            hl.append((run + y - 1)/2/zoom); run = None
    if run is not None: hl.append((run + h - 1)/2/zoom)
    assert len(hl) >= 3 and abs(hl[0]-133.8) < 1.0 and abs(hl[1]-146.8) < 1.0, f'首页模板异常 {hl[:3]}'
    return hl

# ---------- 原文图像 ----------
doc_src = pymupdf.open(SRC_PDF)
p1 = doc_src[0]
probe_geom(p1)
placed = {}
for m in re.finditer(rb'([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\s+/(\w+)\s+Do', p1.read_contents()):
    w, h, x, y = map(float, m.groups()[:4])
    placed[m.group(5).decode('latin1')] = (w, h, x, 842 - y - h)

def xref_of(name):
    t, v = doc_src.xref_get_key(p1.xref, f'Resources/XObject/{name}')
    return int(v.split()[0]) if t == 'xref' else None

logo_rect = qr_rect = None
logo_stream = qr_stream = None
for name, (w, h, x, y0) in placed.items():
    if abs(w - 118) < 3 and abs(h - 30) < 3 and logo_rect is None:
        logo_rect = pymupdf.Rect(x, y0, x + w, y0 + h)
        logo_stream = doc_src.extract_image(xref_of(name))['image']
    elif abs(w - 90) < 3 and abs(h - 88) < 3 and qr_rect is None:
        qr_rect = pymupdf.Rect(x, y0, x + w, y0 + h)
        xr = xref_of(name)
        qr_stream = doc_src.extract_image(xr)['image']
        sm = doc_src.xref_get_key(xr, 'SMask')
        if sm[0] == 'xref':
            axr = int(sm[1].split()[0])
            a = doc_src.extract_image(axr)['image']
            im = PILImage.open(io.BytesIO(qr_stream)).convert('RGB')
            im.putalpha(PILImage.open(io.BytesIO(a)).convert('L'))
            b = io.BytesIO(); im.save(b, 'PNG'); qr_stream = b.getvalue()
assert logo_rect and qr_rect and logo_stream and qr_stream, placed

# ---------- 子集字体 ----------
statics = ['交易明细清单'] + [t for pair in INFO_ROWS for t in pair] + HEADERS
body_texts = []
for r in rows:
    body_texts += [r['交易时间'][:10], r['交易时间'][11:19], fmt_amount(r['交易金额']),
                   money(pf(r['收入'])) if r['收入'] else '', money(pf(r['支出'])) if r['支出'] else '',
                   money(pf(r['余额'])), '人民币', r['对方账号'], r['对方户名'], r['摘要'], r['交易用途']]
charset = set(''.join(statics + body_texts)) | set('0123456789,.-+:() %')
SUB_FONT = workdir / f'_ss_{Path(OUT).stem}.ttf'
print('charset:', len(charset))
build_subset_font(charset, str(SUB_FONT))

# ---------- 排版 ----------
def cell_lines(text, col, size=FONT_SIZE):
    if COL_ALIGN[col] == 'right':
        lim = (COLS[col+1] - COLS[col]) - RIGHT_PAD
        w = tw(text, size)
        if w > lim:
            size = max(MIN_SIZE, size * lim / w)
        return [((COLS[col+1] - RIGHT_PAD - tw(text, size), text, size))], 1
    usable = WRAP_USABLE if col >= 6 else COLS[col+1]-COLS[col]-1.0
    lines, cur = [], ''
    for ch in text:
        if tw(cur + ch, size) <= usable:
            cur += ch
        else:
            if cur: lines.append(cur)
            cur = ch
    if cur: lines.append(cur)
    return [(CENTER_X[col] - tw(ln, size)/2, ln, size) for ln in lines], len(lines)

def row_parts(r):
    parts, n = [(None, [
        (CENTER_X[0] - tw(r['交易时间'][:10])/2, r['交易时间'][:10], 9),
        (CENTER_X[0] - tw(r['交易时间'][11:19])/2, r['交易时间'][11:19], 9)])], 2
    vals = [
        (fmt_amount(r['交易金额']), 1),
        (money(pf(r['收入'])) if r['收入'] else '', 2),
        (money(pf(r['支出'])) if r['支出'] else '', 3),
        (money(pf(r['余额'])), 4), ('人民币', 5),
        (r['对方账号'], 6), (r['对方户名'], 7), (r['摘要'], 8), (r['交易用途'], 9),
    ]
    for text, ci in vals:
        if not text:
            parts.append((ci, [])); continue
        placed, nl = cell_lines(text, ci)
        n = max(n, nl)
        parts.append((ci, placed))
    return parts, n

doc = pymupdf.open()

def new_page():
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_font(fontname='SS', fontfile=str(SUB_FONT))
    return p

def draw_band(page, y, h):
    page.draw_rect(pymupdf.Rect(COLS[0], y, COLS[-1], y + h), color=(0, 0, 0), width=0.5, fill=None)

def put(page, x, y, s, size=9.0, color=(0, 0, 0)):
    if s:
        page.insert_text(pymupdf.Point(x, y), s, fontname='SS', fontsize=size, color=color)

def layout_row(page, y, r):
    parts, n = row_parts(r)
    h = max(30.0, ROW_LEAD * n + 4.0)
    draw_band(page, y, h)
    for ci, placed in parts:
        for i, (x, s, size) in enumerate(placed):
            put(page, x, y + BASE1_OFF + ROW_LEAD * i, s, size=size)
    return h

def est_h(r):
    _, n = row_parts(r)
    return max(30.0, ROW_LEAD * n + 4.0)

def draw_verticals(p, y_top, y_bot):
    for x in COLS[1:-1]:
        p.draw_line(pymupdf.Point(x, y_top), pymupdf.Point(x, y_bot), color=(0, 0, 0), width=0.5)

# 首页
p = new_page()
p.insert_image(logo_rect, stream=logo_stream)
w = tw('交易明细清单', 20.0)
put(p, CENTER_X[4] - w/2, TITLE_BASE, '交易明细清单', size=20.0, color=(1, 0, 0))
for (l, r), yb in zip(INFO_ROWS, INFO_BASES):
    put(p, INFO_XS[0], yb, l); put(p, INFO_XS[1], yb, r)
draw_band(p, P1_HEADER_TOP, 13.0)
for ci, ht in enumerate(HEADERS):
    put(p, CENTER_X[ci] - tw(ht)/2, HEADER_BASE, ht)
y = P1_DATA_TOP
i = 0
while i < len(rows):
    h = est_h(rows[i])
    if y + h > P1_BOTTOM + 0.6:
        break
    y += layout_row(p, y, rows[i]); i += 1
draw_verticals(p, P1_HEADER_TOP, y)
while i < len(rows):
    p = new_page()
    y = CONT_DATA_TOP
    while i < len(rows):
        h = est_h(rows[i])
        if y + h > CONT_BOTTOM + 0.6:
            break
        y += layout_row(p, y, rows[i]); i += 1
    draw_verticals(p, CONT_DATA_TOP, y)
assert i == len(rows)

for pno in range(doc.page_count):
    doc[pno].insert_image(qr_rect, stream=qr_stream)

doc.save(OUT, deflate=True, garbage=3)
print('saved:', OUT, '| pages:', doc.page_count, '| rows:', len(rows))
doc.close(); doc_src.close()
