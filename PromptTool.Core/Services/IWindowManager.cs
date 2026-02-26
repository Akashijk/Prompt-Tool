using System.Threading.Tasks;
using PromptTool.Core.Models;

namespace PromptTool.Core.Services;

public interface IWindowManager
{
    Task<(bool, List<InvokeAIGenerationParams>?)> ShowImageGenerationOptionsDialog(string initialPrompt, object? owner);
    void ShowImagePreview(IReadOnlyList<byte[]> imageData);
    Task<HistoryEntry?> ShowHistoryViewer(object? owner);
    void ShowFavoritesViewer(object? owner);
    void ShowWildcardManager(object? owner);
    void ShowBrainstormingWindow(object? owner);
    void ShowImageInterrogatorWindow(object? owner);
    Task<bool> ShowSettingsWindow(object? owner);
    void ShowInvokeAIModelDefaultsWindow(object? owner);
    void ShowPromptEvolverWindow(object? owner);
    void ShowSystemPromptEditorWindow(object? owner);
}
