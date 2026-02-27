using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Media.Imaging;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using PromptTool.Core.Services;

namespace PromptTool.Services;

public sealed class PromptMatchScoringService
{
    private const string ClipModelFileName = "clip_prompt_match.onnx";
    private const string ClipVocabFileName = "clip_vocab.json";
    private const string ClipMergesFileName = "clip_merges.txt";
    private const string ClipModelUrl = "https://huggingface.co/openai/clip-vit-base-patch32/resolve/main/onnx/model.onnx";
    private const string ClipVocabUrl = "https://huggingface.co/openai/clip-vit-base-patch32/resolve/main/vocab.json";
    private const string ClipMergesUrl = "https://huggingface.co/openai/clip-vit-base-patch32/resolve/main/merges.txt";
    private const int ClipMaxTokens = 77;
    private const int ClipInputSize = 224;
    private static readonly float[] ClipMean = { 0.48145466f, 0.4578275f, 0.40821073f };
    private static readonly float[] ClipStd = { 0.26862954f, 0.26130258f, 0.27577711f };

    private readonly ScoringCacheService _cacheService;
    private readonly SettingsService _settingsService;
    private readonly HttpClient _httpClient = new();
    private readonly SemaphoreSlim _modelGate = new(1, 1);
    private InferenceSession? _clipSession;
    private ClipTokenizer? _tokenizer;
    private string? _inputIdsName;
    private string? _attentionMaskName;
    private string? _pixelValuesName;
    private string? _logitsName;
    private string? _imageEmbedsName;
    private string? _textEmbedsName;

    public PromptMatchScoringService(ScoringCacheService cacheService, SettingsService settingsService)
    {
        _cacheService = cacheService;
        _settingsService = settingsService;
    }

    public async Task<double?> ScorePromptMatchAsync(
        Bitmap bitmap,
        string prompt,
        Func<string, Task<bool>>? confirmDownloadAsync,
        Action<string>? status = null,
        IProgress<DownloadProgressInfo>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(prompt)) return null;
        if (!await EnsureModelsAsync(confirmDownloadAsync, status, progress, cancellationToken))
        {
            return null;
        }

        await _modelGate.WaitAsync(cancellationToken);
        try
        {
            if (_clipSession == null || _tokenizer == null)
            {
                return null;
            }

            using var scaled = bitmap.CreateScaledBitmap(new PixelSize(ClipInputSize, ClipInputSize), BitmapInterpolationMode.HighQuality);
            var pixelTensor = BuildImageTensor(scaled, ClipInputSize);
            var (inputIds, attentionMask) = _tokenizer.Encode(prompt, ClipMaxTokens);

            var inputs = new List<NamedOnnxValue>();
            if (_inputIdsName != null)
            {
                inputs.Add(NamedOnnxValue.CreateFromTensor(_inputIdsName, new DenseTensor<long>(inputIds, new[] { 1, ClipMaxTokens })));
            }
            if (_attentionMaskName != null)
            {
                inputs.Add(NamedOnnxValue.CreateFromTensor(_attentionMaskName, new DenseTensor<long>(attentionMask, new[] { 1, ClipMaxTokens })));
            }
            if (_pixelValuesName != null)
            {
                inputs.Add(NamedOnnxValue.CreateFromTensor(_pixelValuesName, pixelTensor));
            }

            using var results = _clipSession.Run(inputs);
            return ExtractPromptMatch(results);
        }
        finally
        {
            _modelGate.Release();
        }
    }

    private async Task<bool> EnsureModelsAsync(
        Func<string, Task<bool>>? confirmDownloadAsync,
        Action<string>? status,
        IProgress<DownloadProgressInfo>? progress,
        CancellationToken cancellationToken)
    {
        await _modelGate.WaitAsync(cancellationToken);
        try
        {
            if (_clipSession != null && _tokenizer != null)
            {
                return true;
            }

            _cacheService.EnsureDirectories();
            var modelsDir = _cacheService.GetModelsDir();
            var modelPath = Path.Combine(modelsDir, ClipModelFileName);
            var vocabPath = Path.Combine(modelsDir, ClipVocabFileName);
            var mergesPath = Path.Combine(modelsDir, ClipMergesFileName);

            if (!File.Exists(modelPath) || !File.Exists(vocabPath) || !File.Exists(mergesPath))
            {
                if (confirmDownloadAsync == null)
                {
                    status?.Invoke("Prompt match model not downloaded.");
                    return false;
                }

                var confirm = await confirmDownloadAsync(
                    "Prompt match scoring needs the CLIP model and tokenizer (~400MB). Download now?");
                if (!confirm) return false;

                await DownloadAsync(ClipModelUrl, modelPath, "CLIP model", status, progress, cancellationToken);
                await DownloadAsync(ClipVocabUrl, vocabPath, "CLIP vocab", status, progress, cancellationToken);
                await DownloadAsync(ClipMergesUrl, mergesPath, "CLIP merges", status, progress, cancellationToken);
            }

            _tokenizer = new ClipTokenizer(vocabPath, mergesPath);
            _clipSession = new InferenceSession(modelPath);
            ResolveNames(_clipSession);
            if (_inputIdsName == null || _pixelValuesName == null)
            {
                status?.Invoke("CLIP prompt model missing required inputs.");
                _clipSession?.Dispose();
                _clipSession = null;
                _tokenizer = null;
                return false;
            }
            return true;
        }
        finally
        {
            _modelGate.Release();
        }
    }

    private void ResolveNames(InferenceSession session)
    {
        _inputIdsName = FindInputName(session, "input_ids") ?? FindFirstInputByType(session, TensorElementType.Int64);
        _attentionMaskName = FindInputName(session, "attention_mask");
        _pixelValuesName = FindInputName(session, "pixel_values") ?? FindFirstInputByType(session, TensorElementType.Float);

        _logitsName = FindOutputName(session, "logits_per_image");
        _imageEmbedsName = FindOutputName(session, "image_embeds");
        _textEmbedsName = FindOutputName(session, "text_embeds");
    }

    private static string? FindInputName(InferenceSession session, string contains)
    {
        return session.InputMetadata.Keys.FirstOrDefault(
            name => name.Contains(contains, StringComparison.OrdinalIgnoreCase));
    }

    private static string? FindFirstInputByType(InferenceSession session, TensorElementType type)
    {
        foreach (var kvp in session.InputMetadata)
        {
            if (type == TensorElementType.Int64 && kvp.Value.ElementType == typeof(long)) return kvp.Key;
            if (type == TensorElementType.Float && kvp.Value.ElementType == typeof(float)) return kvp.Key;
        }

        return null;
    }

    private static string? FindOutputName(InferenceSession session, string contains)
    {
        return session.OutputMetadata.Keys.FirstOrDefault(
            name => name.Contains(contains, StringComparison.OrdinalIgnoreCase));
    }

    private static double? ExtractPromptMatch(IReadOnlyCollection<DisposableNamedOnnxValue> results)
    {
        if (results.Count == 0) return null;

        var logits = results.FirstOrDefault(r => r.Name.Contains("logits_per_image", StringComparison.OrdinalIgnoreCase));
        if (logits?.Value is Tensor<float> logitsTensor && logitsTensor.Length > 0)
        {
            var value = logitsTensor.ToArray()[0];
            var scaled = 100.0 / (1.0 + Math.Exp(-value));
            return Math.Clamp(scaled, 0, 100);
        }

        var imageEmbeds = results.FirstOrDefault(r => r.Name.Contains("image_embeds", StringComparison.OrdinalIgnoreCase));
        var textEmbeds = results.FirstOrDefault(r => r.Name.Contains("text_embeds", StringComparison.OrdinalIgnoreCase));
        if (imageEmbeds?.Value is Tensor<float> imageTensor && textEmbeds?.Value is Tensor<float> textTensor)
        {
            var imageVec = ExtractVector(imageTensor);
            var textVec = ExtractVector(textTensor);
            if (imageVec == null || textVec == null) return null;
            var score = CosineSimilarity(imageVec, textVec);
            return (score + 1) * 50;
        }

        return null;
    }

    private static float[]? ExtractVector(Tensor<float> tensor)
    {
        if (tensor.Length == 0) return null;
        var data = tensor.ToArray();
        if (data.Length == 0) return null;
        if (tensor.Dimensions.Length <= 1) return data;
        var size = tensor.Dimensions[^1];
        return data.Take(size).ToArray();
    }

    private static double CosineSimilarity(IReadOnlyList<float> a, IReadOnlyList<float> b)
    {
        var len = Math.Min(a.Count, b.Count);
        if (len == 0) return 0;
        double dot = 0;
        double sumA = 0;
        double sumB = 0;
        for (var i = 0; i < len; i++)
        {
            var av = a[i];
            var bv = b[i];
            dot += av * bv;
            sumA += av * av;
            sumB += bv * bv;
        }
        if (sumA == 0 || sumB == 0) return 0;
        return dot / (Math.Sqrt(sumA) * Math.Sqrt(sumB));
    }

    private static DenseTensor<float> BuildImageTensor(Bitmap bitmap, int size)
    {
        var rowBytes = size * 4;
        var buffer = new byte[rowBytes * size];
        var handle = System.Runtime.InteropServices.GCHandle.Alloc(buffer, System.Runtime.InteropServices.GCHandleType.Pinned);
        try
        {
            bitmap.CopyPixels(new PixelRect(0, 0, size, size), handle.AddrOfPinnedObject(), buffer.Length, rowBytes);
        }
        finally
        {
            handle.Free();
        }

        var tensor = new DenseTensor<float>(new[] { 1, 3, size, size });
        var idx = 0;
        for (var y = 0; y < size; y++)
        {
            for (var x = 0; x < size; x++)
            {
                var offset = idx * 4;
                var b = buffer[offset] / 255f;
                var g = buffer[offset + 1] / 255f;
                var r = buffer[offset + 2] / 255f;

                tensor[0, 0, y, x] = (r - ClipMean[0]) / ClipStd[0];
                tensor[0, 1, y, x] = (g - ClipMean[1]) / ClipStd[1];
                tensor[0, 2, y, x] = (b - ClipMean[2]) / ClipStd[2];
                idx++;
            }
        }

        return tensor;
    }

    private async Task DownloadAsync(
        string url,
        string outputPath,
        string label,
        Action<string>? status,
        IProgress<DownloadProgressInfo>? progress,
        CancellationToken cancellationToken)
    {
        if (File.Exists(outputPath)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? _cacheService.GetModelsDir());

        status?.Invoke($"Downloading {label}...");
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (!string.IsNullOrWhiteSpace(_settingsService.Settings.HuggingFaceApiKey))
        {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue(
                "Bearer", _settingsService.Settings.HuggingFaceApiKey.Trim());
        }

        using var resp = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        resp.EnsureSuccessStatusCode();

        var totalBytes = resp.Content.Headers.ContentLength;
        await using var input = await resp.Content.ReadAsStreamAsync(cancellationToken);
        await using var output = File.Create(outputPath);

        var buffer = new byte[1024 * 1024];
        long readTotal = 0;
        int read;
        while ((read = await input.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken)) > 0)
        {
            await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            readTotal += read;
            progress?.Report(new DownloadProgressInfo(label, readTotal, totalBytes));
        }
    }
}
