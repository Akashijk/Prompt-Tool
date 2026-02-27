namespace PromptTool.Core.Models;

using PromptTool.Core.Clients.InvokeAI; // For InvokeAIModel

public record InvokeAIGenerationResult
{
    public int ItemId { get; init; }
    public byte[] ImageBytes { get; init; } = [];
    public string ImageName { get; init; } = "";
    public GenerationParams GenerationParams { get; init; } = new();
    public GenerationJobInfo? JobInfo { get; init; }
}

public record GenerationParams
{
    public string Scheduler { get; init; } = "";
    public InvokeAIModel? Vae { get; init; }
}

public record GenerationJobInfo
{
    public string Status { get; init; } = "";
    public string? ErrorType { get; init; }
    public string? ErrorMessage { get; init; }
    public string? ErrorTraceback { get; init; }
    public int? GenerationDurationMs { get; init; }
    public int? QueueWaitMs { get; init; }
    public int? TotalDurationMs { get; init; }
}
