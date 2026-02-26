using System.Collections.Generic;
using PromptTool.Core.Clients.InvokeAI;

namespace PromptTool.Core.Models;

public class InvokeAIGenerationParams
{
    public string Prompt { get; set; } = string.Empty;
    public string? PositiveStylePrompt { get; set; }
    public string? NegativeStylePrompt { get; set; }
    public string? NegativePrompt { get; set; }
    public string? BaseModelType { get; set; }
    public bool UsedRandomSeed { get; set; }
    public int BaseSeed { get; set; }
    public bool AutoClearedModelCacheBetweenModels { get; set; }
    public string? VaeUsedName { get; set; }
    public string? VaePrecision { get; set; }
    public bool? UseCpuNoise { get; set; }
    public bool? L2iFp32 { get; set; }
    public bool? UseAutoCfgRescale { get; set; }
    public InvokeAIModel? Model { get; set; }
    public int Steps { get; set; } = 30;
    public double CfgScale { get; set; } = 7.0;
    public int Width { get; set; } = 1024;
    public int Height { get; set; } = 1024;
    public int Seed { get; set; } = -1; // -1 for random
    public string Scheduler { get; set; } = "dpmpp_2m_k";
    public double CfgRescaleMultiplier { get; set; } = 0.0;
    public List<LoraParameter> Loras { get; set; } = new();
    public bool SaveToGallery { get; set; }
    public bool UsePromptAsStyleWhenEmpty { get; set; } = true;
}

public class LoraParameter
{
    public InvokeAIModel Lora { get; set; } = new();
    public double Weight { get; set; } = 1.0;
}
