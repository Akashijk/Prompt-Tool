using System.Collections.ObjectModel;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Services;

namespace PromptTool.ViewModels;

public partial class SystemPromptEditorViewModel : ObservableObject
{
    private readonly SettingsService _settings;

    [ObservableProperty]
    private ObservableCollection<PromptFileItem> _promptFiles = new();

    [ObservableProperty]
    private PromptFileItem? _selectedPromptFile;

    [ObservableProperty]
    private string _promptContent = "";

    [ObservableProperty]
    private string _status = "";

    [ObservableProperty]
    private bool? _dialogResult;

    public SystemPromptEditorViewModel(SettingsService settings)
    {
        _settings = settings;
        _ = LoadFilesAsync();
    }

    [RelayCommand]
    private async Task LoadFilesAsync()
    {
        var dir = _settings.GetSystemPromptDir();
        Directory.CreateDirectory(dir);
        var items = new List<PromptFileItem>();

        // Root .txt files
        foreach (var file in Directory.GetFiles(dir, "*.txt"))
        {
            var name = Path.GetFileName(file) ?? file;
            items.Add(new PromptFileItem(name, name, IsJson: false));
        }

        // Variations .json files
        var variationsDir = Path.Combine(dir, "variations");
        if (Directory.Exists(variationsDir))
        {
            foreach (var file in Directory.GetFiles(variationsDir, "*.json"))
            {
                var rel = Path.Combine("variations", Path.GetFileName(file) ?? "");
                var display = $"Variation: {Path.GetFileNameWithoutExtension(file)}";
                // Try to use the "name" field for display
                try
                {
                    var json = File.ReadAllText(file);
                    using var doc = System.Text.Json.JsonDocument.Parse(json);
                    if (doc.RootElement.ValueKind == System.Text.Json.JsonValueKind.Object &&
                        doc.RootElement.TryGetProperty("name", out var n) &&
                        n.ValueKind == System.Text.Json.JsonValueKind.String &&
                        !string.IsNullOrWhiteSpace(n.GetString()))
                    {
                        display = $"Variation: {n.GetString()}";
                    }
                }
                catch
                {
                    // ignore parse errors; fallback name already set
                }

                items.Add(new PromptFileItem(display, rel, IsJson: true));
            }
        }

        PromptFiles = new ObservableCollection<PromptFileItem>(items.OrderBy(i => i.DisplayName, System.StringComparer.OrdinalIgnoreCase));
        SelectedPromptFile = PromptFiles.FirstOrDefault();
        await LoadContentAsync();
    }

    [RelayCommand]
    private async Task LoadContentAsync()
    {
        if (SelectedPromptFile == null) return;
        var path = Path.Combine(_settings.GetSystemPromptDir(), SelectedPromptFile.RelativePath);
        if (File.Exists(path))
        {
            PromptContent = await File.ReadAllTextAsync(path);
            Status = $"Loaded {SelectedPromptFile.DisplayName}";
        }
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        if (SelectedPromptFile == null) return;
        var path = Path.Combine(_settings.GetSystemPromptDir(), SelectedPromptFile.RelativePath);
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(dir))
        {
            Directory.CreateDirectory(dir);
        }
        await File.WriteAllTextAsync(path, PromptContent);
        Status = $"Saved {SelectedPromptFile.DisplayName}";
        DialogResult = true;
    }

    [RelayCommand]
    private void Cancel()
    {
        DialogResult = false;
    }

    public record PromptFileItem(string DisplayName, string RelativePath, bool IsJson);
}
