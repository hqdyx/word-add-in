import streamlit as st
import base64
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
