using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class ImageJsonEditorViewModel : ObservableObject
{
    private readonly HistoryManagerService _historyManager;
    private readonly HistoryIndexService? _historyIndexService;
    private readonly HistoryEntry _entry;
    private readonly HistoryImage _image;

    [ObservableProperty] private string _entryId = string.Empty;
    [ObservableProperty] private string _timestamp = string.Empty;
    [ObservableProperty] private string _templateName = string.Empty;
    [ObservableProperty] private string _workflow = string.Empty;
    [ObservableProperty] private string _status = string.Empty;
    [ObservableProperty] private string _originalPrompt = string.Empty;
    [ObservableProperty] private string _processedPrompt = string.Empty;
    [ObservableProperty] private string _enhancedPrompt = string.Empty;
    [ObservableProperty] private string _ollamaModel = string.Empty;
    [ObservableProperty] private string _invokeAIModel = string.Empty;
    [ObservableProperty] private string _coverImagePath = string.Empty;

    [ObservableProperty] private string _promptType = string.Empty;
    [ObservableProperty] private string _prompt = string.Empty;
    [ObservableProperty] private string _imagePath = string.Empty;
    [ObservableProperty] private bool _isFavorite;
    [ObservableProperty] private string _imageWorkflow = string.Empty;

    [ObservableProperty] private string _genPrompt = string.Empty;
    [ObservableProperty] private string _negativePrompt = string.Empty;
    [ObservableProperty] private string _positiveStylePrompt = string.Empty;
    [ObservableProperty] private string _negativeStylePrompt = string.Empty;
    [ObservableProperty] private string _modelName = string.Empty;
    [ObservableProperty] private string _modelBase = string.Empty;
    [ObservableProperty] private string _modelFormat = string.Empty;
    [ObservableProperty] private string _vaeUsedName = string.Empty;
    [ObservableProperty] private string _baseModelType = string.Empty;
    [ObservableProperty] private string _steps = string.Empty;
    [ObservableProperty] private string _cfgScale = string.Empty;
    [ObservableProperty] private string _width = string.Empty;
    [ObservableProperty] private string _height = string.Empty;
    [ObservableProperty] private string _seed = string.Empty;
    [ObservableProperty] private string _baseSeed = string.Empty;
    [ObservableProperty] private bool _usedRandomSeed;
    [ObservableProperty] private string _scheduler = string.Empty;
    [ObservableProperty] private string _cfgRescaleMultiplier = string.Empty;
    [ObservableProperty] private bool _saveToGallery;
    [ObservableProperty] private bool _autoClearedModelCacheBetweenModels;
    [ObservableProperty] private string _loras = string.Empty;

    [ObservableProperty] private string _rawJson = string.Empty;
    [ObservableProperty] private bool _useRawJson;
    [ObservableProperty] private string _statusText = string.Empty;

    public ImageJsonEditorViewModel(HistoryManagerService historyManager, HistoryEntry entry, HistoryImage image, HistoryIndexService? historyIndexService = null)
    {
        _historyManager = historyManager;
        _historyIndexService = historyIndexService;
        _entry = entry;
        _image = image;

        EntryId = entry.Id;
        Timestamp = entry.Timestamp.ToString("o");
        TemplateName = entry.TemplateName ?? string.Empty;
        Workflow = entry.Workflow ?? string.Empty;
        Status = entry.Status ?? string.Empty;
        OriginalPrompt = entry.OriginalPrompt ?? string.Empty;
        ProcessedPrompt = entry.ProcessedPrompt ?? string.Empty;
        EnhancedPrompt = entry.EnhancedPrompt ?? string.Empty;
        OllamaModel = entry.OllamaModel ?? string.Empty;
        InvokeAIModel = entry.InvokeAIModel ?? string.Empty;
        CoverImagePath = entry.CoverImagePath ?? string.Empty;

        PromptType = image.PromptType ?? string.Empty;
        Prompt = image.Prompt ?? string.Empty;
        ImagePath = image.ImagePath ?? string.Empty;
        IsFavorite = image.IsFavorite;
        ImageWorkflow = image.Workflow ?? string.Empty;

        var parsed = HistoryViewerViewModel.GetOrParseGenParams(image) ?? entry.ImageParameters;
        if (parsed != null)
        {
            GenPrompt = parsed.Prompt ?? string.Empty;
            NegativePrompt = parsed.NegativePrompt ?? string.Empty;
            PositiveStylePrompt = parsed.PositiveStylePrompt ?? string.Empty;
            NegativeStylePrompt = parsed.NegativeStylePrompt ?? string.Empty;
            ModelName = parsed.Model?.Name ?? string.Empty;
            ModelBase = parsed.Model?.Base ?? string.Empty;
            ModelFormat = parsed.Model?.Format ?? string.Empty;
            VaeUsedName = parsed.VaeUsedName ?? string.Empty;
            BaseModelType = parsed.BaseModelType ?? string.Empty;
            Steps = parsed.Steps.ToString();
            CfgScale = parsed.CfgScale.ToString("0.###");
            Width = parsed.Width.ToString();
            Height = parsed.Height.ToString();
            Seed = parsed.Seed.ToString();
            BaseSeed = parsed.BaseSeed.ToString();
            UsedRandomSeed = parsed.UsedRandomSeed;
            Scheduler = parsed.Scheduler ?? string.Empty;
            CfgRescaleMultiplier = parsed.CfgRescaleMultiplier.ToString("0.###");
            SaveToGallery = parsed.SaveToGallery;
            AutoClearedModelCacheBetweenModels = parsed.AutoClearedModelCacheBetweenModels;
            if (parsed.Loras.Any())
            {
                Loras = string.Join(Environment.NewLine, parsed.Loras.Select(l => $"{l.Lora.Name}:{l.Weight:0.##}"));
            }
        }

        RawJson = BuildRawJson(image, parsed);
    }

    public bool ApplyChanges(out string error)
    {
        error = string.Empty;

        _entry.TemplateName = NormalizeNullable(TemplateName);
        _entry.Workflow = NormalizeNullable(Workflow);
        _entry.Status = NormalizeNullable(Status);
        _entry.OriginalPrompt = OriginalPrompt ?? string.Empty;
        _entry.ProcessedPrompt = ProcessedPrompt ?? string.Empty;
        _entry.EnhancedPrompt = NormalizeNullable(EnhancedPrompt);
        _entry.OllamaModel = NormalizeNullable(OllamaModel) ?? string.Empty;
        _entry.InvokeAIModel = NormalizeNullable(InvokeAIModel);
        _entry.CoverImagePath = NormalizeNullable(CoverImagePath);

        _image.PromptType = NormalizeNullable(PromptType);
        _image.Prompt = Prompt ?? string.Empty;
        _image.ImagePath = NormalizeNullable(ImagePath);
        _image.IsFavorite = IsFavorite;
        _image.Workflow = NormalizeNullable(ImageWorkflow);

        if (UseRawJson)
        {
            if (!TryNormalizeJson(RawJson, out var normalized, out error))
            {
                return false;
            }

            _image.GenerationParamsJson = normalized;
            _image.GenerationParams = null;
            HistoryViewerViewModel.GetOrParseGenParams(_image);
        }
        else
        {
            var built = BuildGenerationParams(out error);
            if (built == null)
            {
                return false;
            }

            _image.GenerationParams = built;
            _image.GenerationParamsJson = JsonSerializer.Serialize(built, new JsonSerializerOptions { WriteIndented = true });
            RawJson = _image.GenerationParamsJson ?? string.Empty;
        }

        _entry.IsFavorite = _entry.Images.Any(i => i.IsFavorite);
        _historyManager.SaveChanges();
        _historyIndexService?.Invalidate(_image);
        StatusText = "Saved.";
        return true;
    }

    private InvokeAIGenerationParams? BuildGenerationParams(out string error)
    {
        error = string.Empty;

        var p = new InvokeAIGenerationParams
        {
            Prompt = GenPrompt ?? string.Empty,
            NegativePrompt = NormalizeNullable(NegativePrompt),
            PositiveStylePrompt = NormalizeNullable(PositiveStylePrompt),
            NegativeStylePrompt = NormalizeNullable(NegativeStylePrompt),
            BaseModelType = NormalizeNullable(BaseModelType),
            UsedRandomSeed = UsedRandomSeed,
            AutoClearedModelCacheBetweenModels = AutoClearedModelCacheBetweenModels,
            VaeUsedName = NormalizeNullable(VaeUsedName),
            Scheduler = NormalizeNullable(Scheduler) ?? string.Empty,
            SaveToGallery = SaveToGallery
        };

        if (!TryParseInt(Seed, out var seed, out error)) return null;
        if (!TryParseInt(Width, out var width, out error)) return null;
        if (!TryParseInt(Height, out var height, out error)) return null;
        if (!TryParseInt(Steps, out var steps, out error)) return null;
        if (!TryParseInt(BaseSeed, out var baseSeed, out error)) return null;
        if (!TryParseDouble(CfgScale, out var cfgScale, out error)) return null;
        if (!TryParseDouble(CfgRescaleMultiplier, out var rescale, out error)) return null;

        p.Seed = seed;
        p.Width = width;
        p.Height = height;
        p.Steps = steps;
        p.BaseSeed = baseSeed;
        p.CfgScale = cfgScale;
        p.CfgRescaleMultiplier = rescale;

        if (!string.IsNullOrWhiteSpace(ModelName) || !string.IsNullOrWhiteSpace(ModelBase) || !string.IsNullOrWhiteSpace(ModelFormat))
        {
            p.Model = new InvokeAIModel
            {
                Name = ModelName ?? string.Empty,
                Base = ModelBase ?? string.Empty,
                Format = ModelFormat ?? string.Empty
            };
        }

        p.Loras = ParseLoras(Loras);
        return p;
    }

    private static bool TryParseInt(string? value, out int result, out string error)
    {
        error = string.Empty;
        result = 0;
        if (string.IsNullOrWhiteSpace(value))
        {
            return true;
        }
        if (int.TryParse(value, out result))
        {
            return true;
        }
        error = $"Invalid number: {value}";
        return false;
    }

    private static bool TryParseDouble(string? value, out double result, out string error)
    {
        error = string.Empty;
        result = 0;
        if (string.IsNullOrWhiteSpace(value))
        {
            return true;
        }
        if (double.TryParse(value, out result))
        {
            return true;
        }
        error = $"Invalid number: {value}";
        return false;
    }

    private static List<LoraParameter> ParseLoras(string? text)
    {
        var result = new List<LoraParameter>();
        if (string.IsNullOrWhiteSpace(text)) return result;

        var lines = text
            .Split(new[] { '\r', '\n', ',' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(l => l.Trim())
            .Where(l => !string.IsNullOrWhiteSpace(l));

        foreach (var line in lines)
        {
            var weight = 0.75;
            var name = line;
            var parts = line.Split(':', 2, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 2)
            {
                name = parts[0].Trim();
                if (double.TryParse(parts[1].Trim(), out var w))
                {
                    weight = w;
                }
            }

            if (string.IsNullOrWhiteSpace(name)) continue;
            result.Add(new LoraParameter
            {
                Lora = new InvokeAIModel { Name = name },
                Weight = weight
            });
        }
        return result;
    }

    private static bool TryNormalizeJson(string? raw, out string normalized, out string error)
    {
        normalized = string.Empty;
        error = string.Empty;
        if (string.IsNullOrWhiteSpace(raw))
        {
            return true;
        }
        try
        {
            using var doc = JsonDocument.Parse(raw);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                error = "JSON must be an object.";
                return false;
            }
            normalized = JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
            return true;
        }
        catch (Exception ex)
        {
            error = $"Invalid JSON: {ex.Message}";
            return false;
        }
    }

    private static string BuildRawJson(HistoryImage image, InvokeAIGenerationParams? parsed)
    {
        if (!string.IsNullOrWhiteSpace(image.GenerationParamsJson))
        {
            if (TryNormalizeJson(image.GenerationParamsJson, out var normalized, out _))
            {
                return normalized;
            }
            return image.GenerationParamsJson;
        }

        if (parsed != null)
        {
            return JsonSerializer.Serialize(parsed, new JsonSerializerOptions { WriteIndented = true });
        }

        if (image.GenerationParams != null)
        {
            return JsonSerializer.Serialize(image.GenerationParams, new JsonSerializerOptions { WriteIndented = true });
        }

        return string.Empty;
    }

    private static string? NormalizeNullable(string? value)
    {
        return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    }
}
