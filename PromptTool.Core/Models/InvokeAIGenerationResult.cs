namespace PromptTool.Core.Models;

using PromptTool.Core.Clients.InvokeAI; // For InvokeAIModel

public record InvokeAIGenerationResult
{
    public int ItemId { get; init; }
    public byte[] ImageBytes { get; init; } = [];
    public string ImageName { get; init; } = "";
    public GenerationParams GenerationParams { get; init; } = new();
}

public record GenerationParams
{
    public string Scheduler { get; init; } = "";
    public InvokeAIModel? Vae { get; init; }
}
