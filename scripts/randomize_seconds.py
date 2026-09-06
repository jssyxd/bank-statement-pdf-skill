# -*- coding: utf-8 -*-
"""把银行明细 CSV「交易时间」列中秒数为 00 的行改为 01~59 随机秒（只改秒位，不动行尾）。
用法: python randomize_seconds.py <csv> [输出csv]; 不给出输出则原位覆盖。
"""
import re, random, sys

def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    raw = open(src, 'rb').read()
    crlf = b'\r\n' in raw
    text = raw.decode('utf-8-sig')
    nl = '\r\n' if crlf else '\n'
    lines = text.split(nl)
    pat = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}):00(?=,)')
    changed = []
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            sec = random.randint(1, 59)
            # 只替换匹配到的时间前缀，保留该行其余全部内容
            lines[i] = ln[:m.start()] + f"{m.group(1)}:{sec:02d}" + ln[m.end():]
            changed.append(m.group(1))
    body = '\n'.join(lines)
    if text.startswith('\ufeff'):
        body = '\ufeff' + body
    data = body.encode('utf-8')
    if crlf:
        data = data.replace(b'\n', b'\r\n')
    open(dst, 'wb').write(data)
    print(f'随机化 :00 秒行数: {len(changed)} -> {dst}')
    for c in changed:
        print('  ', c)

if __name__ == '__main__':
    main()
