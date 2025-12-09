import streamlit as st
import os
import time
import requests
import zipfile
import shutil
import subprocess
import tempfile
from pathlib import Path

# 引入比对模块 (保持原有逻辑)
try:
    from comparator import DocComparator
except ImportError:
    DocComparator = None

# =========================================================
# 1. API 客户端
# =========================================================
class Doc2XPDFClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def process(self, file_path):
        uid, upload_url = self._preupload()
        self._upload_file(file_path, upload_url)
        self._wait_for_parsing(uid)
        self._trigger_export(uid)
        download_url = self._wait_for_export_result(uid)
        return self._download_and_extract(download_url, file_path)

    def _preupload(self):
        st.toast("1. 请求上传链接...", icon="☁️")
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: raise Exception(f"预上传失败: {res.text}")
        data = res.json()
        if data["code"] != "success": raise Exception(str(data))
        return data["data"]["uid"], data["data"]["url"]

    def _upload_file(self, file_path, upload_url):
        st.toast("2. 上传文件...", icon="📤")
        with open(file_path, "rb") as f:
            requests.put(upload_url, data=f)

    def _wait_for_parsing(self, uid):
        st.toast("3. AI 正在解析...", icon="🧠")
        progress_text = st.empty()
        bar = st.progress(0)
        while True:
            time.sleep(1)
            try:
                res = requests.get(f"{self.base_url}/api/v2/parse/status", headers=self.headers, params={"uid": uid})
                if res.status_code != 200: continue
                data = res.json()
                if data["code"] != "success": 
                    if data.get("code") == "parse_error": raise Exception(data.get("msg"))
                    continue
                
                status = data["data"]["status"]
                prog = data["data"].get("progress", 0)
                bar.progress(min(prog / 100, 1.0))
                progress_text.text(f"解析进度: {prog}%")
                
                if status == "success": 
                    bar.progress(1.0)
                    progress_text.empty()
                    break
                elif status == "failed": raise Exception(data["data"].get("detail"))
            except requests.RequestException: continue

    def _trigger_export(self, uid):
        st.toast("4. 请求导出格式...", icon="⚙️")
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, 
                      json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        while True:
            time.sleep(1)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            if res.status_code != 200: continue
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success":
                return data["data"]["url"]
            elif data["data"]["status"] == "failed": raise Exception("导出失败")

    def _download_and_extract(self, url, original_file):
        st.toast("5. 下载资源包...", icon="📥")
        r = requests.get(url)
        extract_path = Path(f"./output/{original_file.stem}")
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        return extract_path

# =========================================================
# 2. 格式转换器 (增强版 - 修复数学公式)
# =========================================================
class FormatConverter:
    @staticmethod
    def save_md_content(content, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def get_md_file_path(folder):
        md_files = list(folder.glob("**/output.md"))
        if not md_files: md_files = list(folder.glob("**/*.md"))
        return md_files[0] if md_files else None

    @staticmethod
    def clean_image_captions(md_content):
        """清理 Markdown 中图片的描述文字（alt text）"""
        import re
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        cleaned = re.sub(pattern, r'![](\2)', md_content)
        return cleaned

    @staticmethod
    def run_pandoc(input_file, output_file, format_type, source_filename=None, math_mode="webtex"):
        """
        通用 Pandoc 转换函数
        :param input_file: 输入文件路径 (可以是 .md 或 .docx)
        :param output_file: 输出文件路径
        :param format_type: 目标格式 'docx' 或 'epub'
        :param source_filename: 源文件名（用于设置标题）
        :param math_mode: 数学公式渲染模式 ('webtex', 'mathjax', 'mathml')
        """
        input_path = Path(input_file)
        cwd = input_path.parent
        
        # 如果是 Markdown 转 EPUB，先清理图片标题
        temp_md = None
        if format_type == "epub" and input_path.suffix.lower() == '.md':
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()
            cleaned_content = FormatConverter.clean_image_captions(content)
            temp_md = cwd / f"temp_{input_path.name}"
            with open(temp_md, "w", encoding="utf-8") as f:
                f.write(cleaned_content)
            input_path = temp_md
        
        cmd = ["pandoc", input_path.name, "-o", str(output_file.resolve())]
        
        is_docx_input = input_path.suffix.lower() == '.docx'

        if format_type == "epub":
            # 使用源文件名作为标题
            if source_filename:
                title = Path(source_filename).stem
            else:
                title = input_path.stem
            
            # 创建 metadata 文件
            metadata_content = f"---\ntitle: {title}\n---\n"
            metadata_file = cwd / "epub-metadata.yaml"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(metadata_content)
            
            cmd.extend([
                "--toc",
                "--toc-depth=3",
                "--epub-chapter-level=2",
                "--metadata-file", str(metadata_file),
                "--standalone"
            ])
            
            if not is_docx_input:
                # ⭐ 关键修改：数学公式渲染
                if math_mode == "webtex":
                    # 将公式转为图片（最佳兼容性）
                    cmd.append("--webtex")
                elif math_mode == "mathjax":
                    # 使用 MathJax（需要网络）
                    cmd.append("--mathjax")
                else:
                    # 使用 MathML（部分阅读器不支持）
                    cmd.append("--mathml")
                
                # 添加 CSS
                cmd.extend(["--css", "epub-style.css"])
                
                # 创建CSS文件
                css_content = """body { 
    font-family: serif; 
    line-height: 1.6;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 20px 0;
    border: 1px solid #333;
}
th, td {
    border: 1px solid #666;
    padding: 8px;
    text-align: left;
}
th { 
    background-color: #f2f2f2; 
    font-weight: bold; 
}
img { 
    max-width: 100%; 
    height: auto;
    display: block;
    margin: 10px auto;
}
/* 数学公式样式 */
.math { 
    font-family: "Latin Modern Math", "STIX Two Math", serif;
    overflow-x: auto;
}
mjx-container {
    overflow-x: auto;
}
"""
                css_file = cwd / "epub-style.css"
                with open(css_file, "w", encoding="utf-8") as f:
                    f.write(css_content)
            else:
                cmd.extend(["-f", "docx", "-t", "epub"])
        
        elif format_type == "docx":
            if not is_docx_input:
                # Markdown 转 Docx - 也需要处理数学公式
                cmd.extend([
                    "--standalone",
                    "-f", "markdown+pipe_tables+grid_tables"
                ])
                # Word 文档数学公式支持
                if math_mode == "webtex":
                    cmd.append("--webtex")
        
        cmd.append("--resource-path=.")
        
        # 执行命令
        try:
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Pandoc 转换失败: {e.stderr}")
        
        # 清理临时文件
        if format_type == "epub":
            if not is_docx_input:
                if 'css_file' in locals() and css_file.exists():
                    css_file.unlink()
            if 'metadata_file' in locals() and metadata_file.exists():
                metadata_file.unlink()
        
        if temp_md and temp_md.exists():
            temp_md.unlink()

# =========================================================
# 3. Streamlit 主界面
# =========================================================
def main():
    st.set_page_config(page_title="夷卓汇文档工作台", layout="wide")
    st.title("🛠️ 夷卓汇文档工作台")

    if not DocComparator:
        st.warning("提示: 缺失 comparator.py 模块，比对功能将受限，但转换功能正常。")

    if "step" not in st.session_state:
        st.session_state.step = "upload"
    if "current_md_content" not in st.session_state:
        st.session_state.current_md_content = ""
    if "work_paths" not in st.session_state:
        st.session_state.work_paths = {}

    # -----------------------------------------------------
    # 侧边栏：设置与工具箱
    # -----------------------------------------------------
    with st.sidebar:
        st.header("设置")
        api_key = st.text_input("API Key", type="password")
        
        # 数学公式渲染选项
        st.subheader("数学公式渲染")
        math_mode = st.radio(
            "选择渲染方式",
            ["webtex", "mathjax", "mathml"],
            index=0,
            help="webtex: 转为图片(推荐)\nmathjax: 在线渲染\nmathml: 原生标记"
        )
        st.session_state.math_mode = math_mode
        
        st.divider()
        st.header("🔧 独立工具箱")
        
        # DOCX 转 EPUB
        with st.expander("📄 DOCX 转 EPUB"):
            d2e_file = st.file_uploader("上传 Word 文档", type=["docx"], key="d2e_uploader")
            if d2e_file:
                if st.button("开始转换", key="btn_d2e"):
                    try:
                        with tempfile.TemporaryDirectory() as tmpdirname:
                            tmp_path = Path(tmpdirname)
                            docx_path = tmp_path / d2e_file.name
                            with open(docx_path, "wb") as f:
                                f.write(d2e_file.getbuffer())
                            
                            epub_path = tmp_path / f"{docx_path.stem}.epub"
                            
                            with st.spinner("正在转换 DOCX 到 EPUB..."):
                                FormatConverter.run_pandoc(
                                    docx_path, epub_path, "epub", 
                                    source_filename=d2e_file.name,
                                    math_mode=st.session_state.get('math_mode', 'webtex')
                                )
                            
                            st.success("转换成功！")
                            with open(epub_path, "rb") as f:
                                st.download_button(
                                    label="📥 下载 EPUB",
                                    data=f,
                                    file_name=epub_path.name,
                                    mime="application/epub+zip"
                                )
                    except Exception as e:
                        st.error(f"转换失败: {e}")

        st.divider()
        if st.button("🔄 重置所有状态"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # -----------------------------------------------------
    # 阶段 1: 上传 PDF
    # -----------------------------------------------------
    if st.session_state.step == "upload":
        st.info("步骤 1/3: 上传 PDF 进行智能解析")
        uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

        if uploaded_file and st.button("🚀 开始解析"):
            if not api_key:
                st.error("请先在左侧填写 API Key")
                return

            try:
                temp_dir = Path("./temp_uploads")
                temp_dir.mkdir(exist_ok=True)
                pdf_path = (temp_dir / uploaded_file.name).resolve() 
                
                with open(pdf_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                client = Doc2XPDFClient(api_key)
                output_dir = client.process(pdf_path)
                
                md_path = FormatConverter.get_md_file_path(output_dir)
                if not md_path: raise Exception("未找到解析结果 Markdown")

                with open(md_path, "r", encoding="utf-8") as f:
                    content = f.read()

                st.session_state.work_paths = {
                    "pdf": str(pdf_path),
                    "md": str(md_path.resolve()),
                    "dir": str(output_dir.resolve())
                }
                st.session_state.current_md_content = content
                st.session_state.step = "editing"
                st.rerun()

            except Exception as e:
                st.error(f"处理失败: {str(e)}")

    # -----------------------------------------------------
    # 阶段 2: 编辑与比对
    # -----------------------------------------------------
    elif st.session_state.step == "editing":
        paths = st.session_state.work_paths
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.subheader("步骤 2/3: 校对与编辑")
        with col3:
            if st.button("💾 完成校对，生成文档", type="primary", use_container_width=True):
                st.session_state.step = "generating"
                st.rerun()

        if DocComparator:
            cmp = DocComparator()
            cmp.render_editor_ui(
                paths["pdf"], 
                st.session_state.current_md_content, 
                image_root=paths["dir"]
            )
            if "editor_textarea" in st.session_state:
                st.session_state.current_md_content = st.session_state.editor_textarea
        else:
            st.warning("未检测到 comparator 模块，进入简易编辑模式。")
            new_content = st.text_area("Markdown 编辑", st.session_state.current_md_content, height=600)
            st.session_state.current_md_content = new_content

    # -----------------------------------------------------
    # 阶段 3: 导出
    # -----------------------------------------------------
    elif st.session_state.step == "generating":
        st.subheader("步骤 3/3: 导出文档")
        
        paths = st.session_state.work_paths
        md_path = Path(paths["md"])
        output_dir = Path(paths["dir"])
        pdf_path = Path(paths["pdf"])
        math_mode = st.session_state.get('math_mode', 'webtex')
        
        st.write("1. 保存最终修订内容...")
        FormatConverter.save_md_content(st.session_state.current_md_content, md_path)
        
        try:
            st.write("2. 生成 Word 文档 (Markdown -> Docx)...")
            docx_path = output_dir / f"{md_path.stem}.docx"
            FormatConverter.run_pandoc(md_path, docx_path, "docx", math_mode=math_mode)
            
            st.write(f"3. 生成 EPUB 电子书 (使用 {math_mode} 模式)...")
            epub_path = output_dir / f"{md_path.stem}.epub"
            FormatConverter.run_pandoc(
                md_path, epub_path, "epub", 
                source_filename=pdf_path.name,
                math_mode=math_mode
            )
            
            st.success("✅ 所有任务完成！")
            
            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            
            with open(docx_path, "rb") as f:
                c1.download_button("📘 下载 Word", f, file_name=docx_path.name)
            
            with open(epub_path, "rb") as f:
                c2.download_button("📗 下载 EPUB", f, file_name=epub_path.name)

            with open(md_path, "rb") as f:
                c3.download_button("📝 下载 Markdown", f, file_name=md_path.name)
                
            if c4.button("⬅️ 返回继续修改"):
                st.session_state.step = "editing"
                st.rerun()
                
        except Exception as e:
            st.error(f"转换过程出错: {e}")
            st.info("提示: 请检查是否已安装 pandoc (终端运行 `pandoc -v`)")
            if st.button("重试"):
                st.rerun()

if __name__ == "__main__":
    main()
