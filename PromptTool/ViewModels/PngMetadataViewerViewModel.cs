using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Avalonia.Media.Imaging;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using SixLabors.ImageSharp;

namespace PromptTool.ViewModels;

public partial class PngMetadataViewerViewModel : ObservableObject
{
    private readonly HistoryManagerService? _historyManager;
    [ObservableProperty] private string _fileLabel = "No file loaded";
    [ObservableProperty] private string _fileInfo = "";
    [ObservableProperty] private string _imageInfo = "";
    [ObservableProperty] private string _statusMessage = "";
    [ObservableProperty] private ObservableCollection<PngTextChunkViewModel> _chunks = new();
    [ObservableProperty] private bool _hasChunks;
    [ObservableProperty] private bool _hasPreview;
    [ObservableProperty] private ObservableCollection<PngHistoryDiffItem> _historyDiffs = new();
    [ObservableProperty] private bool _hasDiffs;
    [ObservableProperty] private bool _hasHistoryMatch;
    [ObservableProperty] private string _validationStatus = "";
    [ObservableProperty] private bool _hasGenerationMetadata;
    [ObservableProperty] private bool _hasGraphJson;
    [ObservableProperty] private bool _replayUseCpu;
    [ObservableProperty] private bool _replayFp32 = true;
    [ObservableProperty] private bool _replayIncludeStyleNegative = true;
    [ObservableProperty] private bool _replayIncludePositiveStyle = true;
    [ObservableProperty] private string _replayVaePrecision = "";

    private string? _currentFilePath;
    private Bitmap? _previewBitmap;
    private HistoryEntry? _matchedEntry;
    private HistoryImage? _matchedImage;
    private string? _matchedImagePath;
    private MetadataSnapshot? _lastMetadata;
    private HistorySnapshot? _lastHistory;

    public Func<PngMergedGenerationRequest, Avalonia.Controls.Window?, Task>? GenerateMergedRequested { get; set; }
    public Func<PngGraphReplayRequest, Avalonia.Controls.Window?, Task>? GenerateGraphReplayRequested { get; set; }
    public Func<InvokeAIGenerationParams, Task<string?>>? BuildGenerationGraphJsonAsync { get; set; }
    public Func<string, string, string?, Task>? ShowJsonDiffRequested { get; set; }
    public Avalonia.Controls.Window? OwnerWindow { get; set; }

    public PngMetadataViewerViewModel(HistoryManagerService? historyManager = null)
    {
        _historyManager = historyManager;
    }

    public Bitmap? PreviewBitmap
    {
        get => _previewBitmap;
        private set
        {
            if (ReferenceEquals(_previewBitmap, value))
            {
                return;
            }

            _previewBitmap?.Dispose();
            _previewBitmap = value;
            HasPreview = _previewBitmap != null;
            OnPropertyChanged(nameof(PreviewBitmap));
        }
    }

    public async Task LoadFileAsync(string path)
    {
        StatusMessage = "";
        Chunks.Clear();
        HasChunks = false;
        _currentFilePath = null;
        PreviewBitmap = null;
        ClearValidationState(clearMatch: true);

        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            StatusMessage = "File not found.";
            return;
        }

        if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
        {
            StatusMessage = "Please select a PNG file.";
            return;
        }

        try
        {
            _currentFilePath = path;
            FileLabel = $"File: {Path.GetFileName(path)}";
            try
            {
                PreviewBitmap = new Bitmap(path);
            }
            catch
            {
                PreviewBitmap = null;
            }

            await Task.Run(() =>
            {
                using var image = Image.Load(path);
                var info = new FileInfo(path);

                var fileSizeMb = info.Length / (1024.0 * 1024.0);
                FileInfo = $"Path: {path}\nSize: {fileSizeMb:0.00} MB ({info.Length:N0} bytes)\nModified: {info.LastWriteTime}";
                var colorMode = image.PixelType.BitsPerPixel > 0
                    ? $"{image.PixelType.BitsPerPixel} bpp"
                    : "unknown";
                ImageInfo = $"Dimensions: {image.Width} x {image.Height}\nColor Mode: {colorMode}";

                var textChunks = ReadTextChunks(image);
                foreach (var chunk in textChunks)
                {
                    Chunks.Add(chunk);
                }

                HasChunks = Chunks.Count > 0;
                if (!HasChunks)
                {
                    StatusMessage = "No text metadata found in this PNG.";
                }
            });

            _lastMetadata = BuildMetadataSnapshot();
            HasGenerationMetadata = HasMetadataContent(_lastMetadata);
            HasGraphJson = !string.IsNullOrWhiteSpace(_lastMetadata.GraphJson);
            InitializeGraphOverrides(_lastMetadata.GraphJson);
            TryMatchHistoryForCurrentFile();
        }
        catch (Exception ex)
        {
            StatusMessage = $"Error reading PNG: {ex.Message}";
        }
    }

    public string BuildPlainText()
    {
        var sb = new StringBuilder();
        sb.AppendLine(FileLabel);
        if (!string.IsNullOrWhiteSpace(FileInfo))
        {
            sb.AppendLine(FileInfo);
        }
        if (!string.IsNullOrWhiteSpace(ImageInfo))
        {
            sb.AppendLine(ImageInfo);
        }
        sb.AppendLine();

        if (Chunks.Count == 0)
        {
            sb.AppendLine("No text metadata found.");
            return sb.ToString();
        }

        foreach (var chunk in Chunks)
        {
            sb.AppendLine($"[{chunk.Key}]");
            sb.AppendLine(chunk.Value);
            sb.AppendLine();
        }
        return sb.ToString();
    }

    public string BuildJson()
    {
        var payload = new
        {
            file = _currentFilePath,
            chunks = Chunks.ToDictionary(c => c.Key, c => c.Value, StringComparer.OrdinalIgnoreCase)
        };
        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
    }

    public string BuildCsv()
    {
        var sb = new StringBuilder();
        sb.AppendLine("Key,Value,Length");
        foreach (var chunk in Chunks)
        {
            var value = chunk.Value.Replace("\"", "\"\"");
            sb.AppendLine($"\"{chunk.Key}\",\"{value}\",{chunk.Value.Length}");
        }
        return sb.ToString();
    }

    public void ExpandAll()
    {
        foreach (var chunk in Chunks)
        {
            chunk.IsExpanded = true;
        }
    }

    public void CollapseAll()
    {
        foreach (var chunk in Chunks)
        {
            chunk.IsExpanded = false;
        }
    }

    [RelayCommand]
    private void ValidateAgainstHistory()
    {
        ClearValidationState(clearMatch: false);
        if (_historyManager == null)
        {
            ValidationStatus = "History service is not available.";
            return;
        }
        if (string.IsNullOrWhiteSpace(_currentFilePath))
        {
            ValidationStatus = "Load a PNG file first.";
            return;
        }

        EnsureHistoryMatch();
        if (_matchedEntry == null || _matchedImage == null)
        {
            ValidationStatus = "No matching history entry found for this image.";
            return;
        }

        var metadata = _lastMetadata ?? BuildMetadataSnapshot();
        var history = _lastHistory ?? BuildHistorySnapshot(_matchedEntry, _matchedImage);
        _lastMetadata = metadata;
        _lastHistory = history;
        HasGenerationMetadata = HasMetadataContent(metadata);
        HasGraphJson = !string.IsNullOrWhiteSpace(metadata.GraphJson);
        BuildDiffs(history, metadata);

        if (!HasDiffs)
        {
            ValidationStatus = "No differences found.";
        }
        else
        {
            ValidationStatus = $"{HistoryDiffs.Count} differences found. Select what to apply.";
        }
    }

    [RelayCommand]
    private async Task TestGenerateMerged()
    {
        var request = BuildMergedGenerationRequest(saveToHistory: false, createNewEntryOnSave: false);
        if (request == null)
        {
            ValidationStatus = "No PNG metadata available to generate from.";
            return;
        }

        if (GenerateMergedRequested != null)
        {
            await GenerateMergedRequested(request, OwnerWindow);
            return;
        }

        ValidationStatus = "Generation flow not configured.";
    }

    [RelayCommand]
    private async Task GenerateAndSaveNewEntry()
    {
        var request = BuildMergedGenerationRequest(saveToHistory: true, createNewEntryOnSave: true);
        if (request == null)
        {
            ValidationStatus = "No PNG metadata available to generate from.";
            return;
        }

        if (GenerateMergedRequested != null)
        {
            await GenerateMergedRequested(request, OwnerWindow);
            return;
        }

        ValidationStatus = "Generation flow not configured.";
    }

    [RelayCommand]
    private async Task ShowGenerationJson()
    {
        var request = BuildMergedGenerationRequest(saveToHistory: false, createNewEntryOnSave: false);
        if (request == null)
        {
            ValidationStatus = "No PNG metadata available.";
            return;
        }

        var json = BuildGenerationGraphJsonAsync != null
            ? await BuildGenerationGraphJsonAsync(request.Parameters)
            : JsonSerializer.Serialize(request.Parameters, new JsonSerializerOptions { WriteIndented = true });

        if (json == null)
        {
            ValidationStatus = "Unable to build generation JSON.";
            return;
        }

        if (ShowJsonDiffRequested != null)
        {
            await ShowJsonDiffRequested("Generation JSON", json, null);
        }
    }

    [RelayCommand]
    private async Task ShowGraphDiff()
    {
        var request = BuildMergedGenerationRequest(saveToHistory: false, createNewEntryOnSave: false);
        if (request == null)
        {
            ValidationStatus = "No PNG metadata available.";
            return;
        }

        var pngJson = request.Metadata.GraphJson;
        if (string.IsNullOrWhiteSpace(pngJson))
        {
            ValidationStatus = "PNG graph JSON not found in metadata.";
            return;
        }

        var genJson = BuildGenerationGraphJsonAsync != null
            ? await BuildGenerationGraphJsonAsync(request.Parameters)
            : JsonSerializer.Serialize(request.Parameters, new JsonSerializerOptions { WriteIndented = true });

        if (genJson == null)
        {
            ValidationStatus = "Unable to build generation JSON.";
            return;
        }

        if (ShowJsonDiffRequested != null)
        {
            await ShowJsonDiffRequested("PNG Graph vs Generation", pngJson, genJson);
        }
    }

    [RelayCommand]
    private async Task ReplayFromPngGraph()
    {
        var request = BuildReplayGraphRequest(saveToHistory: false, createNewEntryOnSave: false);
        if (request == null)
        {
            ValidationStatus = "PNG graph JSON not available.";
            return;
        }

        if (GenerateGraphReplayRequested != null)
        {
            await GenerateGraphReplayRequested(request, OwnerWindow);
            return;
        }

        ValidationStatus = "Replay flow not configured.";
    }

    [RelayCommand]
    private async Task ShowReplayGraphJson()
    {
        var metadata = _lastMetadata ?? BuildMetadataSnapshot();
        if (string.IsNullOrWhiteSpace(metadata.GraphJson))
        {
            ValidationStatus = "PNG graph JSON not available.";
            return;
        }

        var graph = ApplyReplayOverrides(metadata.GraphJson);
        if (graph == null)
        {
            ValidationStatus = "Unable to build replay graph JSON.";
            return;
        }

        var json = graph.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
        if (ShowJsonDiffRequested != null)
        {
            await ShowJsonDiffRequested("Replay Graph JSON", json, null);
        }
    }

    [RelayCommand]
    private async Task ReplayAndSaveToEntry()
    {
        var request = BuildReplayGraphRequest(saveToHistory: true, createNewEntryOnSave: false);
        if (request == null)
        {
            ValidationStatus = "PNG graph JSON not available.";
            return;
        }

        if (GenerateGraphReplayRequested != null)
        {
            await GenerateGraphReplayRequested(request, OwnerWindow);
            return;
        }

        ValidationStatus = "Replay flow not configured.";
    }

    [RelayCommand]
    private async Task ReplayAndSaveNewEntry()
    {
        var request = BuildReplayGraphRequest(saveToHistory: true, createNewEntryOnSave: true);
        if (request == null)
        {
            ValidationStatus = "PNG graph JSON not available.";
            return;
        }

        if (GenerateGraphReplayRequested != null)
        {
            await GenerateGraphReplayRequested(request, OwnerWindow);
            return;
        }

        ValidationStatus = "Replay flow not configured.";
    }

    [RelayCommand]
    private void AddEntryOnly()
    {
        if (_historyManager == null)
        {
            ValidationStatus = "History service is not available.";
            return;
        }

        var metadata = _lastMetadata ?? BuildMetadataSnapshot();
        if (!HasMetadataContent(metadata))
        {
            ValidationStatus = "No PNG metadata available to add.";
            return;
        }

        var history = _lastHistory;
        var mergedParams = BuildMergedGenerationParams(metadata, history);
        if (mergedParams == null)
        {
            ValidationStatus = "Unable to build generation params.";
            return;
        }

        var entry = BuildHistoryEntryFromMerged(metadata, history, mergedParams);
        _historyManager.AddEntry(entry);
        ValidationStatus = "New history entry added.";
    }

    [RelayCommand]
    private void ApplySelectedDiffs()
    {
        if (_historyManager == null)
        {
            ValidationStatus = "History service is not available.";
            return;
        }
        if (_matchedEntry == null || _matchedImage == null)
        {
            ValidationStatus = "No history entry selected.";
            return;
        }

        var pending = HistoryDiffs.Where(d => d.Apply).ToList();
        if (pending.Count == 0)
        {
            ValidationStatus = "No changes selected.";
            return;
        }

        var entryChanged = false;
        var imageChanged = false;
        var genChanged = false;
        var promptChanged = false;

        var gen = HistoryViewerViewModel.GetOrParseGenParams(_matchedImage) ?? new InvokeAIGenerationParams();

        var genJsonDiff = pending.FirstOrDefault(d => d.Field == PngHistoryField.GenerationParamsJson);
        if (genJsonDiff?.NewValue != null)
        {
            _matchedImage.GenerationParamsJson = genJsonDiff.NewValue;
            _matchedImage.GenerationParams = null;
            gen = HistoryViewerViewModel.GetOrParseGenParams(_matchedImage) ?? gen;
            genChanged = true;
            imageChanged = true;
        }

        foreach (var diff in pending.Where(d => d.Field != PngHistoryField.GenerationParamsJson))
        {
            switch (diff.Field)
            {
                case PngHistoryField.OriginalPrompt:
                    _matchedEntry.OriginalPrompt = diff.NewValue ?? _matchedEntry.OriginalPrompt;
                    entryChanged = true;
                    break;
                case PngHistoryField.ProcessedPrompt:
                    _matchedEntry.ProcessedPrompt = diff.NewValue ?? _matchedEntry.ProcessedPrompt;
                    entryChanged = true;
                    break;
                case PngHistoryField.OllamaModel:
                    _matchedEntry.OllamaModel = diff.NewValue ?? _matchedEntry.OllamaModel;
                    entryChanged = true;
                    break;
                case PngHistoryField.TemplateName:
                    _matchedEntry.TemplateName = diff.NewValue ?? _matchedEntry.TemplateName;
                    entryChanged = true;
                    break;
                case PngHistoryField.Status:
                    _matchedEntry.Status = diff.NewValue ?? _matchedEntry.Status;
                    entryChanged = true;
                    break;
                case PngHistoryField.Workflow:
                    _matchedEntry.Workflow = diff.NewValue ?? _matchedEntry.Workflow;
                    entryChanged = true;
                    break;
                case PngHistoryField.EnhancedPrompt:
                    _matchedEntry.EnhancedPrompt = diff.NewValue ?? _matchedEntry.EnhancedPrompt;
                    entryChanged = true;
                    break;
                case PngHistoryField.CoverImagePath:
                    _matchedEntry.CoverImagePath = diff.NewValue ?? _matchedEntry.CoverImagePath;
                    entryChanged = true;
                    break;
                case PngHistoryField.EntryIsFavorite:
                    if (diff.NewBool.HasValue)
                    {
                        _matchedEntry.IsFavorite = diff.NewBool.Value;
                        entryChanged = true;
                    }
                    break;
                case PngHistoryField.InvokeAIModel:
                    _matchedEntry.InvokeAIModel = diff.NewValue ?? _matchedEntry.InvokeAIModel;
                    entryChanged = true;
                    break;
                case PngHistoryField.VariationPrompts:
                    if (diff.NewMap != null)
                    {
                        _matchedEntry.VariationPrompts = diff.NewMap;
                        entryChanged = true;
                    }
                    break;
                case PngHistoryField.Context:
                    if (diff.NewMap != null)
                    {
                        _matchedEntry.Context = diff.NewMap;
                        entryChanged = true;
                    }
                    break;
                case PngHistoryField.PromptType:
                    _matchedImage.PromptType = diff.NewValue ?? _matchedImage.PromptType;
                    imageChanged = true;
                    break;
                case PngHistoryField.PromptTypeSuffix:
                    _matchedImage.PromptTypeSuffix = diff.NewValue ?? _matchedImage.PromptTypeSuffix;
                    imageChanged = true;
                    break;
                case PngHistoryField.ImagePrompt:
                    _matchedImage.Prompt = diff.NewValue ?? _matchedImage.Prompt;
                    imageChanged = true;
                    break;
                case PngHistoryField.ImageWorkflow:
                    _matchedImage.Workflow = diff.NewValue ?? _matchedImage.Workflow;
                    imageChanged = true;
                    break;
                case PngHistoryField.ImageIsFavorite:
                    if (diff.NewBool.HasValue)
                    {
                        _matchedImage.IsFavorite = diff.NewBool.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.AestheticScore:
                    if (diff.NewDouble.HasValue)
                    {
                        _matchedImage.AestheticScore = diff.NewDouble.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.AestheticScoreModel:
                    _matchedImage.AestheticScoreModel = diff.NewValue ?? _matchedImage.AestheticScoreModel;
                    imageChanged = true;
                    break;
                case PngHistoryField.AestheticScoreTimestamp:
                    if (diff.NewDateTime.HasValue)
                    {
                        _matchedImage.AestheticScoreTimestamp = diff.NewDateTime.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.AestheticScoreMs:
                    if (diff.NewInt.HasValue)
                    {
                        _matchedImage.AestheticScoreMs = diff.NewInt.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.UpscaleModel:
                    _matchedImage.UpscaleModel = diff.NewValue ?? _matchedImage.UpscaleModel;
                    imageChanged = true;
                    break;
                case PngHistoryField.UpscaleScale:
                    if (diff.NewDouble.HasValue)
                    {
                        _matchedImage.UpscaleScale = diff.NewDouble.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.UpscaleTileSize:
                    if (diff.NewInt.HasValue)
                    {
                        _matchedImage.UpscaleTileSize = diff.NewInt.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.UpscaleFitToMultipleOf8:
                    if (diff.NewBool.HasValue)
                    {
                        _matchedImage.UpscaleFitToMultipleOf8 = diff.NewBool.Value;
                        imageChanged = true;
                    }
                    break;
                case PngHistoryField.UpscaleSourceImagePath:
                    _matchedImage.UpscaleSourceImagePath = diff.NewValue ?? _matchedImage.UpscaleSourceImagePath;
                    imageChanged = true;
                    break;
                case PngHistoryField.GenPrompt:
                    gen.Prompt = diff.NewValue ?? gen.Prompt;
                    genChanged = true;
                    promptChanged = true;
                    break;
                case PngHistoryField.PositiveStylePrompt:
                    gen.PositiveStylePrompt = diff.NewValue;
                    genChanged = true;
                    break;
                case PngHistoryField.NegativeStylePrompt:
                    gen.NegativeStylePrompt = diff.NewValue;
                    genChanged = true;
                    break;
                case PngHistoryField.NegativePrompt:
                    gen.NegativePrompt = diff.NewValue;
                    genChanged = true;
                    break;
                case PngHistoryField.BaseModelType:
                    gen.BaseModelType = diff.NewValue;
                    genChanged = true;
                    break;
                case PngHistoryField.UsedRandomSeed:
                    if (diff.NewBool.HasValue)
                    {
                        gen.UsedRandomSeed = diff.NewBool.Value;
                        genChanged = true;
                    }
                    break;
                case PngHistoryField.BaseSeed:
                    if (diff.NewInt.HasValue)
                    {
                        gen.BaseSeed = diff.NewInt.Value;
                        genChanged = true;
                    }
                    break;
                case PngHistoryField.AutoClearedModelCacheBetweenModels:
                    if (diff.NewBool.HasValue)
                    {
                        gen.AutoClearedModelCacheBetweenModels = diff.NewBool.Value;
                        genChanged = true;
                    }
                    break;
                case PngHistoryField.VaeUsedName:
                    gen.VaeUsedName = diff.NewValue;
                    genChanged = true;
                    break;
                case PngHistoryField.Steps:
                    if (diff.NewInt.HasValue) { gen.Steps = diff.NewInt.Value; genChanged = true; }
                    break;
                case PngHistoryField.CfgScale:
                    if (diff.NewDouble.HasValue) { gen.CfgScale = diff.NewDouble.Value; genChanged = true; }
                    break;
                case PngHistoryField.Width:
                    if (diff.NewInt.HasValue) { gen.Width = diff.NewInt.Value; genChanged = true; }
                    break;
                case PngHistoryField.Height:
                    if (diff.NewInt.HasValue) { gen.Height = diff.NewInt.Value; genChanged = true; }
                    break;
                case PngHistoryField.Seed:
                    if (diff.NewInt.HasValue) { gen.Seed = diff.NewInt.Value; genChanged = true; }
                    break;
                case PngHistoryField.Scheduler:
                    gen.Scheduler = diff.NewValue ?? gen.Scheduler;
                    genChanged = true;
                    break;
                case PngHistoryField.CfgRescaleMultiplier:
                    if (diff.NewDouble.HasValue) { gen.CfgRescaleMultiplier = diff.NewDouble.Value; genChanged = true; }
                    break;
                case PngHistoryField.SaveToGallery:
                    if (diff.NewBool.HasValue) { gen.SaveToGallery = diff.NewBool.Value; genChanged = true; }
                    break;
                case PngHistoryField.UsePromptAsStyleWhenEmpty:
                    if (diff.NewBool.HasValue) { gen.UsePromptAsStyleWhenEmpty = diff.NewBool.Value; genChanged = true; }
                    break;
                case PngHistoryField.ModelName:
                    gen.Model = new InvokeAIModel { Name = diff.NewValue ?? gen.Model?.Name ?? string.Empty };
                    if (!string.IsNullOrWhiteSpace(diff.NewValue))
                    {
                        _matchedEntry.InvokeAIModel = diff.NewValue;
                        entryChanged = true;
                    }
                    genChanged = true;
                    break;
                case PngHistoryField.Loras:
                    gen.Loras = diff.NewLoras?.Select(l => new LoraParameter
                    {
                        Lora = new InvokeAIModel { Name = l.Name ?? string.Empty },
                        Weight = l.Weight ?? 1.0
                    }).ToList() ?? new List<LoraParameter>();
                    genChanged = true;
                    break;
            }
        }

        if (genChanged)
        {
            _matchedImage.GenerationParams = gen;
            _matchedImage.GenerationParamsJson = JsonSerializer.Serialize(gen);
            imageChanged = true;
        }
        if (promptChanged && string.IsNullOrWhiteSpace(_matchedImage.Prompt))
        {
            _matchedImage.Prompt = gen.Prompt;
            imageChanged = true;
        }

        if (imageChanged)
        {
            _historyManager.UpdateImage(_matchedEntry.Id, _matchedImage, save: false);
        }
        if (entryChanged)
        {
            _historyManager.UpdateEntry(_matchedEntry);
        }
        else
        {
            _historyManager.SaveChanges();
        }

        ValidationStatus = $"{pending.Count} change(s) saved to history.";
        ValidateAgainstHistory();
    }

    [RelayCommand]
    private void ClearValidation()
    {
        ClearValidationState(clearMatch: false);
    }

    private static List<PngTextChunkViewModel> ReadTextChunks(Image image)
    {
        var result = new List<PngTextChunkViewModel>();
        var png = image.Metadata.GetPngMetadata();
        if (png?.TextData == null)
        {
            return result;
        }

        foreach (var text in png.TextData)
        {
            var key = text.Keyword ?? string.Empty;
            var value = text.Value ?? string.Empty;
            if (string.IsNullOrWhiteSpace(key) && string.IsNullOrWhiteSpace(value))
            {
                continue;
            }
            result.Add(new PngTextChunkViewModel(key, value));
        }

        return result
            .OrderBy(c => c.Key, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private (HistoryEntry? entry, HistoryImage? image, string? imagePath) FindHistoryMatch(string fullPath)
    {
        var historyDir = _historyManager?.GetHistoryDir();
        if (string.IsNullOrWhiteSpace(historyDir) || _historyManager == null)
        {
            return (null, null, null);
        }

        HistoryEntry? fileNameMatchEntry = null;
        HistoryImage? fileNameMatchImage = null;
        string? fileNameMatchPath = null;
        var targetFile = Path.GetFileName(fullPath);

        foreach (var entry in _historyManager.GetAllEntries())
        {
            foreach (var image in entry.Images)
            {
                if (string.IsNullOrWhiteSpace(image.ImagePath)) continue;
                var candidate = Path.IsPathRooted(image.ImagePath)
                    ? image.ImagePath
                    : Path.Combine(historyDir, image.ImagePath);
                var candidateFull = Path.GetFullPath(candidate);
                if (string.Equals(candidateFull, fullPath, StringComparison.OrdinalIgnoreCase))
                {
                    return (entry, image, candidateFull);
                }

                if (fileNameMatchEntry == null &&
                    string.Equals(Path.GetFileName(candidateFull), targetFile, StringComparison.OrdinalIgnoreCase))
                {
                    fileNameMatchEntry = entry;
                    fileNameMatchImage = image;
                    fileNameMatchPath = candidateFull;
                }
            }
        }

        return (fileNameMatchEntry, fileNameMatchImage, fileNameMatchPath);
    }

    private void TryMatchHistoryForCurrentFile()
    {
        if (_historyManager == null || string.IsNullOrWhiteSpace(_currentFilePath))
        {
            return;
        }

        var fullPath = Path.GetFullPath(_currentFilePath);
        var match = FindHistoryMatch(fullPath);
        if (match.entry == null || match.image == null)
        {
            return;
        }

        _matchedEntry = match.entry;
        _matchedImage = match.image;
        _matchedImagePath = match.imagePath;
        HasHistoryMatch = true;
        _lastHistory = BuildHistorySnapshot(match.entry, match.image);
        ValidationStatus = "Matched history entry. Click Validate to compare.";
    }

    private void EnsureHistoryMatch()
    {
        if (_matchedEntry != null && _matchedImage != null)
        {
            HasHistoryMatch = true;
            return;
        }

        TryMatchHistoryForCurrentFile();
    }

    private void ClearValidationState(bool clearMatch)
    {
        HistoryDiffs.Clear();
        HasDiffs = false;
        ValidationStatus = string.Empty;
        if (clearMatch)
        {
            HasHistoryMatch = false;
            _matchedEntry = null;
            _matchedImage = null;
            _matchedImagePath = null;
            _lastHistory = null;
        }
    }

    private static bool HasMetadataContent(MetadataSnapshot? metadata)
    {
        if (metadata == null) return false;
        return !string.IsNullOrWhiteSpace(metadata.GenPrompt)
               || !string.IsNullOrWhiteSpace(metadata.NegativePrompt)
               || !string.IsNullOrWhiteSpace(metadata.ModelName)
               || metadata.Steps.HasValue
               || metadata.CfgScale.HasValue
               || metadata.Width.HasValue
               || metadata.Height.HasValue
               || metadata.Seed.HasValue
               || (metadata.Loras != null && metadata.Loras.Count > 0);
    }

    private MetadataSnapshot BuildMetadataSnapshot()
    {
        var snapshot = new MetadataSnapshot();
        var chunkMap = Chunks
            .GroupBy(c => c.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First().Value, StringComparer.OrdinalIgnoreCase);

        if (chunkMap.TryGetValue("original_prompt", out var originalPrompt))
        {
            snapshot.OriginalPrompt = originalPrompt;
        }
        if (chunkMap.TryGetValue("prompt", out var prompt))
        {
            snapshot.GenPrompt ??= prompt;
            snapshot.ImagePrompt ??= prompt;
            snapshot.ProcessedPrompt ??= prompt;
        }
        if (chunkMap.TryGetValue("processed_prompt", out var processedPrompt))
        {
            snapshot.ProcessedPrompt ??= processedPrompt;
        }
        if (chunkMap.TryGetValue("negative_prompt", out var negPrompt) ||
            chunkMap.TryGetValue("negative prompt", out negPrompt) ||
            chunkMap.TryGetValue("negativeprompt", out negPrompt))
        {
            snapshot.NegativePrompt = negPrompt;
        }
        if (chunkMap.TryGetValue("template_name", out var templateName))
        {
            snapshot.TemplateName = templateName;
        }
        if (chunkMap.TryGetValue("workflow", out var workflow))
        {
            snapshot.Workflow = workflow;
        }
        if (chunkMap.TryGetValue("status", out var status))
        {
            snapshot.Status = status;
        }
        if (chunkMap.TryGetValue("enhanced_prompt", out var enhancedPrompt))
        {
            snapshot.EnhancedPrompt = enhancedPrompt;
        }
        if (chunkMap.TryGetValue("variation_prompts", out var variationPrompts))
        {
            snapshot.VariationPromptsJson = variationPrompts;
        }
        if (chunkMap.TryGetValue("context", out var context))
        {
            snapshot.ContextJson = context;
        }
        if (chunkMap.TryGetValue("parameters", out var parameters))
        {
            ParseParametersString(snapshot, parameters);
        }

        foreach (var value in chunkMap.Values)
        {
            if (!IsJsonLike(value)) continue;
            try
            {
                using var doc = JsonDocument.Parse(value);
                if (!TryExtractInvokeAIGraph(doc.RootElement, snapshot))
                {
                    ExtractFromJson(snapshot, doc.RootElement);
                }
            }
            catch
            {
                // ignore parse failures
            }
        }

        return snapshot;
    }

    private static bool IsJsonLike(string value)
    {
        var trimmed = value.Trim();
        return (trimmed.StartsWith("{", StringComparison.Ordinal) && trimmed.EndsWith("}", StringComparison.Ordinal)) ||
               (trimmed.StartsWith("[", StringComparison.Ordinal) && trimmed.EndsWith("]", StringComparison.Ordinal));
    }

    private static void ParseParametersString(MetadataSnapshot snapshot, string value)
    {
        var text = value;
        var prompt = ExtractAfterLabel(text, "Prompt:");
        if (!string.IsNullOrWhiteSpace(prompt))
        {
            snapshot.GenPrompt ??= prompt;
            snapshot.ImagePrompt ??= prompt;
            snapshot.ProcessedPrompt ??= prompt;
        }
        snapshot.NegativePrompt ??= ExtractAfterLabel(text, "Negative prompt:");
        snapshot.Steps ??= ExtractIntLabel(text, "Steps:");
        snapshot.Seed ??= ExtractIntLabel(text, "Seed:");
        snapshot.CfgScale ??= ExtractDoubleLabel(text, "CFG scale:");
        var size = ExtractAfterLabel(text, "Size:");
        if (!string.IsNullOrWhiteSpace(size))
        {
            var parts = size.Split('x', 'X');
            if (parts.Length == 2 &&
                int.TryParse(parts[0].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var w) &&
                int.TryParse(parts[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var h))
            {
                snapshot.Width ??= w;
                snapshot.Height ??= h;
            }
        }
    }

    private static string? ExtractAfterLabel(string text, string label)
    {
        var idx = text.IndexOf(label, StringComparison.OrdinalIgnoreCase);
        if (idx < 0) return null;
        var start = idx + label.Length;
        var nextComma = text.IndexOf(',', start);
        if (nextComma < 0) nextComma = text.Length;
        return text[start..nextComma].Trim();
    }

    private static int? ExtractIntLabel(string text, string label)
    {
        var raw = ExtractAfterLabel(text, label);
        return int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var v) ? v : null;
    }

    private static double? ExtractDoubleLabel(string text, string label)
    {
        var raw = ExtractAfterLabel(text, label);
        return double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : null;
    }

    private static bool TryExtractInvokeAIGraph(JsonElement root, MetadataSnapshot snapshot)
    {
        if (root.ValueKind != JsonValueKind.Object ||
            !root.TryGetProperty("nodes", out var nodes) ||
            nodes.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        JsonElement? GetNode(string id)
        {
            if (nodes.TryGetProperty(id, out var node) && node.ValueKind == JsonValueKind.Object)
            {
                return node;
            }
            return null;
        }

        string? GetNodeValue(string id)
        {
            var node = GetNode(id);
            if (node.HasValue && node.Value.TryGetProperty("value", out var value) && value.ValueKind == JsonValueKind.String)
            {
                return value.GetString();
            }
            return null;
        }

        snapshot.GenPrompt ??= GetNodeValue("positive_prompt");
        snapshot.NegativePrompt ??= GetNodeValue("content_negative_prompt");
        snapshot.NegativeStylePrompt ??= GetNodeValue("style_negative_prompt");
        snapshot.PositiveStylePrompt ??= GetNodeValue("style_positive_prompt");

        var posCond = GetNode("positive_conditioning");
        if (posCond.HasValue &&
            posCond.Value.TryGetProperty("style", out var style) &&
            style.ValueKind == JsonValueKind.String)
        {
            var styleValue = style.GetString();
            if (!string.IsNullOrWhiteSpace(styleValue))
            {
                snapshot.PositiveStylePrompt ??= styleValue;
            }
        }

        var modelNode = GetNode("sdxl_model_loader");
        if (modelNode.HasValue &&
            modelNode.Value.TryGetProperty("model", out var modelObj) &&
            modelObj.ValueKind == JsonValueKind.Object)
        {
            if (modelObj.TryGetProperty("name", out var modelName) && modelName.ValueKind == JsonValueKind.String)
            {
                snapshot.ModelName ??= modelName.GetString();
            }
            if (modelObj.TryGetProperty("base", out var baseModel) && baseModel.ValueKind == JsonValueKind.String)
            {
                snapshot.BaseModelType ??= baseModel.GetString();
            }
        }

        var vaeNode = GetNode("sdxl_fp32_vae_loader");
        if (vaeNode.HasValue &&
            vaeNode.Value.TryGetProperty("vae_model", out var vaeObj) &&
            vaeObj.ValueKind == JsonValueKind.Object &&
            vaeObj.TryGetProperty("name", out var vaeName) &&
            vaeName.ValueKind == JsonValueKind.String)
        {
            snapshot.VaeUsedName ??= vaeName.GetString();
        }

        var denoise = GetNode("sdxl_denoise_latents");
        if (denoise.HasValue)
        {
            if (denoise.Value.TryGetProperty("steps", out var steps) && steps.TryGetInt32(out var st))
            {
                snapshot.Steps ??= st;
            }
            if (denoise.Value.TryGetProperty("cfg_scale", out var cfg) && cfg.TryGetDouble(out var cfgVal))
            {
                snapshot.CfgScale ??= cfgVal;
            }
            if (denoise.Value.TryGetProperty("scheduler", out var sched) && sched.ValueKind == JsonValueKind.String)
            {
                snapshot.Scheduler ??= sched.GetString();
            }
            if (denoise.Value.TryGetProperty("cfg_rescale_multiplier", out var rescale) && rescale.TryGetDouble(out var r))
            {
                snapshot.CfgRescaleMultiplier ??= r;
            }
        }

        var noise = GetNode("noise");
        if (noise.HasValue)
        {
            if (noise.Value.TryGetProperty("width", out var w) && w.TryGetInt32(out var wi))
            {
                snapshot.Width ??= wi;
            }
            if (noise.Value.TryGetProperty("height", out var h) && h.TryGetInt32(out var he))
            {
                snapshot.Height ??= he;
            }
            if (noise.Value.TryGetProperty("seed", out var seed) && seed.TryGetInt32(out var s))
            {
                snapshot.Seed ??= s;
            }
        }

        snapshot.Loras ??= new List<LoraSnapshot>();
        foreach (var node in nodes.EnumerateObject())
        {
            if (!node.Name.StartsWith("lora_loader_", StringComparison.OrdinalIgnoreCase)) continue;
            if (node.Value.ValueKind != JsonValueKind.Object) continue;
            if (node.Value.TryGetProperty("lora", out var loraObj) && loraObj.ValueKind == JsonValueKind.Object)
            {
                if (loraObj.TryGetProperty("name", out var loraName) && loraName.ValueKind == JsonValueKind.String)
                {
                    double? weight = null;
                    if (node.Value.TryGetProperty("weight", out var weightElem) && weightElem.TryGetDouble(out var wVal))
                    {
                        weight = wVal;
                    }
                    snapshot.Loras.Add(new LoraSnapshot(loraName.GetString(), weight));
                }
            }
        }

        if (snapshot.Loras.Count == 0)
        {
            snapshot.Loras = null;
        }

        snapshot.GraphJson ??= root.GetRawText();
        return true;
    }

    private static void ExtractFromJson(MetadataSnapshot snapshot, JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in element.EnumerateObject())
            {
                var name = prop.Name;
                var value = prop.Value;
                if (value.ValueKind == JsonValueKind.String)
                {
                    var str = value.GetString();
                    if (IsMatch(name, "original_prompt")) snapshot.OriginalPrompt ??= str;
                    if (IsMatch(name, "prompt"))
                    {
                        snapshot.GenPrompt ??= str;
                        snapshot.ImagePrompt ??= str;
                        snapshot.ProcessedPrompt ??= str;
                    }
                    if (IsMatch(name, "processed_prompt")) snapshot.ProcessedPrompt ??= str;
                    if (IsMatch(name, "negative_prompt") || IsMatch(name, "negativeprompt")) snapshot.NegativePrompt ??= str;
                    if (IsMatch(name, "scheduler")) snapshot.Scheduler ??= str;
                    if (IsMatch(name, "model") || IsMatch(name, "model_name") || IsMatch(name, "modelname")) snapshot.ModelName ??= str;
                    if (IsMatch(name, "template_name")) snapshot.TemplateName ??= str;
                    if (IsMatch(name, "status")) snapshot.Status ??= str;
                    if (IsMatch(name, "workflow") || IsMatch(name, "workflow_source")) snapshot.Workflow ??= str;
                    if (IsMatch(name, "enhanced_prompt")) snapshot.EnhancedPrompt ??= str;
                    if (IsMatch(name, "cover_image") || IsMatch(name, "cover_image_path")) snapshot.CoverImagePath ??= str;
                    if (IsMatch(name, "invokeai_model")) snapshot.InvokeAIModel ??= str;
                    if (IsMatch(name, "ollama_model")) snapshot.OllamaModel ??= str;
                    if (IsMatch(name, "prompt_type")) snapshot.PromptType ??= str;
                    if (IsMatch(name, "prompt_type_suffix")) snapshot.PromptTypeSuffix ??= str;
                    if (IsMatch(name, "image_path")) snapshot.ImagePath ??= str;
                    if (IsMatch(name, "aesthetic_score_model")) snapshot.AestheticScoreModel ??= str;
                    if (IsMatch(name, "upscale_model")) snapshot.UpscaleModel ??= str;
                    if (IsMatch(name, "upscale_source_image_path")) snapshot.UpscaleSourceImagePath ??= str;
                    if (IsMatch(name, "base_model_type")) snapshot.BaseModelType ??= str;
                    if (IsMatch(name, "positive_style_prompt")) snapshot.PositiveStylePrompt ??= str;
                    if (IsMatch(name, "negative_style_prompt")) snapshot.NegativeStylePrompt ??= str;
                    if (IsMatch(name, "vae_used_name")) snapshot.VaeUsedName ??= str;
                    if (IsMatch(name, "generation_params_json") || IsMatch(name, "generation_params"))
                    {
                        snapshot.GenerationParamsJson ??= str;
                    }
                }
                else if (value.ValueKind == JsonValueKind.Number)
                {
                    if (IsMatch(name, "steps") && value.TryGetInt32(out var steps)) snapshot.Steps ??= steps;
                    if (IsMatch(name, "width") && value.TryGetInt32(out var w)) snapshot.Width ??= w;
                    if (IsMatch(name, "height") && value.TryGetInt32(out var h)) snapshot.Height ??= h;
                    if (IsMatch(name, "seed") && value.TryGetInt32(out var seed)) snapshot.Seed ??= seed;
                    if (IsMatch(name, "cfg_scale") || IsMatch(name, "cfgscale"))
                    {
                        if (value.TryGetDouble(out var cfg)) snapshot.CfgScale ??= cfg;
                    }
                    if (IsMatch(name, "cfg_rescale_multiplier") && value.TryGetDouble(out var rescale)) snapshot.CfgRescaleMultiplier ??= rescale;
                    if (IsMatch(name, "base_seed") && value.TryGetInt32(out var baseSeed)) snapshot.BaseSeed ??= baseSeed;
                    if (IsMatch(name, "aesthetic_score") && value.TryGetDouble(out var score)) snapshot.AestheticScore ??= score;
                    if (IsMatch(name, "aesthetic_score_ms") && value.TryGetInt32(out var scoreMs)) snapshot.AestheticScoreMs ??= scoreMs;
                    if (IsMatch(name, "upscale_scale") && value.TryGetDouble(out var upscaleScale)) snapshot.UpscaleScale ??= upscaleScale;
                    if (IsMatch(name, "upscale_tile_size") && value.TryGetInt32(out var tileSize)) snapshot.UpscaleTileSize ??= tileSize;
                }
                else if (value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False)
                {
                    var flag = value.GetBoolean();
                    if (IsMatch(name, "favorite")) snapshot.EntryIsFavorite ??= flag;
                    if (IsMatch(name, "is_favorite")) snapshot.ImageIsFavorite ??= flag;
                    if (IsMatch(name, "used_random_seed")) snapshot.UsedRandomSeed ??= flag;
                    if (IsMatch(name, "auto_cleared_model_cache_between_models")) snapshot.AutoClearedModelCacheBetweenModels ??= flag;
                    if (IsMatch(name, "save_to_gallery")) snapshot.SaveToGallery ??= flag;
                    if (IsMatch(name, "use_prompt_as_style_when_empty")) snapshot.UsePromptAsStyleWhenEmpty ??= flag;
                    if (IsMatch(name, "upscale_fit_to_multiple_of8")) snapshot.UpscaleFitToMultipleOf8 ??= flag;
                }
                else if (value.ValueKind == JsonValueKind.Object)
                {
                    if (IsMatch(name, "model"))
                    {
                        if (value.TryGetProperty("name", out var mn) && mn.ValueKind == JsonValueKind.String)
                        {
                            snapshot.ModelName ??= mn.GetString();
                        }
                    }
                    if (IsMatch(name, "vae"))
                    {
                        if (value.TryGetProperty("name", out var vn) && vn.ValueKind == JsonValueKind.String)
                        {
                            snapshot.VaeUsedName ??= vn.GetString();
                        }
                    }
                    if (IsMatch(name, "variation_prompts") || IsMatch(name, "variations"))
                    {
                        snapshot.VariationPromptsJson ??= value.GetRawText();
                    }
                    if (IsMatch(name, "context"))
                    {
                        snapshot.ContextJson ??= value.GetRawText();
                    }
                    if (IsMatch(name, "generation_params") || IsMatch(name, "generation_params_json"))
                    {
                        snapshot.GenerationParamsJson ??= value.GetRawText();
                    }
                }

                if (IsMatch(name, "loras") && value.ValueKind == JsonValueKind.Array)
                {
                    snapshot.Loras ??= ParseLoras(value);
                }

                ExtractFromJson(snapshot, value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                ExtractFromJson(snapshot, item);
            }
        }
    }

    private static List<LoraSnapshot> ParseLoras(JsonElement array)
    {
        var result = new List<LoraSnapshot>();
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Object)
            {
                string? name = null;
                double? weight = null;
                if (item.TryGetProperty("lora", out var loraObj))
                {
                    if (loraObj.ValueKind == JsonValueKind.String)
                    {
                        name = loraObj.GetString();
                    }
                    else if (loraObj.ValueKind == JsonValueKind.Object)
                    {
                        if (loraObj.TryGetProperty("name", out var ln) && ln.ValueKind == JsonValueKind.String)
                        {
                            name = ln.GetString();
                        }
                    }
                }
                if (item.TryGetProperty("weight", out var weightElem) && weightElem.TryGetDouble(out var w))
                {
                    weight = w;
                }
                if (!string.IsNullOrWhiteSpace(name))
                {
                    result.Add(new LoraSnapshot(name, weight));
                }
            }
            else if (item.ValueKind == JsonValueKind.String)
            {
                result.Add(new LoraSnapshot(item.GetString(), null));
            }
        }
        return result;
    }

    private static bool IsMatch(string name, string target)
    {
        return string.Equals(name, target, StringComparison.OrdinalIgnoreCase)
               || string.Equals(name.Replace("_", ""), target.Replace("_", ""), StringComparison.OrdinalIgnoreCase);
    }

    private static HistorySnapshot BuildHistorySnapshot(HistoryEntry entry, HistoryImage image)
    {
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image);
        return new HistorySnapshot
        {
            EntryId = entry.Id,
            EntryTimestamp = entry.Timestamp,
            OriginalPrompt = entry.OriginalPrompt,
            ProcessedPrompt = entry.ProcessedPrompt,
            OllamaModel = entry.OllamaModel,
            TemplateName = entry.TemplateName,
            Status = entry.Status,
            Workflow = entry.Workflow,
            EnhancedPrompt = entry.EnhancedPrompt,
            CoverImagePath = entry.CoverImagePath,
            EntryIsFavorite = entry.IsFavorite,
            InvokeAIModel = entry.InvokeAIModel,
            VariationPromptsJson = entry.VariationPrompts == null ? null : JsonSerializer.Serialize(entry.VariationPrompts),
            ContextJson = entry.Context == null ? null : JsonSerializer.Serialize(entry.Context),
            ImagePath = image.ImagePath,
            PromptType = image.PromptType,
            PromptTypeSuffix = image.PromptTypeSuffix,
            ImagePrompt = image.Prompt,
            ImageWorkflow = image.Workflow,
            ImageIsFavorite = image.IsFavorite,
            AestheticScore = image.AestheticScore,
            AestheticScoreModel = image.AestheticScoreModel,
            AestheticScoreTimestamp = image.AestheticScoreTimestamp,
            AestheticScoreMs = image.AestheticScoreMs,
            UpscaleModel = image.UpscaleModel,
            UpscaleScale = image.UpscaleScale,
            UpscaleTileSize = image.UpscaleTileSize,
            UpscaleFitToMultipleOf8 = image.UpscaleFitToMultipleOf8,
            UpscaleSourceImagePath = image.UpscaleSourceImagePath,
            GenerationParamsJson = image.GenerationParamsJson,
            GenPrompt = gen?.Prompt ?? image.Prompt ?? entry.ProcessedPrompt,
            PositiveStylePrompt = gen?.PositiveStylePrompt,
            NegativeStylePrompt = gen?.NegativeStylePrompt,
            NegativePrompt = gen?.NegativePrompt,
            BaseModelType = gen?.BaseModelType,
            UsedRandomSeed = gen?.UsedRandomSeed,
            BaseSeed = gen?.BaseSeed,
            AutoClearedModelCacheBetweenModels = gen?.AutoClearedModelCacheBetweenModels,
            VaeUsedName = gen?.VaeUsedName,
            Steps = gen?.Steps,
            CfgScale = gen?.CfgScale,
            Width = gen?.Width,
            Height = gen?.Height,
            Seed = gen?.Seed,
            Scheduler = gen?.Scheduler,
            CfgRescaleMultiplier = gen?.CfgRescaleMultiplier,
            SaveToGallery = gen?.SaveToGallery,
            UsePromptAsStyleWhenEmpty = gen?.UsePromptAsStyleWhenEmpty,
            ModelName = gen?.Model?.Name ?? entry.InvokeAIModel,
            Loras = gen?.Loras?.Select(l => new LoraSnapshot(l.Lora?.Name, l.Weight)).ToList()
        };
    }

    private void BuildDiffs(HistorySnapshot history, MetadataSnapshot metadata)
    {
        HistoryDiffs.Clear();

        AddStringDiff(PngHistoryField.GenPrompt, history.GenPrompt, metadata.GenPrompt, metadata.GenPrompt != null);
        AddStringDiff(PngHistoryField.NegativePrompt, history.NegativePrompt, metadata.NegativePrompt, metadata.NegativePrompt != null);
        AddStringDiff(PngHistoryField.PositiveStylePrompt, history.PositiveStylePrompt, metadata.PositiveStylePrompt, metadata.PositiveStylePrompt != null);
        AddStringDiff(PngHistoryField.NegativeStylePrompt, history.NegativeStylePrompt, metadata.NegativeStylePrompt, metadata.NegativeStylePrompt != null);
        AddIntDiff(PngHistoryField.Steps, history.Steps, metadata.Steps, metadata.Steps.HasValue);
        AddDoubleDiff(PngHistoryField.CfgScale, history.CfgScale, metadata.CfgScale, metadata.CfgScale.HasValue);
        AddIntDiff(PngHistoryField.Width, history.Width, metadata.Width, metadata.Width.HasValue);
        AddIntDiff(PngHistoryField.Height, history.Height, metadata.Height, metadata.Height.HasValue);
        AddIntDiff(PngHistoryField.Seed, history.Seed, metadata.Seed, metadata.Seed.HasValue);
        AddStringDiff(PngHistoryField.Scheduler, history.Scheduler, metadata.Scheduler, metadata.Scheduler != null);
        AddDoubleDiff(PngHistoryField.CfgRescaleMultiplier, history.CfgRescaleMultiplier, metadata.CfgRescaleMultiplier, metadata.CfgRescaleMultiplier.HasValue);
        AddStringDiff(PngHistoryField.ModelName, history.ModelName, metadata.ModelName, metadata.ModelName != null);
        AddStringDiff(PngHistoryField.BaseModelType, history.BaseModelType, metadata.BaseModelType, metadata.BaseModelType != null);
        AddStringDiff(PngHistoryField.VaeUsedName, history.VaeUsedName, metadata.VaeUsedName, metadata.VaeUsedName != null);
        AddLoraDiff(history.Loras, metadata.Loras, metadata.Loras != null);

        HasDiffs = HistoryDiffs.Count > 0;
    }

    private void AddStringDiff(PngHistoryField field, string? current, string? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        if (string.Equals(current?.Trim(), incoming?.Trim(), StringComparison.Ordinal)) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromString(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddIntDiff(PngHistoryField field, int? current, int? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        if (current.HasValue && incoming.HasValue && current.Value == incoming.Value) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromInt(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddDoubleDiff(PngHistoryField field, double? current, double? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        if (current.HasValue && incoming.HasValue && Math.Abs(current.Value - incoming.Value) < 0.0001) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromDouble(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddBoolDiff(PngHistoryField field, bool? current, bool? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        if (current.HasValue && incoming.HasValue && current.Value == incoming.Value) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromBool(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddDateDiff(PngHistoryField field, DateTime? current, DateTime? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        if (current.HasValue && incoming.HasValue && current.Value == incoming.Value) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromDate(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddMapDiff(PngHistoryField field, string? currentJson, string? incomingJson)
    {
        var current = TryParseMap(currentJson);
        var incoming = TryParseMap(incomingJson);
        if (incoming == null) return;
        if (NormalizeMap(current) == NormalizeMap(incoming)) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromMap(field, current, incoming, true, IsApplySupported(field)));
    }

    private void AddLoraDiff(List<LoraSnapshot>? current, List<LoraSnapshot>? incoming, bool hasMetadata)
    {
        if (!hasMetadata) return;
        var currentKey = NormalizeLoras(current);
        var incomingKey = NormalizeLoras(incoming);
        if (string.Equals(currentKey, incomingKey, StringComparison.Ordinal)) return;
        HistoryDiffs.Add(PngHistoryDiffItem.FromLoras(current, incoming, true, IsApplySupported(PngHistoryField.Loras)));
    }

    private static string NormalizeMap(Dictionary<string, string>? map)
    {
        if (map == null || map.Count == 0) return string.Empty;
        return JsonSerializer.Serialize(map, new JsonSerializerOptions { WriteIndented = false });
    }

    private static Dictionary<string, string>? TryParseMap(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return null;
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, string>>(json);
        }
        catch
        {
            return null;
        }
    }

    private static bool IsApplySupported(PngHistoryField field)
    {
        return field switch
        {
            PngHistoryField.EntryId => false,
            PngHistoryField.EntryTimestamp => false,
            PngHistoryField.ImagePath => false,
            _ => true
        };
    }

    private PngMergedGenerationRequest? BuildMergedGenerationRequest(bool saveToHistory, bool createNewEntryOnSave)
    {
        var metadata = _lastMetadata ?? BuildMetadataSnapshot();
        if (!HasMetadataContent(metadata))
        {
            return null;
        }

        var history = _lastHistory;
        var mergedParams = BuildMergedGenerationParams(metadata, history);
        if (mergedParams == null)
        {
            return null;
        }

        var prompt = !string.IsNullOrWhiteSpace(mergedParams.Prompt)
            ? mergedParams.Prompt
            : metadata.GenPrompt ?? history?.GenPrompt ?? string.Empty;

        var workflow = _matchedEntry?.Workflow ?? history?.Workflow;
        return new PngMergedGenerationRequest(
            mergedParams,
            prompt,
            "PNG Merge",
            workflow,
            saveToHistory,
            createNewEntryOnSave,
            _matchedEntry,
            _matchedImage,
            metadata,
            history);
    }

    private PngGraphReplayRequest? BuildReplayGraphRequest(bool saveToHistory, bool createNewEntryOnSave)
    {
        var metadata = _lastMetadata ?? BuildMetadataSnapshot();
        if (string.IsNullOrWhiteSpace(metadata.GraphJson))
        {
            return null;
        }

        var graph = ApplyReplayOverrides(metadata.GraphJson);
        if (graph == null)
        {
            return null;
        }

        var history = _lastHistory;
        var mergedParams = BuildMergedGenerationParams(metadata, history);
        var prompt = mergedParams?.Prompt ?? metadata.GenPrompt ?? history?.GenPrompt ?? string.Empty;
        var workflow = _matchedEntry?.Workflow ?? history?.Workflow;

        return new PngGraphReplayRequest(
            graph,
            mergedParams,
            prompt,
            "PNG Replay",
            workflow,
            saveToHistory,
            createNewEntryOnSave,
            _matchedEntry,
            _matchedImage,
            metadata,
            history);
    }

    private static InvokeAIGenerationParams? BuildMergedGenerationParams(MetadataSnapshot metadata, HistorySnapshot? history)
    {
        var prompt = metadata.GenPrompt ?? history?.GenPrompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            return null;
        }

        var parameters = new InvokeAIGenerationParams
        {
            Prompt = prompt,
            NegativePrompt = metadata.NegativePrompt ?? history?.NegativePrompt,
            PositiveStylePrompt = metadata.PositiveStylePrompt ?? history?.PositiveStylePrompt,
            NegativeStylePrompt = metadata.NegativeStylePrompt ?? history?.NegativeStylePrompt,
            BaseModelType = metadata.BaseModelType ?? history?.BaseModelType,
            VaeUsedName = metadata.VaeUsedName ?? history?.VaeUsedName,
            Scheduler = metadata.Scheduler ?? history?.Scheduler ?? "dpmpp_2m_k",
            Steps = metadata.Steps ?? history?.Steps ?? 30,
            CfgScale = metadata.CfgScale ?? history?.CfgScale ?? 7.0,
            Width = metadata.Width ?? history?.Width ?? 1024,
            Height = metadata.Height ?? history?.Height ?? 1024,
            Seed = metadata.Seed ?? history?.Seed ?? -1,
            CfgRescaleMultiplier = metadata.CfgRescaleMultiplier ?? history?.CfgRescaleMultiplier ?? 0.0,
            UsedRandomSeed = metadata.UsedRandomSeed ?? history?.UsedRandomSeed ?? false,
            BaseSeed = metadata.BaseSeed ?? history?.BaseSeed ?? 0,
            AutoClearedModelCacheBetweenModels = metadata.AutoClearedModelCacheBetweenModels ?? history?.AutoClearedModelCacheBetweenModels ?? false,
            SaveToGallery = metadata.SaveToGallery ?? history?.SaveToGallery ?? false,
            UsePromptAsStyleWhenEmpty = metadata.UsePromptAsStyleWhenEmpty ?? history?.UsePromptAsStyleWhenEmpty ?? true,
            UseAutoCfgRescale = false
        };

        if (!string.IsNullOrWhiteSpace(metadata.GraphJson))
        {
            try
            {
                var graph = JsonNode.Parse(metadata.GraphJson) as JsonObject;
                var nodes = graph?["nodes"] as JsonObject;
                if (nodes != null)
                {
                    if (nodes["noise"] is JsonObject noise &&
                        noise["use_cpu"] is JsonValue useCpuVal &&
                        useCpuVal.TryGetValue(out bool useCpu))
                    {
                        parameters.UseCpuNoise = useCpu;
                    }

                    if (nodes["l2i"] is JsonObject l2i &&
                        l2i["fp32"] is JsonValue fp32Val &&
                        fp32Val.TryGetValue(out bool fp32))
                    {
                        parameters.L2iFp32 = fp32;
                    }

                    if (nodes["sdxl_model_loader"] is JsonObject modelLoader &&
                        modelLoader["vae_precision"] is JsonValue vaeVal &&
                        vaeVal.TryGetValue(out string? vaePrecision))
                    {
                        parameters.VaePrecision = vaePrecision;
                    }
                }
            }
            catch
            {
                // Ignore graph parse errors; fall back to standard params.
            }
        }

        var modelName = metadata.ModelName ?? history?.ModelName;
        if (!string.IsNullOrWhiteSpace(modelName))
        {
            parameters.Model = new InvokeAIModel
            {
                Name = modelName,
                Base = metadata.BaseModelType ?? history?.BaseModelType ?? string.Empty
            };
        }

        var loras = metadata.Loras ?? history?.Loras;
        if (loras != null && loras.Count > 0)
        {
            parameters.Loras = loras
                .Where(l => !string.IsNullOrWhiteSpace(l.Name))
                .Select(l => new LoraParameter
                {
                    Lora = new InvokeAIModel { Name = l.Name ?? string.Empty },
                    Weight = l.Weight ?? 1.0
                })
                .ToList();
        }

        return parameters;
    }

    private void InitializeGraphOverrides(string? graphJson)
    {
        ReplayVaePrecision = string.Empty;
        ReplayUseCpu = false;
        ReplayFp32 = true;
        ReplayIncludeStyleNegative = true;
        ReplayIncludePositiveStyle = true;

        if (string.IsNullOrWhiteSpace(graphJson))
        {
            return;
        }

        JsonObject? graph;
        try
        {
            graph = JsonNode.Parse(graphJson) as JsonObject;
        }
        catch
        {
            return;
        }

        var nodes = graph?["nodes"] as JsonObject;
        if (nodes == null)
        {
            return;
        }

        if (nodes["noise"] is JsonObject noise && noise["use_cpu"] is JsonValue useCpuVal && useCpuVal.TryGetValue(out bool useCpu))
        {
            ReplayUseCpu = useCpu;
        }

        if (nodes["l2i"] is JsonObject l2i && l2i["fp32"] is JsonValue fp32Val && fp32Val.TryGetValue(out bool fp32))
        {
            ReplayFp32 = fp32;
        }

        ReplayIncludeStyleNegative = nodes.ContainsKey("style_negative_prompt");

        if (nodes["sdxl_model_loader"] is JsonObject modelLoader &&
            modelLoader["vae_precision"] is JsonValue vaeVal &&
            vaeVal.TryGetValue(out string? vaePrecision))
        {
            ReplayVaePrecision = vaePrecision ?? string.Empty;
        }

        if (graph?["edges"] is JsonArray edges)
        {
            ReplayIncludePositiveStyle = edges.Any(e =>
                e is JsonObject edge &&
                edge["destination"] is JsonObject dest &&
                string.Equals(dest["node_id"]?.GetValue<string>(), "positive_conditioning", StringComparison.OrdinalIgnoreCase) &&
                string.Equals(dest["field"]?.GetValue<string>(), "style", StringComparison.OrdinalIgnoreCase));
        }
    }

    private JsonObject? ApplyReplayOverrides(string graphJson)
    {
        JsonObject? graph;
        try
        {
            graph = JsonNode.Parse(graphJson) as JsonObject;
        }
        catch
        {
            return null;
        }

        var nodes = graph?["nodes"] as JsonObject;
        if (nodes == null)
        {
            return null;
        }

        if (nodes["noise"] is JsonObject noise)
        {
            noise["use_cpu"] = ReplayUseCpu;
        }

        if (nodes["l2i"] is JsonObject l2i)
        {
            l2i["fp32"] = ReplayFp32;
        }

        if (nodes["sdxl_model_loader"] is JsonObject modelLoader && !string.IsNullOrWhiteSpace(ReplayVaePrecision))
        {
            modelLoader["vae_precision"] = ReplayVaePrecision.Trim();
        }

        if (!ReplayIncludeStyleNegative)
        {
            nodes.Remove("style_negative_prompt");
        }

        if (graph?["edges"] is JsonArray edges)
        {
            for (var i = edges.Count - 1; i >= 0; i--)
            {
                if (edges[i] is not JsonObject edge) continue;
                var src = edge["source"] as JsonObject;
                var dest = edge["destination"] as JsonObject;
                var srcNode = src?["node_id"]?.GetValue<string>();
                var destNode = dest?["node_id"]?.GetValue<string>();
                var destField = dest?["field"]?.GetValue<string>();

                if (!ReplayIncludeStyleNegative &&
                    string.Equals(destNode, "negative_conditioning", StringComparison.OrdinalIgnoreCase) &&
                    string.Equals(destField, "style", StringComparison.OrdinalIgnoreCase))
                {
                    edges.RemoveAt(i);
                    continue;
                }

                if (!ReplayIncludePositiveStyle &&
                    string.Equals(destNode, "positive_conditioning", StringComparison.OrdinalIgnoreCase) &&
                    string.Equals(destField, "style", StringComparison.OrdinalIgnoreCase))
                {
                    edges.RemoveAt(i);
                    continue;
                }

                if (!ReplayIncludeStyleNegative &&
                    string.Equals(srcNode, "style_negative_prompt", StringComparison.OrdinalIgnoreCase))
                {
                    edges.RemoveAt(i);
                }
            }
        }

        return graph;
    }

    private static HistoryEntry BuildHistoryEntryFromMerged(MetadataSnapshot metadata, HistorySnapshot? history, InvokeAIGenerationParams parameters)
    {
        return new HistoryEntry
        {
            OriginalPrompt = metadata.OriginalPrompt ?? history?.OriginalPrompt ?? parameters.Prompt,
            ProcessedPrompt = metadata.ProcessedPrompt ?? history?.ProcessedPrompt ?? parameters.Prompt,
            TemplateName = metadata.TemplateName ?? history?.TemplateName,
            OllamaModel = metadata.OllamaModel ?? history?.OllamaModel ?? string.Empty,
            InvokeAIModel = metadata.ModelName ?? history?.ModelName,
            ImageParameters = parameters,
            Workflow = metadata.Workflow ?? history?.Workflow
        };
    }

    private static string NormalizeLoras(List<LoraSnapshot>? loras)
    {
        if (loras == null || loras.Count == 0) return string.Empty;
        return string.Join(" | ", loras
            .Where(l => !string.IsNullOrWhiteSpace(l.Name))
            .OrderBy(l => l.Name, StringComparer.OrdinalIgnoreCase)
            .Select(l => $"{l.Name}:{l.Weight:0.###}"));
    }
}

public sealed record PngMergedGenerationRequest(
    InvokeAIGenerationParams Parameters,
    string Prompt,
    string PromptType,
    string? Workflow,
    bool SaveToHistory,
    bool CreateNewEntryOnSave,
    HistoryEntry? TargetEntry,
    HistoryImage? TargetImage,
    MetadataSnapshot Metadata,
    HistorySnapshot? History);

public sealed record PngGraphReplayRequest(
    JsonObject Graph,
    InvokeAIGenerationParams? Parameters,
    string Prompt,
    string PromptType,
    string? Workflow,
    bool SaveToHistory,
    bool CreateNewEntryOnSave,
    HistoryEntry? TargetEntry,
    HistoryImage? TargetImage,
    MetadataSnapshot Metadata,
    HistorySnapshot? History);

public enum PngHistoryField
{
    EntryId,
    EntryTimestamp,
    OriginalPrompt,
    ProcessedPrompt,
    OllamaModel,
    TemplateName,
    Status,
    Workflow,
    EnhancedPrompt,
    CoverImagePath,
    EntryIsFavorite,
    InvokeAIModel,
    VariationPrompts,
    Context,
    ImagePath,
    PromptType,
    PromptTypeSuffix,
    ImagePrompt,
    ImageWorkflow,
    ImageIsFavorite,
    AestheticScore,
    AestheticScoreModel,
    AestheticScoreTimestamp,
    AestheticScoreMs,
    UpscaleModel,
    UpscaleScale,
    UpscaleTileSize,
    UpscaleFitToMultipleOf8,
    UpscaleSourceImagePath,
    GenerationParamsJson,
    GenPrompt,
    PositiveStylePrompt,
    NegativeStylePrompt,
    NegativePrompt,
    BaseModelType,
    UsedRandomSeed,
    BaseSeed,
    AutoClearedModelCacheBetweenModels,
    VaeUsedName,
    Steps,
    CfgScale,
    Width,
    Height,
    Seed,
    Scheduler,
    CfgRescaleMultiplier,
    SaveToGallery,
    UsePromptAsStyleWhenEmpty,
    ModelName,
    Loras
}

public sealed class MetadataSnapshot
{
    public string? GraphJson { get; set; }
    public string? OriginalPrompt { get; set; }
    public string? ProcessedPrompt { get; set; }
    public string? TemplateName { get; set; }
    public string? Status { get; set; }
    public string? Workflow { get; set; }
    public string? EnhancedPrompt { get; set; }
    public string? CoverImagePath { get; set; }
    public bool? EntryIsFavorite { get; set; }
    public string? InvokeAIModel { get; set; }
    public string? OllamaModel { get; set; }
    public string? VariationPromptsJson { get; set; }
    public string? ContextJson { get; set; }
    public string? ImagePath { get; set; }
    public string? PromptType { get; set; }
    public string? PromptTypeSuffix { get; set; }
    public string? ImagePrompt { get; set; }
    public string? ImageWorkflow { get; set; }
    public bool? ImageIsFavorite { get; set; }
    public double? AestheticScore { get; set; }
    public string? AestheticScoreModel { get; set; }
    public DateTime? AestheticScoreTimestamp { get; set; }
    public int? AestheticScoreMs { get; set; }
    public string? UpscaleModel { get; set; }
    public double? UpscaleScale { get; set; }
    public int? UpscaleTileSize { get; set; }
    public bool? UpscaleFitToMultipleOf8 { get; set; }
    public string? UpscaleSourceImagePath { get; set; }
    public string? GenerationParamsJson { get; set; }
    public string? GenPrompt { get; set; }
    public string? PositiveStylePrompt { get; set; }
    public string? NegativeStylePrompt { get; set; }
    public string? NegativePrompt { get; set; }
    public string? BaseModelType { get; set; }
    public bool? UsedRandomSeed { get; set; }
    public int? BaseSeed { get; set; }
    public bool? AutoClearedModelCacheBetweenModels { get; set; }
    public string? VaeUsedName { get; set; }
    public int? Steps { get; set; }
    public double? CfgScale { get; set; }
    public int? Width { get; set; }
    public int? Height { get; set; }
    public int? Seed { get; set; }
    public string? Scheduler { get; set; }
    public double? CfgRescaleMultiplier { get; set; }
    public bool? SaveToGallery { get; set; }
    public bool? UsePromptAsStyleWhenEmpty { get; set; }
    public string? ModelName { get; set; }
    public List<LoraSnapshot>? Loras { get; set; }
}

public sealed class HistorySnapshot
{
    public string? EntryId { get; init; }
    public DateTime? EntryTimestamp { get; init; }
    public string? OriginalPrompt { get; init; }
    public string? ProcessedPrompt { get; init; }
    public string? OllamaModel { get; init; }
    public string? TemplateName { get; init; }
    public string? Status { get; init; }
    public string? Workflow { get; init; }
    public string? EnhancedPrompt { get; init; }
    public string? CoverImagePath { get; init; }
    public bool? EntryIsFavorite { get; init; }
    public string? InvokeAIModel { get; init; }
    public string? VariationPromptsJson { get; init; }
    public string? ContextJson { get; init; }
    public string? ImagePath { get; init; }
    public string? PromptType { get; init; }
    public string? PromptTypeSuffix { get; init; }
    public string? ImagePrompt { get; init; }
    public string? ImageWorkflow { get; init; }
    public bool? ImageIsFavorite { get; init; }
    public double? AestheticScore { get; init; }
    public string? AestheticScoreModel { get; init; }
    public DateTime? AestheticScoreTimestamp { get; init; }
    public int? AestheticScoreMs { get; init; }
    public string? UpscaleModel { get; init; }
    public double? UpscaleScale { get; init; }
    public int? UpscaleTileSize { get; init; }
    public bool? UpscaleFitToMultipleOf8 { get; init; }
    public string? UpscaleSourceImagePath { get; init; }
    public string? GenerationParamsJson { get; init; }
    public string? GenPrompt { get; init; }
    public string? PositiveStylePrompt { get; init; }
    public string? NegativeStylePrompt { get; init; }
    public string? NegativePrompt { get; init; }
    public string? BaseModelType { get; init; }
    public bool? UsedRandomSeed { get; init; }
    public int? BaseSeed { get; init; }
    public bool? AutoClearedModelCacheBetweenModels { get; init; }
    public string? VaeUsedName { get; init; }
    public int? Steps { get; init; }
    public double? CfgScale { get; init; }
    public int? Width { get; init; }
    public int? Height { get; init; }
    public int? Seed { get; init; }
    public string? Scheduler { get; init; }
    public double? CfgRescaleMultiplier { get; init; }
    public bool? SaveToGallery { get; init; }
    public bool? UsePromptAsStyleWhenEmpty { get; init; }
    public string? ModelName { get; init; }
    public List<LoraSnapshot>? Loras { get; init; }
}

public sealed record LoraSnapshot(string? Name, double? Weight);

public partial class PngHistoryDiffItem : ObservableObject
{
    [ObservableProperty] private bool _apply = true;
    [ObservableProperty] private bool _canApply = true;
    [ObservableProperty] private bool _hasMetadataValue;
    [ObservableProperty] private PngHistoryField _field;
    [ObservableProperty] private string _label = string.Empty;
    [ObservableProperty] private string _currentDisplay = string.Empty;
    [ObservableProperty] private string _newDisplay = string.Empty;

    public string? NewValue { get; init; }
    public int? NewInt { get; init; }
    public double? NewDouble { get; init; }
    public bool? NewBool { get; init; }
    public DateTime? NewDateTime { get; init; }
    public Dictionary<string, string>? NewMap { get; init; }
    public List<LoraSnapshot>? NewLoras { get; init; }

    public static PngHistoryDiffItem FromString(PngHistoryField field, string? current, string? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = current ?? "(empty)",
            NewDisplay = hasMetadata ? incoming ?? "(empty)" : "(missing in PNG)",
            NewValue = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromInt(PngHistoryField field, int? current, int? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = current?.ToString(CultureInfo.InvariantCulture) ?? "(empty)",
            NewDisplay = hasMetadata ? incoming?.ToString(CultureInfo.InvariantCulture) ?? "(empty)" : "(missing in PNG)",
            NewInt = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromDouble(PngHistoryField field, double? current, double? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = current?.ToString("0.###", CultureInfo.InvariantCulture) ?? "(empty)",
            NewDisplay = hasMetadata ? incoming?.ToString("0.###", CultureInfo.InvariantCulture) ?? "(empty)" : "(missing in PNG)",
            NewDouble = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromBool(PngHistoryField field, bool? current, bool? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = current?.ToString() ?? "(empty)",
            NewDisplay = hasMetadata ? incoming?.ToString() ?? "(empty)" : "(missing in PNG)",
            NewBool = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromDate(PngHistoryField field, DateTime? current, DateTime? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = current?.ToString("o") ?? "(empty)",
            NewDisplay = hasMetadata ? incoming?.ToString("o") ?? "(empty)" : "(missing in PNG)",
            NewDateTime = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromMap(PngHistoryField field, Dictionary<string, string>? current, Dictionary<string, string>? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = field,
            Label = FieldLabel(field),
            CurrentDisplay = FormatMap(current),
            NewDisplay = hasMetadata ? FormatMap(incoming) : "(missing in PNG)",
            NewMap = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    public static PngHistoryDiffItem FromLoras(List<LoraSnapshot>? current, List<LoraSnapshot>? incoming, bool hasMetadata, bool canApply)
    {
        return new PngHistoryDiffItem
        {
            Field = PngHistoryField.Loras,
            Label = FieldLabel(PngHistoryField.Loras),
            CurrentDisplay = FormatLoras(current),
            NewDisplay = hasMetadata ? FormatLoras(incoming) : "(missing in PNG)",
            NewLoras = incoming,
            HasMetadataValue = hasMetadata,
            CanApply = canApply,
            Apply = canApply && hasMetadata
        };
    }

    private static string FormatLoras(List<LoraSnapshot>? loras)
    {
        if (loras == null || loras.Count == 0) return "(none)";
        return string.Join(", ", loras
            .Where(l => !string.IsNullOrWhiteSpace(l.Name))
            .Select(l => l.Weight.HasValue ? $"{l.Name} ({l.Weight:0.###})" : l.Name));
    }

    private static string FormatMap(Dictionary<string, string>? map)
    {
        if (map == null || map.Count == 0) return "(none)";
        return JsonSerializer.Serialize(map, new JsonSerializerOptions { WriteIndented = false });
    }

    private static string FieldLabel(PngHistoryField field)
    {
        return field switch
        {
            PngHistoryField.EntryId => "Entry Id",
            PngHistoryField.EntryTimestamp => "Entry Timestamp",
            PngHistoryField.OriginalPrompt => "Original Prompt",
            PngHistoryField.ProcessedPrompt => "Processed Prompt",
            PngHistoryField.OllamaModel => "Ollama Model",
            PngHistoryField.TemplateName => "Template Name",
            PngHistoryField.Status => "Status",
            PngHistoryField.Workflow => "Workflow",
            PngHistoryField.EnhancedPrompt => "Enhanced Prompt",
            PngHistoryField.CoverImagePath => "Cover Image Path",
            PngHistoryField.EntryIsFavorite => "Entry Favorite",
            PngHistoryField.InvokeAIModel => "InvokeAI Model",
            PngHistoryField.VariationPrompts => "Variation Prompts",
            PngHistoryField.Context => "Context",
            PngHistoryField.ImagePath => "Image Path",
            PngHistoryField.PromptType => "Prompt Type",
            PngHistoryField.PromptTypeSuffix => "Prompt Type Suffix",
            PngHistoryField.ImagePrompt => "Image Prompt",
            PngHistoryField.ImageWorkflow => "Image Workflow",
            PngHistoryField.ImageIsFavorite => "Image Favorite",
            PngHistoryField.AestheticScore => "Aesthetic Score",
            PngHistoryField.AestheticScoreModel => "Aesthetic Score Model",
            PngHistoryField.AestheticScoreTimestamp => "Aesthetic Score Timestamp",
            PngHistoryField.AestheticScoreMs => "Aesthetic Score ms",
            PngHistoryField.UpscaleModel => "Upscale Model",
            PngHistoryField.UpscaleScale => "Upscale Scale",
            PngHistoryField.UpscaleTileSize => "Upscale Tile Size",
            PngHistoryField.UpscaleFitToMultipleOf8 => "Upscale Fit To 8",
            PngHistoryField.UpscaleSourceImagePath => "Upscale Source Image",
            PngHistoryField.GenerationParamsJson => "Generation Params JSON",
            PngHistoryField.GenPrompt => "Generation Prompt",
            PngHistoryField.PositiveStylePrompt => "Positive Style Prompt",
            PngHistoryField.NegativeStylePrompt => "Negative Style Prompt",
            PngHistoryField.NegativePrompt => "Negative Prompt",
            PngHistoryField.BaseModelType => "Base Model Type",
            PngHistoryField.UsedRandomSeed => "Used Random Seed",
            PngHistoryField.BaseSeed => "Base Seed",
            PngHistoryField.AutoClearedModelCacheBetweenModels => "Auto Cleared Model Cache",
            PngHistoryField.VaeUsedName => "VAE Used Name",
            PngHistoryField.Steps => "Steps",
            PngHistoryField.CfgScale => "CFG Scale",
            PngHistoryField.Width => "Width",
            PngHistoryField.Height => "Height",
            PngHistoryField.Seed => "Seed",
            PngHistoryField.Scheduler => "Scheduler",
            PngHistoryField.CfgRescaleMultiplier => "CFG Rescale Multiplier",
            PngHistoryField.SaveToGallery => "Save To Gallery",
            PngHistoryField.UsePromptAsStyleWhenEmpty => "Use Prompt As Style When Empty",
            PngHistoryField.ModelName => "Model Name",
            PngHistoryField.Loras => "LoRAs",
            _ => field.ToString()
        };
    }
}

public partial class PngTextChunkViewModel : ObservableObject
{
    [ObservableProperty] private string _key;
    [ObservableProperty] private string _value;
    [ObservableProperty] private string _displayValue;
    [ObservableProperty] private bool _isExpanded = true;

    public PngTextChunkViewModel(string key, string value)
    {
        _key = key;
        _value = value;
        _displayValue = FormatValue(value);
    }

    public string Preview =>
        string.IsNullOrWhiteSpace(Value)
            ? string.Empty
            : (DisplayValue.Length <= 160 ? DisplayValue : DisplayValue.Substring(0, 160) + "...");

    partial void OnValueChanged(string value)
    {
        DisplayValue = FormatValue(value);
        OnPropertyChanged(nameof(Preview));
    }

    private static string FormatValue(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return value;
        }

        var trimmed = value.Trim();
        if ((trimmed.StartsWith("{", StringComparison.Ordinal) && trimmed.EndsWith("}", StringComparison.Ordinal)) ||
            (trimmed.StartsWith("[", StringComparison.Ordinal) && trimmed.EndsWith("]", StringComparison.Ordinal)))
        {
            try
            {
                using var doc = JsonDocument.Parse(trimmed);
                return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
            }
            catch
            {
                return value;
            }
        }

        return value;
    }
}
