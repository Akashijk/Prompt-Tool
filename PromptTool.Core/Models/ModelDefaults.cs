namespace PromptTool.Core.Models;

public class ModelDefaults
{
    public string ModelName { get; set; } = string.Empty;
    public string Sampler { get; set; } = "euler_ancestral";
    public int Steps { get; set; } = 30;
    public double CfgScale { get; set; } = 7.0;
    public double CfgRescaleMultiplier { get; set; } = 0.0;
    public int Width { get; set; } = 512;
    public int Height { get; set; } = 512;
    public string PositivePromptPrefix { get; set; } = string.Empty;
    public string NegativePromptPrefix { get; set; } = string.Empty;
    public double? LoraWeight { get; set; }
    // Add other model-specific default parameters as needed
}
