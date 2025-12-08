import streamlit as st
import base64
import pdfplumber
import difflib
import re
import mimetypes
from pathlib import Path

class DocComparator:
    def __init__(self):
        pass

    def read_file_base64(self, file_path):
        """通用读取文件为base64"""
        try:
            p = Path(file_path)
            if not p.exists(): return None
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            return None

    def extract_pdf_text(self, pdf_path):
        """提取PDF纯文本"""
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            print(f"PDF Error: {e}")
            return ""
        return text

    def clean_markdown_for_comparison(self, text):
        """清洗 Markdown 用于比对（去除干扰符）"""
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text) 
        text = re.sub(r'[#*`]', '', text) 
        text = re.sub(r'\s+', '', text) 
        return text

    def clean_pdf_for_comparison(self, text):
        return re.sub(r'\s+', '', text)

    def _render_pdf_iframe(self, pdf_path):
        """渲染 PDF iframe，高度拉满"""
        b64_pdf = self.read_file_base64(pdf_path)
        if b64_pdf:
            # 修改为固定像素高度 900px
            return f'''
                <iframe src="data:application/pdf;base64,{b64_pdf}" 
                        width="100%" 
                        height="900px" 
                        type="application/pdf"
                        style="border:1px solid #ddd; border-radius:5px;">
                </iframe>
            '''
        return None

    def _inject_images_for_preview(self, md_content, image_root):
        """
        核心功能：处理 Markdown 预览里的图片
        Markdown 里的图片是相对路径，网页无法直接读取。
        此函数找到所有 ![]() 标签，读取本地图片，转为 Base64 嵌入。
        """
        if not image_root: return md_content
        
        root_path = Path(image_root)
        
        def replace_img(match):
            alt_text = match.group(1)
            img_rel_path = match.group(2)
            
            # 尝试寻找图片文件
            img_full_path = root_path / img_rel_path
            
            if img_full_path.exists():
                # 获取 mime type (png/jpg)
                mime_type, _ = mimetypes.guess_type(img_full_path)
                if not mime_type: mime_type = "image/png"
                
                # 转 base64
                b64_data = self.read_file_base64(img_full_path)
                if b64_data:
                    return f'![{alt_text}](data:{mime_type};base64,{b64_data})'
            
            # 如果找不到图片，保留原样或提示
            return f'![{alt_text} (Image Not Found)]({img_rel_path})'

        # 正则替换所有图片标签
        # pattern: ![alt](path)
        new_md = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img, md_content)
        return new_md

    # ========================================================
    # 界面渲染
    # ========================================================

    def render_editor_ui(self, pdf_path, current_md_content, image_root=None):
        """
        模式1：交互编辑
        """
        st.markdown("### ✏️ 交互编辑")
        
        c1, c2 = st.columns([1, 1])
        
        # --- 左侧：PDF (加长版) ---
        with c1:
            st.caption(f"📄 PDF 原文 ({Path(pdf_path).name})")
            pdf_html = self._render_pdf_iframe(pdf_path)
            if pdf_html:
                st.markdown(pdf_html, unsafe_allow_html=True)
            else:
                st.warning("无法加载 PDF")

        # --- 右侧：Tab 编辑 ---
        with c2:
            st.caption("📝 Markdown 工作区")
            
            tab_src, tab_preview = st.tabs(["💻 源码编辑", "👁️ 版式预览 (表格/公式/图)"])
            
            with tab_src:
                new_content = st.text_area(
                    "editor",
                    value=current_md_content,
                    height=900, # 编辑器也拉高
                    label_visibility="collapsed",
                    key="editor_textarea",
                    help="在此修改文本"
                )
            
            with tab_preview:
                with st.spinner("正在渲染版式..."):
                    # 1. 注入图片 Base64
                    preview_content = self._inject_images_for_preview(new_content, image_root)
                    
                    # 2. 渲染 markdown (unsafe_allow_html=True 有助于更好支持某些表格格式)
                    # 使用 container 固定高度并滚动
                    with st.container(height=900, border=True):
                        st.markdown(preview_content, unsafe_allow_html=True)

        return new_content

    def render_alignment_ui(self, pdf_path, md_content):
        """
        模式2：智能核对 (左右分屏，PDF加长)
        """
        st.markdown("### 🔍 智能核对")
        
        pdf_full_text = self.extract_pdf_text(pdf_path)
        if not pdf_full_text or len(pdf_full_text.strip()) < 10:
            st.error("⚠️ 无法提取 PDF 文字，无法进行智能比对。")
            return

        pdf_clean = self.clean_pdf_for_comparison(pdf_full_text)
        md_paragraphs = re.split(r'\n\s*\n', md_content)

        c1, c2 = st.columns([1, 1])

        # 左侧 PDF
        with c1:
            st.info("📄 PDF 原文 (请手动滚动查找)")
            # 这里同样使用长 Iframe
            pdf_html = self._render_pdf_iframe(pdf_path)
            if pdf_html:
                st.markdown(pdf_html, unsafe_allow_html=True)

        # 右侧 核对列表
        with c2:
            st.info("📊 匹配结果")
            
            # 使用 container 让右侧也可以独立滚动，高度与左侧匹配
            with st.container(height=900):
                for md_para in md_paragraphs:
                    if not md_para.strip(): continue
                    
                    md_clean = self.clean_markdown_for_comparison(md_para)
                    if len(md_clean) < 5: continue 

                    bg_color = "transparent"
                    border_color = "#eee"
                    icon = ""
                    
                    if md_clean in pdf_clean:
                        bg_color = "#e6fffa" # 绿
                        border_color = "#b2f5ea"
                        icon = "✅"
                    else:
                        s = difflib.SequenceMatcher(None, md_clean, pdf_clean)
                        match = s.find_longest_match(0, len(md_clean), 0, len(pdf_clean))
                        ratio = match.size / len(md_clean) if len(md_clean) > 0 else 0
                        
                        if ratio > 0.8:
                            bg_color = "#fffbea" # 黄
                            border_color = "#fefcbf"
                            icon = "⚠️"
                        else:
                            bg_color = "#fff5f5" # 红
                            border_color = "#fed7d7"
                            icon = "❌"

                    st.markdown(
                        f"""
                        <div style="
                            background-color: {bg_color}; 
                            border: 1px solid {border_color}; 
                            border-radius: 8px; 
                            padding: 12px; 
                            margin-bottom: 10px;
                            font-size: 14px;
                            line-height: 1.5;
                        ">
                            <div style="font-weight:bold; margin-bottom:4px;">{icon}</div>
                            {md_para}
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
