using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Media.Imaging;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace PromptTool.Services;

public sealed class AestheticScoringService : IDisposable
{
    private const string ManifestFileName = "scoring_models.json";
    private const string ClipModelFileName = "clip_vision.onnx";
    private const string AestheticModelFileName = "aesthetic_head.onnx";
    public const int DefaultInputSize = 224;
    private static readonly float[] ClipMean = { 0.48145466f, 0.4578275f, 0.40821073f };
    private static readonly float[] ClipStd = { 0.26862954f, 0.26130258f, 0.27577711f };

    private readonly ScoringCacheService _cacheService;
    private readonly PromptTool.Core.Services.SettingsService _settingsService;
    private readonly HttpClient _httpClient = new();
    private readonly SemaphoreSlim _modelGate = new(1, 1);
    private InferenceSession? _clipSession;
    private InferenceSession? _aestheticSession;
    private ModelManifest? _manifest;
    private string? _manifestPath;
    private bool _aestheticIsImageModel;
    private int _aestheticImageSize;
    private string? _aestheticModelName;
    private string? _loadedClipPath;
    private string? _loadedAestheticPath;

    public AestheticScoringService(ScoringCacheService cacheService, PromptTool.Core.Services.SettingsService settingsService)
    {
        _cacheService = cacheService;
        _settingsService = settingsService;
    }

    public string GetCacheDir() => _cacheService.GetCacheDir();

    public async Task<AestheticScoreResult?> ScoreImageAsync(
        string imagePath,
        Func<string, Task<bool>> confirmDownloadAsync,
        Action<string>? status = null,
        IProgress<DownloadProgressInfo>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(imagePath)) return null;

        var backend = _settingsService.Settings.AestheticScoringBackend?.Trim().ToLowerInvariant() ?? "local";
        if (backend == "remote")
        {
            return await ScoreRemoteAsync(imagePath, status, cancellationToken);
        }

        if (!await EnsureModelsAsync(confirmDownloadAsync, status, progress, cancellationToken))
        {
            return null;
        }

        var manifest = _manifest;
        if (manifest == null) return null;

        var watch = Stopwatch.StartNew();
        var score = await Task.Run(async () =>
        {
            using var original = LoadBitmap(imagePath);
            if (original == null) return (double?)null;

            if (_aestheticIsImageModel)
            {
                var inputSize = _aestheticImageSize > 0 ? _aestheticImageSize : (manifest.InputSize > 0 ? manifest.InputSize : DefaultInputSize);
                using var scaled = original.CreateScaledBitmap(new PixelSize(inputSize, inputSize), BitmapInterpolationMode.HighQuality);
                var inputTensor = BuildInputTensorFloat(scaled, inputSize);
                return await RunAestheticImageAsync(inputTensor);
            }

            var clipSize = manifest.InputSize > 0 ? manifest.InputSize : DefaultInputSize;
            using var clipScaled = original.CreateScaledBitmap(new PixelSize(clipSize, clipSize), BitmapInterpolationMode.HighQuality);
            var clipTensor = BuildInputTensorFloat(clipScaled, clipSize);
            var embedding = await RunClipAsync(clipTensor);
            if (embedding == null) return (double?)null;
            var normalized = NormalizeEmbedding(embedding);
            return await RunAestheticHeadAsync(normalized);
        }, cancellationToken);
        watch.Stop();

        if (!score.HasValue) return null;

        return new AestheticScoreResult
        {
            Score = score.Value,
            ModelName = _aestheticModelName ?? manifest.AestheticModelName,
            ElapsedMs = (int)Math.Max(1, watch.ElapsedMilliseconds)
        };
    }

    private async Task<AestheticScoreResult?> ScoreRemoteAsync(string imagePath, Action<string>? status, CancellationToken cancellationToken)
    {
        var baseUrl = _settingsService.Settings.AestheticScoringRemoteUrl?.Trim();
        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            status?.Invoke("Remote scoring URL not configured.");
            return null;
        }

        var url = baseUrl.TrimEnd('/') + "/score";
        try
        {
            status?.Invoke("Sending image to remote scorer...");
            await using var fs = File.OpenRead(imagePath);
            using var content = new MultipartFormDataContent();
            content.Add(new StreamContent(fs), "file", Path.GetFileName(imagePath));

            var watch = Stopwatch.StartNew();
            using var resp = await _httpClient.PostAsync(url, content, cancellationToken);
            watch.Stop();
            if (!resp.IsSuccessStatusCode)
            {
                status?.Invoke($"Remote scoring failed: {resp.StatusCode}");
                return null;
            }

            var json = await resp.Content.ReadAsStringAsync(cancellationToken);
            var parsed = JsonSerializer.Deserialize<RemoteScoreResponse>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (parsed == null || parsed.Score == null)
            {
                status?.Invoke("Remote scoring returned no score.");
                return null;
            }

            return new AestheticScoreResult
            {
                Score = parsed.Score.Value,
                ModelName = parsed.Model ?? "remote",
                ElapsedMs = (int)Math.Max(1, watch.ElapsedMilliseconds)
            };
        }
        catch (Exception ex)
        {
            status?.Invoke($"Remote scoring failed: {ex.Message}");
            return null;
        }
    }

    public async Task<IReadOnlyList<AestheticScoreResult>?> ScoreRemoteBatchAsync(
        IReadOnlyList<string> imagePaths,
        Action<string>? status = null,
        IProgress<DownloadProgressInfo>? progress = null, // unused but keeps signature style consistent
        CancellationToken cancellationToken = default)
    {
        if (imagePaths == null || imagePaths.Count == 0) return Array.Empty<AestheticScoreResult>();

        var baseUrl = _settingsService.Settings.AestheticScoringRemoteUrl?.Trim();
        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            status?.Invoke("Remote scoring URL not configured.");
            return null;
        }

        var url = baseUrl.TrimEnd('/') + "/score_batch";

        try
        {
            status?.Invoke($"Sending {imagePaths.Count} images to remote batch scorer...");

            using var content = new MultipartFormDataContent();

            // IMPORTANT: field name must be "files" to match your FastAPI endpoint
            // -F "files=@path"
            foreach (var p in imagePaths)
            {
                if (string.IsNullOrWhiteSpace(p) || !File.Exists(p)) continue;

                var fs = File.OpenRead(p); // disposed by StreamContent disposal
                var sc = new StreamContent(fs);

                // You can optionally set a content-type, but it's not required for FastAPI UploadFile
                // sc.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");

                content.Add(sc, "files", Path.GetFileName(p));
            }

            var watch = Stopwatch.StartNew();
            using var resp = await _httpClient.PostAsync(url, content, cancellationToken);
            watch.Stop();

            if (!resp.IsSuccessStatusCode)
            {
                var body = await resp.Content.ReadAsStringAsync(cancellationToken);
                status?.Invoke($"Remote batch scoring failed: {resp.StatusCode} {body}");
                return null;
            }

            var json = await resp.Content.ReadAsStringAsync(cancellationToken);
            var parsed = JsonSerializer.Deserialize<RemoteBatchScoreResponse>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (parsed?.Results == null || parsed.Results.Count == 0)
            {
                status?.Invoke("Remote batch scoring returned no results.");
                return null;
            }

            // Preserve response order (server returns in upload order)
            var results = new List<AestheticScoreResult>(parsed.Results.Count);
            foreach (var item in parsed.Results)
            {
                if (item.Score == null) continue;

                results.Add(new AestheticScoreResult
                {
                    Score = item.Score.Value,
                    ModelName = parsed.Model ?? "remote-batch",
                    ElapsedMs = (int)Math.Max(1, watch.ElapsedMilliseconds)
                });
            }

            return results;
        }
        catch (Exception ex)
        {
            status?.Invoke($"Remote batch scoring failed: {ex.Message}");
            return null;
        }
    }

    public async Task<Dictionary<string, AestheticScoreResult>> ScoreRemoteFolderAsync(
        IReadOnlyList<string> imagePaths,
        int batchSize = 0,
        Action<string>? status = null,
        CancellationToken cancellationToken = default)
    {
        if (batchSize <= 0)
        {
            batchSize = _settingsService.Settings.AestheticScoringRemoteBatchSize;
            if (batchSize <= 0) batchSize = 8;
        }
        var map = new Dictionary<string, AestheticScoreResult>(StringComparer.OrdinalIgnoreCase);

        foreach (var batch in Chunk(imagePaths, batchSize))
        {
            var scored = await ScoreRemoteBatchAsync(batch, status, cancellationToken: cancellationToken);
            if (scored == null) continue;

            // Server returns results in upload order, so we can zip to original filenames safely.
            // (If you want bulletproof mapping, you can return "filename" and map explicitly.)
            for (int i = 0; i < Math.Min(batch.Count, scored.Count); i++)
                map[batch[i]] = scored[i];
        }

        return map;
    }

    private async Task<bool> EnsureModelsAsync(
        Func<string, Task<bool>> confirmDownloadAsync,
        Action<string>? status,
        IProgress<DownloadProgressInfo>? progress,
        CancellationToken cancellationToken)
    {
        await _modelGate.WaitAsync(cancellationToken);
        try
        {
            _cacheService.EnsureDirectories();
            var cacheDir = _cacheService.GetCacheDir();
            var manifestPath = Path.Combine(cacheDir, ManifestFileName);
            _manifestPath = manifestPath;
            if (!File.Exists(manifestPath))
            {
                var defaultManifest = ModelManifest.CreateDefault();
                await File.WriteAllTextAsync(manifestPath, JsonSerializer.Serialize(defaultManifest, new JsonSerializerOptions { WriteIndented = true }), cancellationToken);
            }

            _manifest = await LoadManifestAsync(manifestPath, cancellationToken);
            if (_manifest == null) return false;
            if (NeedsManifestUpgrade(_manifest))
            {
                _manifest = ModelManifest.CreateDefault();
                await File.WriteAllTextAsync(
                    manifestPath,
                    JsonSerializer.Serialize(_manifest, new JsonSerializerOptions { WriteIndented = true }),
                    cancellationToken);
            }

            var modelsDir = _cacheService.GetModelsDir();
            var defaultClipPath = Path.Combine(cacheDir, ClipModelFileName);
            var modelsClipPath = Path.Combine(modelsDir, ClipModelFileName);
            var clipPath = File.Exists(modelsClipPath) ? modelsClipPath : defaultClipPath;
            var clipIsCustom = !string.Equals(clipPath, defaultClipPath, StringComparison.OrdinalIgnoreCase);

            var customAestheticPath = _settingsService.Settings.AestheticScoringModelPath?.Trim();
            var hasCustomAesthetic = !string.IsNullOrWhiteSpace(customAestheticPath) && File.Exists(customAestheticPath);
            var defaultAestheticPath = Path.Combine(cacheDir, AestheticModelFileName);
            var modelsAestheticPath = Path.Combine(modelsDir, AestheticModelFileName);
            var aestheticPath = hasCustomAesthetic
                ? customAestheticPath!
                : (File.Exists(modelsAestheticPath) ? modelsAestheticPath : defaultAestheticPath);
            var aestheticIsCustom = hasCustomAesthetic || !string.Equals(aestheticPath, defaultAestheticPath, StringComparison.OrdinalIgnoreCase);

            if (!File.Exists(clipPath) || (!hasCustomAesthetic && !File.Exists(aestheticPath)))
            {
                var message =
                    "Aesthetic scoring requires downloading model files.\n\n" +
                    $"CLIP model:\n{_manifest.GetClipModelUrls().FirstOrDefault()}\n\n" +
                    $"Aesthetic model:\n{_manifest.GetAestheticModelUrls().FirstOrDefault()}\n\n" +
                    "Download now?";

                if (!await confirmDownloadAsync(message))
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: download canceled by user.");
                    return false;
                }

                status?.Invoke("Downloading aesthetic scoring models...");
                if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: downloading models...");
                if (!File.Exists(clipPath))
                {
                    var targetClipPath = modelsClipPath;
                    await DownloadWithFallbackAsync(_manifest.GetClipModelUrls(), _manifest.GetClipModelRepos(), targetClipPath, "CLIP", status, progress, cancellationToken);
                    clipPath = targetClipPath;
                    clipIsCustom = false;
                }
                if (!hasCustomAesthetic && !File.Exists(aestheticPath))
                {
                    var targetAestheticPath = modelsAestheticPath;
                    await DownloadWithFallbackAsync(_manifest.GetAestheticModelUrls(), _manifest.GetAestheticModelRepos(), targetAestheticPath, "Aesthetic", status, progress, cancellationToken);
                    aestheticPath = targetAestheticPath;
                    aestheticIsCustom = false;
                }
            }

            if (!string.IsNullOrWhiteSpace(_loadedClipPath)
                && !string.Equals(_loadedClipPath, clipPath, StringComparison.OrdinalIgnoreCase))
            {
                _clipSession?.Dispose();
                _clipSession = null;
            }

            if (!string.IsNullOrWhiteSpace(_loadedAestheticPath)
                && !string.Equals(_loadedAestheticPath, aestheticPath, StringComparison.OrdinalIgnoreCase))
            {
                _aestheticSession?.Dispose();
                _aestheticSession = null;
            }

            if (_clipSession == null || _aestheticSession == null)
            {
                await Task.Run(() =>
                {
                    if (_clipSession == null)
                    {
                        if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: loading CLIP session from {clipPath}");
                        _clipSession = new InferenceSession(clipPath);
                        _loadedClipPath = clipPath;
                    }
                    if (_aestheticSession == null)
                    {
                        if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: loading aesthetic session from {aestheticPath}");
                        _aestheticSession = new InferenceSession(aestheticPath);
                        _loadedAestheticPath = aestheticPath;
                    }

                    DetectAestheticModel(_aestheticSession);
                    _aestheticModelName = hasCustomAesthetic
                        ? Path.GetFileNameWithoutExtension(aestheticPath)
                        : _manifest.AestheticModelName;
                }, cancellationToken);
            }

            if (!IsValidClipImageModel(_clipSession))
            {
                status?.Invoke("Invalid CLIP model detected; downloading visual image model...");
                if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: invalid CLIP model detected; downloading visual image model.");
                _clipSession?.Dispose();
                _clipSession = null;
                if (File.Exists(clipPath)) File.Delete(clipPath);

                await DownloadWithFallbackAsync(
                    PreferVisualFloat32Urls(_manifest.GetClipModelUrls()),
                    _manifest.GetClipModelRepos(),
                    clipPath,
                    "CLIP",
                    status,
                    progress,
                    cancellationToken);

                Console.WriteLine($"Aesthetic scoring: loading CLIP session from {clipPath}");
                _clipSession = new InferenceSession(clipPath);
                if (!IsValidClipImageModel(_clipSession))
                {
                    status?.Invoke("CLIP model is not an image encoder; unable to score.");
                    if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: CLIP model still invalid after fallback.");
                    return false;
                }
            }

            if (RequiresFloat16(_clipSession) || RequiresFloat16(_aestheticSession))
            {
                if (hasCustomAesthetic && RequiresFloat16(_aestheticSession))
                {
                    status?.Invoke("Selected aesthetic model uses Float16 and is not supported on this system.");
                    if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: custom aesthetic model uses Float16.");
                    return false;
                }
                status?.Invoke("Float16 models detected; downloading float32 variants...");
                if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: float16 models detected; downloading float32 variants.");
                _clipSession?.Dispose();
                _aestheticSession?.Dispose();
                _clipSession = null;
                _aestheticSession = null;

                if (!clipIsCustom && File.Exists(clipPath)) File.Delete(clipPath);
                if (!aestheticIsCustom && File.Exists(aestheticPath)) File.Delete(aestheticPath);

                await DownloadWithFallbackAsync(
                    PreferFloat32Urls(_manifest.GetClipModelUrls()),
                    _manifest.GetClipModelRepos(),
                    clipPath,
                    "CLIP",
                    status,
                    progress,
                    cancellationToken);

                if (!hasCustomAesthetic)
                {
                    await DownloadWithFallbackAsync(
                        PreferFloat32Urls(_manifest.GetAestheticModelUrls()),
                        _manifest.GetAestheticModelRepos(),
                        aestheticPath,
                        "Aesthetic",
                        status,
                        progress,
                        cancellationToken);
                }

                Console.WriteLine($"Aesthetic scoring: loading CLIP session from {clipPath}");
                _clipSession = new InferenceSession(clipPath);
                _loadedClipPath = clipPath;
                if (_aestheticSession == null)
                {
                    if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: loading aesthetic session from {aestheticPath}");
                    _aestheticSession = new InferenceSession(aestheticPath);
                    _loadedAestheticPath = aestheticPath;
                }
                DetectAestheticModel(_aestheticSession);

                if (RequiresFloat16(_clipSession) || RequiresFloat16(_aestheticSession))
                {
                    status?.Invoke("Float16 models still detected; unable to score on this system.");
                    if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: float16 models still detected after fallback.");
                    return false;
                }
            }

            return true;
        }
        catch (Exception ex)
        {
            status?.Invoke($"Aesthetic scoring failed: {ex.Message}");
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring failed: {ex}");
            return false;
        }
        finally
        {
            _modelGate.Release();
        }
    }

    private async Task<ModelManifest?> LoadManifestAsync(string path, CancellationToken cancellationToken)
    {
        try
        {
            var json = await File.ReadAllTextAsync(path, cancellationToken);
            return JsonSerializer.Deserialize<ModelManifest>(json);
        }
        catch
        {
            return null;
        }
    }

    private static bool NeedsManifestUpgrade(ModelManifest manifest)
    {
        if (manifest.ClipModelUrls == null || manifest.ClipModelUrls.Count == 0)
        {
            return true;
        }
        if (manifest.AestheticModelUrls == null || manifest.AestheticModelUrls.Count == 0)
        {
            return true;
        }
        if (string.IsNullOrWhiteSpace(manifest.ClipModelRepo) || string.IsNullOrWhiteSpace(manifest.AestheticModelRepo))
        {
            return true;
        }
        if (manifest.ClipModelRepos == null || manifest.ClipModelRepos.Count == 0)
        {
            return true;
        }
        if (manifest.AestheticModelRepos == null || manifest.AestheticModelRepos.Count == 0)
        {
            return true;
        }
        if (manifest.ClipModelRepo.Contains("onnx-community/clip-vit-base-patch32", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        if (manifest.AestheticModelRepo.Contains("LAION/aesthetic-predictor", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        if (manifest.ClipModelUrls != null && manifest.ClipModelUrls.Any(u => u.Contains("onnx16", StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }
        if (manifest.ClipModelUrl.Contains("openai/clip-vit-base-patch32", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        if (manifest.ClipModelUrls != null && manifest.ClipModelUrls.Any(u => u.Contains("openai/clip-vit-base-patch32", StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }
        return false;
    }

    private async Task DownloadWithFallbackAsync(
        IReadOnlyList<string> urls,
        IReadOnlyList<string> repos,
        string outputPath,
        string label,
        Action<string>? status,
        IProgress<DownloadProgressInfo>? progress,
        CancellationToken cancellationToken,
        Func<string, Task<bool>>? validateAsync = null)
    {
        var attempts = urls.Where(u => !string.IsNullOrWhiteSpace(u)).ToList();
        if (attempts.Count == 0 && repos.Count == 0)
        {
            throw new HttpRequestException($"No download URLs configured for {label} model.");
        }

        string? repoError = null;
        foreach (var repo in repos.Where(r => !string.IsNullOrWhiteSpace(r)))
        {
            status?.Invoke($"Resolving {label} model files from Hugging Face...");
            var (resolved, error) = await ResolveOnnxUrlFromRepoAsync(repo, label, cancellationToken);
            repoError = error;
            if (!string.IsNullOrWhiteSpace(resolved))
            {
                status?.Invoke($"Downloading {label} model (resolved)...");
                var ok = await DownloadAsync(resolved, outputPath, label, progress, cancellationToken, validateAsync);
                if (ok)
                {
                    UpdateManifestResolvedUrl(label, resolved);
                    return;
                }
            }
        }

        foreach (var url in attempts)
        {
            var ok = await DownloadAsync(url, outputPath, label, progress, cancellationToken, validateAsync);
            if (ok)
            {
                UpdateManifestResolvedUrl(label, url);
                return;
            }
        }

        var suffix = string.IsNullOrWhiteSpace(repoError) ? "" : $" Repo resolve failed: {repoError}.";
        throw new HttpRequestException($"Download failed for {label} model: NotFound ({attempts.Last()}).{suffix}");
    }

    private async Task<(string? Url, string? Error)> ResolveOnnxUrlFromRepoAsync(string repo, string label, CancellationToken cancellationToken)
    {
        var token = _settingsService.Settings.HuggingFaceApiKey;
        if (string.IsNullOrWhiteSpace(token))
        {
            var error = "Hugging Face API key required to resolve file list";
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {error}");
            return (null, error);
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, $"https://huggingface.co/api/models/{repo}");
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token.Trim());
            using var resp = await _httpClient.SendAsync(request, cancellationToken);
            if (!resp.IsSuccessStatusCode)
            {
                var error = $"Repo API returned {resp.StatusCode}";
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {error}");
                return (null, error);
            }

            var json = await resp.Content.ReadAsStringAsync(cancellationToken);
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("siblings", out var siblings) || siblings.ValueKind != JsonValueKind.Array)
            {
                var error = "Repo API missing siblings list";
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {error}");
                return (null, error);
            }

            var files = new List<string>();
            foreach (var item in siblings.EnumerateArray())
            {
                if (item.TryGetProperty("rfilename", out var rf) && rf.ValueKind == JsonValueKind.String)
                {
                    files.Add(rf.GetString() ?? string.Empty);
                }
            }

            var onnx = PickBestOnnxFile(files, label);
            if (onnx == null)
            {
                var error = "No .onnx file found in repo";
                Console.WriteLine($"Aesthetic scoring: {error}");
                return (null, error);
            }
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: resolved {label} model file {onnx}");
            return ($"https://huggingface.co/{repo}/resolve/main/{onnx}", null);
        }
        catch
        {
            var error = "Repo API query failed";
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {error}");
            return (null, error);
        }
    }

    private static string? PickBestOnnxFile(IEnumerable<string> files, string label)
    {
        var onnx = files.Where(f => f.EndsWith(".onnx", StringComparison.OrdinalIgnoreCase)).ToList();
        if (onnx.Count == 0) return null;

        var lowerLabel = label.ToLowerInvariant();
        if (lowerLabel.Contains("clip"))
        {
            var preferred = onnx.FirstOrDefault(f =>
                (f.Contains("visual", StringComparison.OrdinalIgnoreCase) && !f.Contains("text", StringComparison.OrdinalIgnoreCase)) &&
                (f.Contains("onnx32", StringComparison.OrdinalIgnoreCase) ||
                 f.Contains("fp32", StringComparison.OrdinalIgnoreCase) ||
                 f.Contains("float32", StringComparison.OrdinalIgnoreCase)));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;

            preferred = onnx.FirstOrDefault(f =>
                f.Contains("visual", StringComparison.OrdinalIgnoreCase) &&
                f.Contains("vit", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;
            preferred = onnx.FirstOrDefault(f =>
                f.Contains("visual", StringComparison.OrdinalIgnoreCase) &&
                f.Contains("clip", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;
            preferred = onnx.FirstOrDefault(f => !f.Contains("text", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;
        }
        else
        {
            var preferred = onnx.FirstOrDefault(f =>
                f.Contains("model.onnx", StringComparison.OrdinalIgnoreCase) ||
                f.Contains("fp32", StringComparison.OrdinalIgnoreCase) ||
                f.Contains("float32", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;

            preferred = onnx.FirstOrDefault(f => f.Contains("optimized", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;
            preferred = onnx.FirstOrDefault(f => f.Contains("aesthetic", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(preferred)) return preferred;
        }

        return onnx.FirstOrDefault();
    }

    private void UpdateManifestResolvedUrl(string label, string url)
    {
        if (_manifest == null || string.IsNullOrWhiteSpace(_manifestPath)) return;
        if (label.Equals("CLIP", StringComparison.OrdinalIgnoreCase))
        {
            _manifest.ClipModelUrl = url;
            _manifest.ClipModelUrls = new List<string> { url };
        }
        else
        {
            _manifest.AestheticModelUrl = url;
            _manifest.AestheticModelUrls = new List<string> { url };
        }

        try
        {
            File.WriteAllText(_manifestPath, JsonSerializer.Serialize(_manifest, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch
        {
            // ignore
        }
    }

    private async Task<bool> DownloadAsync(
        string url,
        string outputPath,
        string label,
        IProgress<DownloadProgressInfo>? progress,
        CancellationToken cancellationToken,
        Func<string, Task<bool>>? validateAsync = null)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        var token = _settingsService.Settings.HuggingFaceApiKey;
        if (!string.IsNullOrWhiteSpace(token))
        {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token.Trim());
        }
        using var resp = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (resp.StatusCode == System.Net.HttpStatusCode.Unauthorized)
        {
            if (string.IsNullOrWhiteSpace(token))
            {
                throw new HttpRequestException("Download unauthorized. Set a Hugging Face API key in Settings > Aesthetic Scoring, then retry.");
            }
            throw new HttpRequestException("Download unauthorized. The Hugging Face API key may be invalid or lack access.");
        }
        if (resp.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {label} model not found at {url}");
            return false;
        }
        if (!resp.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"Download failed for {label} model: {resp.StatusCode} ({url})");
        }

        var total = resp.Content.Headers.ContentLength;
        var targetPath = validateAsync == null ? outputPath : outputPath + ".tmp";
        await using var output = File.Create(targetPath);
        await using var input = await resp.Content.ReadAsStreamAsync(cancellationToken);
        var buffer = new byte[1024 * 1024];
        long readTotal = 0;
        int read;
        while ((read = await input.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken)) > 0)
        {
            await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            readTotal += read;
            if (progress != null)
            {
                progress.Report(new DownloadProgressInfo(label, readTotal, total));
            }
        }
        if (validateAsync != null)
        {
            var isValid = await validateAsync(targetPath);
            if (!isValid)
            {
                if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: {label} model validation failed for {url}");
                File.Delete(targetPath);
                return false;
            }
            File.Move(targetPath, outputPath, true);
        }
        return true;
    }

    private static Bitmap? LoadBitmap(string path)
    {
        try
        {
            using var fs = File.OpenRead(path);
            return new Bitmap(fs);
        }
        catch
        {
            return null;
        }
    }

    private static DenseTensor<float> BuildInputTensorFloat(Bitmap bitmap, int size)
    {
        var stride = size * 4;
        var data = new byte[stride * size];
        var handle = System.Runtime.InteropServices.GCHandle.Alloc(data, System.Runtime.InteropServices.GCHandleType.Pinned);
        try
        {
            bitmap.CopyPixels(new PixelRect(0, 0, size, size), handle.AddrOfPinnedObject(), data.Length, stride);
        }
        finally
        {
            handle.Free();
        }

        var tensor = new DenseTensor<float>(new[] { 1, 3, size, size });
        for (var y = 0; y < size; y++)
        {
            for (var x = 0; x < size; x++)
            {
                var idx = y * stride + x * 4;
                var b = data[idx];
                var g = data[idx + 1];
                var r = data[idx + 2];

                var rf = (r / 255f - ClipMean[0]) / ClipStd[0];
                var gf = (g / 255f - ClipMean[1]) / ClipStd[1];
                var bf = (b / 255f - ClipMean[2]) / ClipStd[2];

                tensor[0, 0, y, x] = rf;
                tensor[0, 1, y, x] = gf;
                tensor[0, 2, y, x] = bf;
            }
        }

        return tensor;
    }

    private Task<float[]?> RunClipAsync(DenseTensor<float> input)
    {
        return Task.Run<float[]?>(() =>
        {
            if (_clipSession == null) return null;
            var inputName = SelectClipInputName(_clipSession);
            if (string.IsNullOrWhiteSpace(inputName)) return null;

            var inputMeta = _clipSession.InputMetadata[inputName];
            using var results = _clipSession.Run(new[] { CreateInputValue(inputName, input, inputMeta) });
            var output = results.FirstOrDefault();
            if (output == null) return null;

            var data = ReadOutputAsFloatArray(output);
            return data.Length > 0 ? data : null;
        });
    }

    private Task<double?> RunAestheticHeadAsync(float[] embedding)
    {
        return Task.Run<double?>(() =>
        {
            if (_aestheticSession == null) return null;
            var inputName = SelectAestheticInputName(_aestheticSession);
            if (string.IsNullOrWhiteSpace(inputName)) return null;

            var meta = _aestheticSession.InputMetadata[inputName];
            var tensor = BuildAestheticInputTensor(embedding, meta);

            using var results = _aestheticSession.Run(new[] { CreateInputValue(inputName, tensor, meta) });
            var output = results.FirstOrDefault();
            if (output == null) return null;

            var scoreArray = ReadOutputAsFloatArray(output);
            var score = scoreArray.FirstOrDefault();
            return (double?)score;
        });
    }

    private Task<double?> RunAestheticImageAsync(DenseTensor<float> input)
    {
        return Task.Run<double?>(() =>
        {
            if (_aestheticSession == null) return null;
            var inputName = SelectAestheticInputName(_aestheticSession);
            if (string.IsNullOrWhiteSpace(inputName)) return null;

            var meta = _aestheticSession.InputMetadata[inputName];
            using var results = _aestheticSession.Run(new[] { CreateInputValue(inputName, input, meta) });
            var output = results.FirstOrDefault();
            if (output == null) return null;

            var scoreArray = ReadOutputAsFloatArray(output);
            var score = scoreArray.FirstOrDefault();
            return (double?)score;
        });
    }

    private static NamedOnnxValue CreateInputValue(string name, DenseTensor<float> tensor, NodeMetadata meta)
    {
        if (IsFloat16(meta))
        {
            var halfTensor = new DenseTensor<Microsoft.ML.OnnxRuntime.Float16>(tensor.Dimensions.ToArray());
            var src = tensor.Buffer.Span;
            var dst = halfTensor.Buffer.Span;
            for (var i = 0; i < src.Length; i++)
            {
                dst[i] = (Microsoft.ML.OnnxRuntime.Float16)src[i];
            }
            return NamedOnnxValue.CreateFromTensor(name, halfTensor);
        }

        return NamedOnnxValue.CreateFromTensor(name, tensor);
    }

    private static bool IsFloat16(NodeMetadata meta)
    {
        if (meta.ElementType == typeof(Microsoft.ML.OnnxRuntime.Float16))
        {
            return true;
        }

        var dataTypeProp = meta.GetType().GetProperty("ElementDataType");
        if (dataTypeProp?.GetValue(meta) is TensorElementType dataType)
        {
            return dataType == TensorElementType.Float16;
        }

        return false;
    }

    private static bool RequiresFloat16(InferenceSession? session)
    {
        if (session == null) return false;
        var inputName = session.InputMetadata.Keys.FirstOrDefault();
        if (string.IsNullOrWhiteSpace(inputName)) return false;
        return IsFloat16(session.InputMetadata[inputName]);
    }

    private static bool IsValidClipImageModel(InferenceSession? session)
    {
        if (session == null) return false;
        foreach (var pair in session.InputMetadata)
        {
            var meta = pair.Value;
            if (!IsFloatInput(meta)) continue;
            if (meta.Dimensions != null && meta.Dimensions.Length == 4)
            {
                return true;
            }
        }
        return false;
    }

    private static string? SelectClipInputName(InferenceSession session)
    {
        foreach (var pair in session.InputMetadata)
        {
            var meta = pair.Value;
            if (!IsFloatInput(meta)) continue;
            if (meta.Dimensions != null && meta.Dimensions.Length == 4)
            {
                return pair.Key;
            }
        }

        foreach (var pair in session.InputMetadata)
        {
            if (IsFloatInput(pair.Value)) return pair.Key;
        }

        return session.InputMetadata.Keys.FirstOrDefault();
    }

    private static bool IsFloatInput(NodeMetadata meta)
    {
        if (IsFloat16(meta)) return true;
        if (meta.ElementType == typeof(float)) return true;

        var dataTypeProp = meta.GetType().GetProperty("ElementDataType");
        if (dataTypeProp?.GetValue(meta) is TensorElementType dataType)
        {
            return dataType == TensorElementType.Float;
        }

        return false;
    }

    private static string? SelectAestheticInputName(InferenceSession session)
    {
        foreach (var pair in session.InputMetadata)
        {
            if (IsFloatInput(pair.Value)) return pair.Key;
        }

        return session.InputMetadata.Keys.FirstOrDefault();
    }

    private static DenseTensor<float> BuildAestheticInputTensor(float[] embedding, NodeMetadata meta)
    {
        var dims = meta.Dimensions?.Select(d => d <= 0 ? 1 : (int)d).ToArray() ?? Array.Empty<int>();
        if (dims.Length == 0)
        {
            dims = new[] { 1, embedding.Length };
        }

        if (dims.Length == 2)
        {
            dims[0] = 1;
            dims[1] = embedding.Length;
        }
        else if (dims.Length >= 3)
        {
            var assigned = false;
            for (var i = 0; i < dims.Length; i++)
            {
                if (dims[i] == embedding.Length)
                {
                    assigned = true;
                }
                else if (dims[i] <= 0)
                {
                    dims[i] = 1;
                }
            }

            if (!assigned)
            {
                dims[^1] = embedding.Length;
                for (var i = 0; i < dims.Length - 1; i++)
                {
                    if (dims[i] <= 0) dims[i] = 1;
                }
            }
        }

        var tensor = new DenseTensor<float>(dims);
        var span = tensor.Buffer.Span;
        var count = Math.Min(span.Length, embedding.Length);
        for (var i = 0; i < count; i++)
        {
            span[i] = embedding[i];
        }
        return tensor;
    }

    private void DetectAestheticModel(InferenceSession? session)
    {
        _aestheticIsImageModel = false;
        _aestheticImageSize = 0;
        if (session == null) return;
        var inputName = SelectAestheticInputName(session);
        if (string.IsNullOrWhiteSpace(inputName)) return;
        var meta = session.InputMetadata[inputName];
        var dims = meta.Dimensions ?? Array.Empty<int>();
        if (dims.Length == 4 && dims[1] == 3 && dims[2] > 0 && dims[2] == dims[3])
        {
            _aestheticIsImageModel = true;
            _aestheticImageSize = dims[2];
            if (_settingsService.Settings.Verbose) Console.WriteLine($"Aesthetic scoring: using image model input {dims[2]}x{dims[3]}");
        }
        else
        {
            if (_settingsService.Settings.Verbose) Console.WriteLine("Aesthetic scoring: using embedding head model");
        }
    }

    private static IReadOnlyList<string> PreferFloat32Urls(IReadOnlyList<string> urls)
    {
        var list = urls.Where(u => !string.IsNullOrWhiteSpace(u)).ToList();
        if (list.Count == 0) return list;

        return list
            .OrderByDescending(u => u.Contains("onnx32", StringComparison.OrdinalIgnoreCase) ||
                                     u.Contains("fp32", StringComparison.OrdinalIgnoreCase) ||
                                     u.Contains("float32", StringComparison.OrdinalIgnoreCase) ||
                                     u.Contains("model.onnx", StringComparison.OrdinalIgnoreCase))
            .ThenBy(u => u.Contains("optimized", StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    private static IReadOnlyList<string> PreferVisualFloat32Urls(IReadOnlyList<string> urls)
    {
        var list = urls.Where(u => !string.IsNullOrWhiteSpace(u)).ToList();
        if (list.Count == 0) return list;

        return list
            .OrderByDescending(u => u.Contains("visual", StringComparison.OrdinalIgnoreCase))
            .ThenBy(u => u.Contains("text", StringComparison.OrdinalIgnoreCase))
            .ThenByDescending(u => u.Contains("onnx32", StringComparison.OrdinalIgnoreCase) ||
                                   u.Contains("fp32", StringComparison.OrdinalIgnoreCase) ||
                                   u.Contains("float32", StringComparison.OrdinalIgnoreCase))
            .ToList();
    }


    private static float[] ReadOutputAsFloatArray(NamedOnnxValue output)
    {
        if (output.Value is DenseTensor<float> floatTensor)
        {
            return floatTensor.ToArray();
        }
        if (output.Value is DenseTensor<Microsoft.ML.OnnxRuntime.Float16> halfTensor)
        {
            var data = new float[halfTensor.Length];
            var src = halfTensor.Buffer.Span;
            for (var i = 0; i < src.Length; i++)
            {
                data[i] = (float)src[i];
            }
            return data;
        }

        try
        {
            return output.AsEnumerable<float>().ToArray();
        }
        catch
        {
            return Array.Empty<float>();
        }
    }

    private static float[] NormalizeEmbedding(float[] embedding)
    {
        var norm = 0f;
        foreach (var v in embedding)
        {
            norm += v * v;
        }
        norm = (float)Math.Sqrt(norm);
        if (norm <= 0f) return embedding;

        var normalized = new float[embedding.Length];
        for (var i = 0; i < embedding.Length; i++)
        {
            normalized[i] = embedding[i] / norm;
        }
        return normalized;
    }

    private static IEnumerable<List<T>> Chunk<T>(IReadOnlyList<T> items, int chunkSize)
    {
        if (chunkSize <= 0) chunkSize = 1;

        for (int i = 0; i < items.Count; i += chunkSize)
        {
            var take = Math.Min(chunkSize, items.Count - i);
            var chunk = new List<T>(take);
            for (int j = 0; j < take; j++)
                chunk.Add(items[i + j]);
            yield return chunk;
        }
    }

    public void Dispose()
    {
        _clipSession?.Dispose();
        _clipSession = null;
        _aestheticSession?.Dispose();
        _aestheticSession = null;
        _httpClient.Dispose();
        _modelGate.Dispose();
    }
}

public sealed class AestheticScoreResult
{
    public double Score { get; init; }
    public string ModelName { get; init; } = "aesthetic-v1";
    public int ElapsedMs { get; init; }
}

public sealed class RemoteScoreResponse
{
    public double? Score { get; set; }
    public string? Model { get; set; }
}

public sealed class RemoteBatchScoreItem
{
    public string? Filename { get; set; }
    public double? Score { get; set; }
}

public sealed class RemoteBatchScoreResponse
{
    public List<RemoteBatchScoreItem>? Results { get; set; }
    public int? Count { get; set; }
    public string[]? Providers_In_Use { get; set; }  // JSON is "providers_in_use" but case-insensitive deserialization can handle it
    public string? Model { get; set; }
}


public sealed record DownloadProgressInfo(string Label, long BytesDownloaded, long? TotalBytes)
{
    public double? Ratio => TotalBytes.HasValue && TotalBytes.Value > 0
        ? BytesDownloaded / (double)TotalBytes.Value
        : null;
}

public sealed class ModelManifest
{
    public string ClipModelUrl { get; set; } = "";
    public List<string> ClipModelUrls { get; set; } = new();
    public string ClipModelRepo { get; set; } = "Marqo/onnx-open_clip-ViT-B-32";
    public List<string> ClipModelRepos { get; set; } = new();
    public string AestheticModelUrl { get; set; } = "";
    public List<string> AestheticModelUrls { get; set; } = new();
    public string AestheticModelRepo { get; set; } = "fpqwecfuw/Aesthetic-Predictor";
    public List<string> AestheticModelRepos { get; set; } = new();
    public string AestheticModelName { get; set; } = "aesthetic-v1";
    public int InputSize { get; set; } = AestheticScoringService.DefaultInputSize;

    public static ModelManifest CreateDefault()
    {
        return new ModelManifest
        {
            ClipModelUrl = "https://huggingface.co/Marqo/onnx-open_clip-ViT-B-32/resolve/main/onnx32-open_clip-ViT-B-32-laion2b_e16-visual.onnx",
            ClipModelUrls = new List<string>
            {
                "https://huggingface.co/Marqo/onnx-open_clip-ViT-B-32/resolve/main/onnx32-open_clip-ViT-B-32-laion2b_e16-visual.onnx"
            },
            ClipModelRepo = "Marqo/onnx-open_clip-ViT-B-32",
            ClipModelRepos = new List<string>
            {
                "Marqo/onnx-open_clip-ViT-B-32",
                "Marqo/onnx-open_clip-ViT-L-14",
                "onnx-community/clip-vit-base-patch32"
            },
            AestheticModelUrl = "https://huggingface.co/fsw/aesthetic-predictor-v2-5_onnx/resolve/main/aesthetic_predictor_v2_5.onnx",
            AestheticModelUrls = new List<string>
            {
                "https://huggingface.co/fsw/aesthetic-predictor-v2-5_onnx/resolve/main/aesthetic_predictor_v2_5.onnx"
            },
            AestheticModelRepo = "fpqwecfuw/Aesthetic-Predictor",
            AestheticModelRepos = new List<string>
            {
                "fpqwecfuw/Aesthetic-Predictor",
                "fsw/aesthetic-predictor-v2-5_onnx"
            },
            AestheticModelName = "clip-vit-base-patch32 + aesthetic-v1",
            InputSize = AestheticScoringService.DefaultInputSize
        };
    }

    public IReadOnlyList<string> GetClipModelUrls()
    {
        if (ClipModelUrls != null && ClipModelUrls.Count > 0)
        {
            return ClipModelUrls;
        }
        return string.IsNullOrWhiteSpace(ClipModelUrl) ? Array.Empty<string>() : new[] { ClipModelUrl };
    }

    public IReadOnlyList<string> GetClipModelRepos()
    {
        if (ClipModelRepos != null && ClipModelRepos.Count > 0)
        {
            return ClipModelRepos;
        }
        return string.IsNullOrWhiteSpace(ClipModelRepo) ? Array.Empty<string>() : new[] { ClipModelRepo };
    }

    public IReadOnlyList<string> GetAestheticModelUrls()
    {
        if (AestheticModelUrls != null && AestheticModelUrls.Count > 0)
        {
            return AestheticModelUrls;
        }
        return string.IsNullOrWhiteSpace(AestheticModelUrl) ? Array.Empty<string>() : new[] { AestheticModelUrl };
    }

    public IReadOnlyList<string> GetAestheticModelRepos()
    {
        if (AestheticModelRepos != null && AestheticModelRepos.Count > 0)
        {
            return AestheticModelRepos;
        }
        return string.IsNullOrWhiteSpace(AestheticModelRepo) ? Array.Empty<string>() : new[] { AestheticModelRepo };
    }
}
