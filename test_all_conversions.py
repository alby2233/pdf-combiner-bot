import os
import shutil
import tempfile
from pdf_utils import (
    word_to_pdf, pdf_to_word,
    ppt_to_pdf, pdf_to_ppt,
    excel_to_pdf, pdf_to_excel,
    add_header_footer_page_numbers,
    merge_pdfs, split_pdf, rotate_pdf,
    ppt_to_images, pdf_to_images, images_to_pdf
)

def create_dummy_word(file_path):
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        doc = word.Documents.Add()
        range_obj = doc.Range(0, 0)
        range_obj.Text = "Hello World! This is a test Word document converted to PDF using Python COM interfaces.\nWithout watermarks!"
        doc.SaveAs(os.path.abspath(file_path))
        doc.Close()
    finally:
        word.Quit()
        pythoncom.CoUninitialize()

def create_dummy_ppt(file_path):
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    try:
        ppt = win32com.client.DispatchEx("PowerPoint.Application")
        pres = ppt.Presentations.Add(WithWindow=False)
        # Add slide with blank layout (index 12 is usually blank, or 1)
        slide = pres.Slides.Add(1, 1) # slide index 1, layout 1 (Title slide)
        slide.Shapes.Title.TextFrame.TextRange.Text = "Dummy PPT presentation"
        slide.Shapes.Placeholders(2).TextFrame.TextRange.Text = "Created programmatically via pythoncom\nNo watermarks here!"
        pres.SaveAs(os.path.abspath(file_path))
        pres.Close()
    finally:
        ppt.Quit()
        pythoncom.CoUninitialize()

def create_dummy_excel(file_path):
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        wb = excel.Workbooks.Add()
        ws = wb.ActiveSheet
        ws.Cells(1, 1).Value = "Header 1"
        ws.Cells(1, 2).Value = "Header 2"
        ws.Cells(2, 1).Value = "Row 1 Col 1"
        ws.Cells(2, 2).Value = "Row 1 Col 2"
        ws.Cells(3, 1).Value = "Row 2 Col 1"
        ws.Cells(3, 2).Value = "Row 2 Col 2"
        wb.SaveAs(os.path.abspath(file_path))
        wb.Close()
    finally:
        excel.Quit()
        pythoncom.CoUninitialize()

def run_tests():
    test_dir = os.path.abspath("test_outputs")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)
    
    print("--- Creating Dummy Office Files ---")
    doc_path = os.path.join(test_dir, "dummy.docx")
    ppt_path = os.path.join(test_dir, "dummy.pptx")
    xls_path = os.path.join(test_dir, "dummy.xlsx")
    
    create_dummy_word(doc_path)
    print(f"Created Word document: {doc_path}")
    create_dummy_ppt(ppt_path)
    print(f"Created PPT presentation: {ppt_path}")
    create_dummy_excel(xls_path)
    print(f"Created Excel workbook: {xls_path}")
    
    print("\n--- Testing Office to PDF ---")
    word_pdf = os.path.join(test_dir, "word.pdf")
    ppt_pdf = os.path.join(test_dir, "ppt.pdf")
    excel_pdf = os.path.join(test_dir, "excel.pdf")
    
    word_to_pdf(doc_path, word_pdf)
    print(f"Converted Word -> PDF: {word_pdf} (Exists: {os.path.exists(word_pdf)})")
    ppt_to_pdf(ppt_path, ppt_pdf)
    print(f"Converted PPT -> PDF: {ppt_pdf} (Exists: {os.path.exists(ppt_pdf)})")
    excel_to_pdf(xls_path, excel_pdf)
    print(f"Converted Excel -> PDF: {excel_pdf} (Exists: {os.path.exists(excel_pdf)})")
    
    print("\n--- Testing PDF to Office ---")
    back_word = os.path.join(test_dir, "back_word.docx")
    back_ppt = os.path.join(test_dir, "back_ppt.pptx")
    back_excel = os.path.join(test_dir, "back_excel.xlsx")
    
    pdf_to_word(word_pdf, back_word)
    print(f"Converted PDF -> Word: {back_word} (Exists: {os.path.exists(back_word)})")
    pdf_to_ppt(ppt_pdf, back_ppt)
    print(f"Converted PDF -> PPT: {back_ppt} (Exists: {os.path.exists(back_ppt)})")
    pdf_to_excel(excel_pdf, back_excel)
    print(f"Converted PDF -> Excel: {back_excel} (Exists: {os.path.exists(back_excel)})")
    
    print("\n--- Testing PDF Layout Settings (Header/Footer/Page Number) ---")
    numbered_pdf = os.path.join(test_dir, "numbered_word.pdf")
    add_header_footer_page_numbers(
        pdf_path=word_pdf,
        output_path=numbered_pdf,
        header_text="CONFIDENTIAL TEST DOCUMENT",
        footer_text="Python PDF Bot Project",
        add_page_numbers=True,
        start_page_num=1,
        exclude_first_page=False
    )
    print(f"Generated Layout Overlay PDF: {numbered_pdf} (Exists: {os.path.exists(numbered_pdf)})")
    
    print("\n--- Testing Merging and Splitting PDFs ---")
    merged_pdf = os.path.join(test_dir, "merged.pdf")
    merge_pdfs([word_pdf, ppt_pdf], merged_pdf)
    print(f"Merged PDFs (Word + PPT): {merged_pdf} (Exists: {os.path.exists(merged_pdf)})")
    
    split_output = os.path.join(test_dir, "split_page2.pdf")
    split_pdf(merged_pdf, "2", split_output)
    print(f"Split PDF page 2: {split_output} (Exists: {os.path.exists(split_output)})")
    
    print("\n--- Testing PPT/PDF to Images ---")
    ppt_images_dir = os.path.join(test_dir, "ppt_images")
    pdf_images_dir = os.path.join(test_dir, "pdf_images")
    
    ppt_imgs = ppt_to_images(ppt_path, ppt_images_dir)
    print(f"Exported PPT Slides to Images: {len(ppt_imgs)} images saved in {ppt_images_dir}")
    pdf_imgs = pdf_to_images(word_pdf, pdf_images_dir)
    print(f"Exported PDF Pages to Images: {len(pdf_imgs)} images saved in {pdf_images_dir}")
    
    rebuilt_pdf = os.path.join(test_dir, "rebuilt_from_images.pdf")
    images_to_pdf(pdf_imgs, rebuilt_pdf)
    print(f"Created PDF from images: {rebuilt_pdf} (Exists: {os.path.exists(rebuilt_pdf)})")
    
    print("\nAll Tests Executed Successfully!")

if __name__ == "__main__":
    run_tests()
