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

# 引入比对模块
try:
    from comparator import DocComparator
except ImportError:
    DocComparator = None

# ⭐ 新增：尝试导入 PyPDF 用于统计页数
try:
    import PyPDF
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

# =========================================================
# 1. Doc2X API 客户端
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
# 2. MinerU 在线 API 客户端
# =========================================================
class MinerUOnlineClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://mineru.net/api/v4"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    def process(self, file_path):
        """
        使用 MinerU 在线 API 解析 PDF
        返回与 Doc2X 相同结构的输出目录
        """
        original_file = Path(file_path)
        
        # 步骤1: 申请上传链接
        st.toast("1. 申请上传链接...", icon="🔗")
        upload_url, batch_id = self._get_upload_url(original_file.name)
        
        # 步骤2: 上传文件
        st.toast("2. 上传文件到解析中心...", icon="📤")
        self._upload_file(file_path, upload_url)
        
        # 步骤3: 等待解析完成
        st.toast("3. AI 正在解析...", icon="🧠")
        download_url = self._wait_for_result(batch_id, original_file.name)
        
        # 步骤4: 下载并解压结果
        st.toast("4. 下载解析结果...", icon="📥")
        output_dir = self._download_and_extract(download_url, original_file)
        
        return output_dir

    def _get_upload_url(self, filename):
        """申请文件上传链接"""
        url = f"{self.base_url}/file-urls/batch"
        data = {
            "files": [{"name": filename}],
            "model_version": "vlm",
            "enable_formula": True,
            "enable_table": True
        }
        
        try:
            res = requests.post(url, headers=self.headers, json=data, timeout=30)
            if res.status_code != 200:
                raise Exception(f"申请上传链接失败: HTTP {res.status_code}")
            
            result = res.json()
            if result["code"] != 0:
                raise Exception(f"解析错误: {result.get('msg', '未知错误')}")
            
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            
            return upload_url, batch_id
            
        except requests.RequestException as e:
            raise Exception(f"网络请求失败: {str(e)}")

    def _upload_file(self, file_path, upload_url):
        """上传文件到 MinerU"""
        try:
            with open(file_path, 'rb') as f:
                res = requests.put(upload_url, data=f, timeout=300)
                if res.status_code != 200:
                    raise Exception(f"文件上传失败: HTTP {res.status_code}")
        except requests.RequestException as e:
            raise Exception(f"上传文件失败: {str(e)}")

    def _wait_for_result(self, batch_id, filename):
        """轮询检查解析状态"""
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        
        progress_text = st.empty()
        bar = st.progress(0)
        
        max_wait_time = 600
        start_time = time.time()
        
        while True:
            if time.time() - start_time > max_wait_time:
                raise Exception("解析超时，请稍后重试")
            
            time.sleep(3)
            
            try:
                res = requests.get(url, headers=self.headers, timeout=30)
                if res.status_code != 200:
                    continue
                
                result = res.json()
                if result["code"] != 0:
                    continue
                
                extract_results = result["data"]["extract_result"]
                file_result = next((r for r in extract_results if r["file_name"] == filename), None)
                
                if not file_result:
                    continue
                
                state = file_result["state"]
                
                if state == "waiting-file":
                    bar.progress(0.1)
                    progress_text.text("等待文件上传...")
                    
                elif state == "pending":
                    bar.progress(0.2)
                    progress_text.text("排队中...")
                    
                elif state == "running":
                    if "extract_progress" in file_result:
                        prog = file_result["extract_progress"]
                        extracted = prog.get("extracted_pages", 0)
                        total = prog.get("total_pages", 1)
                        percent = min(0.2 + (extracted / total) * 0.6, 0.8)
                        bar.progress(percent)
                        progress_text.text(f"解析中: {extracted}/{total} 页")
                    else:
                        bar.progress(0.5)
                        progress_text.text("正在解析...")
                        
                elif state == "converting":
                    bar.progress(0.9)
                    progress_text.text("格式转换中...")
                    
                elif state == "done":
                    bar.progress(1.0)
                    progress_text.empty()
                    st.toast("✅ 解析完成！", icon="🎉")
                    return file_result["full_zip_url"]
                    
                elif state == "failed":
                    err_msg = file_result.get("err_msg", "未知错误")
                    raise Exception(f"解析失败: {err_msg}")
                    
            except requests.RequestException:
                continue

    def _download_and_extract(self, download_url, original_file):
        """下载并解压结果"""
        output_dir = Path(f"./output/{original_file.stem}")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            r = requests.get(download_url, timeout=300)
            zip_path = output_dir / "result.zip"
            with open(zip_path, 'wb') as f:
                f.write(r.content)
            
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(output_dir)
            
            zip_path.unlink()
            
            return output_dir
            
        except Exception as e:
            raise Exception(f"下载结果失败: {str(e)}")

# =========================================================
# 3. 格式转换器
# =========================================================
class FormatConverter:
    @staticmethod
    def save_md_content(content, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def get_md_file_path(folder):
        """查找 Markdown 文件（支持的目录结构）"""
        md_files = list(folder.glob("**/auto/*.md"))
        if not md_files:
            md_files = list(folder.glob("**/output.md"))
        if not md_files:
            md_files = list(folder.glob("**/*.md"))
        return md_files[0] if md_files else None

    @staticmethod
    def normalize_math_formulas(md_content):
        """标准化数学公式格式"""
        if not md_content: return ""
        
        md_content = re.sub(r'\\\(\s*', '$', md_content)
        md_content = re.sub(r'\s*\\\)', '$', md_content)
        md_content = re.sub(r'\\\[\s*', '\n$$\n', md_content)
        md_content = re.sub(r'\s*\\\]', '\n$$\n', md_content)
        md_content = re.sub(r'(?<!\$)\$\s+([^\$]+?)\s+\$(?!\$)', r'$\1$', md_content)
        md_content = re.sub(r'(?<!\$)\$\s+', '$', md_content)
        md_content = re.sub(r'\s+\$(?!\$)', '$', md_content)
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
                "-f", "markdown+tex_math_dollars"
            ])

            if math_mode == "mathml":
                cmd.append("--mathml")
            elif math_mode == "webtex":
                cmd.append("--webtex")
            elif math_mode == "mathjax":
                cmd.append("--mathjax")
            
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
# ⭐ 4. 文档统计工具（新增）
# =========================================================
class DocumentStats:
    @staticmethod
    def count_pdf_pages(pdf_path):
        """统计 PDF 页数"""
        if not PYPDF2_AVAILABLE:
            return None
        
        try:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF.PdfReader(f)
                return len(reader.pages)
        except Exception:
            return None
    
    @staticmethod
    def count_markdown_words(md_content):
        """统计 Markdown 字数（中英文）"""
        if not md_content:
            return 0, 0, 0
        
        # 移除代码块
        md_content = re.sub(r'```[\s\S]*?```', '', md_content)
        # 移除行内代码
        md_content = re.sub(r'`[^`]+`', '', md_content)
        # 移除图片
        md_content = re.sub(r'!\[.*?\]\(.*?\)', '', md_content)
        # 移除链接（保留文字）
        md_content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', md_content)
        # 移除 Markdown 标记
        md_content = re.sub(r'[#*_~`]', '', md_content)
        # 移除数学公式
        md_content = re.sub(r'\$\$[\s\S]*?\$\$', '', md_content)
        md_content = re.sub(r'\$[^\$]+\$', '', md_content)
        
        # 统计中文字符数（包括中文标点）
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', md_content))
        
        # 统计英文单词数
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', md_content))
        
        # 总字数（中文按字符计，英文按单词计）
        total_words = chinese_chars + english_words
        
        return total_words, chinese_chars, english_words

# =========================================================
# 5. Streamlit 主界面
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
    # ⭐ 新增：文档统计数据
    if "doc_stats" not in st.session_state:
        st.session_state.doc_stats = {}

    # ========== 侧边栏 ==========
    with st.sidebar:
        st.header("⚙️ 解析引擎设置")
        
        api_key_doc2x = st.text_input(
            "API Key (标准引擎)",
            type="password",
            help="使用 Doc2X 云端服务解析"
        )
        
        api_key_mineru = st.text_input(
            "API Key (期刊增强)",
            type="password",
            help="使用 期刊增加 在线服务解析（适合学术论文）"
        )
        
        if api_key_mineru:
            st.success("🚀 将使用 期刊增强 引擎")
            selected_engine = "mineru"
        elif api_key_doc2x:
            st.info("☁️ 将使用标准引擎")
            selected_engine = "doc2x"
        else:
            st.warning("请填写至少一个 API Key")
            selected_engine = None
        
        st.divider()
        
        st.subheader("📐 数学公式渲染")
        math_mode = st.radio(
            "选择渲染方式",
            ["mathml", "webtex", "mathjax"],
            index=0,
            help="**MathML**: EPUB标准格式(推荐)\n**WebTex**: 转为图片，兼容老设备\n**MathJax**: 需阅读器支持JS"
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
                            with st.spinner("正在转换..."):
                                FormatConverter.run_pandoc(
                                    docx_path, epub_path, "epub",
                                    source_filename=d2e_file.name,
                                    math_mode=st.session_state.math_mode
                                )
                            st.success("转换成功！")
                            with open(epub_path, "rb") as f:
                                st.download_button("📥 下载 EPUB", f, file_name=epub_path.name)
                    except Exception as e:
                        st.error(f"转换失败: {e}")

        st.divider()
        if st.button("🔄 重置所有状态"):
            st.session_state.clear()
            st.rerun()

    # ========== 主流程 ==========
    
    # 阶段 1: 上传
    if st.session_state.step == "upload":
        st.info("步骤 1/3: 上传 PDF 进行智能解析")
        uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

        if uploaded_file and st.button("🚀 开始解析"):
            if not selected_engine:
                st.error("请先在左侧填写 API Key（标准 或 期刊增强）")
                return
            
            try:
                temp_dir = Path("./temp_uploads")
                temp_dir.mkdir(exist_ok=True)
                pdf_path = (temp_dir / uploaded_file.name).resolve()
                with open(pdf_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # ⭐ 统计 PDF 页数
                pdf_pages = DocumentStats.count_pdf_pages(pdf_path)

                if selected_engine == "mineru":
                    st.info("🔬 使用期刊增强引擎解析...")
                    client = MinerUOnlineClient(api_key_mineru)
                    output_dir = client.process(pdf_path)
                else:
                    st.info("☁️ 使用  标准引擎解析...")
                    client = Doc2XPDFClient(api_key_doc2x)
                    output_dir = client.process(pdf_path)
                
                md_path = FormatConverter.get_md_file_path(output_dir)
                if not md_path:
                    raise Exception("未找到 Markdown 文件")
                
                with open(md_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # ⭐ 统计字数
                total_words, chinese_chars, english_words = DocumentStats.count_markdown_words(content)

                st.session_state.work_paths = {
                    "pdf": str(pdf_path),
                    "md": str(md_path.resolve()),
                    "dir": str(output_dir.resolve())
                }
                st.session_state.current_md_content = content
                
                # ⭐ 保存统计数据
                st.session_state.doc_stats = {
                    "pdf_pages": pdf_pages,
                    "total_words": total_words,
                    "chinese_chars": chinese_chars,
                    "english_words": english_words
                }
                
                st.session_state.step = "editing"
                st.rerun()
                
            except Exception as e:
                st.error(f"处理失败: {str(e)}")
                import traceback
                st.error(f"详细错误:\n```\n{traceback.format_exc()}\n```")

    # 阶段 2: 编辑
    elif st.session_state.step == "editing":
        paths = st.session_state.work_paths
        stats = st.session_state.doc_stats
        
        # ⭐ 显示文档统计信息
        col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
        
        with col_stat1:
            if stats.get("pdf_pages"):
                st.metric("📄 PDF 页数", f"{stats['pdf_pages']} 页")
            else:
                st.metric("📄 PDF 页数", "未知")
                if not PYPDF2_AVAILABLE:
                    st.caption("💡 安装 PyPDF2 可显示页数")
        
        with col_stat2:
            st.metric("📊 总字数", f"{stats.get('total_words', 0):,}")
        
        with col_stat3:
            st.metric("🇨🇳 中文字符", f"{stats.get('chinese_chars', 0):,}")
        
        with col_stat4:
            st.metric("🇬🇧 英文单词", f"{stats.get('english_words', 0):,}")
        
        st.divider()
        
        col1, col3 = st.columns([3, 1])
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
            st.warning("简易编辑模式")
            st.session_state.current_md_content = st.text_area(
                "Markdown",
                st.session_state.current_md_content,
                height=600
            )

    # 阶段 3: 导出
    elif st.session_state.step == "generating":
        st.subheader("步骤 3/3: 导出文档")
        paths = st.session_state.work_paths
        md_path = Path(paths["md"])
        output_dir = Path(paths["dir"])
        pdf_path = Path(paths["pdf"])
        math_mode = st.session_state.get('math_mode', 'mathml')
        
        st.write("1. 保存最终内容...")
        FormatConverter.save_md_content(st.session_state.current_md_content, md_path)
        
        try:
            st.write("2. 生成 Word 文档...")
            docx_path = output_dir / f"{md_path.stem}.docx"
            FormatConverter.run_pandoc(md_path, docx_path, "docx")
            
            st.write(f"3. 生成 EPUB 电子书 (渲染模式: {math_mode})...")
            epub_path = output_dir / f"{md_path.stem}.epub"
            FormatConverter.run_pandoc(
                md_path, epub_path, "epub",
                source_filename=pdf_path.name,
                math_mode=math_mode
            )
            
            st.success("✅ 所有任务完成！")
            
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
            st.error(f"转换出错: {e}")
            if st.button("重试"):
                st.rerun()

if __name__ == "__main__":
    main()
