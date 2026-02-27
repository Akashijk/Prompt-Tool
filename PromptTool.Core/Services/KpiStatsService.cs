using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services;

public class KpiStatsService
{
    private readonly string _filePath;
    private readonly object _lock = new();
    private KpiStatsFile _stats;

    public KpiStatsService(SettingsService settings)
    {
        _filePath = Path.Combine(settings.ConfigDir, "kpi_stats.json");
        _stats = Load();
    }

    public KpiStatsFile GetSnapshot()
    {
        lock (_lock)
        {
            return Clone(_stats);
        }
    }

    public void RecordGeneration(
        InvokeAIGenerationParams? parameters,
        GenerationJobInfo? jobInfo,
        string? workflow)
    {
        if (parameters == null || parameters.Model == null) return;

        var modelName = parameters.Model.Name ?? "";
        if (string.IsNullOrWhiteSpace(modelName)) return;

        var baseModel = parameters.Model.Base ?? parameters.BaseModelType ?? "";
        var workflowLabel = string.IsNullOrWhiteSpace(workflow) ? "" : workflow.Trim();
        var key = BuildKey(modelName, baseModel, workflowLabel);

        var tokenEstimate = EstimateTokenCount(
            parameters.Prompt,
            parameters.PositiveStylePrompt,
            parameters.NegativePrompt,
            parameters.NegativeStylePrompt);

        var promptChars = EstimateCharCount(
            parameters.Prompt,
            parameters.PositiveStylePrompt,
            parameters.NegativePrompt,
            parameters.NegativeStylePrompt);

        var pixels = (long)parameters.Width * parameters.Height;
        var loraNames = parameters.Loras?
            .Where(l => l?.Lora != null && !string.IsNullOrWhiteSpace(l.Lora.Name))
            .Select(l => l.Lora.Name!)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList() ?? new List<string>();
        var loraCount = loraNames.Count;
        var loraBucket = loraCount >= 3 ? "3+" : loraCount.ToString();

        lock (_lock)
        {
            if (!_stats.Models.TryGetValue(key, out var modelStats))
            {
                modelStats = new ModelKpiStats
                {
                    Key = key,
                    ModelName = modelName,
                    BaseModel = baseModel,
                    Workflow = workflowLabel
                };
                _stats.Models[key] = modelStats;
            }

            modelStats.TotalCount++;
            modelStats.LastSeen = DateTime.UtcNow;

            if (jobInfo != null)
            {
                var status = jobInfo.Status?.ToLowerInvariant() ?? "";
                if (status == "completed")
                {
                    modelStats.SuccessCount++;
                }
                else if (status == "canceled")
                {
                    modelStats.CanceledCount++;
                }
                else if (status == "failed")
                {
                    modelStats.FailCount++;
                }

                if (jobInfo.GenerationDurationMs.HasValue)
                {
                    var duration = jobInfo.GenerationDurationMs.Value;
                    modelStats.TotalDurationMs += duration;
                    modelStats.MinDurationMs = modelStats.MinDurationMs.HasValue
                        ? Math.Min(modelStats.MinDurationMs.Value, duration)
                        : duration;
                    modelStats.MaxDurationMs = modelStats.MaxDurationMs.HasValue
                        ? Math.Max(modelStats.MaxDurationMs.Value, duration)
                        : duration;
                }

                if (jobInfo.QueueWaitMs.HasValue)
                {
                    modelStats.TotalQueueWaitMs += jobInfo.QueueWaitMs.Value;
                }
            }
            else
            {
                modelStats.SuccessCount++;
            }

            modelStats.TotalTokens += tokenEstimate;
            modelStats.TotalPromptChars += promptChars;
            modelStats.TotalPixels += pixels;

            var loraBucketKey = BuildKey("lora_count", loraBucket, workflowLabel);
            if (!_stats.LoraCountBuckets.TryGetValue(loraBucketKey, out var bucketStats))
            {
                bucketStats = new LoraCountKpiStats
                {
                    Key = loraBucketKey,
                    Workflow = workflowLabel,
                    Bucket = loraBucket
                };
                _stats.LoraCountBuckets[loraBucketKey] = bucketStats;
            }
            bucketStats.TotalCount++;
            bucketStats.TotalTokens += tokenEstimate;
            if (jobInfo?.GenerationDurationMs is { } bucketDuration)
            {
                bucketStats.TotalDurationMs += bucketDuration;
            }
            bucketStats.LastSeen = DateTime.UtcNow;

            foreach (var loraName in loraNames)
            {
                var loraKey = BuildKey("lora", loraName, workflowLabel);
                if (!_stats.Loras.TryGetValue(loraKey, out var loraStats))
                {
                    loraStats = new LoraKpiStats
                    {
                        Key = loraKey,
                        LoraName = loraName,
                        Workflow = workflowLabel
                    };
                    _stats.Loras[loraKey] = loraStats;
                }
                loraStats.TotalCount++;
                loraStats.TotalTokens += tokenEstimate;
                if (jobInfo?.GenerationDurationMs is { } loraDuration)
                {
                    loraStats.TotalDurationMs += loraDuration;
                }
                loraStats.LastSeen = DateTime.UtcNow;
            }

            _stats.UpdatedAt = DateTime.UtcNow;
            Save(_stats);
        }
    }

    private KpiStatsFile Load()
    {
        try
        {
            if (!File.Exists(_filePath))
            {
                return new KpiStatsFile();
            }

            var json = File.ReadAllText(_filePath);
            if (string.IsNullOrWhiteSpace(json))
            {
                return new KpiStatsFile();
            }

            return JsonSerializer.Deserialize<KpiStatsFile>(json) ?? new KpiStatsFile();
        }
        catch
        {
            return new KpiStatsFile();
        }
    }

    private void Save(KpiStatsFile stats)
    {
        try
        {
            var json = JsonSerializer.Serialize(stats, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_filePath, json);
        }
        catch
        {
            // Ignore save failures
        }
    }

    private static string BuildKey(string modelName, string baseModel, string workflow)
    {
        return $"{workflow}|{baseModel}|{modelName}".Trim();
    }

    private static int EstimateTokenCount(params string?[] parts)
    {
        var text = string.Join(" ", parts.Where(p => !string.IsNullOrWhiteSpace(p))).Trim();
        if (string.IsNullOrWhiteSpace(text)) return 0;
        return text.Split((char[])null!, StringSplitOptions.RemoveEmptyEntries).Length;
    }

    private static int EstimateCharCount(params string?[] parts)
    {
        var text = string.Join(" ", parts.Where(p => !string.IsNullOrWhiteSpace(p))).Trim();
        return text.Length;
    }

    private static KpiStatsFile Clone(KpiStatsFile stats)
    {
        var clone = new KpiStatsFile { UpdatedAt = stats.UpdatedAt };
        foreach (var kvp in stats.Models)
        {
            var s = kvp.Value;
            clone.Models[kvp.Key] = new ModelKpiStats
            {
                Key = s.Key,
                ModelName = s.ModelName,
                BaseModel = s.BaseModel,
                Workflow = s.Workflow,
                TotalCount = s.TotalCount,
                SuccessCount = s.SuccessCount,
                FailCount = s.FailCount,
                CanceledCount = s.CanceledCount,
                TotalDurationMs = s.TotalDurationMs,
                TotalQueueWaitMs = s.TotalQueueWaitMs,
                TotalTokens = s.TotalTokens,
                TotalPromptChars = s.TotalPromptChars,
                TotalPixels = s.TotalPixels,
                MinDurationMs = s.MinDurationMs,
                MaxDurationMs = s.MaxDurationMs,
                LastSeen = s.LastSeen
            };
        }
        foreach (var kvp in stats.Loras)
        {
            var s = kvp.Value;
            clone.Loras[kvp.Key] = new LoraKpiStats
            {
                Key = s.Key,
                LoraName = s.LoraName,
                Workflow = s.Workflow,
                TotalCount = s.TotalCount,
                TotalDurationMs = s.TotalDurationMs,
                TotalTokens = s.TotalTokens,
                LastSeen = s.LastSeen
            };
        }
        foreach (var kvp in stats.LoraCountBuckets)
        {
            var s = kvp.Value;
            clone.LoraCountBuckets[kvp.Key] = new LoraCountKpiStats
            {
                Key = s.Key,
                Workflow = s.Workflow,
                Bucket = s.Bucket,
                TotalCount = s.TotalCount,
                TotalDurationMs = s.TotalDurationMs,
                TotalTokens = s.TotalTokens,
                LastSeen = s.LastSeen
            };
        }
        return clone;
    }
}
