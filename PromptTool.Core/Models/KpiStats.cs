using System;
using System.Collections.Generic;

namespace PromptTool.Core.Models;

public class KpiStatsFile
{
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    public Dictionary<string, ModelKpiStats> Models { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, LoraKpiStats> Loras { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, LoraCountKpiStats> LoraCountBuckets { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public class ModelKpiStats
{
    public string Key { get; set; } = "";
    public string ModelName { get; set; } = "";
    public string BaseModel { get; set; } = "";
    public string Workflow { get; set; } = "";
    public long TotalCount { get; set; }
    public long SuccessCount { get; set; }
    public long FailCount { get; set; }
    public long CanceledCount { get; set; }
    public long TotalDurationMs { get; set; }
    public long TotalQueueWaitMs { get; set; }
    public long TotalTokens { get; set; }
    public long TotalPromptChars { get; set; }
    public long TotalPixels { get; set; }
    public int? MinDurationMs { get; set; }
    public int? MaxDurationMs { get; set; }
    public DateTime LastSeen { get; set; } = DateTime.UtcNow;
}

public class LoraKpiStats
{
    public string Key { get; set; } = "";
    public string LoraName { get; set; } = "";
    public string Workflow { get; set; } = "";
    public long TotalCount { get; set; }
    public long TotalDurationMs { get; set; }
    public long TotalTokens { get; set; }
    public DateTime LastSeen { get; set; } = DateTime.UtcNow;
}

public class LoraCountKpiStats
{
    public string Key { get; set; } = "";
    public string Workflow { get; set; } = "";
    public string Bucket { get; set; } = "";
    public long TotalCount { get; set; }
    public long TotalDurationMs { get; set; }
    public long TotalTokens { get; set; }
    public DateTime LastSeen { get; set; } = DateTime.UtcNow;
}
