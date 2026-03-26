using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;

namespace PromptTool.Services;

public sealed class SimilarityFingerprintCacheService
{
    private const int SchemaVersion = 1;
    private const string CacheFileName = "similarity-cache-v1.json";
    private readonly SemaphoreSlim _ioLock = new(1, 1);
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    private SimilarityFingerprintCacheDocument _document = new();
    private bool _loaded;
    private string? _historyDir;

    public async Task<int> UpsertEntryAsync(
        HistoryEntry entry,
        string historyDir,
        ImageCacheService imageCache,
        CancellationToken ct = default)
    {
        if (entry.Images == null || entry.Images.Count == 0)
        {
            return 0;
        }

        return await UpsertImagesAsync(entry.Images, historyDir, imageCache, ct);
    }

    public async Task<int> UpsertImagesAsync(
        IEnumerable<HistoryImage> images,
        string historyDir,
        ImageCacheService imageCache,
        CancellationToken ct = default,
        int maxCount = int.MaxValue)
    {
        await EnsureLoadedAsync(historyDir, ct);
        await _ioLock.WaitAsync(ct);
        try
        {
            var processed = 0;
            foreach (var image in images)
            {
                ct.ThrowIfCancellationRequested();
                if (processed >= maxCount)
                {
                    break;
                }

                var key = TryBuildCacheKey(image, historyDir);
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                if (TryGetFileFingerprintMetadata(image, historyDir, out var fileSize, out var modifiedTicks) &&
                    _document.Items.TryGetValue(key, out var existing) &&
                    existing.FileSize == fileSize &&
                    existing.ModifiedTicksUtc == modifiedTicks)
                {
                    continue;
                }

                var fingerprint = ComputeFingerprint(image, historyDir, imageCache);
                if (fingerprint == null)
                {
                    continue;
                }

                _document.Items[key] = new SimilarityFingerprintCacheItem
                {
                    ImagePath = image.ImagePath,
                    PHash = fingerprint.Value.PHash,
                    Sharpness = fingerprint.Value.Sharpness,
                    FileSize = fileSize,
                    ModifiedTicksUtc = modifiedTicks
                };
                processed++;
            }

            if (processed > 0)
            {
                _document.Version = SchemaVersion;
                _document.UpdatedUtc = DateTime.UtcNow;
                await SaveDocumentUnsafeAsync(ct);
            }

            return processed;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    public async Task<int> BackfillMissingAsync(
        IReadOnlyList<HistoryEntry> entries,
        string historyDir,
        ImageCacheService imageCache,
        CancellationToken ct = default,
        int maxCount = 25)
    {
        await EnsureLoadedAsync(historyDir, ct);
        await _ioLock.WaitAsync(ct);
        try
        {
            var missing = new List<HistoryImage>();
            foreach (var entry in entries)
            {
                ct.ThrowIfCancellationRequested();
                if (entry.Images == null || entry.Images.Count == 0)
                {
                    continue;
                }

                foreach (var image in entry.Images)
                {
                    var key = TryBuildCacheKey(image, historyDir);
                    if (string.IsNullOrWhiteSpace(key))
                    {
                        continue;
                    }

                    if (_document.Items.TryGetValue(key, out var existing) &&
                        TryGetFileFingerprintMetadata(image, historyDir, out var fileSize, out var modifiedTicks) &&
                        existing.FileSize == fileSize &&
                        existing.ModifiedTicksUtc == modifiedTicks)
                    {
                        continue;
                    }

                    missing.Add(image);
                    if (missing.Count >= maxCount)
                    {
                        break;
                    }
                }

                if (missing.Count >= maxCount)
                {
                    break;
                }
            }

            if (missing.Count == 0)
            {
                return 0;
            }

            var processed = 0;
            foreach (var image in missing)
            {
                ct.ThrowIfCancellationRequested();
                var key = TryBuildCacheKey(image, historyDir);
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                TryGetFileFingerprintMetadata(image, historyDir, out var fileSize, out var modifiedTicks);
                var fingerprint = ComputeFingerprint(image, historyDir, imageCache);
                if (fingerprint == null)
                {
                    continue;
                }

                _document.Items[key] = new SimilarityFingerprintCacheItem
                {
                    ImagePath = image.ImagePath,
                    PHash = fingerprint.Value.PHash,
                    Sharpness = fingerprint.Value.Sharpness,
                    FileSize = fileSize,
                    ModifiedTicksUtc = modifiedTicks
                };
                processed++;
            }

            if (processed > 0)
            {
                _document.Version = SchemaVersion;
                _document.UpdatedUtc = DateTime.UtcNow;
                await SaveDocumentUnsafeAsync(ct);
            }

            return processed;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    public async Task<IReadOnlyDictionary<string, SimilarityFingerprint>> GetFingerprintsAsync(
        string historyDir,
        CancellationToken ct = default)
    {
        await EnsureLoadedAsync(historyDir, ct);
        await _ioLock.WaitAsync(ct);
        try
        {
            var snapshot = new Dictionary<string, SimilarityFingerprint>(StringComparer.OrdinalIgnoreCase);
            foreach (var (key, item) in _document.Items)
            {
                snapshot[key] = new SimilarityFingerprint(
                    item.PHash,
                    item.Sharpness,
                    item.FileSize,
                    item.ModifiedTicksUtc);
            }

            return snapshot;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    public async Task<IReadOnlyList<SimilarityDuplicateMatch>> FindNearDuplicatesAgainstExistingAsync(
        IEnumerable<HistoryImage> targetImages,
        string historyDir,
        int threshold,
        CancellationToken ct = default,
        int maxMatches = 40)
    {
        var targets = targetImages?.ToList() ?? new List<HistoryImage>();
        if (targets.Count == 0 || maxMatches <= 0)
        {
            return Array.Empty<SimilarityDuplicateMatch>();
        }

        await EnsureLoadedAsync(historyDir, ct);
        await _ioLock.WaitAsync(ct);
        try
        {
            var targetKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var targetFingerprints = new List<(string Key, SimilarityFingerprintCacheItem Item)>();
            foreach (var image in targets)
            {
                var key = TryBuildCacheKey(image, historyDir);
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                if (!_document.Items.TryGetValue(key, out var item))
                {
                    continue;
                }

                targetKeys.Add(key);
                targetFingerprints.Add((key, item));
            }

            if (targetFingerprints.Count == 0)
            {
                return Array.Empty<SimilarityDuplicateMatch>();
            }

            var matches = new List<SimilarityDuplicateMatch>();
            foreach (var (sourceKey, sourceFingerprint) in targetFingerprints)
            {
                ct.ThrowIfCancellationRequested();
                foreach (var (candidateKey, candidateFingerprint) in _document.Items)
                {
                    if (targetKeys.Contains(candidateKey))
                    {
                        continue;
                    }

                    var distance = ModelComparisonService.HammingDistance(sourceFingerprint.PHash, candidateFingerprint.PHash);
                    if (distance > threshold)
                    {
                        continue;
                    }

                    matches.Add(new SimilarityDuplicateMatch(
                        sourceKey,
                        sourceFingerprint.ImagePath,
                        candidateKey,
                        candidateFingerprint.ImagePath,
                        distance));

                    if (matches.Count >= maxMatches)
                    {
                        return matches;
                    }
                }
            }

            return matches;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    public async Task<IReadOnlyDictionary<string, int>> GetNearestDuplicateDistancesAsync(
        IEnumerable<HistoryImage> targetImages,
        string historyDir,
        int threshold,
        bool excludeProvidedTargets = true,
        CancellationToken ct = default)
    {
        var targets = targetImages?.ToList() ?? new List<HistoryImage>();
        if (targets.Count == 0)
        {
            return new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        }

        await EnsureLoadedAsync(historyDir, ct);
        await _ioLock.WaitAsync(ct);
        try
        {
            var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            var targetKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var targetFingerprints = new List<(string Key, SimilarityFingerprintCacheItem Item)>();
            foreach (var image in targets)
            {
                var key = TryBuildCacheKey(image, historyDir);
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                if (!_document.Items.TryGetValue(key, out var item))
                {
                    continue;
                }

                targetKeys.Add(key);
                targetFingerprints.Add((key, item));
            }

            foreach (var (sourceKey, sourceFingerprint) in targetFingerprints)
            {
                ct.ThrowIfCancellationRequested();
                var best = int.MaxValue;
                foreach (var (candidateKey, candidateFingerprint) in _document.Items)
                {
                    if (string.Equals(candidateKey, sourceKey, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (excludeProvidedTargets && targetKeys.Contains(candidateKey))
                    {
                        continue;
                    }

                    var distance = ModelComparisonService.HammingDistance(sourceFingerprint.PHash, candidateFingerprint.PHash);
                    if (distance < best)
                    {
                        best = distance;
                        if (best == 0)
                        {
                            break;
                        }
                    }
                }

                if (best <= threshold)
                {
                    result[sourceKey] = best;
                }
            }

            return result;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    private async Task EnsureLoadedAsync(string historyDir, CancellationToken ct)
    {
        if (_loaded && string.Equals(_historyDir, historyDir, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        await _ioLock.WaitAsync(ct);
        try
        {
            if (_loaded && string.Equals(_historyDir, historyDir, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            _historyDir = historyDir;
            _document = new SimilarityFingerprintCacheDocument();
            var path = GetCachePath(historyDir);
            if (File.Exists(path))
            {
                try
                {
                    var json = await File.ReadAllTextAsync(path, ct);
                    var loaded = JsonSerializer.Deserialize<SimilarityFingerprintCacheDocument>(json, _jsonOptions);
                    if (loaded != null && loaded.Version == SchemaVersion)
                    {
                        _document = loaded;
                    }
                }
                catch
                {
                    _document = new SimilarityFingerprintCacheDocument();
                }
            }

            _loaded = true;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    private async Task SaveDocumentUnsafeAsync(CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(_historyDir))
        {
            return;
        }

        var path = GetCachePath(_historyDir);
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var tmpPath = $"{path}.tmp";
        var json = JsonSerializer.Serialize(_document, _jsonOptions);
        await File.WriteAllTextAsync(tmpPath, json, ct);
        File.Move(tmpPath, path, true);
    }

    private static string GetCachePath(string historyDir)
    {
        return Path.Combine(historyDir, "index", CacheFileName);
    }

    public static string? TryBuildImageKey(HistoryImage image, string historyDir)
    {
        if (string.IsNullOrWhiteSpace(image.ImagePath))
        {
            return null;
        }

        var full = Path.IsPathRooted(image.ImagePath)
            ? image.ImagePath
            : Path.Combine(historyDir, image.ImagePath);
        try
        {
            return Path.GetFullPath(full).Replace('\\', '/').ToLowerInvariant();
        }
        catch
        {
            return full.Replace('\\', '/').ToLowerInvariant();
        }
    }

    private static string? TryBuildCacheKey(HistoryImage image, string historyDir)
    {
        return TryBuildImageKey(image, historyDir);
    }

    private static bool TryGetFileFingerprintMetadata(HistoryImage image, string historyDir, out long fileSize, out long modifiedTicks)
    {
        fileSize = 0;
        modifiedTicks = 0;
        if (string.IsNullOrWhiteSpace(image.ImagePath))
        {
            if (image.ImageBytes != null && image.ImageBytes.Length > 0)
            {
                fileSize = image.ImageBytes.Length;
                modifiedTicks = 0;
                return true;
            }

            return false;
        }

        var full = Path.IsPathRooted(image.ImagePath)
            ? image.ImagePath
            : Path.Combine(historyDir, image.ImagePath);
        if (!File.Exists(full))
        {
            return false;
        }

        var info = new FileInfo(full);
        fileSize = info.Length;
        modifiedTicks = info.LastWriteTimeUtc.Ticks;
        return true;
    }

    private static (ulong PHash, double Sharpness)? ComputeFingerprint(HistoryImage image, string historyDir, ImageCacheService imageCache)
    {
        Bitmap? bitmap = null;
        try
        {
            if (!string.IsNullOrWhiteSpace(image.ImagePath))
            {
                bitmap = imageCache.GetOrLoad(image.ImagePath, 512, historyDir);
            }
            else if (image.ImageBytes is { Length: > 0 })
            {
                using var ms = new MemoryStream(image.ImageBytes);
                bitmap = new Bitmap(ms);
            }

            if (bitmap == null)
            {
                return null;
            }

            var phash = ModelComparisonService.ComputePHash(bitmap);
            var sharpness = image.SharpnessScore ?? ScoringHelper.CalculateSharpnessScore(bitmap);
            return (phash, sharpness);
        }
        catch
        {
            return null;
        }
    }

    private sealed class SimilarityFingerprintCacheDocument
    {
        public int Version { get; set; } = SchemaVersion;
        public DateTime UpdatedUtc { get; set; } = DateTime.UtcNow;
        public Dictionary<string, SimilarityFingerprintCacheItem> Items { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    }

    private sealed class SimilarityFingerprintCacheItem
    {
        public string? ImagePath { get; set; }
        public ulong PHash { get; set; }
        public double Sharpness { get; set; }
        public long FileSize { get; set; }
        public long ModifiedTicksUtc { get; set; }
    }
}

public sealed record SimilarityFingerprint(
    ulong PHash,
    double Sharpness,
    long FileSize,
    long ModifiedTicksUtc);

public sealed record SimilarityDuplicateMatch(
    string SourceKey,
    string? SourceImagePath,
    string MatchKey,
    string? MatchImagePath,
    int Distance);
