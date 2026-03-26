using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public partial class PromptEvolverViewModel : ObservableObject
{
    private readonly OllamaClient _ollamaClient;
    private readonly HistoryManagerService? _historyManager;
    private readonly SettingsService? _settingsService;
    private static readonly Regex NumberedLineRegex = new(@"^\s*(?:\d+[\).\:-]\s*)?(?<prompt>.+?)\s*$", RegexOptions.Compiled);

    [ObservableProperty] private ObservableCollection<PromptEvolverHistoryItemViewModel> _historyPrompts = new();
    [ObservableProperty] private PromptEvolverHistoryItemViewModel? _selectedHistoryPrompt;

    [ObservableProperty] private ObservableCollection<string> _parentPrompts = new();
    [ObservableProperty] private string? _selectedParentPrompt;

    [ObservableProperty] private ObservableCollection<PromptEvolverChildItemViewModel> _childPrompts = new();
    [ObservableProperty] private PromptEvolverChildItemViewModel? _selectedChildPrompt;

    [ObservableProperty] private ObservableCollection<string> _ollamaModels = new();
    [ObservableProperty] private string? _selectedOllamaModel;

    [ObservableProperty] private int _numChildren = 5;
    [ObservableProperty] private double _temperature = 0.7;
    [ObservableProperty] private double _topP = 0.9;

    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private string _statusMessage = "Load parent prompts, then breed children.";

    public event EventHandler<string>? ChildPromptSelected;
    public event EventHandler<string>? GenerateImageRequested;
    public event EventHandler<string>? EnhancePromptRequested;

    public PromptEvolverViewModel(
        OllamaClient ollamaClient,
        HistoryManagerService? historyManager = null,
        SettingsService? settingsService = null)
    {
        _ollamaClient = ollamaClient;
        _historyManager = historyManager;
        _settingsService = settingsService;
        LoadPersistedSettings();

        _ = LoadOllamaModelsAsync();
        LoadHistoryPrompts();
    }

    [RelayCommand]
    private async Task LoadOllamaModelsAsync()
    {
        IsBusy = true;
        try
        {
            var models = await _ollamaClient.GetModelNamesAsync();
            OllamaModels = new ObservableCollection<string>(models.OrderBy(m => m, StringComparer.OrdinalIgnoreCase));
            if (OllamaModels.Count > 0)
            {
                if (!string.IsNullOrWhiteSpace(SelectedOllamaModel) &&
                    !OllamaModels.Contains(SelectedOllamaModel, StringComparer.OrdinalIgnoreCase))
                {
                    SelectedOllamaModel = null;
                }

                if (string.IsNullOrWhiteSpace(SelectedOllamaModel))
                {
                    SelectedOllamaModel = OllamaModels[0];
                }
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"Failed to load Ollama models: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    private void AddSelectedHistoryToParents()
    {
        if (SelectedHistoryPrompt == null || string.IsNullOrWhiteSpace(SelectedHistoryPrompt.Prompt))
        {
            return;
        }

        AddParentPrompt(SelectedHistoryPrompt.Prompt);
    }

    [RelayCommand]
    private void RemoveSelectedParent()
    {
        if (string.IsNullOrWhiteSpace(SelectedParentPrompt))
        {
            return;
        }

        ParentPrompts.Remove(SelectedParentPrompt);
        SelectedParentPrompt = ParentPrompts.FirstOrDefault();
    }

    [RelayCommand]
    private void ClearParents()
    {
        ParentPrompts.Clear();
        StatusMessage = "Parent list cleared.";
    }

    [RelayCommand]
    private void UseSelectedChildAsParent()
    {
        if (SelectedChildPrompt == null || string.IsNullOrWhiteSpace(SelectedChildPrompt.Prompt))
        {
            return;
        }

        if (!ParentPrompts.Contains(SelectedChildPrompt.Prompt, StringComparer.OrdinalIgnoreCase))
        {
            ParentPrompts.Add(SelectedChildPrompt.Prompt);
            StatusMessage = "Selected child added as a parent.";
        }
    }

    [RelayCommand]
    private void SendSelectedChildToEditor()
    {
        if (SelectedChildPrompt == null || string.IsNullOrWhiteSpace(SelectedChildPrompt.Prompt))
        {
            return;
        }

        ChildPromptSelected?.Invoke(this, SelectedChildPrompt.Prompt);
    }

    [RelayCommand]
    private void CopySelectedHistoryPrompt()
    {
        // Clipboard is handled in window code-behind; this exposes intent.
    }

    [RelayCommand]
    private void CopySelectedParentPrompt()
    {
        // Clipboard is handled in window code-behind; this exposes intent.
    }

    [RelayCommand]
    private void CopySelectedChildPrompt()
    {
        // Clipboard is handled in window code-behind; this exposes intent.
    }

    [RelayCommand]
    private void UseSelectedChildrenAsParents()
    {
        var selectedChildren = ChildPrompts.Where(c => c.IsSelectedForParent).ToList();
        if (selectedChildren.Count == 0 && SelectedChildPrompt != null)
        {
            selectedChildren.Add(SelectedChildPrompt);
        }

        if (selectedChildren.Count == 0)
        {
            StatusMessage = "Select one or more child prompts first.";
            return;
        }

        var added = 0;
        foreach (var child in selectedChildren)
        {
            if (string.IsNullOrWhiteSpace(child.Prompt))
            {
                continue;
            }

            if (!ParentPrompts.Contains(child.Prompt, StringComparer.OrdinalIgnoreCase))
            {
                ParentPrompts.Add(child.Prompt);
                added++;
            }
        }

        StatusMessage = added > 0
            ? $"Added {added} child prompt(s) to parents."
            : "Selected child prompts are already in parents.";
    }

    [RelayCommand]
    private void GenerateImageFromSelectedHistoryPrompt()
    {
        var prompt = SelectedHistoryPrompt?.Prompt;
        if (!string.IsNullOrWhiteSpace(prompt))
        {
            GenerateImageRequested?.Invoke(this, prompt);
        }
    }

    [RelayCommand]
    private void EnhanceSelectedHistoryPrompt()
    {
        var prompt = SelectedHistoryPrompt?.Prompt;
        if (!string.IsNullOrWhiteSpace(prompt))
        {
            EnhancePromptRequested?.Invoke(this, prompt);
        }
    }

    [RelayCommand]
    private void GenerateImageFromSelectedChildPrompt()
    {
        if (SelectedChildPrompt != null && !string.IsNullOrWhiteSpace(SelectedChildPrompt.Prompt))
        {
            GenerateImageRequested?.Invoke(this, SelectedChildPrompt.Prompt);
        }
    }

    [RelayCommand]
    private void EnhanceSelectedChildPrompt()
    {
        if (SelectedChildPrompt != null && !string.IsNullOrWhiteSpace(SelectedChildPrompt.Prompt))
        {
            EnhancePromptRequested?.Invoke(this, SelectedChildPrompt.Prompt);
        }
    }

    [RelayCommand]
    private async Task BreedPromptsAsync()
    {
        if (ParentPrompts.Count < 2)
        {
            StatusMessage = "Add at least two parent prompts.";
            return;
        }

        if (string.IsNullOrWhiteSpace(SelectedOllamaModel))
        {
            StatusMessage = "Select an Ollama model first.";
            return;
        }

        var childCount = Math.Clamp(NumChildren, 1, 20);
        IsBusy = true;
        StatusMessage = "Breeding prompts with AI...";
        try
        {
            var template = LoadBreedPromptTemplate();
            var parentPromptsStr = string.Join("\n", ParentPrompts.Select((p, i) => $"Parent {i + 1}: {p}"));
            var fullPrompt = template
                .Replace("{parent_prompts_str}", parentPromptsStr, StringComparison.Ordinal)
                .Replace("{num_children}", childCount.ToString(), StringComparison.Ordinal);

            var raw = await _ollamaClient.GenerateAsync(
                SelectedOllamaModel,
                fullPrompt,
                temperature: Temperature,
                topP: TopP);

            var children = ParseChildPrompts(raw, childCount);
            ChildPrompts = new ObservableCollection<PromptEvolverChildItemViewModel>(
                children.Select(prompt => new PromptEvolverChildItemViewModel(prompt)));
            SelectedChildPrompt = ChildPrompts.FirstOrDefault();
            StatusMessage = ChildPrompts.Count == 0
                ? "No child prompts were returned."
                : $"Generated {ChildPrompts.Count} child prompt(s).";
        }
        catch (Exception ex)
        {
            StatusMessage = $"Prompt breeding failed: {ex.Message}";
            ChildPrompts.Clear();
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    private void AddSelectedChildToParents()
    {
        UseSelectedChildAsParent();
    }

    public void AddParentPrompt(string? prompt)
    {
        if (string.IsNullOrWhiteSpace(prompt))
        {
            return;
        }

        if (!ParentPrompts.Contains(prompt, StringComparer.OrdinalIgnoreCase))
        {
            ParentPrompts.Add(prompt);
            StatusMessage = $"Added parent ({ParentPrompts.Count}).";
        }
    }

    public async Task PersistSettingsAsync()
    {
        if (_settingsService == null)
        {
            return;
        }

        var settings = _settingsService.Settings;
        settings.PromptEvolverModel = SelectedOllamaModel ?? string.Empty;
        settings.PromptEvolverNumChildren = Math.Clamp(NumChildren, 1, 20);
        settings.PromptEvolverTemperature = Math.Clamp(Temperature, 0, 2);
        settings.PromptEvolverTopP = Math.Clamp(TopP, 0, 1);
        await _settingsService.SaveSettingsAsync(settings);
    }

    private void LoadHistoryPrompts()
    {
        if (_historyManager == null)
        {
            HistoryPrompts = new ObservableCollection<PromptEvolverHistoryItemViewModel>();
            return;
        }

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var items = new List<PromptEvolverHistoryItemViewModel>();
        foreach (var entry in _historyManager.GetAllEntries().OrderByDescending(e => e.Timestamp))
        {
            foreach (var image in entry.Images)
            {
                var prompt = image.Prompt
                             ?? image.GenerationParams?.Prompt
                             ?? entry.ProcessedPrompt
                             ?? entry.OriginalPrompt;
                if (string.IsNullOrWhiteSpace(prompt)) continue;
                if (!seen.Add(prompt)) continue;

                var model = image.GenerationParams?.Model?.Name
                            ?? entry.InvokeAIModel
                            ?? "(unknown)";
                var imagePath = ResolveImagePath(_historyManager.GetHistoryDir(), image.ImagePath);
                items.Add(new PromptEvolverHistoryItemViewModel(
                    prompt,
                    model,
                    entry.Timestamp,
                    imagePath,
                    TryLoadThumbnail(imagePath)));
                break;
            }

            if (items.Count >= 120)
            {
                break;
            }
        }

        HistoryPrompts = new ObservableCollection<PromptEvolverHistoryItemViewModel>(items);
        SelectedHistoryPrompt = HistoryPrompts.FirstOrDefault();
    }

    private static string LoadBreedPromptTemplate()
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "system_prompts", "ai_tasks", "breed_prompts.txt"),
            Path.Combine(AppContext.BaseDirectory, "..", "system_prompts", "ai_tasks", "breed_prompts.txt"),
            Path.Combine(AppContext.BaseDirectory, "..", "..", "system_prompts", "ai_tasks", "breed_prompts.txt"),
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "system_prompts", "ai_tasks", "breed_prompts.txt"),
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "system_prompts", "ai_tasks", "breed_prompts.txt"),
            Path.Combine(Directory.GetCurrentDirectory(), "system_prompts", "ai_tasks", "breed_prompts.txt")
        }
        .Select(Path.GetFullPath)
        .Distinct(StringComparer.OrdinalIgnoreCase);

        foreach (var path in candidates)
        {
            if (File.Exists(path))
            {
                return File.ReadAllText(path);
            }
        }

        return "Generate {num_children} child prompts as a numbered list using these parents:\n{parent_prompts_str}\nReturn only the list.";
    }

    private static List<string> ParseChildPrompts(string raw, int maxChildren)
    {
        var children = new List<string>();
        if (string.IsNullOrWhiteSpace(raw))
        {
            return children;
        }

        foreach (var line in raw.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var match = NumberedLineRegex.Match(line);
            if (!match.Success)
            {
                continue;
            }

            var prompt = match.Groups["prompt"].Value.Trim().Trim('"');
            if (string.IsNullOrWhiteSpace(prompt))
            {
                continue;
            }

            if (prompt.StartsWith("Parent ", StringComparison.OrdinalIgnoreCase) ||
                prompt.StartsWith("Here", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (!children.Contains(prompt, StringComparer.OrdinalIgnoreCase))
            {
                children.Add(prompt);
            }

            if (children.Count >= maxChildren)
            {
                break;
            }
        }

        if (children.Count == 0)
        {
            var fallback = raw.Trim();
            if (!string.IsNullOrWhiteSpace(fallback))
            {
                children.Add(fallback);
            }
        }

        return children;
    }

    private static string? ResolveImagePath(string historyDir, string? relativeOrAbsolute)
    {
        if (string.IsNullOrWhiteSpace(relativeOrAbsolute))
        {
            return null;
        }

        var full = Path.IsPathRooted(relativeOrAbsolute)
            ? relativeOrAbsolute
            : Path.Combine(historyDir, relativeOrAbsolute);
        return File.Exists(full) ? full : null;
    }

    private static Bitmap? TryLoadThumbnail(string? fullPath)
    {
        if (string.IsNullOrWhiteSpace(fullPath) || !File.Exists(fullPath))
        {
            return null;
        }

        try
        {
            return new Bitmap(fullPath);
        }
        catch
        {
            return null;
        }
    }

    private void LoadPersistedSettings()
    {
        if (_settingsService == null)
        {
            return;
        }

        var settings = _settingsService.Settings;
        NumChildren = Math.Clamp(settings.PromptEvolverNumChildren, 1, 20);
        Temperature = Math.Clamp(settings.PromptEvolverTemperature, 0, 2);
        TopP = Math.Clamp(settings.PromptEvolverTopP, 0, 1);
        if (!string.IsNullOrWhiteSpace(settings.PromptEvolverModel))
        {
            SelectedOllamaModel = settings.PromptEvolverModel;
        }
    }
}

public sealed record PromptEvolverHistoryItemViewModel(
    string Prompt,
    string ModelName,
    DateTime Timestamp,
    string? ImagePath,
    Bitmap? Thumbnail)
{
    public string Preview => Prompt.Length <= 220 ? Prompt : $"{Prompt[..220]}...";
    public string SubLabel => $"{ModelName} • {Timestamp:g}";
}

public partial class PromptEvolverChildItemViewModel : ObservableObject
{
    public PromptEvolverChildItemViewModel(string prompt)
    {
        Prompt = prompt;
    }

    public string Prompt { get; }

    [ObservableProperty]
    private bool _isSelectedForParent;
}
