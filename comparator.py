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
            # 🟢 新增：大文件保护逻辑
            try:
                p = Path(pdf_path)
                if not p.exists(): return None
                
                # 获取文件大小 (字节)
                file_size = p.stat().st_size
                # 设定阈值为 15MB (Base64编码后约20MB，这是大多数浏览器内嵌显示的舒适区上限)
                limit_bytes = 15 * 1024 * 1024 
                
                if file_size > limit_bytes:
                    return f'''
                        <div style="
                            width: 100%; 
                            height: 900px; 
                            display: flex; 
                            flex-direction: column;
                            justify-content: center; 
                            align-items: center; 
                            background-color: #f8f9fa;
                            border: 1px solid #ddd; 
                            border-radius: 5px;
                            color: #555;
                            text-align: center;
                        ">
                            <h3 style="margin-bottom: 10px;">⚠️ PDF 文件过大，已禁用预览</h3>
                            <p style="margin: 5px 0;">当前文件大小: <b>{file_size / (1024 * 1024):.2f} MB</b></p>
                            <p style="margin: 5px 0; font-size: 0.9em; color: #888;">
                                浏览器无法稳定渲染超过 15MB 的内嵌 PDF。<br>
                                强行渲染会导致页面卡死或崩溃。
                            </p>
                            <div style="margin-top: 20px; padding: 10px 20px; background: #e9ecef; border-radius: 4px;">
                                👉 请使用本地 PDF 阅读器打开原文件进行对照
                            </div>
                        </div>
                    '''
            except Exception:
                pass # 如果获取大小出错，尝试继续执行默认逻辑

            # 🟢 原有逻辑：读取并转换为 Base64
            b64_pdf = self.read_file_base64(pdf_path)
            if b64_pdf:
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
        new_md = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img, md_content)
        return new_md

    def _render_markdown_with_math(self, md_content):
        """
        ⭐ 新增：使用 MathJax 渲染包含数学公式的 Markdown
        支持 \( ... \) 和 $$ ... $$ 语法
        """
        # 将 Markdown 转为 HTML（简易版，主要处理基础格式）
        # 注意：这里使用 st.markdown 的 HTML 输出
        # 为了更好的兼容性，我们使用 HTML component
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <script>
                window.MathJax = {{
                    tex: {{
                        inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
                        displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
                        processEscapes: true,
                        processEnvironments: true
                    }},
                    options: {{
                        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
                    }},
                    startup: {{
                        pageReady: () => {{
                            return MathJax.startup.defaultPageReady().then(() => {{
                                console.log('MathJax loaded');
                            }});
                        }}
                    }}
                }};
            </script>
            <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    padding: 20px;
                    color: #333;
                    background-color: white;
                }}
                h1, h2, h3, h4, h5, h6 {{
                    margin-top: 24px;
                    margin-bottom: 16px;
                    font-weight: 600;
                    line-height: 1.25;
                }}
                h1 {{ font-size: 2em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }}
                h2 {{ font-size: 1.5em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }}
                h3 {{ font-size: 1.25em; }}
                p {{ margin-bottom: 16px; }}
                code {{
                    background-color: #f6f8fa;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: 'Courier New', monospace;
                    font-size: 0.9em;
                }}
                pre {{
                    background-color: #f6f8fa;
                    padding: 16px;
                    border-radius: 6px;
                    overflow-x: auto;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                    border: 1px solid #ddd;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 12px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                    font-weight: bold;
                }}
                tr:hover {{
                    background-color: #f5f5f5;
                }}
                img {{
                    max-width: 100%;
                    height: auto;
                    display: block;
                    margin: 20px auto;
                }}
                blockquote {{
                    border-left: 4px solid #ddd;
                    padding-left: 16px;
                    color: #666;
                    margin: 16px 0;
                }}
                /* 数学公式样式 */
                .math {{
                    overflow-x: auto;
                    overflow-y: hidden;
                }}
                mjx-container {{
                    overflow-x: auto;
                    overflow-y: hidden;
                }}
            </style>
        </head>
        <body>
            <div id="content">
                {self._markdown_to_html(md_content)}
            </div>
        </body>
        </html>
        """
        
        return html_content

    def _markdown_to_html(self, md_content):
        """
        简易 Markdown 到 HTML 转换
        保留数学公式的原始格式，让 MathJax 处理
        """
        html = md_content
        
        # 标题
        html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        
        # 粗体和斜体
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # 段落（简单处理：连续的非空行作为段落）
        lines = html.split('\n')
        processed_lines = []
        in_paragraph = False
        
        for line in lines:
            stripped = line.strip()
            # 跳过已经是 HTML 标签的行
            if stripped.startswith('<') or not stripped:
                if in_paragraph:
                    processed_lines.append('</p>')
                    in_paragraph = False
                processed_lines.append(line)
            else:
                if not in_paragraph:
                    processed_lines.append('<p>')
                    in_paragraph = True
                processed_lines.append(line)
        
        if in_paragraph:
            processed_lines.append('</p>')
        
        html = '\n'.join(processed_lines)
        
        # 换行
        html = html.replace('\n\n', '<br><br>')
        
        return html

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
                    height=900,
                    label_visibility="collapsed",
                    key="editor_textarea",
                    help="在此修改文本"
                )
            
            with tab_preview:
                with st.spinner("正在渲染版式（含数学公式）..."):
                    # 1. 注入图片 Base64
                    preview_content = self._inject_images_for_preview(new_content, image_root)
                    
                    # 2. ⭐ 使用 MathJax 渲染（新方法）
                    html_with_math = self._render_markdown_with_math(preview_content)
                    
                    # 3. 使用 components.html 渲染完整 HTML（支持 JavaScript）
                    st.components.v1.html(
                        html_with_math,
                        height=900,
                        scrolling=True
                    )

        return new_content
