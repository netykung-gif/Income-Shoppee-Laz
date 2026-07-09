import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import pypdf

# ---------------------------------------------------------------------------
# ฟอนต์ในไฟล์ PDF ของ Shopee บางไฟล์เข้ารหัสวรรณยุกต์/การันต์ไทยบางตัวไว้ใน
# Private Use Area (PUA) แทน Unicode ปกติ ทำให้จับคำในหัวตารางไม่เจอ
# ต้องแปลงกลับก่อนเสมอ
# ---------------------------------------------------------------------------
PUA_MAP = {
    "\uf70a": "\u0e48",  # ่ ไม้เอก
    "\uf70b": "\u0e49",  # ้ ไม้โท
    "\uf70e": "\u0e4c",  # ์ การันต์
}

# วรรณยุกต์/สระบน ที่บางครั้งถูกดึงมาผิดลำดับ (เช่น "ซ้ือ" แทน "ซื้อ")
# ตัดออกตอนเทียบคำหัวตาราง เพื่อไม่ให้ลำดับตัวอักษรที่คลาดเคลื่อนทำให้จับคำไม่เจอ
DIACRITICS = re.compile("[\u0e34-\u0e3a\u0e47-\u0e4e]")


def fix_thai(s):
    if not s:
        return s
    for bad, good in PUA_MAP.items():
        s = s.replace(bad, good)
    # บางฟอนต์แยก "ำ" (สระอำ) เป็นนิคหิต (ํ) + สระอา (า) สองตัวอักษร
    # ต้องรวมกลับเป็น "ำ" ตัวเดียว ไม่เช่นนั้นจะจับคำเช่น "ชำระ" ไม่เจอ
    s = s.replace("\u0e4d\u0e32", "\u0e33")
    return s


def skeleton(s):
    """ทำให้ข้อความไทยเทียบกันได้ง่าย: แก้ฟอนต์ + ตัดช่องว่าง + ตัดวรรณยุกต์"""
    s = fix_thai(s) or ""
    s = re.sub(r"\s+", "", s)
    s = DIACRITICS.sub("", s)
    return s


def parse_num(s):
    """แปลงข้อความตัวเลข (รวมเลขติดลบที่ใช้เครื่องหมาย − ของ Shopee) เป็น float"""
    if s is None:
        return None
    s = fix_thai(s).replace("−", "-").replace(",", "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_column_indices(header_cells):
    """หา index ของคอลัมน์ที่ต้องการ โดยจับคำในหัวตาราง (ไม่ยึดตำแหน่งตายตัว)
    เพราะรายงานแต่ละเดือนอาจมี/ไม่มีบางคอลัมน์ (เช่น "ค่าจัดส่งสินค้าที่ออกโดย Shopee")"""
    idx = {}
    for i, cell in enumerate(header_cells):
        t = skeleton(cell)
        if skeleton("ราคาสินค้า") in t:
            idx["price"] = i
        elif skeleton("คืนให้ผู้ซื้อ") in t:
            idx["refund"] = i
        elif skeleton("ชำระโดยผู้ซื้อ") in t and skeleton("จัดส่ง") in t:
            idx["ship_paid_by_buyer"] = i
    return idx


def parse_summary_totals(page_text):
    """ดึงยอดสรุปจากตาราง 'สรุปจำนวนเงินที่โอนแล้ว' ในหน้าแรก
    ใช้เป็นค่าอ้างอิงเพื่อตรวจสอบว่าดึงข้อมูลรายวันมาครบ/ถูกต้องหรือไม่"""
    text = fix_thai(page_text) or ""
    totals = {}
    patterns = {
        "price": r"ราคาสินค้า\s*([\-\u2212\d,]+)",
        "refund": r"จำนวนเงินที่ทำการคืนให้ผู้ซื้อ\s*([\-\u2212\d,]+)",
        "ship_paid_by_buyer": r"ค่าจัดส่งที่ชำระโดยผู้ซื้อ\s*([\-\u2212\d,]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            totals[key] = parse_num(m.group(1))
    return totals


def get_shopee_data(file):
    """
    ดึงข้อมูลรายวันจากรายงานการเงิน Shopee (PDF)

    ใช้ pdfplumber อ่านโครงสร้างตารางจริง (ยึดเส้นตาราง) แทนการตัดข้อความด้วย regex
    ล้วนๆ เพราะ:
      1) ตัวเลข/วันที่บางค่าถูกตัดขึ้นบรรทัดใหม่กลางคำเมื่อคอลัมน์แคบ (เช่นเดือนที่มี
         คอลัมน์เยอะกว่าปกติ) ทำให้ regex แบบเดิมจับวันที่ไม่เจอเลย
      2) จำนวนคอลัมน์ในรายงานแต่ละเดือนไม่เท่ากันเสมอไป จึงหาคอลัมน์ที่ต้องการ
         จากชื่อหัวตาราง ไม่ใช่ตำแหน่งคงที่

    คืนค่า (DataFrame, list ของข้อความเตือน)
    """
    data = []
    warnings = []
    col_idx = None
    ncols = None
    summary_totals = {}

    with pdfplumber.open(file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            if page_num == 1:
                try:
                    summary_totals = parse_summary_totals(page.extract_text())
                except Exception:
                    pass

            try:
                tables = page.find_tables()
            except Exception as e:
                warnings.append(f"หน้า {page_num}: อ่านตารางไม่ได้ ({e})")
                continue

            for t in tables:
                try:
                    table_data = t.extract()
                except Exception:
                    continue
                if not table_data:
                    continue

                # หาแถวหัวตาราง (มีคำว่า "ราคาสินค้า" และ "คืนให้ผู้ซื้อ")
                header_row_i = None
                for ri, row in enumerate(table_data):
                    joined = skeleton("".join(c or "" for c in row))
                    if skeleton("ราคาสินค้า") in joined and skeleton("คืนให้ผู้ซื้อ") in joined:
                        header_row_i = ri
                        break

                if header_row_i is not None:
                    new_col_idx = find_column_indices(table_data[header_row_i])
                    if len(new_col_idx) >= 3:
                        col_idx = new_col_idx
                        ncols = len(table_data[header_row_i])

                # แถวสุดท้ายของตารางบนหน้านี้คือแถวข้อมูลรวมของทุกวันที่อยู่ในหน้านั้น
                # (pdfplumber รวมหลายแถวจริงเข้าด้วยกันเมื่อไม่มีเส้นคั่นแนวนอนระหว่างแถว)
                last_row = table_data[-1]
                if not last_row or not last_row[0] or not col_idx or ncols is None:
                    continue
                if len(last_row) != ncols or ncols < 8:
                    continue

                date_text = fix_thai(last_row[0]).replace("\n", "")
                if not re.fullmatch(r"(\d{4}-\d{2}-\d{2})+", date_text):
                    continue

                dates = re.findall(r"\d{4}-\d{2}-\d{2}", date_text)
                R = len(dates)
                if R == 0:
                    continue

                row_values = {"date": dates}
                row_ok = True
                for key in ["price", "refund", "ship_paid_by_buyer"]:
                    ci = col_idx.get(key)
                    if ci is None or ci >= len(last_row) or not last_row[ci]:
                        row_values[key] = [None] * R
                        warnings.append(f"หน้า {page_num}: ไม่พบคอลัมน์ '{key}'")
                        row_ok = False
                        continue

                    frags = last_row[ci].split("\n")
                    M = len(frags)
                    if M == R:
                        vals = frags
                    elif M % R == 0:
                        g = M // R
                        vals = ["".join(frags[i * g:(i + 1) * g]) for i in range(R)]
                    else:
                        warnings.append(
                            f"หน้า {page_num}: จำนวนชิ้นข้อมูลคอลัมน์ '{key}' ไม่ลงตัวกับจำนวนวันที่ "
                            f"(พบ {M} ชิ้น กับ {R} วัน) — ข้ามค่าคอลัมน์นี้ในหน้านี้ กรุณาตรวจสอบด้วยตนเอง"
                        )
                        vals = [None] * R
                        row_ok = False
                    row_values[key] = [parse_num(v) for v in vals]

                for i in range(R):
                    data.append({
                        "วันที่โอนเงิน": row_values["date"][i],
                        "ราคาสินค้า": row_values["price"][i],
                        "ยอดคืนเงิน": row_values["refund"][i],
                        "เงินสนับสนุน": row_values["ship_paid_by_buyer"][i],
                    })

    df = pd.DataFrame(data)

    # ตรวจสอบผลรวมกับยอดสรุปในตัวรายงานเอง เพื่อความปลอดภัย (ไม่ให้ข้อมูลผิดเงียบๆ)
    if not df.empty and summary_totals:
        check_map = {
            "price": "ราคาสินค้า",
            "refund": "ยอดคืนเงิน",
            "ship_paid_by_buyer": "เงินสนับสนุน",
        }
        for key, col in check_map.items():
            expected = summary_totals.get(key)
            if expected is None or col not in df:
                continue
            actual = df[col].sum(skipna=True)
            if abs(actual - expected) > 1:  # ยอมรับความคลาดเคลื่อนจากการปัดเศษเล็กน้อย
                warnings.append(
                    f"ผลรวมคอลัมน์ '{col}' = {actual:,.0f} แต่ยอดสรุปในรายงานระบุ {expected:,.0f} "
                    f"(ต่างกัน {actual - expected:,.0f}) — กรุณาตรวจสอบข้อมูลก่อนใช้งาน"
                )

    return df, warnings


def get_lazada_data(file):
    """
    ดึงข้อมูลรายวันจากรายงานการเงิน Lazada (PDF)

    ไฟล์ Lazada ไม่มีปัญหาข้อความตัดขึ้นบรรทัดใหม่กลางคำแบบ Shopee — แต่ละแถวข้อมูล
    เป็น 1 บรรทัดสมบูรณ์ในรูปแบบ "วันที่ ยอดรายการขาย ค่าธรรมเนียมฯ ... จำนวนเงิน"
    จึงอ่านด้วย extract_text() ทีละบรรทัดแล้วจับด้วย regex ได้โดยตรง โดยดึงเฉพาะ
    วันที่ และ "ยอดรายการขาย" (ตัวเลขค่าแรกหลังวันที่) ตามที่ต้องการ

    คืนค่า (DataFrame, list ของข้อความเตือน)
    """
    rows = []
    warnings = []
    expected_total = None

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = fix_thai(page.extract_text() or "")

            # ดึงยอดรวม "ยอดรายการขาย" จากแถวท้ายตาราง (รวมจำนวนเงิน ...) ไว้ตรวจสอบ
            m = re.search(r"รวมจำนวนเงิน\s+([\d,]+\.\d{2})", text)
            if m:
                expected_total = parse_num(m.group(1))

            for line in text.split("\n"):
                line = line.strip()
                m = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$", line)
                if not m:
                    continue
                date_str, rest = m.groups()
                nums = re.findall(r"-?[\d,]+\.\d{2}", rest)
                if not nums:
                    continue
                # แปลงวันที่ dd/mm/yyyy (พ.ศ. ปฏิทินสากลตามที่ระบุในรายงาน) เป็น yyyy-mm-dd
                d, mth, y = date_str.split("/")
                iso_date = f"{y}-{mth}-{d}"
                rows.append({
                    "วันที่ทำรายการ": iso_date,
                    "ยอดรายการขาย": parse_num(nums[0]),
                })

    df = pd.DataFrame(rows)

    if not df.empty and expected_total is not None:
        actual = df["ยอดรายการขาย"].sum(skipna=True)
        if abs(actual - expected_total) > 1:
            warnings.append(
                f"ผลรวมคอลัมน์ 'ยอดรายการขาย' = {actual:,.2f} แต่ยอดสรุปในรายงานระบุ "
                f"{expected_total:,.2f} (ต่างกัน {actual - expected_total:,.2f}) — กรุณาตรวจสอบข้อมูลก่อนใช้งาน"
            )

    return df, warnings


def get_expense_shopee_data(file, source_type):
    """
    ดึงข้อมูลค่าใช้จ่ายจากไฟล์ PDF (Shopee หรือ Lazada)
    source_type: "shopee" หรือ "lazada"
    """
    data_list = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            reader = pypdf.PdfReader(pdf_path)
total_pages = len(reader.pages)
print(f"Total pages: {total_pages}")

# สร้าง List สำหรับเก็บข้อมูลแต่ละแถวเพื่อทำเป็นตาราง
data_list = []

for idx, page in enumerate(reader.pages):
    text = page.extract_text()
    if not text:
        continue
        
    lines = [line.strip() for line in text.split('\n') if line.strip()]
   
    # แยกประเภทเอกสารจากการเช็ค Keyword ในหน้า
    shopee = "Shopee" in text or "Receipt/Tax Invoice" in text
    spx = "SPX Express" in text or ("Receipt" in text and not shopee)
   
    total_amount = "Unknown"
    doc_no = "Unknown"
    doc_date = "Unknown"
   
    # --- 1. สกัดเลขที่เอกสาร (2 บรรทัด) และวันที่ ---
    for i, line in enumerate(lines):
        # หาบรรทัดที่เป็นเลขที่เอกสารหลัก (ต้องมีตัวพิมพ์ใหญ่ยาว ๆ เช่น TRSPEMKP หรือ RCSPXSPW)
        if ("เลขที่" in line or "No." in line) and re.search(r"[A-Z]{3,}", line):
            top_match = re.search(r"([A-Z0-9\-]{10,})", line)
            if top_match:
                top_no = top_match.group(1)
                bottom_no = ""
                
                # ส่องบรรทัดถัดไปทันทีเพื่อเอาเลขชุดล่าง
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    bottom_match = re.search(r"([0-9]{4,}\-[0-9]{4,})", next_line)
                    if not bottom_match:
                        bottom_match = re.search(r"([0-9\-]{6,15})", next_line)
                        
                    if bottom_match:
                        bottom_no = bottom_match.group(1)
                
                if bottom_no:
                    doc_no = f"{top_no} / {bottom_no}"
                else:
                    doc_no = top_no
        
        # ดึงวันที่ (Date) จากบรรทัด "วันที่/ Date" ในตารางฝั่งขวา
        if "วันที่" in line or "Date" in line:
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
            if date_match:
                doc_date = date_match.group(1)

    # --- 2. สกัดจำนวนเงินรวม (Total Amount) ---
    shopee_match = re.search(r"Included VAT\)?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if not shopee_match:
        shopee_match = re.search(r"Total Value of Services \(Included VAT\)\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
   
    spx_match = re.search(r"Total amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if not spx_match:
        spx_match = re.search(r"จำนวนเงินรวม/\s*Total\s*amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
   
    if shopee:
        company_name = "Shopee"
        doc_type = "Tax Invoice"
        if shopee_match:
            total_amount = shopee_match.group(1)
    elif spx:
        company_name = "SPX Express"
        doc_type = "Shipping Fee"
        if spx_match:
            total_amount = spx_match.group(1)
    else:
        company_name = "Unknown"
        doc_type = "Unknown Type"
        total_match = re.search(r"(?:Total|รวม)\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        if total_match:
            total_amount = total_match.group(1)

    # แปลงยอดเงินให้เป็น float เพื่อให้ Excel นำไปกดบวก ลบ คูณ หาร หรือใช้สูตร SUM ต่อได้เลย
    if total_amount != "Unknown":
        try:
            total_amount = float(total_amount.replace(",", ""))
        except ValueError:
            pass

    # เก็บรวมข้อมูล
    data_list.append({
        "Page": idx + 1,
        "Company": company_name,
        "Document Type": doc_type,
        "Document No.": doc_no,
        "Date": doc_date,
        "Total Amount": total_amount
    })
    print(f"Processed Page {idx+1}/{total_pages} | No: {doc_no} | Amount: {total_amount}")

# --- 3. แปลงเป็น DataFrame และสร้างไฟล์ Excel ---
print("\nกำลังสร้างและจัดฟอร์แมตตารางลง Excel...")
df = pd.DataFrame(data_list)

with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer_excel:
    df.to_excel(writer_excel, index=False, sheet_name='Shopee_SPX Data')
    
    # ขยายความกว้างของคอลัมน์อัตโนมัติเปิดมาจะได้อ่านง่าย ไม่ขึ้น ###
    worksheet = writer_excel.sheets['Shopee_SPX Data']
    for col in worksheet.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = col[0].column_letter
        worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)


def get_expense_Lazada_data(file, source_type):
    reader = pypdf.PdfReader(pdf_path)
total_pages = len(reader.pages)
print(f"Total pages: {total_pages}")

# สร้าง List สำหรับเก็บข้อมูลแต่ละแถวเพื่อทำเป็นตาราง
data_list = []

for idx, page in enumerate(reader.pages):
    text = page.extract_text()
    if not text:
        continue
        
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    company_name = "Lazada"
    doc_type = "Unknown Type"
    doc_no = "Unknown"
    doc_date = "Unknown"
    total_amount = "Unknown"

    # --- 1. เช็คชื่อบริษัท และ ประเภทเอกสาร ---
    if "Lazada Express" in text or "ลาซาด้า เอ็กซ์เพรส" in text:
        company_name = "Lazada Express"
        
    if "CREDIT NOTE" in text:
        doc_type = "Credit Note"
    elif "Shipping Fee Receipt" in text:
        doc_type = "Shipping Fee"
    elif "TAX INVOICE" in text:
        doc_type = "Tax Invoice"

    # --- 2. วิ่งเจาะหา No., Date และ ยอดเงินรวม ---
    for i, line in enumerate(lines):
        # หาเลขที่เอกสาร
        if "Credit Note:" in line:
            no_match = re.search(r"Credit Note:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
            if no_match:
                doc_no = no_match.group(1)
        elif "Invoice No.:" in line:
            no_match = re.search(r"Invoice No\.:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
            if no_match:
                doc_no = no_match.group(1)

        # หาวันที่เอกสาร
        if "Invoice Date:" in line:
            date_match = re.search(r"Invoice Date:\s*([\d\-]+)", line, re.IGNORECASE)
            if date_match:
                doc_date = date_match.group(1)
        elif "Date:" in line and "Digitally" not in line:
            date_match = re.search(r"Date:\s*([\d\-]+)", line, re.IGNORECASE)
            if date_match:
                doc_date = date_match.group(1)

        # หาจำนวนเงินรวม (ดึงยอดที่มีทศนิยมจากบรรทัดสรุปของตาราง)
        if "Total (Including Tax)" in line:
            amt_match = re.search(r"([\d,]+\.\d{2})", line)
            if amt_match:
                total_amount = amt_match.group(1)
        elif "Net Total Shipping Fee" in line:
            amt_match = re.search(r"([\d,]+\.\d{2})", line)
            if amt_match:
                total_amount = amt_match.group(1)

    # ตัวช่วยสำรองขุดหายอดเงิน: ถ้าหาตามคำสำคัญข้างบนไม่เจอจริงๆ ให้เอาตัวเลขทศนิยมตัวสุดท้ายในตารางมา
    if total_amount == "Unknown":
        all_amounts = []
        for line in lines:
            amt_match = re.findall(r"([\d,]+\.\d{2})", line)
            if amt_match:
                if "7%" not in line and "3%" not in line and "1%" not in line:
                    all_amounts.extend(amt_match)
        if all_amounts:
            total_amount = all_amounts[-1]

    # แปลงยอดเงินให้เป็นตัวเลขประเภท float สำหรับนำไปคำนวณต่อใน Excel ได้ทันที (ลบคอมมาออก)
    if total_amount != "Unknown":
        try:
            total_amount = float(total_amount.replace(",", ""))
        except ValueError:
            pass

    # เพิ่มข้อมูลเข้าไปในรูปแบบ Dictionary
    data_list.append({
        "Page": idx + 1,
        "Company": company_name,
        "Document Type": doc_type,
        "Document No.": doc_no,
        "Date": doc_date,
        "Total Amount": total_amount
    })

    print(f"Processed Page {idx+1}/{total_pages}")

# --- 3. แปลงเป็น DataFrame และส่งออกไฟล์ Excel ---
print("\nกำลังแปลงข้อมูลและจัดรูปแบบลง Excel...")
df = pd.DataFrame(data_list)

# ใช้ ExcelWriter เพื่อเปิดใช้งานตัวจัดฟอร์แมตอัตโนมัติ
with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer_excel:
    df.to_excel(writer_excel, index=False, sheet_name='Lazada Data')
    
    # ดึงเอกสารชีตมาขยายความกว้างคอลัมน์อัตโนมัติ จะได้ไม่ขึ้นหน้าต่างข้อความแคบเกินไป
    workbook = writer_excel.book
    worksheet = writer_excel.sheets['Lazada Data']
    for col in worksheet.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = col[0].column_letter
        worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)



# ---------------------------------------------------------------------------
# หน้าตาเว็บ
# ---------------------------------------------------------------------------
st.title("📊 โปรแกรมสรุปรายได้")

tab_shopee, tab_lazada = st.tabs(["Shopee", "Lazada"])

with tab_shopee:
    st.write("อัปโหลดไฟล์ PDF รายงาน Shopee เพื่อคำนวณยอดสุทธิ")

    uploaded_file = st.file_uploader("เลือกไฟล์ PDF ของ Shopee", type=["pdf"], key="shopee_uploader")

    if uploaded_file is not None:
        with st.spinner("กำลังอ่านไฟล์..."):
            df, warnings = get_shopee_data(uploaded_file)

        if df.empty:
            st.error(
                "ไม่สามารถดึงข้อมูลจากไฟล์นี้ได้ กรุณาตรวจสอบว่าเป็นไฟล์รายงานการเงิน Shopee "
                "ที่มีตาราง 'รายละเอียดการโอนเงิน' หรือไม่"
            )
        else:
            # คำนวณสูตรใน DataFrame
            df["ยอดสุทธิ"] = (df["ราคาสินค้า"] - df["ยอดคืนเงิน"].abs()) + df["เงินสนับสนุน"]

            for w in warnings:
                st.warning(w)

            if not warnings:
                st.success(f"ดึงข้อมูลสำเร็จ {len(df)} แถว และผลรวมตรงกับยอดสรุปในรายงาน ✅")

            st.write("ตัวอย่างข้อมูลที่ดึงได้:")
            st.dataframe(df)

            # ปุ่มดาวน์โหลด Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Shopee")

            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ Excel",
                data=output.getvalue(),
                file_name="สรุปรายได้_Shopee.xlsx",
                mime="application/vnd.ms-excel",
                key="shopee_download",
            )

with tab_lazada:
    st.write("อัปโหลดไฟล์ PDF รายงาน Lazada เพื่อดึงวันที่และยอดรายการขาย")

    uploaded_file_lzd = st.file_uploader("เลือกไฟล์ PDF ของ Lazada", type=["pdf"], key="lazada_uploader")

    if uploaded_file_lzd is not None:
        with st.spinner("กำลังอ่านไฟล์..."):
            df_lzd, warnings_lzd = get_lazada_data(uploaded_file_lzd)

        if df_lzd.empty:
            st.error(
                "ไม่สามารถดึงข้อมูลจากไฟล์นี้ได้ กรุณาตรวจสอบว่าเป็นไฟล์รายงานการเงิน Lazada "
                "ที่มีตาราง 'รายละเอียดธุรกรรม' หรือไม่"
            )
        else:
            for w in warnings_lzd:
                st.warning(w)

            if not warnings_lzd:
                st.success(f"ดึงข้อมูลสำเร็จ {len(df_lzd)} แถว และผลรวมตรงกับยอดสรุปในรายงาน ✅")

            st.write("ตัวอย่างข้อมูลที่ดึงได้:")
            st.dataframe(df_lzd)

            output_lzd = io.BytesIO()
            with pd.ExcelWriter(output_lzd, engine="xlsxwriter") as writer:
                df_lzd.to_excel(writer, index=False, sheet_name="Lazada")

            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ Excel",
                data=output_lzd.getvalue(),
                file_name="สรุปรายได้_Lazada.xlsx",
                mime="application/vnd.ms-excel",
                key="lazada_download",
            )
