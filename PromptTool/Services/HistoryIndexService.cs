using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using PromptTool.Core.Models;
using PromptTool.ViewModels;

namespace PromptTool.Services;

public sealed class HistoryIndexService
{
    private readonly ConcurrentDictionary<HistoryImage, HistoryImageIndex> _imageIndex = new();

    public HistoryImageIndex GetIndex(HistoryEntry entry, HistoryImage image)
    {
        if (_imageIndex.TryGetValue(image, out var cached))
        {
            PerfLogger.Count("HistoryIndex.Hit");
            return cached;
        }

        PerfLogger.Count("HistoryIndex.Miss");
        var index = BuildIndex(entry, image);
        _imageIndex[image] = index;
        return index;
    }

    public void Invalidate(HistoryImage image)
    {
        _imageIndex.TryRemove(image, out _);
    }

    public void Clear()
    {
        _imageIndex.Clear();
    }

    private static HistoryImageIndex BuildIndex(HistoryEntry entry, HistoryImage image)
    {
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image);
        var modelName = gen?.Model?.Name ?? entry.InvokeAIModel ?? string.Empty;
        var loraNames = gen?.Loras?
            .Select(l => l.Lora?.Name)
            .Where(n => !string.IsNullOrWhiteSpace(n))
            .Select(n => n!)
            .ToList() ?? new List<string>();

        return new HistoryImageIndex(
            NormalizeTemplateName(entry.TemplateName),
            image.PromptType ?? string.Empty,
            modelName,
            loraNames,
            entry.Workflow ?? string.Empty);
    }

    private static string NormalizeTemplateName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return string.Empty;
        var trimmed = name.Trim();
        return Path.GetFileNameWithoutExtension(trimmed);
    }
}

public sealed record HistoryImageIndex(
    string TemplateName,
    string PromptType,
    string ModelName,
    IReadOnlyList<string> LoraNames,
    string Workflow);
