import pandas as pd
import streamlit as st
import plotly.express as px
import os
import json
import requests
from io import BytesIO
from datetime import datetime
import time
import copy
from supabase import create_client, Client

# Supabase 配置
SUPABASE_URL = "https://ivhhzckkfofyvmbtbljx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml2aGh6Y2trZm9meXZtYnRibGp4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTg2NjkwMDMsImV4cCI6MjA3NDI0NTAwM30.HGw1yakVBdE5iyz8j8OR_AcViOUA1xFDMVVIqwZhHss"

# 初始化 Supabase 客户端
@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase 初始化失败: {e}")
        return None

# 页面设置
st.set_page_config(
    page_title="口号评选系统",
    page_icon="🏆",
    layout="wide"
)

# 初始化session state - 增强版本
def initialize_session_state():
    """初始化session state，防止数据丢失"""
    if 'votes' not in st.session_state:
        st.session_state.votes = {}
    if 'slogan_df' not in st.session_state:
        st.session_state.slogan_df = None
    if 'voter_id' not in st.session_state:
        st.session_state.voter_id = ""
    if 'voted' not in st.session_state:
        st.session_state.voted = False
    if 'max_votes' not in st.session_state:
        st.session_state.max_votes = 20
    if 'all_votes_data' not in st.session_state:
        st.session_state.all_votes_data = {}
    if 'votes_df' not in st.session_state:
        st.session_state.votes_df = pd.DataFrame()
    if 'last_save_time' not in st.session_state:
        st.session_state.last_save_time = 0
    if 'selections_updated' not in st.session_state:
        st.session_state.selections_updated = False
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'initialized' not in st.session_state:
        st.session_state.initialized = False
    if 'last_voter_id' not in st.session_state:
        st.session_state.last_voter_id = ""
    if 'save_success' not in st.session_state:
        st.session_state.save_success = False
    if 'form_submitted' not in st.session_state:
        st.session_state.form_submitted = False
    if 'supabase' not in st.session_state:
        st.session_state.supabase = init_supabase()
    if 'auto_save_enabled' not in st.session_state:
        st.session_state.auto_save_enabled = True

# 调用初始化
initialize_session_state()

def load_slogan_data_from_github():
    """从GitHub Raw URL加载口号数据"""
    try:
        github_raw_url = "https://raw.githubusercontent.com/cadyjko/slogan/main/slogans.xlsx"
        response = requests.get(github_raw_url)
        response.raise_for_status()
        df = pd.read_excel(BytesIO(response.content))

        if '序号' not in df.columns or '口号' not in df.columns:
            st.error("Excel文件必须包含'序号'和'口号'列")
            return None
        
        # 确保序号列是整数类型
        df['序号'] = df['序号'].astype(int)
        return df
    except Exception as e:
        st.error(f"从GitHub加载数据失败: {e}")
        return None

def load_slogan_data_from_supabase():
    """从Supabase加载口号数据"""
    try:
        if st.session_state.supabase is None:
            st.error("数据库连接失败")
            return None
            
        response = st.session_state.supabase.table('slogans').select('*').execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df = df.rename(columns={'serial_number': '序号', 'slogan_text': '口号'})
            df = df.sort_values('序号')
            return df
        else:
            st.info("Supabase中暂无口号数据，将从GitHub加载")
            return load_slogan_data_from_github()
    except Exception as e:
        st.error(f"从Supabase加载口号数据失败: {e}")
        return load_slogan_data_from_github()

def sync_slogans_to_supabase(df):
    """将口号数据同步到Supabase"""
    try:
        if st.session_state.supabase is None:
            return False
            
        # 清空现有数据
        st.session_state.supabase.table('slogans').delete().neq('id', 0).execute()
        
        # 插入新数据
        slogans_data = []
        for _, row in df.iterrows():
            slogans_data.append({
                'serial_number': int(row['序号']),
                'slogan_text': str(row['口号'])
            })
        
        # 分批插入避免超限
        batch_size = 50
        for i in range(0, len(slogans_data), batch_size):
            batch = slogans_data[i:i + batch_size]
            st.session_state.supabase.table('slogans').insert(batch).execute()
        
        return True
    except Exception as e:
        st.error(f"同步口号数据到Supabase失败: {e}")
        return False

def load_all_votes_data():
    """从Supabase加载所有投票数据"""
    try:
        if st.session_state.supabase is None:
            st.error("数据库连接失败")
            return {}
            
        response = st.session_state.supabase.table('votes').select('*').execute()
        
        votes_data = {}
        for record in response.data:
            voter_id = record['voter_id']
            slogan_id = record['slogan_id']
            voted = record['voted']
            
            if voter_id not in votes_data:
                votes_data[voter_id] = {
                    "votes": [],
                    "voted": voted
                }
            
            votes_data[voter_id]["votes"].append(slogan_id)
        
        return votes_data
    except Exception as e:
        st.error(f"从Supabase加载投票数据失败: {e}")
        return {}

def save_vote_to_supabase(voter_id, slogan_id, voted=False):
    """保存单个投票到Supabase"""
    try:
        if st.session_state.supabase is None:
            return False
            
        # 检查是否已存在
        response = st.session_state.supabase.table('votes')\
            .select('*')\
            .eq('voter_id', voter_id)\
            .eq('slogan_id', slogan_id)\
            .execute()
        
        if response.data:
            # 更新现有记录
            st.session_state.supabase.table('votes')\
                .update({'voted': voted, 'updated_at': datetime.now().isoformat()})\
                .eq('voter_id', voter_id)\
                .eq('slogan_id', slogan_id)\
                .execute()
        else:
            # 插入新记录
            st.session_state.supabase.table('votes').insert({
                'voter_id': voter_id,
                'slogan_id': slogan_id,
                'voted': voted,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).execute()
        
        return True
    except Exception as e:
        st.error(f"保存投票到Supabase失败: {e}")
        return False

def delete_vote_from_supabase(voter_id, slogan_id):
    """从Supabase删除投票"""
    try:
        if st.session_state.supabase is None:
            return False
            
        st.session_state.supabase.table('votes')\
            .delete()\
            .eq('voter_id', voter_id)\
            .eq('slogan_id', slogan_id)\
            .execute()
        
        return True
    except Exception as e:
        st.error(f"从Supabase删除投票失败: {e}")
        return False

def save_voter_status_to_supabase(voter_id, voted):
    """更新投票人状态到Supabase"""
    try:
        if st.session_state.supabase is None:
            return False
            
        # 获取该投票人的所有记录
        response = st.session_state.supabase.table('votes')\
            .select('*')\
            .eq('voter_id', voter_id)\
            .execute()
        
        # 更新所有记录的状态
        for record in response.data:
            st.session_state.supabase.table('votes')\
                .update({'voted': voted, 'updated_at': datetime.now().isoformat()})\
                .eq('voter_id', voter_id)\
                .eq('slogan_id', record['slogan_id'])\
                .execute()
        
        return True
    except Exception as e:
        st.error(f"更新投票人状态失败: {e}")
        return False

def auto_save_votes(voter_id, selected_slogans):
    """自动保存投票选择"""
    try:
        if not st.session_state.auto_save_enabled:
            return True
            
        if st.session_state.supabase is None:
            return False
        
        # 获取当前在数据库中的选择
        response = st.session_state.supabase.table('votes')\
            .select('slogan_id')\
            .eq('voter_id', voter_id)\
            .execute()
        
        current_db_selections = {record['slogan_id'] for record in response.data}
        new_selections = set(selected_slogans)
        
        # 需要添加的
        to_add = new_selections - current_db_selections
        # 需要删除的
        to_remove = current_db_selections - new_selections
        
        # 批量操作
        success = True
        
        # 删除不再选择的
        for slogan_id in to_remove:
            if not delete_vote_from_supabase(voter_id, slogan_id):
                success = False
        
        # 添加新选择的
        for slogan_id in to_add:
            if not save_vote_to_supabase(voter_id, slogan_id, voted=False):
                success = False
        
        return success
    except Exception as e:
        st.error(f"自动保存失败: {e}")
        return False

def update_votes_dataframe():
    """更新投票DataFrame - 从Supabase"""
    try:
        if st.session_state.supabase is None:
            st.session_state.votes_df = pd.DataFrame(columns=["投票人", "口号序号", "投票时间"])
            return
            
        # 只获取已提交的投票
        response = st.session_state.supabase.table('votes')\
            .select('voter_id, slogan_id, created_at')\
            .eq('voted', True)\
            .execute()
        
        votes_data = []
        for record in response.data:
            votes_data.append({
                "投票人": record['voter_id'],
                "口号序号": record['slogan_id'],
                "投票时间": record['created_at']
            })
        
        if votes_data:
            st.session_state.votes_df = pd.DataFrame(votes_data)
        else:
            st.session_state.votes_df = pd.DataFrame(columns=["投票人", "口号序号", "投票时间"])
    except Exception as e:
        st.error(f"更新投票数据框时出错: {e}")

def initialize_data():
    """初始化数据加载"""
    if not st.session_state.data_loaded or st.session_state.slogan_df is None:
        # 加载口号数据
        if st.session_state.slogan_df is None:
            st.session_state.slogan_df = load_slogan_data_from_supabase()
            # 如果Supabase中没有数据，从GitHub加载并同步到Supabase
            if st.session_state.slogan_df is not None and st.session_state.supabase is not None:
                # 检查Supabase中是否有数据
                response = st.session_state.supabase.table('slogans').select('id', count='exact').execute()
                if response.count == 0:
                    sync_slogans_to_supabase(st.session_state.slogan_df)
        
        # 加载投票数据
        loaded_data = load_all_votes_data()
        if loaded_data is not None:
            st.session_state.all_votes_data = loaded_data
            # 同步当前用户的投票状态
            if st.session_state.voter_id in st.session_state.all_votes_data:
                voter_data = st.session_state.all_votes_data[st.session_state.voter_id]
                st.session_state.voted = voter_data.get("voted", False)
            
            update_votes_dataframe()
        
        st.session_state.data_loaded = True

def check_voter_status():
    """检查当前用户的投票状态"""
    if not st.session_state.voter_id:
        return "not_started"
    
    initialize_data()
    
    voter_id = st.session_state.voter_id
    if voter_id in st.session_state.all_votes_data:
        voter_data = st.session_state.all_votes_data[voter_id]
        votes = voter_data.get("votes", [])
        voted = voter_data.get("voted", False)
        
        if voted:
            return "voted"
        elif votes and len(votes) > 0:
            return "editing"
        else:
            return "started_but_not_voted"
    
    return "not_started"

def main():
    st.title("🏆 宣传口号评选系统")

    # 初始化数据
    initialize_data()
    
    # 检查用户状态
    voter_status = check_voter_status()

    # 如果用户已投票，显示结果
    if voter_status == "voted":
        display_voting_result()
        return
        
    # 如果用户正在编辑（已保存选择但未最终提交）
    elif voter_status == "editing":
        st.warning("⚠️ 检测到您有未提交的投票记录，可以继续编辑或最终提交")
        display_voting_interface()
        return
        
    # 如果用户已开始但未投票
    elif voter_status == "started_but_not_voted":
        st.info("请继续完成投票")
        display_voting_interface()
        return

    # 用户标识输入
    if not st.session_state.voter_id:
        display_voter_login()
        return

    # 显示投票界面
    display_voting_interface()
    
def display_voter_login():
    """显示用户登录界面"""
    st.subheader("请输入您的姓名")
    voter_id = st.text_input("姓名", placeholder="请输入您的姓名", key="voter_input")
    
    if st.button("开始投票", key="start_vote"):
        if voter_id and voter_id.strip():
            clean_voter_id = voter_id.strip()
            
            if clean_voter_id in st.session_state.all_votes_data:
                voter_data = st.session_state.all_votes_data[clean_voter_id]
                voted = voter_data.get("voted", False)
                votes_count = len(voter_data.get("votes", []))
                
                if voted:
                    st.warning(f"该姓名已完成最终投票（投了{votes_count}条口号），请使用其他姓名或联系管理员")
                    return
                else:
                    st.session_state.voter_id = clean_voter_id
                    st.session_state.voted = False
                    st.rerun()
            else:
                st.session_state.voter_id = clean_voter_id
                st.session_state.voted = False
                st.session_state.all_votes_data[clean_voter_id] = {
                    "votes": [],
                    "voted": False
                }
                st.rerun()
        else:
            st.error("请输入有效的姓名")

def display_voting_result():
    """显示投票结果"""
    st.success("🎉 您已完成投票，感谢参与！")
    
    voter_id = st.session_state.voter_id
    voter_data = st.session_state.all_votes_data.get(voter_id, {"votes": [], "voted": False})
    current_selection = voter_data.get("votes", [])
    
    if st.session_state.slogan_df is not None and current_selection:
        selected_slogans = st.session_state.slogan_df[st.session_state.slogan_df['序号'].isin(current_selection)]
        
        st.subheader("您的投票结果")
        for _, row in selected_slogans.iterrows():
            st.write(f"**{row['序号']}.** {row['口号']}")
    
    st.info("💫 您的投票已成功提交，无法再次修改。如需帮助请联系管理员。")

def display_voting_interface():
    """显示投票界面 - 自动保存版本"""
    if st.session_state.slogan_df is None:
        st.error("数据加载失败，请刷新页面重试")
        return

    df = st.session_state.slogan_df
    voter_id = st.session_state.voter_id
    
    voter_data = st.session_state.all_votes_data.get(voter_id, {"votes": [], "voted": False})
    current_selection = set(voter_data.get("votes", []))
    current_count = len(current_selection)
    voted = voter_data.get("voted", False)
    max_votes = st.session_state.max_votes

    if voted:
        st.header(f"欢迎 {voter_id}，您已完成投票")
    else:
        st.header(f"欢迎 {voter_id}，请选出最符合南岳衡山全球旅游品牌宣传的口号")
    
    status_col1, status_col2 = st.columns([2, 1])
    with status_col1:
        if voted:
            st.success(f"您已完成投票，选择了 **{current_count}** 条口号")
        else:
            if current_count <= max_votes:
                st.info(f"您最多可以选择 {max_votes} 条口号，当前已选择 **{current_count}** 条")
            else:
                st.error(f"❌ 您已选择 {current_count} 条口号，超过限制 {max_votes} 条！请取消部分选择")
    
    with status_col2:
        if st.button("🔄 刷新数据状态", key="refresh_status"):
            st.session_state.all_votes_data = load_all_votes_data()
            initialize_data()
            st.rerun()

    if voted:
        display_voting_result()
        return

    progress = min(current_count / max_votes, 1.0)
    st.progress(progress, text=f"{current_count}/{max_votes}")

    search_term = st.text_input("搜索口号", placeholder="输入关键词筛选口号", key="search_slogan")

    page_size = 50
    total_pages = (len(df) + page_size - 1) // page_size

    if 'current_page' not in st.session_state:
        st.session_state.current_page = 1

    # 显示已选口号详情
    if current_count > 0:
        selected_slogans = df[df['序号'].isin(current_selection)]
        with st.expander(f"📋 查看已选口号 ({current_count}条)", expanded=False):
            st.write("**您已选择的口号：**")
            for _, row in selected_slogans.iterrows():
                st.write(f"✅ {row['序号']}. {row['口号']}")
            
            if st.button("🗑️ 清空所有选择", key="clear_all"):
                # 从Supabase删除所有该用户的投票
                try:
                    if st.session_state.supabase:
                        st.session_state.supabase.table('votes')\
                            .delete()\
                            .eq('voter_id', voter_id)\
                            .execute()
                    
                    st.session_state.all_votes_data[voter_id]["votes"] = []
                    update_votes_dataframe()
                    st.success("已清空所有选择")
                    st.rerun()
                except Exception as e:
                    st.error(f"清空失败: {e}")

    # 分页控件
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("⬅️ 上一页", key="prev_page") and st.session_state.current_page > 1:
            st.session_state.current_page -= 1
            st.rerun()
    with col2:
        st.write(f"**第 {st.session_state.current_page} 页，共 {total_pages} 页**")
        page_input = st.number_input("跳转到页面", min_value=1, max_value=total_pages, 
                                   value=st.session_state.current_page, key="page_jump")
        if page_input != st.session_state.current_page:
            st.session_state.current_page = page_input
            st.rerun()
    with col3:
        if st.button("下一页 ➡️", key="next_page") and st.session_state.current_page < total_pages:
            st.session_state.current_page += 1
            st.rerun()

    # 过滤数据
    filtered_df = df
    if search_term:
        filtered_df = df[df['口号'].str.contains(search_term, case=False, na=False)]

    # 当前页数据
    start_idx = (st.session_state.current_page - 1) * page_size
    end_idx = min(start_idx + page_size, len(filtered_df))
    current_page_df = filtered_df.iloc[start_idx:end_idx]

    st.write("### 请选择您喜欢的口号（可多选）：")
    
    # 自动保存的界面 - 不使用form
    new_selections = set(current_selection)
    selections_changed = False
    
    # 显示当前页的口号选择框
    for _, row in current_page_df.iterrows():
        slogan_id = row['序号']
        slogan_text = row['口号']
        
        is_disabled = (current_count >= max_votes and slogan_id not in current_selection)
        
        col1, col2 = st.columns([0.9, 0.1])
        with col1:
            st.write(f"**{slogan_id}.** {slogan_text}")
        with col2:
            # 使用checkbox的on_change参数实现自动保存
            is_selected = st.checkbox(
                "选择",
                value=slogan_id in current_selection,
                key=f"cb_{slogan_id}_{st.session_state.current_page}",
                disabled=is_disabled,
                label_visibility="collapsed"
            )
        
        # 实时更新选择
        if is_selected != (slogan_id in current_selection):
            if is_selected:
                new_selections.add(slogan_id)
            else:
                new_selections.discard(slogan_id)
            selections_changed = True
    
    # 如果选择发生变化，自动保存
    if selections_changed and not voted:
        if len(new_selections) <= max_votes:
            # 更新session state
            st.session_state.all_votes_data[voter_id]["votes"] = list(new_selections)
            
            # 自动保存到Supabase
            if auto_save_votes(voter_id, list(new_selections)):
                st.success("✅ 选择已自动保存")
                update_votes_dataframe()
                st.rerun()
            else:
                st.error("保存失败，请重试")
        else:
            st.error(f"选择数量超过限制，最多只能选择 {max_votes} 条")

    # 单独的提交投票按钮
    st.markdown("---")
    st.write("### 完成选择后提交投票")
    
    current_selection = st.session_state.all_votes_data.get(voter_id, {"votes": []})["votes"]
    current_count = len(current_selection)
    
    if current_count > 0:
        st.info(f"您当前选择了 {current_count} 条口号")
        
        with st.expander("📋 查看最终选择", expanded=False):
            selected_slogans = df[df['序号'].isin(current_selection)]
            for _, row in selected_slogans.iterrows():
                st.write(f"✅ {row['序号']}. {row['口号']}")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        can_submit = 1 <= current_count <= max_votes
        
        if not can_submit:
            if current_count == 0:
                st.error("❌ 请至少选择一条口号")
            else:
                st.error(f"❌ 选择数量超过限制（最多{max_votes}条）")
        
        if st.button("✅ 最终提交投票", 
                    type="primary", 
                    use_container_width=True,
                    disabled=not can_submit,
                    key="final_submit"):
            
            if current_count == 0:
                st.error("请至少选择一条口号")
            elif current_count > max_votes:
                st.error(f"选择数量超过限制")
            else:
                # 标记为已投票
                st.session_state.all_votes_data[voter_id]["voted"] = True
                st.session_state.voted = True
                
                # 更新Supabase中的投票状态
                if save_voter_status_to_supabase(voter_id, True):
                    st.success(f"🎉 投票成功！您选择了 {current_count} 条口号。感谢您的参与！")
                    st.balloons()
                    
                    with st.expander("您的投票详情", expanded=True):
                        selected_slogans = df[df['序号'].isin(current_selection)]
                        for _, row in selected_slogans.iterrows():
                            st.write(f"**{row['序号']}.** {row['口号']}")
                    
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("投票提交失败，请重试或联系管理员")

# 管理员界面
def admin_interface():
    """管理员界面"""
    st.title("🏆 口号评选系统 - 管理员界面")

    password = st.text_input("请输入管理员密码", type="password", key="admin_password")
    if password != "admin123":
        if password:
            st.error("密码错误")
        return

    st.success("管理员登录成功！")
    
    initialize_data()
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 刷新数据", type="primary", key="refresh_data"):
            st.session_state.all_votes_data = load_all_votes_data()
            st.session_state.slogan_df = load_slogan_data_from_supabase()
            update_votes_dataframe()
            st.success("数据刷新成功！")
            st.rerun()

    if st.session_state.slogan_df is None:
        st.error("口号数据加载失败")
        return

    df = st.session_state.slogan_df

    # 统计信息
    st.header("📊 投票统计")
    
    total_voters = len([v for v in st.session_state.all_votes_data.values() if v.get("voted", False)])
    total_votes = sum(len(v.get("votes", [])) for v in st.session_state.all_votes_data.values() if v.get("voted", False))
    avg_votes = total_votes / total_voters if total_voters > 0 else 0

    total_registered = len(st.session_state.all_votes_data)
    pending_voters = len([v for v in st.session_state.all_votes_data.values() if not v.get("voted", False) and len(v.get("votes", [])) > 0])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总参与人数", total_voters)
    col2.metric("总投票数", total_votes)
    col3.metric("人均投票数", f"{avg_votes:.1f}")
    col4.metric("待提交人数", pending_voters)

    # 投票人员管理
    if total_registered > 0:
        with st.expander(f"👥 投票人员管理 ({total_registered}人)", expanded=True):
            st.subheader("评委投票记录")
            
            search_voter = st.text_input("搜索评委姓名", placeholder="输入评委姓名搜索", key="search_voter")
            
            voters = sorted(st.session_state.all_votes_data.keys())
            
            if search_voter:
                voters = [v for v in voters if search_voter.lower() in v.lower()]
            
            if not voters:
                st.info("未找到匹配的评委")
            else:
                st.write(f"找到 {len(voters)} 位评委")
                
                for i, voter in enumerate(voters, 1):
                    voter_data = st.session_state.all_votes_data[voter]
                    votes = voter_data.get("votes", [])
                    voted = voter_data.get("voted", False)
                    vote_count = len(votes)
                    
                    if voted:
                        status = "✅ 已投票"
                        status_color = "green"
                    elif vote_count > 0:
                        status = "⏸️ 未提交"
                        status_color = "orange"
                    else:
                        status = "⏸️ 未投票"
                        status_color = "gray"
                    
                    with st.container():
                        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                        
                        with col1:
                            st.write(f"**{voter}**")
                        
                        with col2:
                            st.write(f"投票数: **{vote_count}**")
                        
                        with col3:
                            st.markdown(f"<span style='color: {status_color}'>{status}</span>", 
                                      unsafe_allow_html=True)
                        
                        with col4:
                            delete_key = f"delete_{voter}_{i}"
                            if st.button("🗑️", key=delete_key, help=f"删除 {voter} 的投票记录"):
                                if st.session_state.get(f"confirm_delete_{voter}") != True:
                                    st.session_state[f"confirm_delete_{voter}"] = True
                                    st.rerun()
                                else:
                                    try:
                                        # 从Supabase删除
                                        if st.session_state.supabase:
                                            st.session_state.supabase.table('votes')\
                                                .delete()\
                                                .eq('voter_id', voter)\
                                                .execute()
                                        
                                        del st.session_state.all_votes_data[voter]
                                        update_votes_dataframe()
                                        st.success(f"已删除评委 {voter} 的投票记录")
                                        st.session_state[f"confirm_delete_{voter}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"删除失败: {e}")
                        
                        if st.session_state.get(f"confirm_delete_{voter}") == True:
                            st.warning(f"确定要删除评委 **{voter}** 的投票记录吗？此操作不可恢复！")
                            col1, col2, col3 = st.columns([1, 1, 2])
                            with col1:
                                if st.button("✅ 确认删除", key=f"confirm_{voter}"):
                                    try:
                                        if st.session_state.supabase:
                                            st.session_state.supabase.table('votes')\
                                                .delete()\
                                                .eq('voter_id', voter)\
                                                .execute()
                                        
                                        del st.session_state.all_votes_data[voter]
                                        update_votes_dataframe()
                                        st.success(f"已删除评委 {voter} 的投票记录")
                                        st.session_state[f"confirm_delete_{voter}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"删除失败: {e}")
                            with col2:
                                if st.button("❌ 取消", key=f"cancel_{voter}"):
                                    st.session_state[f"confirm_delete_{voter}"] = False
                                    st.rerun()
                        
                        with st.expander("查看投票详情", expanded=False):
                            if vote_count > 0:
                                selected_slogans = df[df['序号'].isin(votes)]
                                for _, row in selected_slogans.iterrows():
                                    st.write(f"**{row['序号']}.** {row['口号']}")
                            else:
                                st.write("暂无投票记录")
                        
                        st.markdown("---")

    # 投票结果
    st.header("🏅 投票结果")
    
    if total_votes == 0:
        st.info("暂无投票数据")
        return

    vote_counts = {}
    for voter_data in st.session_state.all_votes_data.values():
        if voter_data.get("voted", False):
            votes = voter_data.get("votes", [])
            for slogan_id in votes:
                try:
                    slogan_id_int = int(slogan_id)
                    vote_counts[slogan_id_int] = vote_counts.get(slogan_id_int, 0) + 1
                except (ValueError, TypeError):
                    continue

    if not vote_counts:
        st.info("暂无有效的投票数据")
        return

    vote_counts_df = pd.DataFrame(list(vote_counts.items()), columns=["口号序号", "得票数"])
    result_df = pd.merge(vote_counts_df, df, left_on="口号序号", right_on="序号", how="left")
    result_df = result_df.sort_values("得票数", ascending=False)
    result_df["排名"] = range(1, len(result_df) + 1)

    st.dataframe(result_df[["排名", "序号", "口号", "得票数"]], use_container_width=True)

    csv = result_df.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="📥 下载完整结果",
        data=csv,
        file_name=f"口号评选结果_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="download_results"
    )

    # 可视化
    st.header("📈 数据可视化")
    if len(result_df) > 0:
        top_n = st.slider("显示前多少名", 10, min(100, len(result_df)), 20, key="top_n_slider")

        fig = px.bar(
            result_df.head(top_n),
            x="得票数",
            y="口号",
            orientation='h',
            title=f"前{top_n}名口号得票情况"
        )
        fig.update_layout(height=600, yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("📋 查看原始投票记录", expanded=False):
        if not st.session_state.votes_df.empty:
            st.dataframe(st.session_state.votes_df, use_container_width=True)
        else:
            st.write("暂无投票记录数据")

# 运行应用
if __name__ == "__main__":
    query_params = st.query_params
    if "admin" in query_params and query_params["admin"] == "true":
        admin_interface()
    else:
        main()
去掉上一页下一页。跳转页面在页尾也放一个。去掉显示已选口号详情。投票时间按照北京时间修复
