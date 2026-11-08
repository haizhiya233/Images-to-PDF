#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Images-to-PDF 手机端：在手机上跑一个本地网页，用浏览器选文件夹、点一下出 PDF。

启动（Termux）：
    python mobile_app.py                # 只监听 127.0.0.1:8765
    python mobile_app.py --open         # 顺便用默认浏览器打开
    python mobile_app.py --host 0.0.0.0 --port 8765   # 允许同局域网其他设备访问

产物默认写到 /storage/emulated/0/Download/Images-to-PDF，
在手机「文件管理 → 下载」里直接能看到，也能用 termux-open 调起 PDF 阅读器。

全部标准库；只依赖 ffmpeg（非 JPEG / progressive / 带旋转照片的重编码）。
"""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.parse

from pdf_builder import build_pdf, ConversionCancelled, PageError
from folder_to_pdf import natural_key, IMAGE_EXTS, subfolders_with_images

DEFAULT_OUTPUT_DIR = Path("/storage/emulated/0/Download/Images-to-PDF")
DEFAULT_PORT = 8765

# 允许浏览的根目录（手机存储 + Termux 家目录）。只监听回环，仍做一层约束。
def _allowed_roots():
    roots = [Path.home().resolve()]
    for p in ("/storage/emulated/0", "/sdcard"):
        try:
            roots.append(Path(p).resolve())
        except OSError:
            pass
    # Termux 的临时目录（很多用户在这里解包图片 / 从分享接收文件）
    try:
        roots.append(Path(tempfile.gettempdir()).resolve())
    except OSError:
        pass
    seen = []
    for r in roots:
        if r not in seen:
            seen.append(r)
    return seen


ALLOWED_ROOTS = _allowed_roots()


def safe_path(raw, must_exist=True):
    """把用户给的路径限制在允许的根目录内，返回 Path。"""
    p = Path(str(raw)).expanduser()
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        raise ValueError("路径无法解析：%s" % raw)
    if not any(p == r or r in p.parents for r in ALLOWED_ROOTS):
        raise ValueError("路径不在允许范围内（仅可访问手机存储 / Termux 家目录）")
    if must_exist and not p.exists():
        raise ValueError("路径不存在：%s" % p)
    return p


def list_folder(raw):
    """列目录：子文件夹 + 顶层图片，按自然序。"""
    p = safe_path(raw)
    if not p.is_dir():
        raise ValueError("不是文件夹：%s" % p)

    dirs = []
    for d in p.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            try:
                n_images = sum(
                    1 for x in d.iterdir()
                    if x.is_file() and x.suffix.lower() in IMAGE_EXTS
                )
            except OSError:
                n_images = 0
            dirs.append({"name": d.name, "path": str(d), "images": n_images})
    dirs.sort(key=lambda x: natural_key(x["name"]))

    images = [
        {"name": f.name, "path": str(f), "size": f.stat().st_size}
        for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    ]
    images.sort(key=lambda x: natural_key(x["name"]))

    parent = str(p.parent) if p.parent != p else str(p)
    return {
        "path": str(p),
        "parent": parent,
        "dirs": dirs,
        "images": images[:60],
        "image_count": len(images),
    }


class Job:
    """一次转换任务的状态。手机同一时间只跑一个，避免多个 ffmpeg 抢 CPU。"""

    def __init__(self):
        self.id = 0
        self.state = "idle"          # idle / running / done / cancelled / error
        self.mode = "single"
        self.folder = ""
        self.total = 0               # 目标文件夹数（批量）或 1（单个）
        self.done = 0                # 已完成的 PDF 个数
        self.pages_total = 0         # 所有 PDF 的总页数
        self.pages_done = 0          # 已写入的页数
        self.current = ""
        self.message = ""
        self.results = []            # [{name, pages, size, output, reencoded}]
        self.cancel_flag = threading.Event()

    def to_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "mode": self.mode,
            "folder": self.folder,
            "total": self.total,
            "done": self.done,
            "pages_total": self.pages_total,
            "pages_done": self.pages_done,
            "current": self.current,
            "message": self.message,
            # 浅拷贝：后台线程可能正在 append，别让 json 序列化遍历到半截状态
            "results": list(self.results),
        }


JOB = Job()
JOB_LOCK = threading.Lock()
JOB_COUNTER = [0]


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%.1f TB" % n


def _images_in(folder):
    """某文件夹顶层图片，自然序（与 Windows 版 collect_images 一致，但不抛空异常）。"""
    return sorted(
        [x for x in folder.iterdir()
         if x.is_file() and x.suffix.lower() in IMAGE_EXTS],
        key=lambda x: natural_key(x.name),
    )


def run_job(job, folder, mode, page_size, quality, output_dir):
    """后台线程：单文件夹 或 批量（每个子文件夹一个 PDF）。"""
    try:
        out_dir = safe_path(output_dir, must_exist=False)
        out_dir.mkdir(parents=True, exist_ok=True)

        if mode == "batch":
            targets = [(s, s.name) for s in subfolders_with_images(folder)]
        else:
            targets = [(folder, folder.name)]

        # 预先算总页数，进度条按页推进（比按文件夹推进细腻得多）
        plan = [(name, _images_in(target)) for target, name in targets]
        plan = [(name, imgs) for name, imgs in plan if imgs]
        if not plan:
            job.state = "error"
            job.message = "没有找到可转换的图片" if mode == "single" else "没有找到含图片的子文件夹"
            return

        job.total = len(plan)
        job.pages_total = sum(len(imgs) for _, imgs in plan)
        job.done = 0
        job.pages_done = 0

        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        for name, images in plan:
            if job.cancel_flag.is_set():
                job.state = "cancelled"
                job.message = "已停止"
                return
            job.current = name
            out_pdf = out_dir / ("%s.pdf" % name)

            def progress(done, total, img_name, reencoded, _name=name, _n=len(images)):
                job.pages_done = min(job.pages_total, job.pages_done + 1)
                job.message = "%s：第 %d/%d 页 %s%s" % (
                    _name, done, total, img_name, "（已转码）" if reencoded else ""
                )

            result = build_pdf(
                images, out_pdf,
                page_size=page_size,
                quality=quality,
                ffmpeg=ffmpeg,
                progress=progress,
                should_cancel=job.cancel_flag.is_set,
            )
            job.results.append({
                "name": name,
                "pages": result["pages"],
                "size": result["size"],
                "size_h": _human(result["size"]),
                "output": result["output"],
                "reencoded": result["reencoded"],
            })
            job.done += 1
            job.message = "完成：%s（%d 页，%s）" % (
                name, result["pages"], _human(result["size"])
            )

        if job.cancel_flag.is_set():
            job.state = "cancelled"
            job.message = "已停止"
        else:
            job.state = "done"
            job.message = "全部完成，共 %d 个 PDF" % len(job.results)
    except ConversionCancelled:
        job.state = "cancelled"
        job.message = "已停止"
    except Exception as e:
        job.state = "error"
        job.message = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()


def start_job(folder_raw, mode, page_size, quality, output_dir_raw):
    # 先做全部校验，再改全局状态：任何参数错误都不能把 JOB 卡在 running
    folder = safe_path(folder_raw)
    if not folder.is_dir():
        raise ValueError("不是文件夹：%s" % folder)
    if mode not in ("single", "batch"):
        raise ValueError("mode 必须是 single 或 batch")
    if page_size not in ("auto", "a4"):
        raise ValueError("page_size 必须是 auto 或 a4")
    quality = max(1, min(31, int(quality)))
    output_dir = str(safe_path(output_dir_raw, must_exist=False))

    with JOB_LOCK:
        if JOB.state == "running":
            raise RuntimeError("已有任务正在进行，请先等它结束或点「停止」")
        JOB_COUNTER[0] += 1
        JOB.id = JOB_COUNTER[0]
        JOB.state = "running"
        JOB.mode = mode
        JOB.folder = str(folder)
        JOB.total = 0
        JOB.done = 0
        JOB.pages_total = 0
        JOB.pages_done = 0
        JOB.current = ""
        JOB.message = "准备中…"
        JOB.results = []
        JOB.cancel_flag = threading.Event()

    t = threading.Thread(
        target=run_job,
        args=(JOB, folder, mode, page_size, quality, output_dir),
        daemon=True,
    )
    t.start()
    return JOB.id


# ---------------------------------------------------------------- 页面 HTML

INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>图片转 PDF · 手机版</title>
<style>
:root{--bg:#12151c;--card:#1c212c;--line:#2c3444;--txt:#e8edf6;--dim:#8b97ab;--acc:#4c9aff;--ok:#3ddc97;--bad:#ff6b6b}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;padding-bottom:40px}
header{position:sticky;top:0;z-index:5;background:#12151cee;backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:12px 14px}
h1{font-size:17px;margin:0 0 8px;font-weight:650}
.crumb{font-size:12px;color:var(--dim);word-break:break-all;line-height:1.35;max-height:3.9em;overflow:hidden}
.wrap{padding:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
.card h2{font-size:14px;margin:0 0 10px;color:var(--dim);font-weight:600;letter-spacing:.3px}
button{font:inherit;color:var(--txt);background:#263044;border:1px solid var(--line);border-radius:11px;padding:11px 14px;min-height:44px;cursor:pointer}
button:active{transform:scale(.98)}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:650}
button.ghost{background:transparent}
button.stop{background:#4a2730;border-color:#6b3540}
button:disabled{opacity:.45}
.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.row>button{flex:1;min-width:100px}
input,select{font:inherit;width:100%;background:#141a24;color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:10px 11px;min-height:44px}
label{display:block;font-size:12px;color:var(--dim);margin:10px 0 5px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.list{max-height:46vh;overflow:auto;-webkit-overflow-scrolling:touch}
.item{display:flex;align-items:center;gap:11px;padding:11px 4px;border-bottom:1px solid var(--line);cursor:pointer}
.item:last-child{border-bottom:0}
.ico{font-size:19px;width:26px;text-align:center;flex:none}
.nm{flex:1;min-width:0;word-break:break-all;font-size:14px}
.sub{color:var(--dim);font-size:11px;white-space:nowrap;flex:none}
.thumbs{display:flex;gap:8px;overflow-x:auto;padding:4px 0 2px;-webkit-overflow-scrolling:touch}
.thumbs img{height:92px;border-radius:8px;background:#000;flex:none}
.bar{height:9px;background:#0e131c;border-radius:9px;overflow:hidden;margin:10px 0 6px}
.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--ok));transition:width .25s}
.msg{font-size:13px;color:var(--dim);word-break:break-all;min-height:1.4em}
.res{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--line);font-size:13px}
.res:last-child{border-bottom:0}
.res .nm{color:var(--txt)}
.res button{flex:none;padding:8px 12px;min-height:38px;font-size:13px}
.tag{font-size:11px;padding:2px 7px;border-radius:6px;background:#263044;color:var(--dim)}
.empty{color:var(--dim);font-size:13px;padding:16px 0;text-align:center}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#2b3446;border:1px solid var(--line);padding:10px 16px;border-radius:10px;font-size:13px;z-index:20;max-width:88vw;text-align:center}
.hidden{display:none}
</style>
</head>
<body>
<header>
  <h1>🖼️ 图片转 PDF · 手机版</h1>
  <div class="crumb" id="crumb">加载中…</div>
</header>
<div class="wrap">

  <div class="card">
    <h2>① 选择图片文件夹</h2>
    <div class="row">
      <button class="ghost" onclick="go(parentPath)">⬆ 上一级</button>
      <button class="ghost" onclick="go('/storage/emulated/0/DCIM')">📷 DCIM</button>
      <button class="ghost" onclick="go('/storage/emulated/0/Pictures')">🖼 图片</button>
      <button class="ghost" onclick="go('/storage/emulated/0/Download')">⬇ 下载</button>
    </div>
    <label>或直接输入完整路径</label>
    <div class="row">
      <input id="pathInput" placeholder="/storage/emulated/0/DCIM/Camera" style="flex:1;min-width:180px">
      <button class="ghost" style="flex:none;min-width:70px" onclick="go(document.getElementById('pathInput').value)">跳转</button>
    </div>
    <div class="list" id="dirs"></div>
    <div class="sub" id="imgcount" style="margin-top:8px"></div>
    <div class="thumbs" id="thumbs"></div>
  </div>

  <div class="card">
    <h2>② 转换设置</h2>
    <div class="grid2">
      <div><label>模式</label>
        <select id="mode">
          <option value="single">单个 PDF（本文件夹图片）</option>
          <option value="batch">批量（每个子文件夹一个）</option>
        </select></div>
      <div><label>页面尺寸</label>
        <select id="pageSize">
          <option value="auto">原图尺寸（1px=1pt）</option>
          <option value="a4">A4 纵向等比居中</option>
        </select></div>
    </div>
    <label>非 JPEG 转码质量（ffmpeg -q:v，1 最好 / 31 最小）</label>
    <input id="quality" type="number" value="2" min="1" max="31">
    <label>PDF 输出目录</label>
    <input id="outDir" value="/storage/emulated/0/Download/Images-to-PDF">
    <div class="row" style="margin-top:14px">
      <button class="primary" id="btnGo" onclick="startConvert()">🚀 开始转换</button>
      <button class="stop" id="btnStop" onclick="cancelJob()">停止</button>
    </div>
  </div>

  <div class="card">
    <h2>③ 进度与结果</h2>
    <div class="bar"><i id="barFill"></i></div>
    <div class="msg" id="msg">空闲</div>
    <div id="results" style="margin-top:8px"></div>
    <div class="row" style="margin-top:10px">
      <button class="ghost" onclick="showOutputs()">📂 查看输出目录</button>
    </div>
  </div>
</div>

<script>
let curPath='/storage/emulated/0/DCIM', parentPath='/storage/emulated/0', poll=null;
const $=id=>document.getElementById(id);
function toast(t){const e=document.createElement('div');e.className='toast';e.textContent=t;document.body.appendChild(e);setTimeout(()=>e.remove(),2600)}
async function api(url,opt){const r=await fetch(url,opt);const j=await r.json();if(!r.ok||j.error)throw new Error(j.error||('HTTP '+r.status));return j}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function enc(p){return encodeURIComponent(p)}

async function go(p){
  if(!p)return;
  try{
    const d=await api('/api/browse?path='+enc(p));
    curPath=d.path;parentPath=d.parent;
    $('crumb').textContent=curPath;
    $('pathInput').value=curPath;
    $('dirs').innerHTML=d.dirs.length?d.dirs.map(x=>
      `<div class="item" data-path="${esc(x.path)}" onclick="go(this.dataset.path)"><span class="ico">📁</span><span class="nm">${esc(x.name)}</span><span class="sub">${x.images?x.images+' 张':'空'}</span></div>`
    ).join(''):'<div class="empty">此目录没有子文件夹</div>';
    $('imgcount').textContent='本文件夹图片：'+d.image_count+' 张'+(d.image_count>60?'（预览前 60 张）':'');
    $('thumbs').innerHTML=d.images.map(x=>
      `<img loading="lazy" src="/api/thumb?path=${enc(x.path)}" alt="${esc(x.name)}">`
    ).join('')||'<div class="empty">此文件夹没有图片</div>';
    $('mode').value=d.dirs.some(x=>x.images>0)?'batch':'single';
  }catch(e){toast('打开失败：'+e.message)}
}

async function startConvert(){
  try{
    const body=JSON.stringify({path:curPath,mode:$('mode').value,page_size:$('pageSize').value,
      quality:Number($('quality').value),output_dir:$('outDir').value});
    await api('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},body});
    $('results').innerHTML='';$('btnGo').disabled=true;
    if(poll)clearInterval(poll);poll=setInterval(status,450);status();
  }catch(e){toast(e.message)}
}
async function cancelJob(){try{await api('/api/cancel',{method:'POST'});toast('正在停止…')}catch(e){toast(e.message)}}
async function status(){
  try{
    const s=await api('/api/status');
    const total=s.pages_total||s.total||1;
    const done=s.pages_total?s.pages_done:s.done;
    $('barFill').style.width=(done/total*100)+'%';
    const finished=s.state!=='running';
    $('msg').textContent=(!finished?'⏳ ':'')+s.message+
      (!finished&&s.pages_total?' · 共 '+s.pages_done+'/'+s.pages_total+' 页':'')+
      (!finished&&s.current?' · '+s.current:'');
    $('results').innerHTML=s.results.map(r=>
      `<div class="res"><span class="ico">📄</span><span class="nm">${esc(r.name)}.pdf<br><span class="sub">${r.pages} 页 · ${esc(r.size_h)}${r.reencoded?' · '+r.reencoded+' 张转码':''}</span></span><button data-path="${esc(r.output)}" onclick="openPdf(this.dataset.path)">打开</button></div>`
    ).join('');
    if(finished){clearInterval(poll);poll=null;$('btnGo').disabled=false;
      if(s.state==='done')toast('✅ '+s.message);
      else if(s.state==='error')toast('❌ '+s.message);
      else if(s.state==='cancelled')toast('已停止');}
  }catch(e){}
}
async function openPdf(p){try{await api('/api/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p})});toast('已调起 PDF 阅读器')}catch(e){toast(e.message)}}
async function showOutputs(){go($('outDir').value)}
// 同步服务端的默认输出目录 / 起始位置后再加载首页
api('/api/defaults').then(d=>{
  $('outDir').value=d.output_dir;
  if(d.start)curPath=d.start+'/DCIM';
}).catch(()=>{}).finally(()=>go(curPath));
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ImagesToPDFMobile/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _err(self, msg, code=400):
        self._json({"error": str(msg)}, code)

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("请求体不是合法 JSON")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            elif path == "/api/browse":
                q = self._query()
                raw = q.get("path", [str(ALLOWED_ROOTS[-1])])[0]
                self._json(list_folder(raw))
            elif path == "/api/thumb":
                raw = self._query().get("path", [""])[0]
                p = safe_path(raw)
                if not p.is_file():
                    raise ValueError("不是文件")
                ext = p.suffix.lower()
                passthrough = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jpe": "image/jpeg",
                    ".jfif": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                    ".gif": "image/gif", ".bmp": "image/bmp",
                }
                if ext in passthrough:
                    self._send(200, p.read_bytes(), passthrough[ext])
                else:
                    # HEIC/AVIF/TIFF 等浏览器不认的格式，用 ffmpeg 转一张缩略图
                    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
                    proc = subprocess.run(
                        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                         "-i", str(p), "-frames:v", "1",
                         "-vf", "scale='min(360,iw)':-1",
                         "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                        capture_output=True, timeout=60,
                    )
                    if proc.returncode != 0:
                        raise ValueError("无法生成缩略图")
                    self._send(200, proc.stdout, "image/jpeg")
            elif path == "/api/status":
                with JOB_LOCK:
                    self._json(JOB.to_dict())
            elif path == "/api/defaults":
                # 默认起始位置显式指向手机存储；ALLOWED_ROOTS[-1] 可能是临时目录
                start = "/storage/emulated/0"
                if not Path(start).is_dir():
                    start = next(
                        (str(r) for r in ALLOWED_ROOTS if "storage" in str(r)),
                        str(Path.home()),
                    )
                self._json({
                    "output_dir": str(DEFAULT_OUTPUT_DIR),
                    "start": start,
                    "ffmpeg": shutil.which("ffmpeg"),
                })
            else:
                self._err("未知接口", 404)
        except ValueError as e:
            self._err(e)
        except Exception as e:
            traceback.print_exc()
            self._err("服务器内部错误：%s" % e, 500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/convert":
                b = self._body()
                jid = start_job(
                    b.get("path", ""),
                    b.get("mode", "single"),
                    b.get("page_size", "auto"),
                    b.get("quality", 2),
                    b.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
                )
                self._json({"job_id": jid, "ok": True})
            elif path == "/api/cancel":
                with JOB_LOCK:
                    if JOB.state == "running":
                        JOB.cancel_flag.set()
                    state = JOB.state
                self._json({"ok": True, "state": state})
            elif path == "/api/open":
                p = safe_path(self._body().get("path", ""))
                if not p.is_file():
                    raise ValueError("文件不存在：%s" % p)
                try:
                    subprocess.Popen(
                        ["termux-open", "--view", str(p)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    self._json({"ok": True})
                except FileNotFoundError:
                    self._json({"ok": False, "path": str(p),
                                "error": "termux-open 不可用，请手动到下载目录打开"})
            else:
                self._err("未知接口", 404)
        except ValueError as e:
            self._err(e)
        except RuntimeError as e:
            self._err(e, 409)
        except Exception as e:
            traceback.print_exc()
            self._err("服务器内部错误：%s" % e, 500)


def main():
    ap = argparse.ArgumentParser(description="Images-to-PDF 手机端（本地网页）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="端口，默认 8765")
    ap.add_argument("--open", action="store_true", help="启动后用默认浏览器打开")
    args = ap.parse_args()

    url = "http://127.0.0.1:%d" % args.port
    if not shutil.which("ffmpeg"):
        print("⚠ 未找到 ffmpeg：非 JPEG / 带旋转的照片将无法转换。")
        print("  安装：pkg install ffmpeg")
    else:
        print("✓ ffmpeg:", shutil.which("ffmpeg"))
    print("✓ 输出目录:", DEFAULT_OUTPUT_DIR)
    print("✓ 手机浏览器打开:", url)
    print("  （Ctrl+C 停止服务）")

    if args.open:
        try:
            subprocess.Popen(["termux-open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
