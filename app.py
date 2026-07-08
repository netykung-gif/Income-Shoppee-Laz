import streamlit as st
import pandas as pd
import pypdf
import re
import io

# ฟังก์ชันดึงข้อมูล Shopee
def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    data = []
    for page in reader.pages:
        text = page.extract_text()
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)
        chunks = re.split(r'\d{4}-\d{2}-\d{2}', text)[1:]
        
        for date, chunk in zip(dates, chunks):
            # แยกบรรทัดและลบค่าว่างออก
            tokens = [t.strip().replace('−', '-') for t in chunk.split('\n') if t.strip()]
            
            # [จุดสำคัญ] เราจะดึงมาแค่ 4 ตัวแรกเท่านั้น ไม่ว่าบรรทัดนั้นจะมีข้อมูลกี่คอลัมน์ก็ตาม
            if len(tokens) >= 4:
                try:
                    # ใช้แค่ tokens[0] ถึง tokens[3] ตามลำดับ
                    col1 = date
                    col2 = float((tokens[0] + tokens[1]).replace(',', '')) # บางทีเลขหลักพันถูกแยกบรรทัด
                    col3 = float(tokens[2].replace(',', ''))
                    col4 = float(tokens[3].replace(',', ''))
                    
                    data.append({
                        "วันที่": col1,
                        "ราคาสินค้า": col2,
                        "ยอดคืนเงิน": col3,
                        "เงินสนับสนุน": col4
                    })
                except: continue
    
    return pd.DataFrame(data)

# หน้าตาเว็บ
st.title("📊 โปรแกรมสรุปรายได้ Shopee")
st.write("อัปโหลดไฟล์ PDF รายงาน Shopee เพื่อคำนวณยอดสุทธิ")

uploaded_file = st.file_uploader("เลือกไฟล์ PDF ของ Shopee", type=["pdf"])

if uploaded_file is not None:
    df = get_shopee_data(uploaded_file)
    
    # คำนวณสูตรใน DataFrame
    # แก้บรรทัดคำนวณสูตรเป็นแบบนี้ครับ:
    df["ยอดสุทธิ"] = (df.iloc[:, 1] - df.iloc[:, 2].abs()) + df.iloc[:, 3]
    
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df)
    
    # ปุ่มดาวน์โหลด Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Shopee')
    
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel",
        data=output.getvalue(),
        file_name="สรุปรายได้_Shopee.xlsx",
        mime="application/vnd.ms-excel"
    )
