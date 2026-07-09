import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- ส่วนที่ 1: ฟังก์ชัน Helper (ใช้ได้กับทุกฟังก์ชัน) ---
def parse_num(s):
    try: return float(str(s).replace(",", "").replace("(", "").replace(")", ""))
    except: return 0.0

# --- ส่วนที่ 2: ฟังก์ชันรายได้ (จากโค้ดเดิมของคุณ) ---
def get_shopee_data(file):
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
    # วาง Logic รายได้ Shopee ของคุณที่นี่
    return pd.DataFrame(), []

def get_lazada_data(file):
    # วาง Logic รายได้ Lazada ของคุณที่นี่
    return pd.DataFrame(), []

# --- ส่วนที่ 3: ฟังก์ชันค่าใช้จ่าย (ที่ปรับแก้ให้เข้ากับ Streamlit) ---
def get_shopee_expense_data(file):
    data_list = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            # ใส่ Logic สกัดข้อมูลค่าใช้จ่าย
            data_list.append({"Page": idx+1, "Info": text[:50]}) # ตัวอย่าง
    return pd.DataFrame(data_list)

def get_lazada_expense_data(file):
    rows = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            rows.append({"Page": idx+1, "Info": text[:50]}) # ตัวอย่าง
    return pd.DataFrame(rows)

# --- ส่วนที่ 4: หน้าจอ UI ---
st.title("📊 ระบบสรุปงาน Shopee & Lazada")
tabs = st.tabs(["รายได้ Shopee", "รายได้ Lazada", "ค่าใช้จ่าย Shopee", "ค่าใช้จ่าย Lazada"])

# กำหนดฟังก์ชันและ key ให้แต่ละ tab
config = [
    {"tab": tabs[0], "func": get_shopee_data, "name": "รายได้ Shopee"},
    {"tab": tabs[1], "func": get_lazada_data, "name": "รายได้ Lazada"},
    {"tab": tabs[2], "func": get_shopee_expense_data, "name": "ค่าใช้จ่าย Shopee"},
    {"tab": tabs[3], "func": get_lazada_expense_data, "name": "ค่าใช้จ่าย Lazada"},
]

for item in config:
    with item["tab"]:
        uploaded_file = st.file_uploader(f"อัปโหลดไฟล์ {item['name']}", type=["pdf"], key=item["name"])
        if uploaded_file:
            df = item["func"](uploaded_file)
            if isinstance(df, tuple): df = df[0] # รองรับฟังก์ชันที่มี return 2 ค่า
            st.dataframe(df)
            # ปุ่มดาวน์โหลด
            buf = io.BytesIO()
            df.to_excel(buf, index=False)
            st.download_button(f"โหลด Excel {item['name']}", buf.getvalue(), f"{item['name']}.xlsx")
