import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- Googleスプレッドシートへの接続設定 ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("your-key.json", scope)
client = gspread.authorize(creds)

# スプレッドシート名で開く
spreadsheet = client.open("認定式メッセージ管理")
master_sheet = spreadsheet.worksheet("master")
msg_sheet = spreadsheet.worksheet("messages")

# masterデータを読み込む
master_rows = master_sheet.get_all_values()

# 「A列が対象者、B-E列が先生」の構造を処理しやすい形に変換
master_data = []
all_teachers = set()

for row in master_rows[1:]: # 2行目以降を処理
    if not row or row[0].strip() == "":
        continue
    target = row[0] # A列：対象者名
    
    # B列以降（先生たちの名前）をチェック
    for teacher in row[1:]:
        t_name = teacher.strip()
        if t_name != "":
            all_teachers.add(t_name)
            master_data.append({"先生名": t_name, "対象者": target})

master_df = pd.DataFrame(master_data)

try:
    msg_df = pd.DataFrame(msg_sheet.get_all_records())
except:
    msg_df = pd.DataFrame(columns=["タイムスタンプ", "先生名", "対象者名", "メッセージ"])

# --- 画面の構築 (Streamlit) ---
st.set_page_config(page_title="認定式メッセージ回収", layout="wide")
tab1, tab2 = st.tabs(["✍️ 先生用入力フォーム", "📊 管理者用進捗ダッシュボード"])

# --- タブ1: 先生用画面 ---
with tab1:
    st.title("🎓 認定式メッセージ回収フォーム")
    
    teachers_list = ["-- 選択してください --"] + sorted(list(all_teachers))
    selected_teacher = st.selectbox("あなたの名前を選択してください", teachers_list)
    
    if selected_teacher != "-- 選択してください --":
        # B〜E列のどこかに自分の名前がある対象者を自動抽出
        my_targets = master_df[master_df["先生名"] == selected_teacher]["対象者"].tolist()
        
        if not msg_df.empty:
            submitted_targets = msg_df[msg_df["先生名"] == selected_teacher]["対象者名"].tolist()
        else:
            submitted_targets = []
        
        remaining = len(my_targets) - len(submitted_targets)
        if remaining == 0:
            st.success(f"🎉 {selected_teacher}のメッセージはすべて提出完了しています！ありがとうございます！")
        else:
            st.warning(f"📝 {selected_teacher}の未提出メッセージは【あと {remaining} 件】です。")
            
        st.write("---")
        
        for target in my_targets:
            if not msg_df.empty:
                existing_row = msg_df[(msg_df["先生名"] == selected_teacher) & (msg_df["対象者名"] == target)]
                existing_msg = existing_row["メッセージ"].values[0] if not existing_row.empty else ""
            else:
                existing_msg = ""
            
            status_label = "【🟢 提出済】" if target in submitted_targets else "【🔴 未提出】"
            st.markdown(f"### 🎯 **{target}** さんへのメッセージ {status_label}")
            
            msg = st.text_area(f"{target}さんへのお祝いの言葉", value=existing_msg, key=f"text_{target}", height=150)
            
            if st.button(f"{target}さん分を送信・保存", key=f"btn_{target}"):
                if msg.strip() == "":
                    st.error("メッセージが空欄です。")
                else:
                    if not msg_df.empty and target in submitted_targets:
                        try:
                            # 重複防止のために古いデータを削除
                            cells = msg_sheet.findall(target)
                            for cell in cells:
                                if msg_sheet.cell(cell.row, 2).value == selected_teacher:
                                    msg_sheet.delete_rows(cell.row)
                        except:
                            pass
                    
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg_sheet.append_row([now, selected_teacher, target, msg])
                    st.success(f"✨ {target}さんへのメッセージを保存しました！")
                    st.rerun()
            st.write("---")

# --- タブ2: 管理者用画面 ---
with tab2:
    st.title("📊 リアルタイム提出管理画面")
    
    total_slots = len(master_df)
    total_done = len(msg_df) if not msg_df.empty else 0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("全体の必要メッセージ数", f"{total_slots} 件")
    col2.metric("回収済み", f"{total_done} 件")
    col3.metric("現在の提出率", f"{int(total_done/total_slots*100) if total_slots > 0 else 0} %")
    
    all_pairs = set(zip(master_df["先生名"], master_df["対象者"]))
    done_pairs = set(zip(msg_df["先生名"], msg_df["対象者名"])) if not msg_df.empty else set()
    undone_pairs = all_pairs - done_pairs
    undone_teachers = set([p[0] for p in undone_pairs])
    
    st.subheader("📋 リアルタイムステータス一覧")
    display_rows = []
    for _, row in master_df.iterrows():
        t_name = row["先生名"]
        tg_name = row["対象者"]
        is_done = (t_name, tg_name) in done_pairs
        
        if is_done and not msg_df.empty:
            m_content = msg_df[(msg_df["先生名"] == t_name) & (msg_df["対象者名"] == tg_name)]["メッセージ"].values[0]
        else:
            m_content = "（未入力）"
        
        display_rows.append({
            "記入者（先生）": t_name,
            "お祝い対象者": tg_name,
            "状況": "🟢 提出済" if is_done else "🔴 未提出",
            "メッセージ内容": m_content
        })
    
    if display_rows:
        st.dataframe(pd.DataFrame(display_rows), use_container_width=True)
    
    st.subheader("📲 LINE催促用のテキスト自動生成")
    if undone_teachers:
        t_str = "、".join(undone_teachers)
        remind_text = f"【メッセージ提出のお願い】\n" \
                      f"認定式メッセージが未提出の先生方（{t_str}）は、" \
                      f"お忙しいところ恐縮ですが、下記サイトよりご入力をお願いいたします！"
        st.code(remind_text, language="text")
    else:
        st.success("すべてのメッセージが回収完了しています！")