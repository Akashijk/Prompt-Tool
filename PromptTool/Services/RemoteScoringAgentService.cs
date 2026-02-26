using System;
using System.Text;

namespace PromptTool.Services;

public static class RemoteScoringAgentService
{
    public static string BuildInstallScript(string installDir, int port)
    {
        var dir = string.IsNullOrWhiteSpace(installDir) ? "$HOME/prompttool-aesthetic" : installDir;
        var sb = new StringBuilder();
        sb.AppendLine("#!/usr/bin/env bash");
        sb.AppendLine("set -euo pipefail");
        sb.AppendLine($"INSTALL_DIR=\"{dir}\"");
        sb.AppendLine($"PORT=\"{port}\"");
        sb.AppendLine("mkdir -p \"$INSTALL_DIR\"");
        sb.AppendLine("python3 -m venv \"$INSTALL_DIR/venv\"");
        sb.AppendLine("\"$INSTALL_DIR/venv/bin/pip\" install --upgrade pip");
        sb.AppendLine("\"$INSTALL_DIR/venv/bin/pip\" install fastapi uvicorn[standard] onnxruntime pillow requests");
        sb.AppendLine("cat > \"$INSTALL_DIR/server.py\" <<'PY'");
        sb.AppendLine("from fastapi import FastAPI, UploadFile");
        sb.AppendLine("from fastapi.responses import JSONResponse");
        sb.AppendLine("import io, os, math, requests");
        sb.AppendLine("from PIL import Image");
        sb.AppendLine("import numpy as np");
        sb.AppendLine("import onnxruntime as ort");
        sb.AppendLine("app = FastAPI()");
        sb.AppendLine("MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')");
        sb.AppendLine("CLIP_URL = 'https://huggingface.co/openai/clip-vit-base-patch32/resolve/main/onnx/model.onnx'");
        sb.AppendLine("AESTHETIC_URL = 'https://huggingface.co/LAION/aesthetic-predictor/resolve/main/aesthetic_predictor.onnx'");
        sb.AppendLine("CLIP_PATH = os.path.join(MODEL_DIR, 'clip_vision.onnx')");
        sb.AppendLine("AESTHETIC_PATH = os.path.join(MODEL_DIR, 'aesthetic_head.onnx')");
        sb.AppendLine("MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)");
        sb.AppendLine("STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)");
        sb.AppendLine("INPUT_SIZE = 224");
        sb.AppendLine("clip_session = None");
        sb.AppendLine("aesthetic_session = None");
        sb.AppendLine("def download(url, path):");
        sb.AppendLine("    os.makedirs(os.path.dirname(path), exist_ok=True)");
        sb.AppendLine("    if os.path.exists(path): return");
        sb.AppendLine("    with requests.get(url, stream=True, timeout=120) as r:");
        sb.AppendLine("        r.raise_for_status()");
        sb.AppendLine("        with open(path, 'wb') as f:");
        sb.AppendLine("            for chunk in r.iter_content(chunk_size=1024*1024):");
        sb.AppendLine("                if chunk: f.write(chunk)");
        sb.AppendLine("def ensure_models():");
        sb.AppendLine("    download(CLIP_URL, CLIP_PATH)");
        sb.AppendLine("    download(AESTHETIC_URL, AESTHETIC_PATH)");
        sb.AppendLine("    global clip_session, aesthetic_session");
        sb.AppendLine("    if clip_session is None: clip_session = ort.InferenceSession(CLIP_PATH, providers=['CPUExecutionProvider'])");
        sb.AppendLine("    if aesthetic_session is None: aesthetic_session = ort.InferenceSession(AESTHETIC_PATH, providers=['CPUExecutionProvider'])");
        sb.AppendLine("def preprocess(img):");
        sb.AppendLine("    img = img.convert('RGB').resize((INPUT_SIZE, INPUT_SIZE))");
        sb.AppendLine("    arr = np.asarray(img).astype(np.float32) / 255.0");
        sb.AppendLine("    arr = (arr - MEAN) / STD");
        sb.AppendLine("    arr = np.transpose(arr, (2, 0, 1))");
        sb.AppendLine("    return arr[np.newaxis, :]");
        sb.AppendLine("def normalize(vec):");
        sb.AppendLine("    norm = math.sqrt(float(np.sum(vec * vec)))");
        sb.AppendLine("    return vec / norm if norm > 0 else vec");
        sb.AppendLine("@app.post('/score')");
        sb.AppendLine("async def score(file: UploadFile):");
        sb.AppendLine("    ensure_models()");
        sb.AppendLine("    data = await file.read()");
        sb.AppendLine("    img = Image.open(io.BytesIO(data))");
        sb.AppendLine("    inp = preprocess(img)");
        sb.AppendLine("    clip_out = clip_session.run(None, {clip_session.get_inputs()[0].name: inp})[0]");
        sb.AppendLine("    clip_out = normalize(clip_out)");
        sb.AppendLine("    score = aesthetic_session.run(None, {aesthetic_session.get_inputs()[0].name: clip_out})[0][0]");
        sb.AppendLine("    return JSONResponse({'score': float(score), 'model': 'clip-vit-base-patch32 + aesthetic-v1'})");
        sb.AppendLine("PY");
        sb.AppendLine("cat > \"$INSTALL_DIR/prompttool-aesthetic.service\" <<EOF");
        sb.AppendLine("[Unit]");
        sb.AppendLine("Description=PromptTool Aesthetic Scoring");
        sb.AppendLine("After=network.target");
        sb.AppendLine("[Service]");
        sb.AppendLine($"WorkingDirectory={dir}");
        sb.AppendLine($"ExecStart={dir}/venv/bin/uvicorn server:app --host 127.0.0.1 --port {port}");
        sb.AppendLine("Restart=always");
        sb.AppendLine("[Install]");
        sb.AppendLine("WantedBy=multi-user.target");
        sb.AppendLine("EOF");
        sb.AppendLine("sudo mv \"$INSTALL_DIR/prompttool-aesthetic.service\" /etc/systemd/system/prompttool-aesthetic.service");
        sb.AppendLine("sudo systemctl daemon-reload");
        sb.AppendLine("sudo systemctl enable --now prompttool-aesthetic.service");
        return sb.ToString();
    }

    public static string BuildRemoveScript(string installDir)
    {
        var dir = string.IsNullOrWhiteSpace(installDir) ? "$HOME/prompttool-aesthetic" : installDir;
        var sb = new StringBuilder();
        sb.AppendLine("#!/usr/bin/env bash");
        sb.AppendLine("set -euo pipefail");
        sb.AppendLine("sudo systemctl disable --now prompttool-aesthetic.service || true");
        sb.AppendLine("sudo rm -f /etc/systemd/system/prompttool-aesthetic.service");
        sb.AppendLine("sudo systemctl daemon-reload");
        sb.AppendLine($"rm -rf \"{dir}\"");
        return sb.ToString();
    }
}
