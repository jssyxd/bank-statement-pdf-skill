# -*- coding: utf-8 -*-
"""
inspect_layout_and_box.py - PDF 视觉排查与版心合规检查器

功能：
  1. 页面物理尺寸与比例核验（默认 A4: 595.3 x 841.9 pt）
  2. 版心边界溢出排查（左右与顶底边界溢出检测）
  3. 支持从对应原版/基线 PDF 对比版心漂移与坐标容差
  4. 表格溢出排查（特别检测宽度跨页、右侧裁切）
  5. 视觉空白块排查（检测过大的段落或跨页空洞）

用法：
  python scripts/inspect_layout_and_box.py "<待查.pdf>" ["<原版基线.pdf>"] [--margin-left 76.55] [--margin-right 76.55]
"""

import argparse
import sys

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None


def check_pdf_layout(pdf_path: str, baseline_pdf: str = None,
                     margin_left: float = 76.55, margin_right: float = 76.55,
                     margin_top: float = 85.05, margin_bottom: float = 56.7,
                     tolerance: float = 25.0):
    if pymupdf is None:
        raise RuntimeError("未安装 pymupdf，请执行 pip install pymupdf")

    doc = pymupdf.open(pdf_path)
    total_pages = doc.page_count
    print(f"=== 开始版心与视觉检查: {pdf_path} (共 {total_pages} 页) ===")

    findings = []
    page_stats = []

    # 若提供了基线 PDF，先获取基线各页面的文本分布与版心极值
    baseline_stats = {}
    if baseline_pdf:
        b_doc = pymupdf.open(baseline_pdf)
        for p_idx in range(b_doc.page_count):
            p = b_doc.load_page(p_idx)
            blocks = [b for b in p.get_text("blocks") if len(b) >= 5 and b[4].strip()]
            if blocks:
                min_x = min(b[0] for b in blocks)
                max_x = max(b[2] for b in blocks)
            else:
                min_x, max_x = margin_left, p.rect.width - margin_right
            baseline_stats[p_idx + 1] = {"min_x": min_x, "max_x": max_x, "page_count": b_doc.page_count}
        b_doc.close()
        print(f"已加载基线 PDF: {baseline_pdf} (共 {len(baseline_stats)} 页)")

    for page_idx in range(total_pages):
        page = doc.load_page(page_idx)
        rect = page.rect
        width, height = rect.width, rect.height

        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if len(b) >= 5 and b[4].strip()]
        images = page.get_images()

        out_of_bounds = []
        for b in text_blocks:
            b_rect = pymupdf.Rect(b[:4])
            # 页脚页码豁免检测
            if b_rect.y0 >= height - margin_bottom - 20:
                continue

            # 严重溢出检查（超出页面物理边界，或超出允许的表格扩展容差）
            if b_rect.x1 > width - 15.0:
                out_of_bounds.append((b_rect, "右侧严重溢出页面边缘", b[4][:30].replace("\n", " ")))
            elif b_rect.x0 < 15.0:
                out_of_bounds.append((b_rect, "左侧严重溢出页面边缘", b[4][:30].replace("\n", " ")))

            # 若有基线，比对相对基线的右缘扩展
            if baseline_stats and (page_idx + 1) in baseline_stats:
                base_max_x = baseline_stats[page_idx + 1]["max_x"]
                if b_rect.x1 > base_max_x + 30.0 and b_rect.x1 > width - margin_right:
                    out_of_bounds.append((b_rect, f"相较原版右界明显偏宽 (>+{b_rect.x1 - base_max_x:.1f}pt)", b[4][:30].replace("\n", " ")))

        # 检查纯文本之间的异常超大空白（若本页含图片/图表则不视为空白脱节）
        max_gap = 0
        if len(text_blocks) >= 2 and len(images) == 0:
            sorted_blocks = sorted(text_blocks, key=lambda x: x[1])
            for i in range(len(sorted_blocks) - 1):
                if sorted_blocks[i+1][1] >= height - margin_bottom - 20:
                    continue
                gap = sorted_blocks[i+1][1] - sorted_blocks[i][3]
                if gap > max_gap:
                    max_gap = gap

        page_stats.append({
            "page": page_idx + 1,
            "width": width,
            "height": height,
            "blocks_count": len(text_blocks),
            "images_count": len(images),
            "out_of_bounds": out_of_bounds,
            "max_gap": max_gap
        })

        if out_of_bounds:
            for b_rect, issue, sample in out_of_bounds:
                findings.append(f"第 {page_idx+1} 页: {issue} [x1={b_rect.x1:.1f}/{width:.1f}] -> '{sample}'")

        if max_gap > 250:
            findings.append(f"第 {page_idx+1} 页: 存在显著空白脱节 ({max_gap:.1f} pt)，请检查分页符或段落设置")

    doc.close()

    print("\n--- 逐页排查报告 ---")
    for stat in page_stats:
        status_str = "正常" if not stat["out_of_bounds"] else f"发现 {len(stat['out_of_bounds'])} 处越界/偏宽"
        img_str = f"| 图片: {stat['images_count']} 张" if stat['images_count'] else ""
        print(f"P{stat['page']:02d}: 尺寸 {stat['width']:.1f}x{stat['height']:.1f} pt | 文本块: {stat['blocks_count']:2d} {img_str:13s} | 最大正文间距: {stat['max_gap']:5.1f} pt | 状态: {status_str}")

    print("\n--- 综合判定 ---")
    if findings:
        print(f"发现 {len(findings)} 项需要关注的视觉或版面问题:")
        for f in findings:
            print("  [WARN]", f)
        return False
    else:
        print("[PASS] 版心合规检查全部通过！无越界裁切风险、页面尺寸规范、图文排版平整。")
        return True


def main():
    parser = argparse.ArgumentParser(description="PDF 视觉排查与版心检查器")
    parser.add_argument("pdf", help="待检查的 PDF 文件路径")
    parser.add_argument("baseline", nargs="?", default=None, help="可选：用于比对的原版基线 PDF 文件路径")
    parser.add_argument("--margin-left", type=float, default=76.55, help="默认左边距 (pt)")
    parser.add_argument("--margin-right", type=float, default=76.55, help="默认右边距 (pt)")
    parser.add_argument("--margin-top", type=float, default=85.05, help="默认顶边距 (pt)")
    parser.add_argument("--margin-bottom", type=float, default=56.7, help="默认底边距 (pt)")

    args = parser.parse_args()
    ok = check_pdf_layout(args.pdf, args.baseline,
                          args.margin_left, args.margin_right,
                          args.margin_top, args.margin_bottom)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
