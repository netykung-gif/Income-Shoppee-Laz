import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

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


def _assign_column(x0, x1, col_bounds):
    """หา index คอลัมน์จากตำแหน่ง x ของคำ โดยเทียบจุดกึ่งกลางคำกับขอบเขตคอลัมน์"""
    xc = (x0 + x1) / 2
    for i, (cx0, cx1) in enumerate(col_bounds):
        if cx0 <= xc < cx1:
            return i
    return None


def _extract_rows_from_table(page, table):
    """
    สร้างแถวข้อมูลจริงจากตาราง โดยอ่านตำแหน่ง x,y ของคำแต่ละคำบนหน้ากระดาษ
    (ไม่ใช่แค่ข้อความที่ pdfplumber รวมมาให้) เพราะบางค่าตัดขึ้นบรรทัดใหม่กลางคำ
    (เช่น "14,052" กลายเป็น "14," + "052") แต่บางแถวในหน้าเดียวกันไม่ตัด
    (เช่น "1,484" พอดีไม่ต้องตัด) การนับจำนวนชิ้นแล้วหารเฉลี่ยจึงใช้ไม่ได้เสมอไป
    ต้องอิงตำแหน่งจริงว่าแต่ละคำอยู่ "แถวไหน" (โดยดูว่าคอลัมน์วันที่ขึ้นต้นด้วย
    ปี-เดือนหรือไม่ = แถวใหม่) และ "คอลัมน์ไหน" (จากตำแหน่ง x เทียบกับขอบเขตคอลัมน์)

    คืนค่า: (list ของ dict {col_index: ข้อความเต็มของคอลัมน์นั้นในแถวนี้}, คำเตือน)
    """
    warnings = []
    header_row = table.rows[0] if table.rows else None
    # หาแถวที่มีเส้นแบ่งคอลัมน์จริง (แถวหัวตาราง หรือแถวข้อมูล ใช้ขอบเขตเดียวกันทั้งตาราง)
    col_bounds = None
    for row in table.rows:
        if row.cells and all(c is not None for c in row.cells) and len(row.cells) >= 8:
            col_bounds = [(c[0], c[2]) for c in row.cells]
            break
    if not col_bounds:
        return [], warnings

    top = table.bbox[1]
    bottom = table.bbox[3]
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    words = [w for w in words if top - 1 <= w["top"] <= bottom + 1]
    words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))

    # จัดกลุ่มคำเป็น "บรรทัดจริง" ตามตำแหน่งแนวตั้ง (top ใกล้กันถือว่าเป็นบรรทัดเดียวกัน)
    lines = []
    current_line = []
    current_top = None
    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= 2.5:
            current_line.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(current_line)
            current_line = [w]
            current_top = w["top"]
    if current_line:
        lines.append(current_line)

    NUMERIC_OK = re.compile(r"^[0-9,.\-\u2212]+$")

    rows = []
    pending = None  # dict {col_index: text} กำลังสร้างแถวปัจจุบัน

    for line in lines:
        line_cols = {}
        for w in line:
            ci = _assign_column(w["x0"], w["x1"], col_bounds)
            if ci is None:
                continue
            line_cols[ci] = line_cols.get(ci, "") + w["text"]

        date_frag = fix_thai(line_cols.get(0, ""))
        is_new_row = bool(re.match(r"^\d{4}-\d{2}", date_frag))

        if is_new_row:
            if pending is not None:
                rows.append(pending)
            pending = dict(line_cols)
            continue

        # ไม่ใช่จุดเริ่มแถวใหม่ -> เป็นได้แค่ (ก) ส่วนต่อของตัวเลข/วันที่ที่ตัดบรรทัด
        # หรือ (ข) บรรทัดอื่นที่ไม่ใช่ข้อมูล (หัวข้อ/ยอดรวม) ซึ่งมีตัวอักษรปน
        all_numeric = all(NUMERIC_OK.match(fix_thai(v)) for v in line_cols.values() if v)
        if all_numeric and pending is not None:
            for ci, text in line_cols.items():
                pending[ci] = pending.get(ci, "") + text
        else:
            # แถวหัวข้อ/ยอดรวม -> ปิดแถวที่ค้างอยู่ (ถ้ามี) แล้วข้ามบรรทัดนี้ไป
            if pending is not None:
                rows.append(pending)
                pending = None

    if pending is not None:
        rows.append(pending)

    return rows, warnings


def get_shopee_data(file):
    """
    ดึงข้อมูลรายวันจากรายงานการเงิน Shopee (PDF)

    ใช้ pdfplumber อ่านทั้งโครงสร้างตาราง (เส้นตาราง กำหนดขอบเขตคอลัมน์) และตำแหน่ง
    x,y ของคำแต่ละคำบนหน้ากระดาษ (ไม่ใช่แค่นับจำนวนบรรทัดแล้วหารเฉลี่ย) เพราะ:
      1) ตัวเลข/วันที่บางค่าถูกตัดขึ้นบรรทัดใหม่กลางคำเมื่อคอลัมน์แคบ
      2) การตัดบรรทัดไม่ได้เกิดสม่ำเสมอทุกแถวในหน้าเดียวกันเสมอไป (บางแถวตัด บางแถวไม่ตัด)
         จึงต้องอิงตำแหน่งจริงของคำแต่ละคำ ไม่ใช่การเดาสัดส่วน
      3) จำนวนคอลัมน์ในรายงานแต่ละเดือน/ร้านไม่เท่ากันเสมอไป จึงหาคอลัมน์ที่ต้องการ
         จากชื่อหัวตาราง ไม่ใช่ตำแหน่งคงที่

    คืนค่า (DataFrame, list ของข้อความเตือน)
    """
    data = []
    warnings = []
    col_idx = None
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
                if not table_data or len(table_data[0] if table_data else []) < 8:
                    continue

                # หาแถวหัวตาราง (มีคำว่า "ราคาสินค้า" และ "คืนให้ผู้ซื้อ") เพื่อระบุคอลัมน์ที่ต้องการ
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

                if not col_idx:
                    continue

                row_dicts, w2 = _extract_rows_from_table(page, t)
                warnings.extend(f"หน้า {page_num}: {w}" for w in w2)

                for row_cols in row_dicts:
                    date_text = fix_thai(row_cols.get(0, "")).replace(" ", "")
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
                        continue  # ไม่ใช่แถวข้อมูลจริง (เช่นแถวยอดรวม) ข้ามไป
                    entry = {"วันที่โอนเงิน": date_text}
                    for key, out_col in [
                        ("price", "ราคาสินค้า"),
                        ("refund", "ยอดคืนเงิน"),
                        ("ship_paid_by_buyer", "เงินสนับสนุน"),
                    ]:
                        ci = col_idx.get(key)
                        val = row_cols.get(ci) if ci is not None else None
                        if val is None or val == "":
                            warnings.append(
                                f"หน้า {page_num}: แถว {date_text} ไม่พบค่าคอลัมน์ '{key}'"
                            )
                        entry[out_col] = parse_num(val)
                    data.append(entry)

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


def get_lazada_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษี/Credit Note ค่าใช้จ่ายของ Lazada (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) ดัดแปลงจากสคริปต์ 'Lazada Expenses PDF File read.py' เดิม
    ให้ทำงานกับไฟล์ที่อัปโหลดผ่านเว็บได้ (จากเดิมที่อ่านจากพาธไฟล์ในเครื่อง)

    คืนค่า DataFrame คอลัมน์: Page, Company, Document Type, Document No., Date, Total Amount
    """
    data_list = []
    for file in files:
        with pdfplumber.open(file) as pdf:
            for idx, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                company_name = "Lazada"
                doc_type = "Unknown Type"
                doc_no = "Unknown"
                doc_date = "Unknown"
                total_amount = "Unknown"

                if "Lazada Express" in text or "ลาซาด้า เอ็กซ์เพรส" in text:
                    company_name = "Lazada Express"

                if "CREDIT NOTE" in text:
                    doc_type = "Credit Note"
                elif "Shipping Fee Receipt" in text:
                    doc_type = "Shipping Fee"
                elif "TAX INVOICE" in text:
                    doc_type = "Tax Invoice"

                for line in lines:
                    if "Credit Note:" in line:
                        m = re.search(r"Credit Note:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
                        if m:
                            doc_no = m.group(1)
                    elif "Invoice No.:" in line:
                        m = re.search(r"Invoice No\.:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
                        if m:
                            doc_no = m.group(1)

                    if "Invoice Date:" in line:
                        m = re.search(r"Invoice Date:\s*([\d\-]+)", line, re.IGNORECASE)
                        if m:
                            doc_date = m.group(1)
                    elif "Date:" in line and "Digitally" not in line:
                        m = re.search(r"Date:\s*([\d\-]+)", line, re.IGNORECASE)
                        if m:
                            doc_date = m.group(1)

                    if "Total (Including Tax)" in line:
                        m = re.search(r"([\d,]+\.\d{2})", line)
                        if m:
                            total_amount = m.group(1)
                    elif "Net Total Shipping Fee" in line:
                        m = re.search(r"([\d,]+\.\d{2})", line)
                        if m:
                            total_amount = m.group(1)

                if total_amount == "Unknown":
                    all_amounts = []
                    for line in lines:
                        found = re.findall(r"([\d,]+\.\d{2})", line)
                        if found and "7%" not in line and "3%" not in line and "1%" not in line:
                            all_amounts.extend(found)
                    if all_amounts:
                        total_amount = all_amounts[-1]

                total_amount = parse_num(total_amount) if total_amount != "Unknown" else None

                data_list.append({
                    "ไฟล์": getattr(file, "name", ""),
                    "Page": idx + 1,
                    "Company": company_name,
                    "Document Type": doc_type,
                    "Document No.": doc_no,
                    "Date": doc_date,
                    "Total Amount": total_amount,
                })

    return pd.DataFrame(data_list)


def get_shopee_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายของ Shopee/SPX Express (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) ดัดแปลงจากสคริปต์ 'Shoppee Expenses PDF File read.py' เดิม
    ให้ทำงานกับไฟล์ที่อัปโหลดผ่านเว็บได้ (จากเดิมที่อ่านจากพาธไฟล์ในเครื่อง)

    คืนค่า DataFrame คอลัมน์: Page, Company, Document Type, Document No., Date, Total Amount
    """
    data_list = []
    for file in files:
        with pdfplumber.open(file) as pdf:
            for idx, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                shopee = "Shopee" in text or "Receipt/Tax Invoice" in text
                spx = "SPX Express" in text or ("Receipt" in text and not shopee)

                total_amount = "Unknown"
                doc_no = "Unknown"
                doc_date = "Unknown"

                for i, line in enumerate(lines):
                    if ("เลขที่" in line or "No." in line) and re.search(r"[A-Z]{3,}", line):
                        top_match = re.search(r"([A-Z0-9\-]{10,})", line)
                        if top_match:
                            top_no = top_match.group(1)
                            bottom_no = ""
                            if i + 1 < len(lines):
                                next_line = lines[i + 1]
                                bottom_match = re.search(r"([0-9]{4,}\-[0-9]{4,})", next_line)
                                if not bottom_match:
                                    bottom_match = re.search(r"([0-9\-]{6,15})", next_line)
                                if bottom_match:
                                    bottom_no = bottom_match.group(1)
                            doc_no = f"{top_no} / {bottom_no}" if bottom_no else top_no

                    if "วันที่" in line or "Date" in line:
                        m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                        if m:
                            doc_date = m.group(1)

                shopee_match = re.search(r"Included VAT\)?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
                if not shopee_match:
                    shopee_match = re.search(
                        r"Total Value of Services \(Included VAT\)\s*([\d,]+\.\d{2})", text, re.IGNORECASE
                    )

                spx_match = re.search(r"Total amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
                if not spx_match:
                    spx_match = re.search(
                        r"จำนวนเงินรวม/\s*Total\s*amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE
                    )

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

                total_amount = parse_num(total_amount) if total_amount != "Unknown" else None

                data_list.append({
                    "ไฟล์": getattr(file, "name", ""),
                    "Page": idx + 1,
                    "Company": company_name,
                    "Document Type": doc_type,
                    "Document No.": doc_no,
                    "Date": doc_date,
                    "Total Amount": total_amount,
                })

    return pd.DataFrame(data_list)


def get_tiktok_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายฝั่ง TikTok Shop (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) เอกสารมีหลายรูปแบบย่อย เช่น ค่าขนส่ง (Thai Happy Logistics),
    ค่าธรรมเนียม Affiliate (TikTok Pte. Ltd.), ค่าคอมมิชชั่นครีเอเตอร์ (Creator name)
    จึงต้องดึง "เวนเดอร์" (ชื่อที่อยู่มุมซ้ายบนของเอกสาร) แยกออกมาต่างหาก เพราะแต่ละ
    เอกสารเป็นคนละนิติบุคคล/บุคคลกัน

    คืนค่า DataFrame คอลัมน์: ไฟล์, Page, Company, Vendor, Document Type, Document No., Date, Total Amount
    """
    data_list = []
    for file in files:
        with pdfplumber.open(file) as pdf:
            for idx, page in enumerate(pdf.pages):
                text = fix_thai(page.extract_text() or "")
                if not text:
                    continue

                # --- เวนเดอร์ (ชื่อมุมซ้ายบนของเอกสาร) ---
                vendor = "Unknown"
                m = re.search(r"Creator name:\s*(.+)", text)
                if m:
                    vendor = m.group(1).strip()
                else:
                    m = re.search(r"^(.*(?:Ltd\.|Co\., Ltd\.|Pte\. Ltd\.).*)$", text, re.MULTILINE)
                    if m:
                        vendor = m.group(1).strip()

                # --- ประเภทเอกสาร ---
                if "Creator commission" in text:
                    doc_type = "Creator Commission"
                elif "Logistics fee" in text or "Logistics" in text:
                    doc_type = "Logistics Fee"
                elif "Affiliate Service Fee" in text or "Affiliate commission" in text:
                    doc_type = "Affiliate Service Fee"
                elif "CREDIT NOTE" in text:
                    doc_type = "Credit Note"
                elif "TAX INVOICE" in text or "Tax Invoice" in text:
                    doc_type = "Tax Invoice"
                else:
                    doc_type = "Unknown Type"

                # --- เลขที่เอกสาร (รองรับทั้ง : ปกติ และ ： แบบเต็มความกว้าง, ไม่สนตัวพิมพ์เล็ก-ใหญ่) ---
                m = re.search(
                    r"(?:Receipt number|Invoice number|Receipt Number|Credit note number)\s*[:：]\s*([A-Za-z0-9]+)",
                    text,
                    re.IGNORECASE,
                )
                doc_no = m.group(1) if m else "Unknown"

                # --- วันที่เอกสาร ---
                m = re.search(
                    r"(?:Receipt date|Invoice date|Receipt Date|Credit note date)\s*[:：]\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
                    text,
                    re.IGNORECASE,
                )
                doc_date = m.group(1) if m else "Unknown"

                # --- ยอดเงินรวม (เอกสารบางแบบเขียน "Total amount" ตัว a เล็ก จึงต้องไม่สนตัวพิมพ์เล็ก-ใหญ่) ---
                m = re.search(r"Total Amount\D*?([\d,]+\.\d{2})", text, re.IGNORECASE)
                total_amount = parse_num(m.group(1)) if m else None

                data_list.append({
                    "ไฟล์": getattr(file, "name", ""),
                    "Page": idx + 1,
                    "Company": "TikTok Shop",
                    "Vendor": vendor,
                    "Document Type": doc_type,
                    "Document No.": doc_no,
                    "Date": doc_date,
                    "Total Amount": total_amount,
                })

    return pd.DataFrame(data_list)


# ---------------------------------------------------------------------------
# หน้าตาเว็บ
# ---------------------------------------------------------------------------
st.set_page_config(page_title="สรุปรายได้/ค่าใช้จ่าย", page_icon="📊", layout="wide")
def draw_card(title, icon):
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        if st.button(f"เลือก {title}", key=f"btn_{title}"):
            st.session_state.platform = title.lower()
            st.rerun()

# ส่วนการใช้งาน
cols = st.columns(3)
with cols[0]:
    draw_card("Shopee", "🛍️")
with cols[1]:
    draw_card("Lazada", "❤️")
with cols[2]:
    draw_card("TikTok", "🎵")
# --- 2. Logic การเลือก (วางแทนที่แผงปุ่มเดิม) ---
st.title("📊 สรุปรายได้ / ค่าใช้จ่าย")

# สร้าง Columns เพื่อวาง Card
cols = st.columns(3)

# ดึงค่าปัจจุบันมาเช็ค (ถ้าไม่มีให้เป็น 'shopee')
if "platform" not in st.session_state:
    st.session_state.platform = "shopee"

with cols[0]:
    if st.button("🛍️ Shopee", use_container_width=True):
        st.session_state.platform = "shopee"
        st.rerun()
with cols[1]:
    if st.button("❤️ Lazada", use_container_width=True):
        st.session_state.platform = "lazada"
        st.rerun()
with cols[2]:
    if st.button("🎵 TikTok", use_container_width=True):
        st.session_state.platform = "tiktok"
        st.rerun()

st.divider()

# --- 3. ส่วนแสดงเนื้อหา (อันเดิมของคุณ) ---
current_platform = st.session_state.platform

# 3. ใช้ Tabs แยก รายรับ/รายจ่าย
if platform == "Shopee":
    tab1, tab2 = st.tabs(["💰 รายรับ", "📉 ค่าใช้จ่าย (Shopee/SPX)"])
    with tab1:
        render_shopee_income()
    with tab2:
        render_shopee_expense()

elif platform == "Lazada":
    tab1, tab2 = st.tabs(["💰 รายรับ", "📉 ค่าใช้จ่าย"])
    with tab1:
        render_lazada_income()
    with tab2:
        render_lazada_expense()

elif platform == "TikTok":
    # TikTok มีแค่ค่าใช้จ่ายตามโจทย์เดิม
    render_tiktok_expense()
