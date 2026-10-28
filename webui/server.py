"""Breeze TTS 2 本地控制台。

在官方 ``breeze_infer.api`` 的 FastAPI 实例上挂载一个静态前端，**不改动上游源码**：
    - GET  /                     -> webui/index.html
    - GET  /webui/*              -> webui/ 静态资源
    - POST /api/save             -> 把前端生成的 WAV 落盘到项目 outputs 目录
    - GET  /api/voices           -> 列出音色库
    - POST /api/voices           -> 保存一个音色（含参考音频 + 参数配方）
    - DELETE /api/voices/{id}    -> 删除音色
    - GET  /api/voices/{id}/ref  -> 取回音色的参考音频
    - GET  /api/voices/{id}/sample -> 取回音色的试听样本
    - POST /api/log              -> 记录一次生成（写入本次会话日志 + manifest + 归档音频）
    - GET  /api/history          -> 读取历史生成记录（本次会话 + 之前会话）
    - GET  /api/history/{id}/wav -> 取回归档的音频
    - GET  /api/history/{id}/ref -> 取回归档的参考音频
    - GET  /api/session          -> 当前会话 id 与日志路径

每个进程启动都会新建 ``logs/session_<时间戳>.log``，所有生成流水都会追加进去，
同时写一条机器可读的 ``logs/manifest.jsonl``，音频归档在 ``outputs/gen/``。

用法：
    .venv\\Scripts\\python.exe -m webui.server checkpoints\\Breeze-TTS-2 --port 7860
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sys
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import breeze_infer.api as api
from breeze_infer.api import ApiSettings, ModelResolutionError, app, build_model_info, resolve_model_dir

WEBUI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEBUI_DIR.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
VOICES_DIR = PROJECT_ROOT / "voices"
LOGS_DIR = PROJECT_ROOT / "logs"
GEN_DIR = OUTPUTS_DIR / "gen"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-\u4e00-\u9fff]{1,120}$")
_SAFE_ID = re.compile(r"^v_[0-9a-f]{12}$")
_SAFE_GEN = re.compile(r"^g_[0-9a-f]{12}$")
MAX_SAVE_BYTES = 64 * 1024 * 1024
MAX_VOICE_NOTE = 2000
MAX_LOG_TEXT = 8000
MAX_HISTORY = 500

# 每次启动生成一个独立的会话日志，方便事后追溯
SESSION_ID = time.strftime("%Y-%m-%d_%H%M%S")
SESSION_LOG = LOGS_DIR / f"session_{SESSION_ID}.log"
MANIFEST = LOGS_DIR / "manifest.jsonl"
_log_lock = threading.Lock()


def slog(msg: str) -> None:
    """往本次会话日志追加一行（同时打到控制台）。"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with _log_lock:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with SESSION_LOG.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def _append_manifest(record: dict) -> None:
    with _log_lock:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_manifest() -> list[dict]:
    if not MANIFEST.is_file():
        return []
    items: list[dict] = []
    try:
        with MANIFEST.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return items


def _gen_path(gid: str, suffix: str) -> Path:
    if not _SAFE_GEN.match(gid):
        raise HTTPException(status_code=400, detail="非法的记录 id")
    path = GEN_DIR / f"{gid}{suffix}"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="归档文件不存在")
    return path



@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEBUI_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.post("/api/save", include_in_schema=False)
async def save_wav(request: Request, name: str = "breeze_webui.wav") -> JSONResponse:
    """把前端拿到的 WAV 字节写进 outputs/。

    前端只传文件名（无路径），这里再做一次白名单校验，防止路径穿越。
    """
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="非法的文件名")
    if not name.lower().endswith(".wav"):
        name += ".wav"

    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="内容为空")
    if len(payload) > MAX_SAVE_BYTES:
        raise HTTPException(status_code=413, detail="文件过大（上限 64 MB）")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    target = (OUTPUTS_DIR / name).resolve()
    if OUTPUTS_DIR.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="非法的目标路径")
    target.write_bytes(payload)
    return JSONResponse({"path": str(target), "bytes": len(payload)})


# ============================================================
# 音色库：把「参考音频 + 文字配方 + 参数」存成一个可复用的音色
# ============================================================
def _voice_path(vid: str) -> Path:
    if not _SAFE_ID.match(vid):
        raise HTTPException(status_code=400, detail="非法的音色 id")
    return VOICES_DIR / f"{vid}.json"


def _read_voice(vid: str) -> dict:
    path = _voice_path(vid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="音色不存在")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/voices", include_in_schema=False)
def list_voices() -> JSONResponse:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(VOICES_DIR.glob("v_*.json")):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return JSONResponse({"voices": items})


@app.post("/api/voices", include_in_schema=False)
async def create_voice(request: Request) -> JSONResponse:
    """保存音色。

    multipart 字段：
        name       音色名（必填）
        mode       design / clone / direct
        instruction 音色描述或导演指令（可为空）
        cfg        CFG（数字）
        seed       种子（整数）
        refText    参考音频的逐字文本
        note       备注
        sampleText 试听样本对应的文本
        refAudio   参考音频文件（可选）
        sample     试听样本 WAV（可选）
    """
    form = await request.form()
    name = str(form.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="音色名不能为空")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="音色名过长（上限 60 字）")

    vid = "v_" + secrets.token_hex(6)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)

    ref_name = None
    ref_audio = form.get("refAudio")
    if ref_audio is not None and hasattr(ref_audio, "read"):
        payload = await ref_audio.read()
        if payload:
            if len(payload) > MAX_SAVE_BYTES:
                raise HTTPException(status_code=413, detail="参考音频过大（上限 64 MB）")
            ref_name = f"{vid}_ref.wav"
            (VOICES_DIR / ref_name).write_bytes(payload)

    sample_name = None
    sample = form.get("sample")
    if sample is not None and hasattr(sample, "read"):
        payload = await sample.read()
        if payload:
            if len(payload) > MAX_SAVE_BYTES:
                raise HTTPException(status_code=413, detail="试听样本过大（上限 64 MB）")
            sample_name = f"{vid}_sample.wav"
            (VOICES_DIR / sample_name).write_bytes(payload)

    record = {
        "id": vid,
        "name": name,
        "mode": str(form.get("mode") or "design"),
        "instruction": str(form.get("instruction") or ""),
        "cfg": float(form.get("cfg") or 4),
        "seed": int(float(form.get("seed") or 42)),
        "refText": str(form.get("refText") or ""),
        "note": str(form.get("note") or "")[:MAX_VOICE_NOTE],
        "sampleText": str(form.get("sampleText") or ""),
        "refFile": ref_name,
        "sampleFile": sample_name,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (VOICES_DIR / f"{vid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return JSONResponse(record)


@app.delete("/api/voices/{vid}", include_in_schema=False)
def delete_voice(vid: str) -> JSONResponse:
    record = _read_voice(vid)
    for key in ("refFile", "sampleFile"):
        fname = record.get(key)
        if fname and _SAFE_NAME.match(fname):
            (VOICES_DIR / fname).unlink(missing_ok=True)
    _voice_path(vid).unlink(missing_ok=True)
    return JSONResponse({"deleted": vid})


@app.get("/api/voices/{vid}/ref", include_in_schema=False)
def get_voice_ref(vid: str) -> FileResponse:
    record = _read_voice(vid)
    fname = record.get("refFile")
    if not fname:
        raise HTTPException(status_code=404, detail="该音色没有参考音频")
    path = VOICES_DIR / fname
    if not path.is_file():
        raise HTTPException(status_code=404, detail="参考音频文件丢失")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voices/{vid}/sample", include_in_schema=False)
def get_voice_sample(vid: str) -> FileResponse:
    record = _read_voice(vid)
    fname = record.get("sampleFile")
    if not fname:
        raise HTTPException(status_code=404, detail="该音色没有试听样本")
    path = VOICES_DIR / fname
    if not path.is_file():
        raise HTTPException(status_code=404, detail="试听样本文件丢失")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/session", include_in_schema=False)
def get_session() -> JSONResponse:
    """当前进程的会话信息，前端启动时拉一次用于显示。"""
    return JSONResponse({
        "session": SESSION_ID,
        "log": str(SESSION_LOG),
        "manifest": str(MANIFEST),
        "archive": str(GEN_DIR),
    })


@app.post("/api/log", include_in_schema=False)
async def log_generation(request: Request) -> JSONResponse:
    """记录一次生成。

    multipart 字段（全部可选，除 text/texts 至少一个）：
        mode / endpoint / locked / batch / text / texts / instruction /
        cfg / seed / refName / refText / ttfa / total / dur / sampleRate /
        voice / ok / error
    文件字段：
        wav  本次生成的 WAV（归档到 outputs/gen/）
        ref  本次使用的参考音频（归档，便于以后原样重放）
    """
    form = await request.form()
    gid = "g_" + secrets.token_hex(6)
    GEN_DIR.mkdir(parents=True, exist_ok=True)

    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(form.get(key) or default)
        except Exception:
            return default

    def _b(key: str) -> bool:
        return str(form.get(key) or "").lower() in ("1", "true", "yes", "on")

    wav_sha = None
    wav_bytes = 0
    wav_file = form.get("wav")
    if wav_file is not None and hasattr(wav_file, "read"):
        payload = await wav_file.read()
        if payload:
            if len(payload) > MAX_SAVE_BYTES:
                raise HTTPException(status_code=413, detail="音频过大（上限 64 MB）")
            (GEN_DIR / f"{gid}.wav").write_bytes(payload)
            wav_sha = hashlib.sha256(payload).hexdigest()
            wav_bytes = len(payload)

    has_ref = False
    ref_file = form.get("ref")
    if ref_file is not None and hasattr(ref_file, "read"):
        payload = await ref_file.read()
        if payload:
            if len(payload) > MAX_SAVE_BYTES:
                raise HTTPException(status_code=413, detail="参考音频过大（上限 64 MB）")
            (GEN_DIR / f"{gid}_ref.wav").write_bytes(payload)
            has_ref = True

    texts_raw = str(form.get("texts") or "").strip()
    texts: list[str] = []
    if texts_raw:
        try:
            parsed = json.loads(texts_raw)
            if isinstance(parsed, list):
                texts = [str(x) for x in parsed]
        except Exception:
            texts = [texts_raw]

    dur = _f("dur")
    total = _f("total")
    record = {
        "id": gid,
        "session": SESSION_ID,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": str(form.get("mode") or "design"),
        "endpoint": str(form.get("endpoint") or "/v1/audio/speech"),
        "locked": _b("locked"),
        "batch": _b("batch"),
        "ok": str(form.get("ok") or "1").lower() not in ("0", "false"),
        "error": str(form.get("error") or ""),
        "text": str(form.get("text") or "")[:MAX_LOG_TEXT],
        "texts": [t[:MAX_LOG_TEXT] for t in texts],
        "instruction": str(form.get("instruction") or "")[:MAX_LOG_TEXT],
        "cfg": _f("cfg", 1.0),
        "seed": int(_f("seed", 42)),
        "refName": str(form.get("refName") or ""),
        "refText": str(form.get("refText") or "")[:MAX_LOG_TEXT],
        "voice": str(form.get("voice") or ""),
        "ttfa": _f("ttfa", -1) if str(form.get("ttfa") or "") != "" else None,
        "total": total,
        "dur": dur,
        "rtf": round(total / 1000.0 / dur, 3) if dur > 0 else None,
        "sampleRate": int(_f("sampleRate", 24000)),
        "wavSha256": wav_sha,
        "wavBytes": wav_bytes,
        "hasWav": wav_sha is not None,
        "hasRef": has_ref,
    }
    _append_manifest(record)

    tag = "可复现" if record["locked"] else "流式"
    slog(
        f"生成 {gid} · {record['mode']} · {tag} · seed={record['seed']} "
        f"cfg={record['cfg']} · {dur:.2f}s 音频 · 用时 {total / 1000:.2f}s "
        f"· sha256={(wav_sha or '-')[:16]}"
    )
    if record["text"]:
        slog(f"  文本: {record['text'][:120]}")
    if record["instruction"]:
        slog(f"  音色: {record['instruction'][:120]}")
    if record["refName"]:
        slog(f"  参考: {record['refName']} · 文本「{record['refText'][:60]}」")

    return JSONResponse({"id": gid, "record": record})


@app.get("/api/history", include_in_schema=False)
def get_history(limit: int = 200, session: str | None = None) -> JSONResponse:
    """历史生成记录，新的在前。

    session 传具体值可只看某一次会话；默认返回全部（跨会话）。
    """
    items = _read_manifest()
    if session:
        items = [x for x in items if x.get("session") == session]
    items = items[-max(1, min(limit, MAX_HISTORY)):]
    items.reverse()
    return JSONResponse({"items": items, "session": SESSION_ID})


@app.get("/api/history/{gid}/wav", include_in_schema=False)
def get_history_wav(gid: str) -> FileResponse:
    return FileResponse(_gen_path(gid, ".wav"), media_type="audio/wav")


@app.get("/api/history/{gid}/ref", include_in_schema=False)
def get_history_ref(gid: str) -> FileResponse:
    return FileResponse(_gen_path(gid, "_ref.wav"), media_type="audio/wav")


app.mount("/webui", StaticFiles(directory=str(WEBUI_DIR)), name="webui")


def main() -> None:
    parser = argparse.ArgumentParser(description="Breeze TTS 2 本地控制台（WebUI + API）")
    parser.add_argument("model", help="本地模型目录，或 Hugging Face repo id")
    parser.add_argument("--revision", help="repo id 的 revision，本地目录会被忽略")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--fast-all", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--fast-text-encoder", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fast-backbone-prefill", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fast-backbone-decode", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fast-depth-decoder", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fast-codec", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    try:
        model_dir = resolve_model_dir(args.model, args.revision)
    except ModelResolutionError as exc:
        parser.error(str(exc))

    api._settings = ApiSettings(
        model=model_dir,
        fast_all=args.fast_all,
        fast_text_encoder=args.fast_text_encoder,
        fast_backbone_prefill=args.fast_backbone_prefill,
        fast_backbone_decode=args.fast_backbone_decode,
        fast_depth_decoder=args.fast_depth_decoder,
        fast_codec=args.fast_codec,
        model_info=build_model_info(model_dir),
    )

    print("=" * 62, flush=True)
    print("  Breeze TTS 2 本地控制台", flush=True)
    print(f"  界面  http://{args.host}:{args.port}/", flush=True)
    print(f"  接口  http://{args.host}:{args.port}/v1/audio/speech", flush=True)
    print(f"  文档  http://{args.host}:{args.port}/docs", flush=True)
    print("=" * 62, flush=True)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    slog("=" * 58)
    slog(f"会话开始 {SESSION_ID}")
    slog(f"模型   {model_dir}")
    slog(f"监听   http://{args.host}:{args.port}/")
    slog(f"日志   {SESSION_LOG}")
    slog("=" * 58)

    import uvicorn

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        slog(f"会话结束 {SESSION_ID}")


if __name__ == "__main__":
    sys.exit(main())
