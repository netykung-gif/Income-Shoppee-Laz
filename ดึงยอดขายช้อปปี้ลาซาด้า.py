import pypdf
import re
import pandas as pd

# ระบุที่อยู่ไฟล์ (แก้ไข Path ให้ตรงกับเครื่องของพี่นะครับ)
shopee_pdf_path = r"C:\Users\ASUS\Desktop\Work\ไฟล์งานกำลังทำ\โค้ดทดสอบ\monthly_report_20260601 sh.pdf"
lazada_pdf_path = r"C:\Users\ASUS\Desktop\Work\ไฟล์งานกำลังทำ\โค้ดทดสอบ\รายได้ LZD 06-69.pdf"
output_excel_path = r"C:\Users\ASUS\Downloads\รายงานสรุปรายได้รวม_มิถุนายน_Final.xlsx"

# =========================================================================
# 1. ประมวลผลฝั่ง SHOPEE (ทุกหน้า, รวม Col 4)
# =========================================================================
print("กำลังประมวลผลข้อมูล Shopee...")
reader_sh = pypdf.PdfReader(shopee_pdf_path)
shopee_data = []

for page in reader_sh.pages:
    text = page.extract_text()
    if not text: continue
    
    # ดึงวันที่และแยกบล็อก
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)
    chunks = re.split(r'\d{4}-\d{2}-\d{2}', text)[1:]
    
    for date, chunk in zip(dates, chunks):
        tokens = [t.strip().replace('−', '-') for t in chunk.split('\n') if t.strip()]
        try:
            # สมานเลขหลักพัน Col 2, ดึง Col 3, Col 4
            col2 = float((tokens[0] + tokens[1]).replace(',', ''))
            col3 = float(tokens[2].replace(',', ''))
            col4 = float(tokens[3].replace(',', ''))
            
            shopee_data.append({
                "วันที่โอนเงิน": date,
                "ราคาสินค้า (Col 2)": col2,
                "จำนวนเงินคืนผู้ซื้อ (Col 3)": col3,
                "ส่วนลด/เงินสนับสนุน (Col 4)": col4
            })
        except:
            continue

df_shopee = pd.DataFrame(shopee_data).drop_duplicates().sort_values("วันที่โอนเงิน").reset_index(drop=True)

# =========================================================================
# 2. ประมวลผลฝั่ง LAZADA
# =========================================================================
print("กำลังประมวลผลข้อมูล Lazada...")
reader_lz = pypdf.PdfReader(lazada_pdf_path)
lazada_rows = []

for page in reader_lz.pages:
    text = page.extract_text()
    if not text: continue
    for line in text.split('\n'):
        if re.search(r"^\d{2}/\d{2}/\d{4}", line.strip()):
            amounts = re.findall(r"(-?[\d,]+\.\d{2})", line)
            if len(amounts) >= 5:
                parts = line.split()
                lazada_rows.append({
                    "วันที่": parts[0],
                    "ยอดขาย": float(amounts[0].replace(",", "")),
                    "ค่าธรรมเนียม": float(amounts[1].replace(",", "")),
                    "ค่าขนส่ง": float(amounts[2].replace(",", "")),
                    "ค่าการตลาด": float(amounts[3].replace(",", "")),
                    "ยอดสุทธิ": float(amounts[-1].replace(",", ""))
                })
df_lazada = pd.DataFrame(lazada_rows)

# =========================================================================
# 3. บันทึกออก Excel และฝังสูตร Shopee (B-C)+D
# =========================================================================
print("กำลังเขียนไฟล์ Excel...")
with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
    df_shopee.to_excel(writer, index=False, sheet_name='รายได้ Shopee')
    df_lazada.to_excel(writer, index=False, sheet_name='รายได้ Lazada')
    
    # ฝังสูตรคำนวณในชีต Shopee
    ws = writer.sheets['รายได้ Shopee']
    ws["E1"] = "ยอดสุทธิ (B-C)+D"
    for row in range(2, len(df_shopee) + 2):
        ws[f"E{row}"] = f"=(B{row}-ABS(C{row}))+D{row}"
        
    # ปรับขนาดคอลัมน์ให้อ่านง่าย
    for sheet in writer.sheets.values():
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 20

print(f"\n[สำเร็จ!] ไฟล์อยู่ที่: {output_excel_path}")