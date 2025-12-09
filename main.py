import streamlit as st
import os
import time
import requests
import zipfile
import shutil
import subprocess
import tempfile
import re
from pathlib import Path

# 引入比对模块 (保持原有逻辑)
try:
    from comparator import DocComparator
except ImportError:
    DocComparator = None

# =========================================================
# 1. API 客户端 (保持原有逻辑)
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
# 2. 格式转换器 (⭐ 核心修改：修复正则逻辑)
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
    def normalize_math_formulas(md_content):
        """
        ⭐ 核心修复：清理公式内部的空格
        Pandoc 要求 $ 和内容之间不能有空格，否则不识别
        """
        if not md_content: return ""
        
        # 1. 转换 \( ... \) 为 $...$，并去除紧邻的空格
        # \( 及其后所有空格 -> $
        md_content = re.sub(r'\\\(\s*', '$', md_content)
        # 空格及其后 \) -> $
        md_content = re.sub(r'\s*\\\)', '$', md_content)
        
        # 2. 转换 \[ ... \] 为 $$...$$
        md_content = re.sub(r'\\\[\s*', '\n$$\n', md_content)
        md_content = re.sub(r'\s*\\\]', '\n$$\n', md_content)
        
        # 3. ⭐ 关键：修复已有的 $ 格式中的空格问题
        # 将 "$  x  $" 替换为 "$x$"
        # (?<!\$) 表示前面不是 $ (避免匹配到 $$)
        # ([^\$]+?) 捕获内部内容
        md_content = re.sub(r'(?<!\$)\$\s+([^\$]+?)\s+\$(?!\$)', r'$\1$', md_content)
        
        # 4. 修复单独的 $ 后空格
        md_content = re.sub(r'(?<!\$)\$\s+', '$', md_content)
        md_content = re.sub(r'\s+\$(?!\$)', '$', md_content)

        # 5. 规范块级公式 $$ 的换行
        md_content = re.sub(r'([^\n])\$\$', r'\1\n$$', md_content)
        md_content = re.sub(r'\$\$([^\n])', r'$$\n\1', md_content)
        
        return md_content

    @staticmethod
    def clean_image_captions(md_content):
        if not md_content: return ""
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        cleaned = re.sub(pattern, r'![](\2)', md_content)
        return cleaned

    @staticmethod
    def run_pandoc(input_file, output_file, format_type, source_filename=None, math_mode="mathml"):
        input_path = Path(input_file)
        cwd = input_path.parent
        
        # 预处理：标准化 Markdown (修正公式空格)
        temp_input = None
        if input_path.suffix.lower() == '.md':
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content = FormatConverter.normalize_math_formulas(content)
            content = FormatConverter.clean_image_captions(content)
            
            temp_input = cwd / f"temp_fix_{input_path.name}"
            with open(temp_input, 'w', encoding='utf-8') as f:
                f.write(content)
            target_input = temp_input.name
        else:
            target_input = input_path.name

        cmd = ["pandoc", target_input, "-o", str(output_file.resolve())]
        
        if format_type == "epub":
            title = Path(source_filename).stem if source_filename else input_path.stem
            metadata_file = cwd / "metadata.yaml"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(f"---\ntitle: {title}\n---\n")
            
            cmd.extend([
                "--standalone",
                "--toc",
                "--metadata-file", str(metadata_file),
                "-f", "markdown+tex_math_dollars" # 明确告诉 Pandoc 识别 $公式$
            ])

            # ⭐ 公式渲染逻辑
            if math_mode == "mathml":
                cmd.append("--mathml")  # EPUB3 标准，矢量清晰，推荐
            elif math_mode == "webtex":
                cmd.append("--webtex")  # 转为图片，兼容性好但可能慢
            elif math_mode == "mathjax":
                cmd.append("--mathjax") # JS渲染，EPUB兼容性差
            
        elif format_type == "docx":
            cmd.extend(["--standalone", "-f", "markdown+tex_math_dollars"])

        cmd.append("--resource-path=.")

        try:
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Pandoc 转换失败: {e.stderr}")
        finally:
            if temp_input and temp_input.exists(): temp_input.unlink()
            if format_type == "epub" and metadata_file.exists(): metadata_file.unlink()

# =========================================================
# 3. Streamlit 主界面 (保持原有逻辑)
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

    with st.sidebar:
        st.header("设置")
        api_key = st.text_input("API Key", type="password")
        
        st.subheader("数学公式渲染")
        # 默认改为 MathML，因为它是 EPUB 标准，如果阅读器支持会显示得很完美
        math_mode = st.radio(
            "选择渲染方式",
            ["mathml", "webtex", "mathjax"],
            index=0,
            help="**MathML**: EPUB标准格式(推荐)。\n**WebTex**: 转为图片，兼容老设备。\n**MathJax**: 需阅读器支持JS。"
        )
        st.session_state.math_mode = math_mode
        
        st.divider()
        st.header("🔧 独立工具箱")
        
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
                                    math_mode=st.session_state.math_mode
                                )
                            st.success("转换成功！")
                            with open(epub_path, "rb") as f:
                                st.download_button(label="📥 下载 EPUB", data=f, file_name=epub_path.name)
                    except Exception as e:
                        st.error(f"转换失败: {e}")

        st.divider()
        if st.button("🔄 重置所有状态"):
            st.session_state.clear()
            st.rerun()

    # 阶段 1: 上传
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
                with open(pdf_path, "wb") as f: f.write(uploaded_file.getbuffer())

                client = Doc2XPDFClient(api_key)
                output_dir = client.process(pdf_path)
                md_path = FormatConverter.get_md_file_path(output_dir)
                
                with open(md_path, "r", encoding="utf-8") as f: content = f.read()

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

    # 阶段 2: 编辑
    elif st.session_state.step == "editing":
        paths = st.session_state.work_paths
        col1, col3 = st.columns([3, 1])
        with col1: st.subheader("步骤 2/3: 校对与编辑")
        with col3:
            if st.button("💾 完成校对，生成文档", type="primary", use_container_width=True):
                st.session_state.step = "generating"
                st.rerun()

        if DocComparator:
            cmp = DocComparator()
            cmp.render_editor_ui(paths["pdf"], st.session_state.current_md_content, image_root=paths["dir"])
            if "editor_textarea" in st.session_state:
                st.session_state.current_md_content = st.session_state.editor_textarea
        else:
            st.warning("简易模式")
            st.session_state.current_md_content = st.text_area("Markdown", st.session_state.current_md_content, height=600)

    # 阶段 3: 导出
    elif st.session_state.step == "generating":
        st.subheader("步骤 3/3: 导出文档")
        paths = st.session_state.work_paths
        md_path = Path(paths["md"])
        output_dir = Path(paths["dir"])
        pdf_path = Path(paths["pdf"])
        math_mode = st.session_state.get('math_mode', 'mathml')
        
        st.write("1. 保存内容...")
        FormatConverter.save_md_content(st.session_state.current_md_content, md_path)
        
        try:
            st.write("2. 生成 Word...")
            docx_path = output_dir / f"{md_path.stem}.docx"
            FormatConverter.run_pandoc(md_path, docx_path, "docx")
            
            st.write(f"3. 生成 EPUB (模式: {math_mode})...")
            epub_path = output_dir / f"{md_path.stem}.epub"
            FormatConverter.run_pandoc(md_path, epub_path, "epub", source_filename=pdf_path.name, math_mode=math_mode)
            
            st.success("✅ 完成！")
            c1, c2, c3, c4 = st.columns(4)
            with open(docx_path, "rb") as f: c1.download_button("📘 Word", f, file_name=docx_path.name)
            with open(epub_path, "rb") as f: c2.download_button("📗 EPUB", f, file_name=epub_path.name)
            with open(md_path, "rb") as f: c3.download_button("📝 Markdown", f, file_name=md_path.name)
            if c4.button("⬅️ 返回修改"):
                st.session_state.step = "editing"
                st.rerun()
        except Exception as e:
            st.error(f"错误: {e}")
            if st.button("重试"): st.rerun()

if __name__ == "__main__":
    main()
