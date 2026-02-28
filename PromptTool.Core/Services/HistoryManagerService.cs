using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services;

public class HistoryManagerService
{
    private static readonly string[] LegacyHistoryMarkers =
    {
        "original_prompt",
        "processed_prompt",
        "workflow_source",
        "cover_image",
        "original_images",
        "image_file_path",
        "image_path"
    };
    private readonly SettingsService _settings;
    private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNameCaseInsensitive = true };
    private List<HistoryEntry> _historyEntries = new();

    public HistoryManagerService(SettingsService settings)
    {
        _settings = settings;
        EnsureDirectories();
        LoadHistory();
    }

    public string GetHistoryDir() => _settings.GetHistoryDir();

    public void SaveChanges()
    {
        SaveHistory();
    }

    private void LoadHistory()
    {
        MigrateLegacyRootHistoryIfNeeded();

        var historyDir = _settings.GetHistoryDir();
        var jsonlPath = Path.Combine(historyDir, "history.jsonl");
        var jsonPath = Path.Combine(historyDir, "history.json");

        var hasJson = File.Exists(jsonPath);
        if (hasJson)
        {
            if (TryLoadJson(jsonPath))
            {
                return;
            }
        }

        if (File.Exists(jsonlPath))
        {
            _historyEntries = LoadFromJsonl(jsonlPath);
            SaveHistory();
            return;
        }

        _historyEntries = new List<HistoryEntry>();
    }

    private bool TryLoadJson(string path)
    {
        try
        {
            var json = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            if (IsLegacyHistoryArray(doc.RootElement))
            {
                _historyEntries = doc.RootElement
                    .EnumerateArray()
                    .Select(MapLegacyEntry)
                    .ToList();
                SaveHistory();
                return true;
            }

            _historyEntries = JsonSerializer.Deserialize<List<HistoryEntry>>(json, _jsonOptions) ?? new List<HistoryEntry>();
            return true;
        }
        catch (JsonException ex)
        {
            if (_settings.Settings.Verbose) Console.Error.WriteLine($"Error loading history: {ex.Message}");
            return false;
        }
        catch (Exception ex)
        {
            if (_settings.Settings.Verbose) Console.Error.WriteLine($"Error loading history: {ex.Message}");
            return false;
        }
    }

    private static bool IsLegacyHistoryArray(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        foreach (var entry in root.EnumerateArray())
        {
            if (entry.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            foreach (var marker in LegacyHistoryMarkers)
            {
                if (entry.TryGetPropertyIgnoreCase(marker, out _))
                {
                    return true;
                }
            }
        }

        return false;
    }

    private void MigrateLegacyRootHistoryIfNeeded()
    {
        try
        {
            var baseHistoryDir = _settings.Settings.HistoryDir;
            var workflowHistoryDir = _settings.GetHistoryDir();
            if (string.IsNullOrWhiteSpace(baseHistoryDir) || string.IsNullOrWhiteSpace(workflowHistoryDir))
            {
                return;
            }

            var baseFullPath = Path.GetFullPath(baseHistoryDir);
            var workflowFullPath = Path.GetFullPath(workflowHistoryDir);
            if (string.Equals(baseFullPath, workflowFullPath, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            var rootJsonPath = Path.Combine(baseFullPath, "history.json");
            var rootJsonlPath = Path.Combine(baseFullPath, "history.jsonl");
            var workflowJsonPath = Path.Combine(workflowFullPath, "history.json");
            var workflowJsonlPath = Path.Combine(workflowFullPath, "history.jsonl");

            var hasRootHistory = File.Exists(rootJsonPath) || File.Exists(rootJsonlPath);
            var hasWorkflowHistory = File.Exists(workflowJsonPath) || File.Exists(workflowJsonlPath);
            if (!hasRootHistory || hasWorkflowHistory)
            {
                return;
            }

            Directory.CreateDirectory(workflowFullPath);
            PromoteLegacyRootFile(rootJsonPath, workflowJsonPath);
            PromoteLegacyRootFile(rootJsonlPath, workflowJsonlPath);

            var rootImagesDir = Path.Combine(baseFullPath, "images");
            var workflowImagesDir = Path.Combine(workflowFullPath, "images");
            PromoteLegacyRootDirectory(rootImagesDir, workflowImagesDir);
        }
        catch (Exception ex)
        {
            if (_settings.Settings.Verbose)
            {
                Console.Error.WriteLine($"Error migrating legacy root history: {ex.Message}");
            }
        }
    }

    private static void PromoteLegacyRootFile(string sourcePath, string targetPath)
    {
        if (!File.Exists(sourcePath))
        {
            return;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(targetPath) ?? Path.GetTempPath());
        if (!File.Exists(targetPath))
        {
            File.Move(sourcePath, targetPath);
        }
    }

    private static void PromoteLegacyRootDirectory(string sourceDir, string targetDir)
    {
        if (!Directory.Exists(sourceDir))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(sourceDir, "*", SearchOption.AllDirectories).ToList())
        {
            var relative = Path.GetRelativePath(sourceDir, file);
            var targetPath = Path.Combine(targetDir, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(targetPath) ?? targetDir);
            if (!File.Exists(targetPath))
            {
                File.Move(file, targetPath);
            }
        }

        try
        {
            Directory.Delete(sourceDir, recursive: true);
        }
        catch
        {
            // Best effort cleanup only.
        }
    }

    private List<HistoryEntry> LoadFromJsonl(string path)
    {
        var results = new List<HistoryEntry>();
        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            try
            {
                using var doc = JsonDocument.Parse(line, new JsonDocumentOptions { AllowTrailingCommas = true });
                var entry = MapLegacyEntry(doc.RootElement);
                results.Add(entry);
            }
            catch (Exception ex)
            {
                if (_settings.Settings.Verbose) Console.Error.WriteLine($"Error parsing history line: {ex.Message}");
            }
        }
        return results;
    }

    private HistoryEntry MapLegacyEntry(JsonElement element)
    {
        var historyDir = _settings.GetHistoryDir();
        var entryId = element.GetPropertyOrDefault("id") ?? Guid.NewGuid().ToString();

        var entry = new HistoryEntry
        {
            Id = entryId,
            OriginalPrompt = element.GetPropertyOrDefault("original_prompt") ?? element.GetPropertyOrDefault("original") ?? string.Empty,
            ProcessedPrompt = element.GetPropertyOrDefault("prompt") ?? element.GetPropertyOrDefault("processed_prompt") ?? string.Empty,
            TemplateName = element.GetPropertyOrDefault("template_name"),
            Status = element.GetPropertyOrDefault("status"),
            Workflow = element.GetPropertyOrDefault("workflow_source"),
            EnhancedPrompt = element.GetPropertyOrDefault("enhanced_prompt") ??
                             (element.TryGetProperty("enhanced", out var enh) ? enh.GetPropertyOrDefault("prompt") : null),
            CoverImagePath = element.GetPropertyOrDefault("cover_image") ?? element.GetPropertyOrDefault("cover_image_path"),
            IsFavorite = element.GetPropertyOrDefaultBool("favorite"),
        };

        if (element.TryGetPropertyIgnoreCase("timestamp", out var tsProp) && tsProp.ValueKind == JsonValueKind.String && DateTime.TryParse(tsProp.GetString(), out var ts))
        {
            entry.Timestamp = ts;
        }

        // Gather images from original/enhanced/variations
        if (element.TryGetPropertyIgnoreCase("original_images", out var originals) && originals.ValueKind == JsonValueKind.Array)
        {
            foreach (var img in originals.EnumerateArray())
            {
                entry.Images.Add(MapLegacyImage(img, "Original", entry.OriginalPrompt, entryId, historyDir));
            }
        }

        if (element.TryGetPropertyIgnoreCase("enhanced", out var enhanced))
        {
            var enhancedPrompt = enhanced.GetPropertyOrDefault("prompt");
            if (enhanced.TryGetPropertyIgnoreCase("images", out var enhImages) && enhImages.ValueKind == JsonValueKind.Array)
            {
                foreach (var img in enhImages.EnumerateArray())
                {
                    entry.Images.Add(MapLegacyImage(img, "Enhanced", enhancedPrompt, entryId, historyDir));
                }
            }
        }

        if (element.TryGetPropertyIgnoreCase("variations", out var variations) && variations.ValueKind == JsonValueKind.Object)
        {
            entry.VariationPrompts = new Dictionary<string, string>();
            foreach (var kvp in variations.EnumerateObject())
            {
                var varName = kvp.Name;
                var varObj = kvp.Value;
                var varPrompt = varObj.GetPropertyOrDefault("prompt");
                if (varPrompt != null)
                {
                    entry.VariationPrompts[varName] = varPrompt;
                }

                if (varObj.TryGetPropertyIgnoreCase("images", out var varImages) && varImages.ValueKind == JsonValueKind.Array)
                {
                    foreach (var img in varImages.EnumerateArray())
                    {
                        entry.Images.Add(MapLegacyImage(img, $"Variation:{varName}", varPrompt, entryId, historyDir));
                    }
                }
            }
        }

        // Some legacy records may have a flat "images" list
        if (element.TryGetPropertyIgnoreCase("images", out var flatImages) && flatImages.ValueKind == JsonValueKind.Array)
        {
            foreach (var img in flatImages.EnumerateArray())
            {
                entry.Images.Add(MapLegacyImage(img, "Image", entry.ProcessedPrompt ?? entry.OriginalPrompt, entryId, historyDir));
            }
        }

        // Fallback single image path fields
        var fallbackPath = element.GetPropertyOrDefault("image_path") ?? element.GetPropertyOrDefault("image_file_path");
        if (!string.IsNullOrWhiteSpace(fallbackPath) && !entry.Images.Any())
        {
            entry.Images.Add(new HistoryImage
            {
                ImagePath = NormalizeIncomingPath(fallbackPath, historyDir, entryId),
                Prompt = entry.ProcessedPrompt ?? entry.OriginalPrompt,
                PromptType = "Generated",
                IsFavorite = entry.IsFavorite
            });
        }

        // Ensure cover image is also tracked as an image if nothing else exists
        if (entry.Images.Count == 0 && !string.IsNullOrWhiteSpace(entry.CoverImagePath))
        {
            entry.Images.Add(new HistoryImage
            {
                ImagePath = NormalizeIncomingPath(entry.CoverImagePath, historyDir, entryId),
                Prompt = entry.ProcessedPrompt ?? entry.OriginalPrompt,
                PromptType = "Cover",
                IsFavorite = entry.IsFavorite
            });
        }

        // Preserve favorite if any image is favorited
        if (entry.Images.Any(i => i.IsFavorite))
        {
            entry.IsFavorite = true;
        }

        return entry;
    }

    private HistoryImage MapLegacyImage(JsonElement img, string promptType, string? prompt, string entryId, string historyDir)
    {
        var path = img.GetPropertyOrDefault("image_path") ?? img.GetPropertyOrDefault("path");
        var genParams = img.TryGetPropertyIgnoreCase("generation_params", out var gp) ? gp.GetRawText() : null;
        var genGraph = img.TryGetPropertyIgnoreCase("generation_graph", out var gg) ? gg.GetRawText() : null;
        var explicitPromptType = img.GetPropertyOrDefault("prompt_type");
        var explicitPrompt = img.GetPropertyOrDefault("prompt");
        var aestheticScore = img.GetPropertyOrDefaultDouble("aesthetic_score");
        if (aestheticScore.HasValue && _settings.Settings.Verbose)
        {
            Console.WriteLine($"[History Load] Found aesthetic_score: {aestheticScore.Value}");
        }
        return new HistoryImage
        {
            ImagePath = NormalizeIncomingPath(path, historyDir, entryId),
            GenerationParamsJson = genParams,
            GenerationGraphJson = genGraph,
            IsFavorite = img.GetPropertyOrDefaultBool("is_favorite"),
            PromptType = string.IsNullOrWhiteSpace(explicitPromptType) ? promptType : explicitPromptType,
            Prompt = string.IsNullOrWhiteSpace(explicitPrompt) ? prompt : explicitPrompt,
            AestheticScore = aestheticScore,
            AestheticScoreModel = img.GetPropertyOrDefault("aesthetic_score_model"),
            AestheticScoreTimestamp = img.GetPropertyOrDefaultDateTime("aesthetic_score_at"),
            AestheticScoreMs = img.GetPropertyOrDefaultInt("aesthetic_score_ms"),
            GenerationDurationMs = img.GetPropertyOrDefaultInt("generation_duration_ms"),
            QueueWaitMs = img.GetPropertyOrDefaultInt("queue_wait_ms"),
            TotalDurationMs = img.GetPropertyOrDefaultInt("total_duration_ms"),
            GenerationStatus = img.GetPropertyOrDefault("generation_status"),
            ErrorType = img.GetPropertyOrDefault("error_type"),
            ErrorMessage = img.GetPropertyOrDefault("error_message"),
            ErrorTraceback = img.GetPropertyOrDefault("error_traceback")
        };
    }

    private string? NormalizeIncomingPath(string? path, string historyDir, string entryId)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        var normalized = path.Replace('\\', Path.DirectorySeparatorChar).Replace('/', Path.DirectorySeparatorChar);

        if (Path.IsPathRooted(normalized))
        {
            var relative = Path.GetRelativePath(historyDir, normalized);
            return relative.StartsWith("..", StringComparison.Ordinal) ? normalized : relative;
        }

        // Ensure images live under images/<entryId>/filename.png for consistency
        var parts = normalized.Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 3 || !parts[0].Equals("images", StringComparison.OrdinalIgnoreCase))
        {
            var fileName = Path.GetFileName(normalized);
            return Path.Combine("images", entryId, fileName);
        }

        return normalized;
    }

    public void SaveHistory() 
    {
        try
        {
            var historyDir = _settings.GetHistoryDir();
            Directory.CreateDirectory(historyDir);

            var jsonPath = Path.Combine(historyDir, "history.json");
            var json = JsonSerializer.Serialize(_historyEntries, new JsonSerializerOptions { WriteIndented = true });
            if (_settings.Settings.Verbose) Console.WriteLine($"[History Save] JSON backup: {json}");
            File.WriteAllText(jsonPath, json);

            var jsonlPath = Path.Combine(historyDir, "history.jsonl");
            if (File.Exists(jsonlPath))
            {
                File.Delete(jsonlPath);
            }
        }
        catch (Exception ex)
        {
            if (_settings.Settings.Verbose) Console.Error.WriteLine($"Error saving history: {ex.Message}");
        }
    }

    private HistoryEntryDto ToLegacyDto(HistoryEntry entry)
    {
        var entryId = string.IsNullOrWhiteSpace(entry.Id) ? Guid.NewGuid().ToString() : entry.Id;
        entry.Id = entryId;

        var cover = entry.CoverImagePath
                    ?? entry.Images.FirstOrDefault()?.ImagePath
                    ?? entry.ImageFilePath;

        var originalImages = new List<HistoryImageDto>();
        var enhancedImages = new List<HistoryImageDto>();
        var variationGroups = new Dictionary<string, List<HistoryImageDto>>(StringComparer.OrdinalIgnoreCase);

        foreach (var img in entry.Images)
        {
            var pt = img.PromptType ?? string.Empty;
            if (pt.StartsWith("Enhanced", StringComparison.OrdinalIgnoreCase))
            {
                enhancedImages.Add(ToLegacyImage(entryId, img));
            }
            else if (pt.StartsWith("Variation:", StringComparison.OrdinalIgnoreCase))
            {
                var key = pt.Split(':', 2).ElementAtOrDefault(1)?.Trim() ?? "variant";
                if (!variationGroups.ContainsKey(key)) variationGroups[key] = new List<HistoryImageDto>();
                variationGroups[key].Add(ToLegacyImage(entryId, img));
            }
            else
            {
                // Catch-all for Original, Generated, Regenerated, Upscale, or unknown types
                originalImages.Add(ToLegacyImage(entryId, img));
            }
        }
        
        if (entry.VariationPrompts != null)
        {
            foreach (var key in entry.VariationPrompts.Keys)
            {
                if (!variationGroups.ContainsKey(key))
                {
                    variationGroups[key] = new List<HistoryImageDto>();
                }
            }
        }

        var variations = variationGroups.ToDictionary(
            kvp => kvp.Key,
            kvp => new VariationDto
            {
                Prompt = entry.VariationPrompts != null && entry.VariationPrompts.TryGetValue(kvp.Key, out var vp) ? vp : null,
                Images = kvp.Value
            },
            StringComparer.OrdinalIgnoreCase);

        var dto = new HistoryEntryDto
        {
            Id = entryId,
            Timestamp = entry.Timestamp.ToString("o"),
            Original_Prompt = entry.OriginalPrompt ?? string.Empty,
            Prompt = entry.ProcessedPrompt ?? string.Empty,
            Template_Name = entry.TemplateName,
            Status = entry.Status ?? (entry.Images.Any() ? "generated" : "text_only"),
            Workflow_Source = entry.Workflow,
            Favorite = entry.IsFavorite || entry.Images.Any(i => i.IsFavorite),
            Cover_Image = cover,
            Original_Images = originalImages,
            Image_File_Path = entry.ImageFilePath // Legacy field
        };

        if (!string.IsNullOrWhiteSpace(entry.EnhancedPrompt) || enhancedImages.Any())
        {
            dto.Enhanced = new EnhancedDto
            {
                Prompt = entry.EnhancedPrompt,
                Images = enhancedImages
            };
        }

        if (variations.Any())
        {
            dto.Variations = variations;
        }

        return dto;
    }

    private HistoryImageDto ToLegacyImage(string entryId, HistoryImage image)
    {
        var path = NormalizeForSave(image.ImagePath, entryId);
        object? graphObject = null;
        if (!string.IsNullOrWhiteSpace(image.GenerationGraphJson))
        {
            try
            {
                graphObject = JsonSerializer.Deserialize<JsonElement>(image.GenerationGraphJson);
            }
            catch
            {
                graphObject = image.GenerationGraphJson;
            }
        }
        return new HistoryImageDto
        {
            Image_Path = path, // Renamed from ImagePath
            Generation_Params = GetGenerationParamsObject(image), // Renamed from generation_params
            Generation_Graph = graphObject,
            Is_Favorite = image.IsFavorite, // Renamed from is_favorite
            Prompt_Type = image.PromptType, // Renamed from PromptType
            Prompt = image.Prompt,
            Aesthetic_Score = image.AestheticScore, // Renamed from AestheticScore
            Aesthetic_Score_Model = image.AestheticScoreModel, // Renamed from AestheticScoreModel
            Aesthetic_Score_At = image.AestheticScoreTimestamp?.ToString("o"), // Renamed from AestheticScoreTimestamp
            Aesthetic_Score_Ms = image.AestheticScoreMs, // Renamed from AestheticScoreMs
            Generation_Duration_Ms = image.GenerationDurationMs,
            Queue_Wait_Ms = image.QueueWaitMs,
            Total_Duration_Ms = image.TotalDurationMs,
            Generation_Status = image.GenerationStatus,
            Error_Type = image.ErrorType,
            Error_Message = image.ErrorMessage,
            Error_Traceback = image.ErrorTraceback
        };
    }

    private object? GetGenerationParamsObject(HistoryImage image)
    {
        if (!string.IsNullOrWhiteSpace(image.GenerationParamsJson))
        {
            try
            {
                return JsonSerializer.Deserialize<JsonElement>(image.GenerationParamsJson);
            }
            catch
            {
                return image.GenerationParamsJson;
            }
        }

        if (image.GenerationParams != null)
        {
            try
            {
                return JsonSerializer.Deserialize<JsonElement>(JsonSerializer.Serialize(image.GenerationParams));
            }
            catch
            {
                return image.GenerationParams;
            }
        }

        return null;
    }

    private string? NormalizeForSave(string? path, string entryId)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        var historyDir = _settings.GetHistoryDir();
        var normalized = path.Replace('\\', Path.DirectorySeparatorChar).Replace('/', Path.DirectorySeparatorChar);
        if (Path.IsPathRooted(normalized))
        {
            var relative = Path.GetRelativePath(historyDir, normalized);
            return relative.StartsWith("..", StringComparison.Ordinal) ? normalized : relative;
        }
        // Ensure the image is stored in the entry folder
        var fileName = Path.GetFileName(normalized);
        return Path.Combine("images", entryId, fileName);
    }

    public void AddEntry(HistoryEntry entry)
    {
        EnsureDirectories();
        HydrateImages(entry);
        if (entry.ImageParameters == null && entry.Images.FirstOrDefault()?.GenerationParams != null)
        {
            entry.ImageParameters = entry.Images.First().GenerationParams;
        }
        if (string.IsNullOrWhiteSpace(entry.InvokeAIModel))
        {
            entry.InvokeAIModel = entry.ImageParameters?.Model?.Name ?? entry.Images.FirstOrDefault()?.GenerationParams?.Model?.Name;
        }
        if (string.IsNullOrWhiteSpace(entry.CoverImagePath))
        {
            entry.CoverImagePath = entry.Images.FirstOrDefault()?.ImagePath;
        }
        entry.Status ??= entry.Images.Any() ? "generated" : "text_only";
        _historyEntries.Add(entry);
        SaveHistory();
    }

    public HistoryEntry? UpdateEntry(HistoryEntry entry)
    {
        if (entry == null || string.IsNullOrWhiteSpace(entry.Id)) return null;
        var existing = _historyEntries.FirstOrDefault(e => string.Equals(e.Id, entry.Id, StringComparison.OrdinalIgnoreCase));
        if (existing == null) return null;

        // Preserve images but update metadata fields
        existing.OriginalPrompt = entry.OriginalPrompt ?? existing.OriginalPrompt;
        existing.ProcessedPrompt = entry.ProcessedPrompt ?? existing.ProcessedPrompt;
        existing.EnhancedPrompt = entry.EnhancedPrompt ?? existing.EnhancedPrompt;
        existing.VariationPrompts = entry.VariationPrompts ?? existing.VariationPrompts;
        existing.TemplateName = entry.TemplateName ?? existing.TemplateName;
        existing.OllamaModel = !string.IsNullOrWhiteSpace(entry.OllamaModel) ? entry.OllamaModel : existing.OllamaModel;
        existing.InvokeAIModel = !string.IsNullOrWhiteSpace(entry.InvokeAIModel) ? entry.InvokeAIModel : existing.InvokeAIModel;
        existing.Workflow = entry.Workflow ?? existing.Workflow;
        existing.ImageParameters ??= entry.ImageParameters;

        SaveHistory();
        return existing;
    }

    public void UpdateImage(string entryId, HistoryImage image, bool save = true)
    {
        var entry = _historyEntries.FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase));
        if (entry == null) return;

        var existing = entry.Images.FirstOrDefault(i => string.Equals(i.ImagePath, image.ImagePath, StringComparison.OrdinalIgnoreCase));

        if (existing == null && !string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var fileName = Path.GetFileName(image.ImagePath);
            existing = entry.Images.FirstOrDefault(i => string.Equals(Path.GetFileName(i.ImagePath), fileName, StringComparison.OrdinalIgnoreCase));
        }

        if (existing != null)
        {
            existing.IsFavorite = image.IsFavorite;
            existing.AestheticScore = image.AestheticScore;
            existing.AestheticScoreModel = image.AestheticScoreModel;
            existing.AestheticScoreTimestamp = image.AestheticScoreTimestamp;
            existing.AestheticScoreMs = image.AestheticScoreMs;
            existing.Prompt = image.Prompt;
            existing.PromptType = image.PromptType;
            existing.GenerationParams = image.GenerationParams;
            existing.GenerationParamsJson = image.GenerationParamsJson;
            existing.GenerationGraphJson = image.GenerationGraphJson;
            
            if (save) SaveHistory();
        }
    }

    public void AddEntries(IEnumerable<HistoryEntry> entries)
    {
        EnsureDirectories();
        foreach (var entry in entries)
        {
            HydrateImages(entry);
            _historyEntries.Add(entry);
        }
        SaveHistory();
    }

    public HistoryEntry? AppendImages(string entryId, IEnumerable<HistoryImage> images)
    {
        var entry = _historyEntries.FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase));
        if (entry == null) return null;

        EnsureDirectories();
        foreach (var img in images)
        {
            var copy = new HistoryImage
            {
                GenerationParams = img.GenerationParams,
                GenerationParamsJson = img.GenerationParamsJson,
                GenerationGraphJson = img.GenerationGraphJson,
                IsFavorite = img.IsFavorite,
                PromptType = img.PromptType,
                PromptTypeSuffix = img.PromptTypeSuffix,
                Prompt = img.Prompt ?? entry.ProcessedPrompt ?? entry.OriginalPrompt,
                Workflow = img.Workflow,
                ImageBytes = img.ImageBytes,
                UpscaleModel = img.UpscaleModel,
                UpscaleScale = img.UpscaleScale,
                UpscaleTileSize = img.UpscaleTileSize,
                UpscaleFitToMultipleOf8 = img.UpscaleFitToMultipleOf8,
                UpscaleSourceImagePath = img.UpscaleSourceImagePath
            };

            if (img.ImageBytes is { Length: > 0 })
            {
                copy.ImagePath = SaveImage(entry.Id, img.ImageBytes);
            }
            else if (!string.IsNullOrWhiteSpace(img.ImagePath))
            {
                copy.ImagePath = CopyImageToEntry(entry.Id, img.ImagePath);
            }

            if (copy.ImagePath != null)
            {
                entry.Images.Add(copy);
            }
        }
        var firstWithParams = entry.Images.FirstOrDefault(i => i.GenerationParams != null);
        if (entry.ImageParameters == null && firstWithParams?.GenerationParams != null)
        {
            entry.ImageParameters = firstWithParams.GenerationParams;
        }
        if (string.IsNullOrWhiteSpace(entry.InvokeAIModel) && firstWithParams?.GenerationParams?.Model?.Name is { Length: > 0 } modelName)
        {
            entry.InvokeAIModel = modelName;
        }
        if (string.IsNullOrWhiteSpace(entry.CoverImagePath))
        {
            entry.CoverImagePath = entry.Images.FirstOrDefault()?.ImagePath;
        }
        entry.Status ??= entry.Images.Any() ? "generated" : "text_only";

        SaveHistory();
        return entry;
    }

    private string? CopyImageToEntry(string entryId, string sourcePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath)) return null;

        var fullSource = Path.IsPathRooted(sourcePath)
            ? sourcePath
            : Path.Combine(_settings.GetHistoryDir(), sourcePath);

        if (!File.Exists(fullSource))
        {
            return NormalizeForSave(sourcePath, entryId);
        }

        try
        {
            var bytes = File.ReadAllBytes(fullSource);
            return SaveImage(entryId, bytes);
        }
        catch (Exception ex)
        {
            if (_settings.Settings.Verbose)
            {
                Console.Error.WriteLine($"Error copying history image {fullSource}: {ex.Message}");
            }
            return NormalizeForSave(sourcePath, entryId);
        }
    }

    private void HydrateImages(HistoryEntry entry)
    {
        var entryId = string.IsNullOrWhiteSpace(entry.Id) ? Guid.NewGuid().ToString() : entry.Id;
        entry.Id = entryId;

        // If we have transient bytes but no image records, create one.
        if (entry.GeneratedImageBytes != null && entry.GeneratedImageBytes.Length > 0 && !entry.Images.Any())
        {
            var relative = SaveImage(entryId, entry.GeneratedImageBytes);
            entry.Images.Add(new HistoryImage
            {
                ImagePath = relative,
                GenerationParams = entry.ImageParameters,
                Prompt = entry.ProcessedPrompt ?? entry.OriginalPrompt,
                PromptType = "Generated"
            });
            entry.GeneratedImageBytes = null;
        }

        // If ImageFilePath was set directly, capture it as an image
        if (!string.IsNullOrWhiteSpace(entry.ImageFilePath) && !entry.Images.Any())
        {
            entry.Images.Add(new HistoryImage
            {
                ImagePath = NormalizeForSave(entry.ImageFilePath, entryId),
                GenerationParams = entry.ImageParameters,
                Prompt = entry.ProcessedPrompt ?? entry.OriginalPrompt,
                PromptType = "Generated"
            });
            entry.ImageFilePath = null;
        }

        // Persist any inline bytes on HistoryImage records
        foreach (var img in entry.Images)
        {
            if (img.ImageBytes != null && img.ImageBytes.Length > 0)
            {
                img.ImagePath = SaveImage(entryId, img.ImageBytes);
                img.ImageBytes = null;
            }
        }
    }

    public IReadOnlyList<HistoryEntry> GetAllEntries()
    {
        return _historyEntries.AsReadOnly();
    }

    public bool HasLegacyHistory(out int missingImageFieldsCount)
    {
        missingImageFieldsCount = 0;
        var historyDir = _settings.GetHistoryDir();
        var jsonlPath = Path.Combine(historyDir, "history.jsonl");
        var jsonPath = Path.Combine(historyDir, "history.json");

        if (File.Exists(jsonlPath))
        {
            return ScanHistoryFile(jsonlPath, ref missingImageFieldsCount);
        }

        if (File.Exists(jsonPath))
        {
            return ScanHistoryFile(jsonPath, ref missingImageFieldsCount);
        }

        return false;
    }

    public bool NormalizeHistoryWithBackup(out string backupDir, out string error)
    {
        error = string.Empty;
        backupDir = string.Empty;
        try
        {
            var historyDir = _settings.GetHistoryDir();
            backupDir = Path.Combine(historyDir, "backups", DateTime.Now.ToString("yyyyMMdd_HHmmss"));
            Directory.CreateDirectory(backupDir);

            foreach (var file in Directory.EnumerateFiles(historyDir, "history*.json*"))
            {
                var dest = Path.Combine(backupDir, Path.GetFileName(file));
                File.Copy(file, dest, overwrite: true);
            }

            SaveHistory();
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
    }

    public List<FavoriteImage> GetAllFavoriteImages()
    {
        var favoriteImages = new List<FavoriteImage>();
        foreach (var entry in _historyEntries)
        {
            foreach (var image in entry.Images)
            {
                if (image.IsFavorite)
                {
                    favoriteImages.Add(new FavoriteImage(entry, image));
                }
            }
        }
        return favoriteImages;
    }


    public int PruneMissingImageEntries()
    {
        var historyDir = _settings.GetHistoryDir();
        int pruned = 0;
        foreach (var entry in _historyEntries)
        {
            var before = entry.Images.Count;
            entry.Images = entry.Images
                .Where(i =>
                {
                    var path = i.ImagePath;
                    if (string.IsNullOrWhiteSpace(path)) return false;
                    var full = Path.IsPathRooted(path) ? path : Path.Combine(historyDir, path);
                    return File.Exists(full);
                }).ToList();
            pruned += before - entry.Images.Count;
        }
        SaveHistory();
        return pruned;
    }

    public int GarbageCollectOrphanedImages()
    {
        var historyDir = _settings.GetHistoryDir();
        var imagesDir = _settings.GetHistoryImagesDir();
        if (!Directory.Exists(imagesDir)) return 0;

        var referenced = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in _historyEntries)
        {
            foreach (var img in entry.Images)
            {
                if (!string.IsNullOrWhiteSpace(img.ImagePath))
                {
                    var rel = Path.IsPathRooted(img.ImagePath)
                        ? Path.GetRelativePath(historyDir, img.ImagePath)
                        : img.ImagePath;
                    referenced.Add(rel.Replace('\\', Path.DirectorySeparatorChar));
                }
            }
        }

        int deleted = 0;
        foreach (var file in Directory.EnumerateFiles(imagesDir, "*.*", SearchOption.AllDirectories))
        {
            var rel = Path.GetRelativePath(historyDir, file).Replace('\\', Path.DirectorySeparatorChar);
            if (!referenced.Contains(rel))
            {
                try
                {
                    File.Delete(file);
                    deleted++;
                }
                catch {{ }}
            }
        }
        return deleted;
    }

    public (int EntriesCreated, int ImagesAdded) RecoverOrphanedImages()
    {
        EnsureDirectories();
        var historyDir = _settings.GetHistoryDir();
        var imagesDir = _settings.GetHistoryImagesDir();
        if (!Directory.Exists(imagesDir)) return (0, 0);

        var referenced = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in _historyEntries)
        {
            foreach (var img in entry.Images)
            {
                if (!string.IsNullOrWhiteSpace(img.ImagePath))
                {
                    var rel = Path.IsPathRooted(img.ImagePath)
                        ? Path.GetRelativePath(historyDir, img.ImagePath)
                        : img.ImagePath;
                    referenced.Add(rel.Replace('\\', Path.DirectorySeparatorChar));
                }
            }
        }

        var entryMap = _historyEntries.ToDictionary(e => e.Id, StringComparer.OrdinalIgnoreCase);
        var entriesCreated = 0;
        var imagesAdded = 0;

        foreach (var dir in Directory.EnumerateDirectories(imagesDir))
        {
            var entryId = Path.GetFileName(dir);
            if (string.IsNullOrWhiteSpace(entryId)) continue;

            if (!entryMap.TryGetValue(entryId, out var entry))
            {
                entry = new HistoryEntry
                {
                    Id = entryId,
                    Timestamp = Directory.GetLastWriteTime(dir),
                    Status = "recovered",
                    TemplateName = "Recovered",
                    OriginalPrompt = "Recovered entry",
                    ProcessedPrompt = "Recovered entry",
                    Workflow = _settings.Settings.Workflow ?? "sfw"
                };
                _historyEntries.Add(entry);
                entryMap[entryId] = entry;
                entriesCreated++;
            }

            foreach (var file in Directory.EnumerateFiles(dir))
            {
                var rel = Path.GetRelativePath(historyDir, file).Replace('\\', Path.DirectorySeparatorChar);
                if (referenced.Contains(rel)) continue;

                entry.Images.Add(new HistoryImage
                {
                    ImagePath = rel,
                    Prompt = entry.ProcessedPrompt ?? entry.OriginalPrompt,
                    PromptType = "Recovered"
                });
                referenced.Add(rel);
                imagesAdded++;
            }

            if (string.IsNullOrWhiteSpace(entry.CoverImagePath))
            {
                entry.CoverImagePath = entry.Images.FirstOrDefault()?.ImagePath;
            }
        }

        SaveHistory();
        return (entriesCreated, imagesAdded);
    }

    public bool DeleteEntry(string entryId)
    {
        var entry = _historyEntries.FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase));
        if (entry == null) return false;

        DeleteImages(entry.Images);

        _historyEntries.Remove(entry);
        SaveHistory();
        return true;
    }

    public bool DeleteImage(string entryId, string? imagePath)
    {
        if (string.IsNullOrWhiteSpace(imagePath)) return false;
        var entry = _historyEntries.FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase));
        if (entry == null) return false;

        var image = entry.Images.FirstOrDefault(i => string.Equals(i.ImagePath, imagePath, StringComparison.OrdinalIgnoreCase));
        if (image == null) return false;

        DeleteImages(new[] { image });
        entry.Images.Remove(image);

        if (string.Equals(entry.CoverImagePath, image.ImagePath, StringComparison.OrdinalIgnoreCase))
        {
            entry.CoverImagePath = entry.Images.FirstOrDefault()?.ImagePath;
        }

        if (entry.Images.Count == 0)
        {
            entry.Status = "text_only";
            entry.CoverImagePath = null;
        }

        SaveHistory();
        return true;
    }

    private void DeleteImages(IEnumerable<HistoryImage> images)
    {
        foreach (var img in images)
        {
            var path = img.ImagePath;
            if (string.IsNullOrWhiteSpace(path)) continue;
            var full = Path.IsPathRooted(path) ? path : Path.Combine(_settings.GetHistoryDir(), path);
            try
            {
                if (File.Exists(full))
                {
                    File.Delete(full);
                }
            }
            catch (Exception ex)
            {
                if (_settings.Settings.Verbose) Console.Error.WriteLine($"Error deleting image {full}: {ex.Message}");
            }
        }
    }

    public void Reload()
    {
        _historyEntries.Clear();
        LoadHistory();
    }

    private void EnsureDirectories()
    {
        var dir = _settings.GetHistoryDir();
        Directory.CreateDirectory(dir);
        Directory.CreateDirectory(_settings.GetHistoryImagesDir());
    }

    private string SaveImage(string entryId, byte[] imageBytes)
    {
        var imagesDir = Path.Combine(_settings.GetHistoryImagesDir(), entryId);
        Directory.CreateDirectory(imagesDir);
        var fileName = $"{DateTime.Now:yyyyMMdd_HHmmss}_{Guid.NewGuid():N}.png";
        var path = Path.Combine(imagesDir, fileName);
        File.WriteAllBytes(path, imageBytes);

        // Store relative path for compatibility with the Qt app
        var relativeDir = Path.Combine("images", entryId);
        return Path.Combine(relativeDir, fileName);
    }

    // DTO classes for serialization
    public class HistoryEntryDto
    {
        [JsonPropertyName("id")] public string? Id { get; set; }
        [JsonPropertyName("timestamp")] public string? Timestamp { get; set; }
        [JsonPropertyName("original_prompt")] public string? Original_Prompt { get; set; } // Renamed from OriginalPrompt
        [JsonPropertyName("prompt")] public string? Prompt { get; set; } // ProcessedPrompt
        [JsonPropertyName("template_name")] public string? Template_Name { get; set; } // Renamed from TemplateName
        [JsonPropertyName("status")] public string? Status { get; set; }
        [JsonPropertyName("workflow_source")] public string? Workflow_Source { get; set; } // Renamed from Workflow
        [JsonPropertyName("favorite")] public bool Favorite { get; set; } // Renamed from IsFavorite
        [JsonPropertyName("cover_image")] public string? Cover_Image { get; set; } // Renamed from CoverImagePath
        [JsonPropertyName("original_images")] public List<HistoryImageDto>? Original_Images { get; set; } // Renamed from originalImages
        [JsonPropertyName("enhanced")] public EnhancedDto? Enhanced { get; set; }
        [JsonPropertyName("variations")] public Dictionary<string, VariationDto>? Variations { get; set; }
        [JsonPropertyName("image_file_path")] public string? Image_File_Path { get; set; } // Legacy field
    }

    public class EnhancedDto
    {
        [JsonPropertyName("prompt")] public string? Prompt { get; set; }
        [JsonPropertyName("images")] public List<HistoryImageDto>? Images { get; set; }
    }

    public class VariationDto
    {
        [JsonPropertyName("prompt")] public string? Prompt { get; set; }
        [JsonPropertyName("images")] public List<HistoryImageDto>? Images { get; set; }
    }

    public class HistoryImageDto
    {
        [JsonPropertyName("image_path")] public string? Image_Path { get; set; } // Renamed from ImagePath
        [JsonPropertyName("generation_params")] public object? Generation_Params { get; set; } // Renamed from generation_params
        [JsonPropertyName("generation_graph")] public object? Generation_Graph { get; set; }
        [JsonPropertyName("is_favorite")] public bool Is_Favorite { get; set; } // Renamed from is_favorite
        [JsonPropertyName("prompt_type")] public string? Prompt_Type { get; set; } // Renamed from PromptType
        [JsonPropertyName("prompt")] public string? Prompt { get; set; }
        [JsonPropertyName("aesthetic_score")] public double? Aesthetic_Score { get; set; } // Renamed from AestheticScore
        [JsonPropertyName("aesthetic_score_model")] public string? Aesthetic_Score_Model { get; set; } // Renamed from AestheticScoreModel
        [JsonPropertyName("aesthetic_score_at")] public string? Aesthetic_Score_At { get; set; } // Renamed from AestheticScoreTimestamp
        [JsonPropertyName("aesthetic_score_ms")] public int? Aesthetic_Score_Ms { get; set; } // Renamed from AestheticScoreMs
        [JsonPropertyName("generation_duration_ms")] public int? Generation_Duration_Ms { get; set; }
        [JsonPropertyName("queue_wait_ms")] public int? Queue_Wait_Ms { get; set; }
        [JsonPropertyName("total_duration_ms")] public int? Total_Duration_Ms { get; set; }
        [JsonPropertyName("generation_status")] public string? Generation_Status { get; set; }
        [JsonPropertyName("error_type")] public string? Error_Type { get; set; }
        [JsonPropertyName("error_message")] public string? Error_Message { get; set; }
        [JsonPropertyName("error_traceback")] public string? Error_Traceback { get; set; }
    }

    private static bool ScanHistoryFile(string path, ref int missingCount)
    {
        try
        {
            var text = File.ReadAllText(path);
            if (string.IsNullOrWhiteSpace(text)) return false;

            var trimmed = text.TrimStart();
            if (trimmed.StartsWith("[", StringComparison.Ordinal))
            {
                using var doc = JsonDocument.Parse(text, new JsonDocumentOptions { AllowTrailingCommas = true });
                if (doc.RootElement.ValueKind != JsonValueKind.Array) return false;
                foreach (var entry in doc.RootElement.EnumerateArray())
                {
                    missingCount += CountMissingImageFields(entry);
                }
                return missingCount > 0;
            }

            foreach (var line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                using var doc = JsonDocument.Parse(line, new JsonDocumentOptions { AllowTrailingCommas = true });
                missingCount += CountMissingImageFields(doc.RootElement);
            }
            return missingCount > 0;
        }
        catch
        {
            return false;
        }
    }

    private static int CountMissingImageFields(JsonElement entry)
    {
        var count = 0;
        AddMissingFromImages(entry, "original_images", ref count);

        if (entry.TryGetPropertyIgnoreCase("enhanced", out var enhanced))
        {
            AddMissingFromImages(enhanced, "images", ref count);
        }

        if (entry.TryGetPropertyIgnoreCase("variations", out var variations) && variations.ValueKind == JsonValueKind.Object)
        {
            foreach (var variation in variations.EnumerateObject())
            {
                AddMissingFromImages(variation.Value, "images", ref count);
            }
        }

        AddMissingFromImages(entry, "images", ref count);
        return count;
    }

    private static void AddMissingFromImages(JsonElement parent, string propertyName, ref int count)
    {
        if (!parent.TryGetPropertyIgnoreCase(propertyName, out var images) || images.ValueKind != JsonValueKind.Array) return;

        foreach (var img in images.EnumerateArray())
        {
            if (img.ValueKind != JsonValueKind.Object) continue;
            var hasPromptType = img.TryGetPropertyIgnoreCase("prompt_type", out var pt) && pt.ValueKind == JsonValueKind.String;
            var hasPrompt = img.TryGetPropertyIgnoreCase("prompt", out var p) && p.ValueKind == JsonValueKind.String;
            if (!hasPromptType || !hasPrompt)
            {
                count++;
            }
        }
    }
}

internal static class JsonElementExtensions
{
    public static bool TryGetPropertyIgnoreCase(this JsonElement element, string propertyName, out JsonElement value)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            if (element.TryGetProperty(propertyName, out value)) return true;
            foreach (var prop in element.EnumerateObject())
            {
                if (string.Equals(prop.Name, propertyName, StringComparison.OrdinalIgnoreCase))
                {
                    value = prop.Value;
                    return true;
                }
            }
        }
        value = default;
        return false;
    }

    public static string? GetPropertyOrDefault(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return null;
        if (element.TryGetPropertyIgnoreCase(propertyName, out var prop) && prop.ValueKind == JsonValueKind.String)
        {
            return prop.GetString();
        }
        return null;
    }

    public static bool GetPropertyOrDefaultBool(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return false;
        if (element.TryGetPropertyIgnoreCase(propertyName, out var prop))
        {
            return prop.ValueKind switch
            {
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                JsonValueKind.String when bool.TryParse(prop.GetString(), out var b) => b,
                _ => false
            };
        }
        return false;
    }

    public static double? GetPropertyOrDefaultDouble(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return null;
        if (!element.TryGetPropertyIgnoreCase(propertyName, out var prop)) return null;
        return prop.ValueKind switch
        {
            JsonValueKind.Number when prop.TryGetDouble(out var d) => d,
            JsonValueKind.String when double.TryParse(prop.GetString(), out var ds) => ds,
            _ => null
        };
    }

    public static int? GetPropertyOrDefaultInt(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return null;
        if (!element.TryGetPropertyIgnoreCase(propertyName, out var prop)) return null;
        return prop.ValueKind switch
            {
                JsonValueKind.Number when prop.TryGetInt32(out var i) => i,
                JsonValueKind.String when int.TryParse(prop.GetString(), out var si) => si,
                _ => null
            };
        }

    public static DateTime? GetPropertyOrDefaultDateTime(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return null;
        if (!element.TryGetPropertyIgnoreCase(propertyName, out var prop)) return null;
        if (prop.ValueKind == JsonValueKind.String && DateTime.TryParse(prop.GetString(), out var dt))
        {
            return dt;
        }
        return null;
    }
}
