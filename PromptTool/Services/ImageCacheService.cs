using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Avalonia.Media.Imaging;

namespace PromptTool.Services;

public sealed class ImageCacheService : IDisposable
{
    private sealed class CacheItem
    {
        public CacheItem(string key, Bitmap bitmap, long bytes)
        {
            Key = key;
            Bitmap = bitmap;
            Bytes = bytes;
        }

        public string Key { get; }
        public Bitmap Bitmap { get; }
        public long Bytes { get; }
    }

    private readonly Dictionary<string, LinkedListNode<CacheItem>> _entries = new(StringComparer.OrdinalIgnoreCase);
    private readonly LinkedList<CacheItem> _lru = new();
    private readonly object _lock = new();
    private long _currentBytes;

    public long MaxBytes { get; set; } = 512L * 1024 * 1024; // 512 MB
    public long MaxDiskBytes { get; set; } = 2L * 1024 * 1024 * 1024; // 2 GB
    public string? DiskCacheDir { get; set; }
    public long CurrentBytes
    {
        get
        {
            lock (_lock)
            {
                return _currentBytes;
            }
        }
    }

    public Bitmap? GetOrLoad(string? path, int? decodeWidth = null, string? baseDir = null)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        var full = Path.IsPathRooted(path)
            ? path
            : string.IsNullOrWhiteSpace(baseDir) ? path : Path.Combine(baseDir, path);
        if (!File.Exists(full)) return null;

        var key = $"{full}|w={decodeWidth?.ToString() ?? "full"}";
        if (TryGet(key, out var cached))
        {
            PerfLogger.Count("ImageCache.Hit");
            return cached;
        }

        if (decodeWidth.HasValue && TryGetFromDisk(full, decodeWidth.Value, out var diskCached) && diskCached != null)
        {
            PerfLogger.Count("ImageCache.DiskHit");
            Add(key, diskCached);
            return diskCached;
        }

        Bitmap? bitmap = null;
        try
        {
            if (decodeWidth.HasValue)
            {
                using var fs = File.OpenRead(full);
                bitmap = Bitmap.DecodeToWidth(fs, decodeWidth.Value);
            }
            else
            {
                bitmap = new Bitmap(full);
            }
        }
        catch
        {
            bitmap?.Dispose();
            return null;
        }

        if (bitmap == null) return null;

        PerfLogger.Count("ImageCache.Miss");
        Add(key, bitmap);
        if (decodeWidth.HasValue)
        {
            TryWriteToDisk(full, decodeWidth.Value, bitmap);
        }
        return bitmap;
    }

    public bool TryGetCached(string? path, int? decodeWidth, string? baseDir, out Bitmap? bitmap)
    {
        bitmap = null;
        if (string.IsNullOrWhiteSpace(path)) return false;
        var full = Path.IsPathRooted(path)
            ? path
            : string.IsNullOrWhiteSpace(baseDir) ? path : Path.Combine(baseDir, path);
        if (string.IsNullOrWhiteSpace(full)) return false;

        var key = $"{full}|w={decodeWidth?.ToString() ?? "full"}";
        return TryGet(key, out bitmap);
    }

    public long GetDiskCacheBytes()
    {
        var dir = DiskCacheDir;
        if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir)) return 0;
        try
        {
            return Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories)
                .Select(path => new FileInfo(path).Length)
                .Sum();
        }
        catch
        {
            return 0;
        }
    }

    public void ClearDiskCache()
    {
        var dir = DiskCacheDir;
        if (string.IsNullOrWhiteSpace(dir)) return;
        try
        {
            if (Directory.Exists(dir))
            {
                Directory.Delete(dir, true);
            }
        }
        catch
        {
            // ignore
        }
    }

    private bool TryGet(string key, out Bitmap? bitmap)
    {
        lock (_lock)
        {
            if (_entries.TryGetValue(key, out var node))
            {
                _lru.Remove(node);
                _lru.AddFirst(node);
                bitmap = node.Value.Bitmap;
                return true;
            }
        }

        bitmap = null;
        return false;
    }

    private void Add(string key, Bitmap bitmap)
    {
        lock (_lock)
        {
            if (_entries.TryGetValue(key, out var existing))
            {
                _lru.Remove(existing);
                _entries.Remove(key);
                _currentBytes -= existing.Value.Bytes;
                existing.Value.Bitmap.Dispose();
            }

            var bytes = EstimateBytes(bitmap);
            var item = new CacheItem(key, bitmap, bytes);
            var node = new LinkedListNode<CacheItem>(item);
            _lru.AddFirst(node);
            _entries[key] = node;
            _currentBytes += bytes;

            EvictIfNeeded();
        }
    }

    private bool TryGetFromDisk(string fullPath, int decodeWidth, out Bitmap? bitmap)
    {
        bitmap = null;
        var cachePath = GetDiskCachePath(fullPath, decodeWidth);
        if (cachePath == null || !File.Exists(cachePath)) return false;
        try
        {
            bitmap = new Bitmap(cachePath);
            return bitmap != null;
        }
        catch
        {
            bitmap?.Dispose();
            bitmap = null;
            return false;
        }
    }

    private void TryWriteToDisk(string fullPath, int decodeWidth, Bitmap bitmap)
    {
        var cachePath = GetDiskCachePath(fullPath, decodeWidth);
        if (cachePath == null) return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(cachePath)!);
            using var fs = File.Open(cachePath, FileMode.Create, FileAccess.Write, FileShare.Read);
            bitmap.Save(fs);
            CleanupDiskCache();
        }
        catch
        {
            // ignore
        }
    }

    private string? GetDiskCachePath(string fullPath, int decodeWidth)
    {
        var dir = DiskCacheDir;
        if (string.IsNullOrWhiteSpace(dir)) return null;
        try
        {
            var info = new FileInfo(fullPath);
            var stamp = info.Exists ? info.LastWriteTimeUtc.Ticks : 0;
            var key = $"{fullPath}|w={decodeWidth}|t={stamp}";
            var hash = ComputeHash(key);
            var sizeDir = Path.Combine(dir, $"w{decodeWidth}");
            return Path.Combine(sizeDir, $"{hash}.png");
        }
        catch
        {
            return null;
        }
    }

    private void CleanupDiskCache()
    {
        var dir = DiskCacheDir;
        if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir)) return;
        try
        {
            var files = Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories)
                .Select(path => new FileInfo(path))
                .OrderBy(fi => fi.LastWriteTimeUtc)
                .ToList();
            long total = files.Sum(f => f.Length);
            if (total <= MaxDiskBytes) return;

            foreach (var file in files)
            {
                try
                {
                    total -= file.Length;
                    file.Delete();
                    PerfLogger.Count("ImageCache.DiskEvict");
                    if (total <= MaxDiskBytes) break;
                }
                catch
                {
                    // ignore
                }
            }
        }
        catch
        {
            // ignore
        }
    }

    private static string ComputeHash(string input)
    {
        using var sha = SHA256.Create();
        var bytes = sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes);
    }
    private void EvictIfNeeded()
    {
        while (_currentBytes > MaxBytes && _lru.Last != null)
        {
            var node = _lru.Last;
            _lru.RemoveLast();
            if (node == null) break;
            _entries.Remove(node.Value.Key);
            _currentBytes -= node.Value.Bytes;
            node.Value.Bitmap.Dispose();
            PerfLogger.Count("ImageCache.Evict");
        }
    }

    private static long EstimateBytes(Bitmap bitmap)
    {
        var size = bitmap.PixelSize;
        return (long)size.Width * size.Height * 4;
    }

    public void Clear()
    {
        lock (_lock)
        {
            foreach (var node in _lru)
            {
                node.Bitmap.Dispose();
            }
            _lru.Clear();
            _entries.Clear();
            _currentBytes = 0;
        }
    }

    public void Dispose()
    {
        Clear();
    }
}
