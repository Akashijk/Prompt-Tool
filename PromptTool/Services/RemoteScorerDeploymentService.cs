using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Renci.SshNet;
using Renci.SshNet.Common;

namespace PromptTool.Services;

public sealed class RemoteScorerDeploymentService
{
    public const string ModelUrl = "https://huggingface.co/fsw/aesthetic-predictor-v2-5_onnx/resolve/main/aesthetic_predictor_v2_5.onnx";
    public const string ImageTag = "prompttool-aesthetic:rocm";
    public const string ContainerName = "prompttool-aesthetic";
    public const string VolumeName = "prompttool_aesthetic_models";

public const string RequirementsTxt = @"fastapi
uvicorn[standard]
pillow
numpy
requests
onnxruntime
python-multipart
";

    public const string Dockerfile = @"FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
EXPOSE 7861
CMD [""uvicorn"", ""server:app"", ""--host"", ""0.0.0.0"", ""--port"", ""7861""]
";

    public const string ServerPy = @"from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse
import io, os, requests
from PIL import Image
import numpy as np
import onnxruntime as ort

app = FastAPI()

MODEL_DIR = os.path.join(os.path.dirname(__file__), ""models"")
os.makedirs(MODEL_DIR, exist_ok=True)

# Match your C# defaults
AESTHETIC_URL = ""https://huggingface.co/fsw/aesthetic-predictor-v2-5_onnx/resolve/main/aesthetic_predictor_v2_5.onnx""
AESTHETIC_PATH = os.path.join(MODEL_DIR, ""aesthetic_predictor_v2_5.onnx"")

# Same normalization as your C# code
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD  = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

AESTHETIC_INPUT_SIZE = 384  # model expects 384x384

# Optional auth: set API_KEY env var; client sends X-API-Key
API_KEY = os.environ.get(""API_KEY"", """").strip()

aesthetic_session = None
providers_in_use = None


def download(url: str, path: str) -> None:
    if os.path.exists(path):
        return
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = path + "".tmp""
        with open(tmp, ""wb"") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp, path)


def pick_providers():
    # Avoid MIGraphX here; if the image doesn't include migraphx libs it will spam errors.
    avail = ort.get_available_providers()
    if ""ROCMExecutionProvider"" in avail:
        return [""ROCMExecutionProvider"", ""CPUExecutionProvider""]
    if ""CUDAExecutionProvider"" in avail:
        return [""CUDAExecutionProvider"", ""CPUExecutionProvider""]
    return [""CPUExecutionProvider""]


def ensure_ready():
    global aesthetic_session, providers_in_use
    download(AESTHETIC_URL, AESTHETIC_PATH)

    if aesthetic_session is None:
        providers_in_use = pick_providers()
        so = ort.SessionOptions()
        aesthetic_session = ort.InferenceSession(
            AESTHETIC_PATH,
            sess_options=so,
            providers=providers_in_use,
        )


def preprocess(img: Image.Image) -> np.ndarray:
    # Returns float32 tensor shape [1, 3, 384, 384]
    img = img.convert(""RGB"").resize((AESTHETIC_INPUT_SIZE, AESTHETIC_INPUT_SIZE))
    arr = np.asarray(img).astype(np.float32) / 255.0
    arr = (arr - MEAN) / STD
    arr = np.transpose(arr, (2, 0, 1))  # HWC -> CHW
    return arr[np.newaxis, :]


def check_key(x_api_key: Optional[str]) -> None:
    if not API_KEY:
        return
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail=""Missing/invalid X-API-Key"")


def score_tensor(batch_nchw: np.ndarray) -> np.ndarray:
    """"""
    batch_nchw: float32 array [B,3,384,384]
    returns: float32 array [B]
    """"""
    ensure_ready()
    in_name = aesthetic_session.get_inputs()[0].name  # usually ""input""
    out = aesthetic_session.run(None, {in_name: batch_nchw})

    # Model output[0] is shape [B,1]
    scores = out[0].reshape(-1)
    return scores


@app.get(""/health"")
def health():
    return {
        ""ok"": True,
        ""available_providers"": ort.get_available_providers(),
        ""providers_in_use"": providers_in_use,
        ""sessions_loaded"": bool(aesthetic_session),
        ""api_key_enabled"": bool(API_KEY),
        ""aesthetic_model_path"": AESTHETIC_PATH,
        ""aesthetic_url"": AESTHETIC_URL,
        ""input_size"": AESTHETIC_INPUT_SIZE,
    }


@app.post(""/score"")
async def score(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(default=None, alias=""X-API-Key""),
):
    check_key(x_api_key)

    data = await file.read()
    img = Image.open(io.BytesIO(data))
    img.load()

    batch = preprocess(img)  # [1,3,384,384]
    val = float(score_tensor(batch)[0])

    return JSONResponse({
        ""score"": val,
        ""providers_in_use"": providers_in_use,
        ""model"": ""fsw/aesthetic-predictor-v2-5_onnx (image 384x384)"",
    })


@app.post(""/score_batch"")
async def score_batch(
    files: List[UploadFile] = File(...),
    x_api_key: Optional[str] = Header(default=None, alias=""X-API-Key""),
):
    check_key(x_api_key)

    # Build batch
    tensors = []
    results = []

    for f in files:
        try:
            data = await f.read()
            img = Image.open(io.BytesIO(data))
            img.load()
            t = preprocess(img)[0]  # [3,384,384] (no batch dim)
            tensors.append(t)
            results.append({""filename"": f.filename})
        except Exception as e:
            results.append({""filename"": f.filename, ""error"": str(e)})

    # If all failed
    good_idx = [i for i, r in enumerate(results) if ""error"" not in r]
    if not good_idx:
        return JSONResponse({
            ""results"": results,
            ""count"": 0,
            ""providers_in_use"": providers_in_use,
            ""model"": ""fsw/aesthetic-predictor-v2-5_onnx (image 384x384)"",
        }, status_code=200)

    batch = np.stack(tensors, axis=0).astype(np.float32)  # [B,3,384,384]
    scores = score_tensor(batch)  # [B]

    # Fill scores back into results (only for successful ones)
    s = 0
    for i in range(len(results)):
        if ""error"" in results[i]:
            continue
        results[i][""score""] = float(scores[s])
        s += 1

    return JSONResponse({
        ""results"": results,
        ""count"": int(len(scores)),
        ""providers_in_use"": providers_in_use,
        ""model"": ""fsw/aesthetic-predictor-v2-5_onnx (image 384x384)"",
    })
";

    public async Task DeployAsync(DeployOptions options, IProgress<string> log, CancellationToken ct)
    {
        log.Report($"Connecting to {options.Host}:{options.Port}...");
        var connection = BuildConnectionInfo(options);

        using var ssh = new SshClient(connection);
        using var sftp = new SftpClient(connection);
        ssh.Connect();
        sftp.Connect();

        var installDir = await ResolveInstallDirAsync(ssh, options.InstallDir, ct);
        log.Report($"Using install directory: {installDir}");

        EnsureRemoteDependencies(ssh, options, log);

        RunCommand(ssh, $"mkdir -p {Escape(installDir)}", log);
        UploadFile(sftp, ServerPy, $"{installDir}/server.py", log);
        UploadFile(sftp, RequirementsTxt, $"{installDir}/requirements.txt", log);
        UploadFile(sftp, Dockerfile, $"{installDir}/Dockerfile", log);

        RunCommand(ssh, $"docker build -t {ImageTag} {Escape(installDir)}", log);
        RunCommand(ssh, $"docker volume create {VolumeName} || true", log);
        RunCommand(ssh, $"docker rm -f {ContainerName} || true", log);

        var enableRocm = options.EnableRocm && HasRocmDevices(ssh, log);
        if (options.EnableRocm && !enableRocm)
        {
            log.Report("ROCm devices not detected. Running without ROCm flags.");
        }
        var dockerRun = BuildDockerRunCommand(options.ExposedPort, enableRocm);
        RunCommand(ssh, dockerRun, log);

        var healthCmd = $"curl -s http://127.0.0.1:{options.ExposedPort}/health";
        var health = RetryHealthCheck(ssh, healthCmd, log, attempts: 8, delaySeconds: 2);
        if (!health.Contains("\"ok\"") || !health.Contains("true", StringComparison.OrdinalIgnoreCase))
        {
            RunCommandAllowFailure(ssh, $"docker ps --filter name={ContainerName}", log, out _);
            RunCommandAllowFailure(ssh, $"docker logs --tail 100 {ContainerName}", log, out _);
            throw new InvalidOperationException("Health check failed. The /health response did not indicate ok=true.");
        }

        log.Report("Deployment completed successfully.");
        ssh.Disconnect();
        sftp.Disconnect();
    }

    public async Task TestConnectionAsync(DeployOptions options, IProgress<string> log, CancellationToken ct)
    {
        log.Report($"Testing connection to {options.Host}:{options.Port}...");
        var connection = BuildConnectionInfo(options);
        using var ssh = new SshClient(connection);
        ssh.Connect();
        RunCommand(ssh, "echo ok", log);
        ssh.Disconnect();
        log.Report("Connection successful.");
        await Task.CompletedTask;
    }

    public string BuildManualInstructions(DeployOptions options)
    {
        var installDir = options.InstallDir;
        var port = options.ExposedPort;
        var dockerRun = BuildDockerRunCommand(port, options.EnableRocm);

        var sb = new StringBuilder();
        sb.AppendLine($"mkdir -p {installDir}");
        sb.AppendLine($"cd {installDir}");
        sb.AppendLine();
        sb.AppendLine("cat > server.py << 'PY'");
        sb.AppendLine(ServerPy.TrimEnd());
        sb.AppendLine("PY");
        sb.AppendLine();
        sb.AppendLine("cat > requirements.txt << 'REQ'");
        sb.AppendLine(RequirementsTxt.TrimEnd());
        sb.AppendLine("REQ");
        sb.AppendLine();
        sb.AppendLine("cat > Dockerfile << 'DOCKER'");
        sb.AppendLine(Dockerfile.TrimEnd());
        sb.AppendLine("DOCKER");
        sb.AppendLine();
        sb.AppendLine($"docker build -t {ImageTag} {installDir}");
        sb.AppendLine($"docker volume create {VolumeName} || true");
        sb.AppendLine($"docker rm -f {ContainerName} || true");
        sb.AppendLine(dockerRun);
        sb.AppendLine($"curl http://127.0.0.1:{port}/health");
        return sb.ToString();
    }

    private static string BuildDockerRunCommand(int port, bool enableRocm)
    {
        var rocmFlags = enableRocm
            ? "  --device=/dev/kfd --device=/dev/dri \\\n  --group-add video \\\n"
            : string.Empty;
        return
$"""
docker run -d --restart unless-stopped \
  --name {ContainerName} \
 {rocmFlags}  -p {port}:7861 \
  -v {VolumeName}:/app/models \
  {ImageTag}
""".TrimEnd();
    }

    private static string RunCommand(SshClient ssh, string command, IProgress<string> log)
    {
        log.Report($"> {command}");
        var cmd = ssh.CreateCommand(command);
        var result = cmd.Execute();
        if (!string.IsNullOrWhiteSpace(cmd.Error))
        {
            log.Report(cmd.Error.Trim());
        }
        if (!string.IsNullOrWhiteSpace(result))
        {
            log.Report(result.Trim());
        }
        if (cmd.ExitStatus != 0)
        {
            throw new InvalidOperationException($"Command failed: {command}");
        }
        return result ?? string.Empty;
    }

    private static int RunCommandAllowFailure(SshClient ssh, string command, IProgress<string> log, out string output)
    {
        log.Report($"> {command}");
        var cmd = ssh.CreateCommand(command);
        var result = cmd.Execute();
        if (!string.IsNullOrWhiteSpace(cmd.Error))
        {
            log.Report(cmd.Error.Trim());
        }
        if (!string.IsNullOrWhiteSpace(result))
        {
            log.Report(result.Trim());
        }
        output = result ?? string.Empty;
        return cmd.ExitStatus;
    }

    private static void EnsureRemoteDependencies(SshClient ssh, DeployOptions options, IProgress<string> log)
    {
        if (!CommandExists(ssh, "apt-get", log))
        {
            throw new InvalidOperationException("apt-get not found on remote host. Automatic install requires Debian/Ubuntu.");
        }

        if (!CommandExists(ssh, "curl", log))
        {
            RunSudoAptUpdate(ssh, options, log);
            RunSudoCommand(ssh, "apt-get install -y curl", options, log);
        }

        if (!CommandExists(ssh, "docker", log))
        {
            RunSudoAptUpdate(ssh, options, log);
            RunSudoCommand(ssh, "apt-get install -y docker.io", options, log);
            RunSudoCommand(ssh, "systemctl enable --now docker || true", options, log);
            RunSudoCommand(ssh, $"usermod -aG docker {Escape(options.Username)} || true", options, log);
        }

    }

    private static bool CommandExists(SshClient ssh, string name, IProgress<string> log)
    {
        var status = RunCommandAllowFailure(ssh, $"command -v {name} >/dev/null 2>&1", log, out _);
        return status == 0;
    }

    private static void RunSudoCommand(SshClient ssh, string command, DeployOptions options, IProgress<string> log)
    {
        if (options.AuthType == AuthType.Password && !string.IsNullOrWhiteSpace(options.Password))
        {
            var safePassword = EscapeForShell(options.Password);
            log.Report($"> sudo {command} (password hidden)");
            var cmd = ssh.CreateCommand($"echo '{safePassword}' | sudo -S {command}");
            var result = cmd.Execute();
            if (!string.IsNullOrWhiteSpace(cmd.Error))
            {
                log.Report(cmd.Error.Trim());
            }
            if (!string.IsNullOrWhiteSpace(result))
            {
                log.Report(result.Trim());
            }
            if (cmd.ExitStatus != 0)
            {
                throw new InvalidOperationException($"Command failed: sudo {command}");
            }
            return;
        }

        var status = RunCommandAllowFailure(ssh, $"sudo -n {command}", log, out _);
        if (status != 0)
        {
            throw new InvalidOperationException("sudo requires a password. Use password auth or enable passwordless sudo on the server.");
        }
    }

    private static void UploadFile(SftpClient sftp, string content, string remotePath, IProgress<string> log)
    {
        log.Report($"Uploading {remotePath}...");
        using var ms = new MemoryStream(Encoding.UTF8.GetBytes(content));
        sftp.UploadFile(ms, remotePath, true);
    }

    private static string Escape(string value)
    {
        return value.Replace("'", "'\\''");
    }

    private static string EscapeForShell(string value)
    {
        return value.Replace("'", "'\"'\"'");
    }

    private static bool HasRocmDevices(SshClient ssh, IProgress<string> log)
    {
        var status = RunCommandAllowFailure(ssh, "test -e /dev/kfd -a -e /dev/dri", log, out _);
        return status == 0;
    }

    private static void RunSudoAptUpdate(SshClient ssh, DeployOptions options, IProgress<string> log)
    {
        try
        {
            RunSudoCommand(ssh, "apt-get update -y", options, log);
        }
        catch (InvalidOperationException ex) when (ex.Message.Contains("apt-get update", StringComparison.OrdinalIgnoreCase))
        {
            // Retry after disabling stale cdrom entries (common on Ubuntu server installs).
            RunSudoCommand(ssh, "sed -i.bak '/^deb cdrom:/s/^/#/' /etc/apt/sources.list", options, log);
            RunSudoCommand(ssh, "sed -i.bak '/^deb cdrom:/s/^/#/' /etc/apt/sources.list.d/*.list || true", options, log);
            RunSudoCommand(ssh, "apt-get update -y", options, log);
        }
    }

    private static string RetryHealthCheck(SshClient ssh, string command, IProgress<string> log, int attempts, int delaySeconds)
    {
        var last = string.Empty;
        for (var i = 0; i < attempts; i++)
        {
            var status = RunCommandAllowFailure(ssh, command, log, out var output);
            last = output ?? string.Empty;
            if (status == 0 && !string.IsNullOrWhiteSpace(last))
            {
                return last;
            }
            Thread.Sleep(TimeSpan.FromSeconds(delaySeconds));
        }
        return last;
    }

    private static ConnectionInfo BuildConnectionInfo(DeployOptions options)
    {
        if (options.AuthType == AuthType.Password)
        {
            return new ConnectionInfo(options.Host, options.Port, options.Username,
                new PasswordAuthenticationMethod(options.Username, options.Password ?? string.Empty));
        }

        var keyFile = new PrivateKeyFile(options.KeyFilePath ?? string.Empty);
        return new ConnectionInfo(options.Host, options.Port, options.Username,
            new PrivateKeyAuthenticationMethod(options.Username, keyFile));
    }

    private static async Task<string> ResolveInstallDirAsync(SshClient ssh, string rawDir, CancellationToken ct)
    {
        if (!rawDir.StartsWith("~", StringComparison.Ordinal))
        {
            return rawDir;
        }

        var home = RunCommand(ssh, "echo $HOME", new Progress<string>(_ => { })).Trim();
        if (string.IsNullOrWhiteSpace(home))
        {
            return rawDir;
        }
        var suffix = rawDir.TrimStart('~');
        return $"{home}{suffix}";
    }

    public sealed class DeployOptions
    {
        public string Host { get; set; } = "";
        public int Port { get; set; } = 22;
        public string Username { get; set; } = "";
        public AuthType AuthType { get; set; } = AuthType.KeyFile;
        public string? KeyFilePath { get; set; }
        public string? Password { get; set; }
        public string InstallDir { get; set; } = "~/prompttool-aesthetic";
        public int ExposedPort { get; set; } = 7861;
        public bool EnableRocm { get; set; } = true;
    }

    public enum AuthType
    {
        KeyFile,
        Password
    }
}
