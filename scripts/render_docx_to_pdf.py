# -*- coding: utf-8 -*-
"""
render_docx_to_pdf.py - 高保真 Word (.docx) 导出为 PDF 及高清预览图生成器

特性：
  - Windows 环境通过 Word COM 组件导出（保持与 Office 100% 像素一致的字体与版面）
  - 导出前安全复制到临时副本，防止 Office 运行时自动回写、篡改原 docx 结构
  - 支持异常静默重试机制与进程回收
  - 自动调用 PyMuPDF (fitz) 生成逐页高清 PNG 渲染切片（默认 150 DPI）

依赖：
  pip install pywin32 pymupdf

用法：
  python scripts/render_docx_to_pdf.py "<输入.docx>" "[输出.pdf]" "[预览图目录]"
"""

import glob
import os
import shutil
import sys
import time

try:
    import win32com.client as win32
except ImportError:
    win32 = None

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

WD_FORMAT_PDF = 17
DEFAULT_DPI = 150


def docx_to_pdf(docx_path: str, pdf_path: str) -> None:
    """使用 Word COM 导出 PDF，具备临时副本保护与重试机制。"""
    if win32 is None:
        raise RuntimeError("未安装 pywin32，无法调用 Word COM 导出。请执行 pip install pywin32")

    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.abspath(pdf_path)
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    # 保护性拷贝：避免 Word 回写/添加默认页眉部件污染原版 docx
    tmp_docx = docx_path + ".tmp_export.docx"
    shutil.copyfile(docx_path, tmp_docx)

    word = win32.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0

    last_err = None
    for attempt in range(2):
        try:
            doc = word.Documents.Open(tmp_docx, ReadOnly=True, AddToRecentFiles=False)
            try:
                doc.SaveAs(pdf_path, FileFormat=WD_FORMAT_PDF)
            finally:
                doc.Close(SaveChanges=0)
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(2)

    word.Quit()

    # 清理临时文件
    if os.path.exists(tmp_docx):
        try:
            os.remove(tmp_docx)
        except OSError:
            pass

    if last_err is not None:
        raise last_err

    print(f"[OK] PDF 导出完成: {pdf_path} ({os.path.getsize(pdf_path)} 字节)")


def pdf_to_previews(pdf_path: str, preview_dir: str, dpi: int = DEFAULT_DPI) -> int:
    """使用 PyMuPDF 将 PDF 渲染为逐页高清 PNG 切片。"""
    if pymupdf is None:
        raise RuntimeError("未安装 pymupdf，无法生成预览图。请执行 pip install pymupdf")

    pdf_path = os.path.abspath(pdf_path)
    preview_dir = os.path.abspath(preview_dir)
    os.makedirs(preview_dir, exist_ok=True)

    # 清除旧的预览文件
    for f in glob.glob(os.path.join(preview_dir, "page*.png")):
        try:
            os.remove(f)
        except OSError:
            pass

    doc = pymupdf.open(pdf_path)
    page_count = doc.page_count
    for i in range(page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=dpi)
        out_png = os.path.join(preview_dir, f"page{i+1:02d}.png")
        pix.save(out_png)
    doc.close()

    print(f"[OK] 逐页预览图生成完成: 共 {page_count} 页 -> {preview_dir}")
    return page_count


def main():
    if len(sys.argv) < 2:
        print("用法: python render_docx_to_pdf.py <输入.docx> [输出.pdf] [预览图目录]")
        sys.exit(1)

    docx_path = sys.argv[1]
    if not os.path.isfile(docx_path):
        print(f"错误: 找不到输入文件 {docx_path}")
        sys.exit(1)

    if len(sys.argv) >= 3:
        pdf_path = sys.argv[2]
    else:
        pdf_path = os.path.splitext(docx_path)[0] + ".pdf"

    if len(sys.argv) >= 4:
        preview_dir = sys.argv[3]
    else:
        preview_dir = os.path.join(os.path.dirname(pdf_path), "_preview")

    docx_to_pdf(docx_path, pdf_path)
    pdf_to_previews(pdf_path, preview_dir)


if __name__ == "__main__":
    main()
