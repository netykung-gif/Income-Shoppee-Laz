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


# ---------------------------------------------------------------------------
# หน้าตาเว็บ
# ---------------------------------------------------------------------------
st.title("📊 โปรแกรมสรุปรายได้ Shopee")
st.write("อัปโหลดไฟล์ PDF รายงาน Shopee เพื่อคำนวณยอดสุทธิ")

uploaded_file = st.file_uploader("เลือกไฟล์ PDF ของ Shopee", type=["pdf"])

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
        )
