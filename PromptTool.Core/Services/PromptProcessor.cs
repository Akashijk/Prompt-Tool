using PromptTool.Core.Clients;

namespace PromptTool.Core.Services;

public sealed class PromptProcessor
{
    private readonly OllamaClient _ollama;

    public PromptProcessor(OllamaClient ollama)
    {
        _ollama = ollama;
    }

    public Task<string> GenerateAsync(string prompt, string model)
    {
        return _ollama.GenerateAsync(model, prompt);
    }

}
