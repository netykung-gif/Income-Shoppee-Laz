import streamlit as st
import pandas as pd
import pypdf
import re
import io

st.set_page_config(layout="wide", page_title="Shopee Report Processor")
st.title("📊 โปรแกรมสรุปรายได้ Shopee (ฉบับรองรับทุกเดือน)")

def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    data = []
    
    for page in reader.pages:
        text = page.extract_text()
        lines = text.split('\n')
        
        for line in lines:
            # หาบรรทัดที่มีวันที่ YYYY-MM-DD
            match = re.search(r'\d{4}-\d{2}-\d{2}', line)
            if match:
                date = match.group()
                # แทนที่วันที่ในบรรทัดนั้นด้วยช่องว่าง เพื่อไม่ให้มันนับเลขปีเป็นตัวเลขเงิน
                cleaned_line = line.replace(date, " ")
                
                # ดึงตัวเลขที่เหลือในบรรทัด (คราวนี้จะไม่โดนเลขปีหลอกแล้ว)
                numbers = re.findall(r'(-?[\d,]+\.?\d*)', cleaned_line)
                
                # กรองเอาเฉพาะตัวเลขที่มีค่าจริงๆ (ไม่เอาตัวเลขหลักเดียวที่เป็นเลขหน้า/เลขย่อ)
                valid_numbers = [float(n.replace(',', '')) for n in numbers if len(n.replace(',', '').replace('.', '')) > 2]
                
                if len(valid_numbers) >= 3:
                    data.append({
                        "วันที่": date,
                        "ราคาสินค้า": valid_numbers[0],
                        "ยอดคืนเงิน": valid_numbers[1],
                        "เงินสนับสนุน": valid_numbers[2]
                    })
    return pd.DataFrame(data)

# --- UI ส่วนแสดงผล ---
uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF รายงาน Shopee", type=["pdf"])

if uploaded_file is not None:
    df = get_shopee_data(uploaded_file)
    
    if not df.empty:
        # บังคับตั้งชื่อคอลัมน์ให้แน่นอนก่อนคำนวณ
        df.columns = ["วันที่", "ราคาสินค้า", "ยอดคืนเงิน", "เงินสนับสนุน"]
        
        # คำนวณสูตร
        df["ยอดสุทธิ"] = (df["ราคาสินค้า"] - df["ยอดคืนเงิน"].abs()) + df["เงินสนับสนุน"]
        
        st.success(f"พบข้อมูลทั้งหมด {len(df)} รายการ")
        st.dataframe(df, use_container_width=True)
        
        # ปุ่มดาวน์โหลด
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        
        st.download_button("📥 ดาวน์โหลด Excel", output.getvalue(), "Shopee_Report_Final.xlsx", "application/vnd.ms-excel")
    else:
        st.error("ไม่พบข้อมูลที่ตรงเงื่อนไข กรุณาตรวจสอบไฟล์ PDF")
