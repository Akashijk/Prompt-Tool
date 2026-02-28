using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using System.Text.Json;
using System.Collections.Generic;
using Avalonia.Threading;
using System.Text.RegularExpressions;

namespace PromptTool.ViewModels;

public partial class WildcardManagerViewModel : ObservableObject
{
    private readonly WildcardService _wildcardService;
    private bool _structuredDirty;
    private int _findIndex = -1;

    [ObservableProperty]
    private ObservableCollection<WildcardFileEntry> _wildcards = new();

    [ObservableProperty]
    private WildcardFileEntry? _selectedWildcard;

    [ObservableProperty]
    private StructuredWildcard? _structured;

    [ObservableProperty]
    private ObservableCollection<WildcardChoiceViewModel> _choices = new();

    [ObservableProperty]
    private WildcardChoiceViewModel? _selectedChoice;

    [ObservableProperty]
    private string _currentWildcardName = "";

    [ObservableProperty]
    private string _currentWildcardContent = "";

    [ObservableProperty]
    private ObservableCollection<ValidationIssue> _validationErrors = new();

    [ObservableProperty]
    private ObservableCollection<DependencyInfo> _dependencies = new();
    [ObservableProperty]
    private ObservableCollection<string> _unusedWildcards = new();
    [ObservableProperty]
    private ValidationIssue? _selectedValidationIssue;
    [ObservableProperty]
    private string _status = "";
    [ObservableProperty]
    private int _selectedTabIndex;

    [ObservableProperty]
    private string _filterText = "";

    [ObservableProperty]
    private int _wildcardCount;

    [ObservableProperty]
    private bool _showArchived;

    [ObservableProperty]
    private bool _canArchive;

    [ObservableProperty]
    private bool _canUnarchive;

    [ObservableProperty]
    private bool _isFindVisible;

    [ObservableProperty]
    private string _findText = "";

    [ObservableProperty]
    private string _replaceText = "";

    partial void OnFindTextChanged(string value)
    {
        _findIndex = -1;
    }

    public WildcardManagerViewModel(WildcardService wildcardService)
    {
        _wildcardService = wildcardService;
        SelectedTabIndex = 0;
        LoadWildcardsCommand.Execute(null);
    }

    public async Task SelectWildcardAfterLoadAsync(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return;
        FilterText = string.Empty;
        await LoadWildcardsAsync();
        await Dispatcher.UIThread.InvokeAsync(() => SelectWildcardByName(name));
    }

    [RelayCommand]
    private async Task LoadWildcardsAsync()
    {
        var entries = await _wildcardService.GetWildcardFileEntries(ShowArchived);
        var sorted = entries.OrderBy(e => e.Name, StringComparer.OrdinalIgnoreCase).ToList();
        Wildcards = new ObservableCollection<WildcardFileEntry>(ApplyFilter(sorted, FilterText));
        WildcardCount = sorted.Count;
        LoadDependencies();
    }

    partial void OnFilterTextChanged(string value)
    {
        _ = LoadWildcardsAsync();
    }

    partial void OnShowArchivedChanged(bool value)
    {
        _ = LoadWildcardsAsync();
    }

    private IEnumerable<WildcardFileEntry> ApplyFilter(IEnumerable<WildcardFileEntry> entries, string filter)
    {
        if (string.IsNullOrWhiteSpace(filter)) return entries;
        var term = filter.Trim();
        var filtered = entries.Where(e =>
            e.Name.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            (e.Content?.IndexOf(term, StringComparison.OrdinalIgnoreCase) ?? -1) >= 0);
        return filtered;
    }

    partial void OnSelectedWildcardChanged(WildcardFileEntry? value)
    {
        _ = HandleSelectedWildcardAsync(value);
    }

    partial void OnSelectedValidationIssueChanged(ValidationIssue? value)
    {
        if (value == null) return;

        var location = value.Location?.ToLowerInvariant() ?? string.Empty;
        if (location.Contains("require") || location.Contains("include") || location.Contains("choice"))
        {
            SelectedTabIndex = 0;
        }
        else
        {
            SelectedTabIndex = 1;
        }

        SetStatus($"Selected issue: {value.Message}");
    }

    private async Task HandleSelectedWildcardAsync(WildcardFileEntry? value)
    {
        if (value == null)
        {
            CurrentWildcardName = "";
            CurrentWildcardContent = "";
            Structured = null;
            Choices.Clear();
            SelectedChoice = null;
            CanArchive = false;
            CanUnarchive = false;
            return;
        }

        CanArchive = !value.IsArchived;
        CanUnarchive = value.IsArchived;

        if (IsLegacyText(value.FilePath))
        {
            var conversion = await _wildcardService.ConvertLegacyTextWildcardAsync(value.FilePath);
            if (conversion.Converted)
            {
                SetStatus($"Converted legacy TXT wildcard to JSON (backup created at {conversion.BackupPath}).");
                await LoadWildcardsAsync();
                SelectWildcardByName(value.Name);
                return;
            }
            if (conversion.SkippedBecauseJsonExists && conversion.JsonPath != null)
            {
                SetStatus("JSON version already exists; using JSON.");
                await LoadWildcardsAsync();
                SelectWildcardByName(value.Name);
                return;
            }
            if (!string.IsNullOrWhiteSpace(conversion.Error))
            {
                SetStatus($"Conversion failed: {conversion.Error}");
            }
        }

        CurrentWildcardName = value.Name;
        CurrentWildcardContent = value.Content ?? string.Empty;
        LoadStructured(value.Name);
        SelectedTabIndex = 0;
    }

    private void LoadStructured(string name)
    {
        Structured = _wildcardService.GetStructuredWildcards().TryGetValue(name, out var s) ? s : null;
        ApplyStructuredModel(Structured);
    }

    [RelayCommand]
    private async Task SaveWildcardAsync()
    {
        if (string.IsNullOrWhiteSpace(CurrentWildcardName) || string.IsNullOrWhiteSpace(CurrentWildcardContent))
        {
            SetStatus("Name and content are required.");
            return;
        }

        try
        {
            if (_structuredDirty && Choices.Any())
            {
                CurrentWildcardContent = BuildContentFromChoices();
                _structuredDirty = false;
            }
            await _wildcardService.SaveWildcardFileContent(CurrentWildcardName, CurrentWildcardContent);
            await LoadWildcardsAsync(); // Refresh list
            SelectedWildcard = Wildcards.FirstOrDefault(w => w.Name == CurrentWildcardName); // Reselect
            SetStatus($"Saved {CurrentWildcardName}.");
        }
        catch (ArgumentException)
        {
            SetStatus("Save failed: invalid JSON.");
        }
        catch (Exception ex)
        {
            SetStatus($"Save failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private void NewWildcard()
    {
        SelectedWildcard = null;
        CurrentWildcardName = "new_wildcard";
        CurrentWildcardContent = "{\n  \"choices\": [\n    \"choice1\",\n    \"choice2\"\n  ]\n}"; // Corrected string literal
    }

    [RelayCommand]
    private void AddChoice()
    {
        var insertIndex = SelectedChoice != null ? Choices.IndexOf(SelectedChoice) + 1 : Choices.Count;
        var model = new WildcardChoice { Value = "new choice" };
        var vm = new WildcardChoiceViewModel(model, insertIndex + 1, MarkStructuredDirty);
        Choices.Insert(Math.Clamp(insertIndex, 0, Choices.Count), vm);
        SelectedChoice = vm;
        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        MarkStructuredDirty();
    }

    [RelayCommand]
    private void DeleteChoice()
    {
        if (SelectedChoice == null) return;
        Choices.Remove(SelectedChoice);
        SelectedChoice = Choices.LastOrDefault();
        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        MarkStructuredDirty();
    }

    [RelayCommand]
    private void MoveChoiceUp()
    {
        if (SelectedChoice == null) return;
        var index = Choices.IndexOf(SelectedChoice);
        if (index <= 0) return;
        Choices.Move(index, index - 1);
        UpdateChoiceIndices();
        MarkStructuredDirty();
    }

    [RelayCommand]
    private void MoveChoiceDown()
    {
        if (SelectedChoice == null) return;
        var index = Choices.IndexOf(SelectedChoice);
        if (index < 0 || index >= Choices.Count - 1) return;
        Choices.Move(index, index + 1);
        UpdateChoiceIndices();
        MarkStructuredDirty();
    }

    [RelayCommand]
    private void ToggleFind()
    {
        IsFindVisible = !IsFindVisible;
        _findIndex = -1;
    }

    [RelayCommand]
    private void FindNext()
    {
        if (string.IsNullOrWhiteSpace(FindText) || Choices.Count == 0) return;
        var start = _findIndex + 1;
        for (var i = 0; i < Choices.Count; i++)
        {
            var idx = (start + i) % Choices.Count;
            if (ChoiceMatches(Choices[idx], FindText))
            {
                _findIndex = idx;
                SelectedChoice = Choices[idx];
                SelectedTabIndex = 0;
                SetStatus($"Found in row {Choices[idx].Index}.");
                return;
            }
        }

        SetStatus("No matches found.");
    }

    [RelayCommand]
    private void ReplaceNext()
    {
        if (SelectedChoice == null || string.IsNullOrWhiteSpace(FindText)) return;
        if (!ChoiceMatches(SelectedChoice, FindText))
        {
            FindNext();
            return;
        }

        ApplyReplace(SelectedChoice, FindText, ReplaceText);
        UpdateChoiceWarnings();
        MarkStructuredDirty();
        FindNext();
    }

    [RelayCommand]
    private void ReplaceAll()
    {
        if (string.IsNullOrWhiteSpace(FindText) || Choices.Count == 0) return;
        var replaced = 0;
        foreach (var choice in Choices)
        {
            if (ChoiceMatches(choice, FindText))
            {
                ApplyReplace(choice, FindText, ReplaceText);
                replaced++;
            }
        }
        UpdateChoiceWarnings();
        MarkStructuredDirty();
        SetStatus(replaced == 0 ? "No matches found." : $"Replaced in {replaced} row(s).");
    }

    [RelayCommand]
    private void DeduplicateChoices()
    {
        if (Choices.Count == 0) return;
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var toRemove = new List<WildcardChoiceViewModel>();
        foreach (var choice in Choices)
        {
            var key = NormalizeWhitespace(choice.Value);
            if (seen.Contains(key))
            {
                toRemove.Add(choice);
            }
            else
            {
                seen.Add(key);
            }
        }

        foreach (var choice in toRemove)
        {
            Choices.Remove(choice);
        }

        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        MarkStructuredDirty();
        SetStatus(toRemove.Count == 0 ? "No duplicates found." : $"Removed {toRemove.Count} duplicate choice(s).");
    }

    public async Task RenameWildcardToAsync(string newName)
    {
        if (SelectedWildcard == null) return;
        if (string.IsNullOrWhiteSpace(newName)) return;
        try
        {
            await _wildcardService.RenameWildcardFileAsync(SelectedWildcard.FilePath, newName.Trim());
            await LoadWildcardsAsync();
            SelectWildcardByName(newName.Trim());
            SetStatus($"Renamed to {newName}.");
        }
        catch (Exception ex)
        {
            SetStatus($"Rename failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task ArchiveWildcardAsync()
    {
        if (SelectedWildcard == null) return;
        try
        {
            await _wildcardService.ArchiveWildcardFileAsync(SelectedWildcard.FilePath);
            await LoadWildcardsAsync();
            SelectedWildcard = null;
            SetStatus("Wildcard archived.");
        }
        catch (Exception ex)
        {
            SetStatus($"Archive failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task UnarchiveWildcardAsync()
    {
        if (SelectedWildcard == null) return;
        try
        {
            await _wildcardService.UnarchiveWildcardFileAsync(SelectedWildcard.FilePath);
            await LoadWildcardsAsync();
            SelectedWildcard = null;
            SetStatus("Wildcard restored from archive.");
        }
        catch (Exception ex)
        {
            SetStatus($"Unarchive failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task ConvertAllLegacyAsync()
    {
        var result = await _wildcardService.ConvertAllLegacyTextWildcardsAsync();
        await LoadWildcardsAsync();
        if (result.Failed > 0)
        {
            SetStatus($"Converted {result.Converted}, skipped {result.SkippedExistingJson}, failed {result.Failed}.");
        }
        else
        {
            SetStatus($"Converted {result.Converted}, skipped {result.SkippedExistingJson}.");
        }
    }

    [RelayCommand]
    private async Task DeleteWildcardAsync()
    {
        if (SelectedWildcard == null) return;

        try
        {
            await _wildcardService.DeleteWildcardFileByPath(SelectedWildcard.FilePath);
            await LoadWildcardsAsync(); // Refresh list
            SelectedWildcard = null; // Clear selection
            SetStatus("Deleted wildcard.");
        }
        catch (Exception ex)
        {
            SetStatus($"Delete failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private void ApplyStructuredToRaw()
    {
        if (!Choices.Any()) return;
        CurrentWildcardContent = BuildContentFromChoices();
        _structuredDirty = false;
        SetStatus("Structured data applied to raw JSON.");
    }

    [RelayCommand]
    private void ReloadStructuredFromRaw()
    {
        try
        {
            var parsed = _wildcardService.ParseStructuredContent(CurrentWildcardName ?? "current", CurrentWildcardContent ?? "");
            Structured = parsed;
            ApplyStructuredModel(parsed);
            SetStatus("Structured view refreshed from raw JSON.");
        }
        catch (Exception ex)
        {
            SetStatus($"Refresh failed: {ex.Message}");
        }
    }

    [RelayCommand]
    private void InsertWeightedChoiceTemplate()
    {
        var template = "{\n  \"value\": \"your_choice\",\n  \"weight\": 1.0,\n  \"includes\": [],\n  \"requires\": {\"tag\": \"value\"}\n}";
        AppendTemplateSnippet(template);
    }

    [RelayCommand]
    private void InsertIncludeTemplate()
    {
        var template = "{\n  \"value\": \"your_choice\",\n  \"includes\": [\"other_wildcard\"]\n}";
        AppendTemplateSnippet(template);
    }

    [RelayCommand]
    private void InsertRequiresTemplate()
    {
        var template = "{\n  \"value\": \"your_choice\",\n  \"requires\": {\"tag\": \"value\"}\n}";
        AppendTemplateSnippet(template);
    }

    private void AppendTemplateSnippet(string snippet)
    {
        if (string.IsNullOrWhiteSpace(CurrentWildcardContent))
        {
            CurrentWildcardContent = "{\n  \"choices\": [\n" + snippet + "\n  ]\n}";
        }
        else
        {
            CurrentWildcardContent += "\n" + snippet;
        }
        LoadStructured(CurrentWildcardName);
    }

    [RelayCommand]
    private Task ValidateAsync()
    {
        ValidationErrors.Clear();
        if (string.IsNullOrWhiteSpace(CurrentWildcardContent))
        {
            return Task.CompletedTask;
        }

        try
        {
            var options = new JsonSerializerOptions { AllowTrailingCommas = true, ReadCommentHandling = JsonCommentHandling.Skip };
            var doc = JsonDocument.Parse(CurrentWildcardContent, new JsonDocumentOptions { AllowTrailingCommas = true });
            var root = doc.RootElement;
            if (!root.TryGetProperty("choices", out var choices) || choices.ValueKind != JsonValueKind.Array || choices.GetArrayLength() == 0)
            {
                ValidationErrors.Add(new ValidationIssue("Missing or empty 'choices' array.", "root"));
            }
            else
            {
                foreach (var item in choices.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String)
                    {
                        var val = item.GetString();
                        if (string.IsNullOrWhiteSpace(val))
                        {
                            ValidationErrors.Add(new ValidationIssue("Empty choice string detected.", "choices"));
                        }
                    }
                    else if (item.ValueKind == JsonValueKind.Object)
                    {
                        if (!item.TryGetProperty("value", out var valProp) && !item.TryGetProperty("choice", out valProp))
                        {
                            ValidationErrors.Add(new ValidationIssue("Object choice missing 'value'.", "choices"));
                        }
                        else if (string.IsNullOrWhiteSpace(valProp.GetString()))
                        {
                            ValidationErrors.Add(new ValidationIssue("Object choice has empty 'value'.", "choices"));
                        }

                        if (item.TryGetProperty("requires", out var reqProp))
                        {
                            if (reqProp.ValueKind != JsonValueKind.Object)
                            {
                                ValidationErrors.Add(new ValidationIssue("Requires must be an object.", "requires"));
                            }
                            else
                            {
                                try
                                {
                                    using var _ = JsonDocument.Parse(reqProp.GetRawText());
                                }
                                catch
                                {
                                    ValidationErrors.Add(new ValidationIssue("Requires contains invalid JSON.", "requires"));
                                }
                            }
                        }

                        if (item.TryGetProperty("includes", out var incProp))
                        {
                            if (incProp.ValueKind == JsonValueKind.String || incProp.ValueKind == JsonValueKind.Array)
                            {
                                foreach (var inc in FlattenIncludes(incProp))
                                {
                                    if (!_wildcardService.GetStructuredWildcards().ContainsKey(inc))
                                    {
                                        ValidationErrors.Add(new ValidationIssue($"Includes references missing wildcard '{inc}'.", "includes"));
                                    }
                                }
                            }
                            else
                            {
                                ValidationErrors.Add(new ValidationIssue("Includes must be string or array.", "includes"));
                            }
                        }
                    }
                    else
                    {
                        ValidationErrors.Add(new ValidationIssue("Choices must be strings or objects.", "choices"));
                    }
                }
            }
        }
        catch (JsonException ex)
        {
            ValidationErrors.Add(new ValidationIssue($"Invalid JSON: {ex.Message}", "json"));
        }
        catch (Exception ex)
        {
            ValidationErrors.Add(new ValidationIssue($"Unexpected error: {ex.Message}", "unknown"));
        }

        UpdateChoiceWarnings();
        SetStatus(ValidationErrors.Count == 0 ? "Validation passed." : $"Validation found {ValidationErrors.Count} issue(s).");
        return Task.CompletedTask;
    }

    [RelayCommand]
    private async Task FindDuplicatesAsync()
    {
        ValidationErrors.Clear();
        var entries = await _wildcardService.GetAllWildcardFileEntries();
        var duplicates = entries
            .GroupBy(e => e.Name, StringComparer.OrdinalIgnoreCase)
            .Where(g => g.Count() > 1)
            .Select(g => $"Duplicate wildcard name: {g.Key} ({g.Count()} files)")
            .ToList();

        if (duplicates.Count == 0)
        {
            ValidationErrors.Add(new ValidationIssue("No duplicate wildcard files found.", "info"));
        }
        else
        {
            foreach (var d in duplicates) ValidationErrors.Add(new ValidationIssue(d, "duplicate"));
        }

        SetStatus("Duplicate scan complete.");
    }

    [RelayCommand]
    private void RefreshDependencies()
    {
        LoadDependencies();
        SetStatus("Dependencies refreshed.");
    }

    [RelayCommand]
    private void SelectWildcardByName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return;
        var match = Wildcards.FirstOrDefault(w => string.Equals(w.Name, name, StringComparison.OrdinalIgnoreCase));
        if (match != null)
        {
            SelectedWildcard = match;
        }
    }

    [RelayCommand]
    private async Task DeleteUnusedWildcardAsync(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return;
        try
        {
            await _wildcardService.DeleteWildcardFile(name);
            await LoadWildcardsAsync();
            SetStatus($"Deleted unused wildcard '{name}'.");
        }
        catch (Exception ex)
        {
            SetStatus($"Failed to delete '{name}': {ex.Message}");
        }
    }

    [RelayCommand]
    private async Task DeleteAllUnusedAsync()
    {
        if (UnusedWildcards.Count == 0)
        {
            SetStatus("No unused wildcards to delete.");
            return;
        }

        foreach (var name in UnusedWildcards.ToList())
        {
            try
            {
                await _wildcardService.DeleteWildcardFile(name);
            }
            catch (Exception ex)
            {
                SetStatus($"Failed to delete '{name}': {ex.Message}");
                return;
            }
        }

        await LoadWildcardsAsync();
        SetStatus("Deleted all unused wildcards.");
    }

    private string BuildContentFromChoices()
    {
        var payload = new
        {
            choices = Choices
                .Select(c => new
            {
                value = c.Value,
                weight = c.Weight,
                tags = (c.Tags ?? string.Empty)
                    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .ToList(),
                includes = c.Includes switch
                {
                    null or "" => null,
                    _ => c.Includes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                },
                requires = ParseRequires(c.Requires)
            }).ToList()
        };

        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
    }

    private void LoadDependencies()
    {
        var deps = _wildcardService.GetDependencies();
        Dependencies = new ObservableCollection<DependencyInfo>(
            deps.Select(d => new DependencyInfo(d.Name, d.RequiredBy.Count, d.Includes.ToArray(), d.RequiredBy.ToArray())));
        UnusedWildcards = new ObservableCollection<string>(_wildcardService.FindUnusedWildcards());
        SetStatus($"Loaded {Wildcards.Count} wildcards. {UnusedWildcards.Count} unused.");
    }

    private void UpdateChoiceIndices()
    {
        for (var i = 0; i < Choices.Count; i++)
        {
            Choices[i].Index = i + 1;
        }
    }

    private void UpdateChoiceWarnings()
    {
        var known = _wildcardService.GetStructuredWildcards().Keys.ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var choice in Choices)
        {
            var warnings = new List<string>();
            foreach (var inc in ExtractIncludes(choice.Includes))
            {
                if (!known.Contains(inc))
                {
                    warnings.Add($"Missing include: {inc}");
                }
            }

            foreach (var req in ExtractRequires(choice.Requires))
            {
                if (!known.Contains(req))
                {
                    warnings.Add($"Missing requires: {req}");
                }
            }

            choice.Warning = string.Join("; ", warnings);
        }
    }

    private static IEnumerable<string> FlattenIncludes(JsonElement incProp)
    {
        switch (incProp.ValueKind)
        {
            case JsonValueKind.String:
                var s = incProp.GetString();
                return string.IsNullOrWhiteSpace(s) ? Array.Empty<string>() : new[] { s.Trim() };
            case JsonValueKind.Array:
                return incProp.EnumerateArray()
                    .Where(e => e.ValueKind == JsonValueKind.String)
                    .Select(e => e.GetString()?.Trim())
                    .Where(v => !string.IsNullOrWhiteSpace(v))!;
            default:
                return Array.Empty<string>();
        }
    }

    private void MarkStructuredDirty()
    {
        _structuredDirty = true;
        UpdateChoiceWarnings();
    }
    private void ApplyStructuredModel(StructuredWildcard? model)
    {
        Choices = model != null
            ? new ObservableCollection<WildcardChoiceViewModel>(
                model.Choices
                    .Select((c, idx) => new WildcardChoiceViewModel(c, idx + 1, MarkStructuredDirty)
                    {
                        Includes = c.Includes switch
                        {
                            string sInc => sInc,
                            IEnumerable<string> arr => string.Join(", ", arr),
                            _ => ""
                        },
                        Requires = c.RequiresJson ?? ""
                    }))
            : new ObservableCollection<WildcardChoiceViewModel>();

        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        _structuredDirty = false;
    }

    private static object? ParseRequires(string? requires)
    {
        if (string.IsNullOrWhiteSpace(requires)) return null;
        try
        {
            return JsonSerializer.Deserialize<JsonElement>(requires);
        }
        catch
        {
            return requires;
        }
    }

    private void SetStatus(string message) => Status = message;

    private static bool IsLegacyText(string? path)
    {
        return !string.IsNullOrWhiteSpace(path) && path.EndsWith(".txt", StringComparison.OrdinalIgnoreCase);
    }

    private static string NormalizeWhitespace(string input)
    {
        if (string.IsNullOrWhiteSpace(input)) return string.Empty;
        var collapsed = Regex.Replace(input.Trim(), @"\s+", " ");
        return collapsed;
    }

    private static IEnumerable<string> ExtractIncludes(string? includesText)
    {
        if (string.IsNullOrWhiteSpace(includesText)) return Array.Empty<string>();
        var items = includesText.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var results = new List<string>();
        foreach (var item in items)
        {
            var cleaned = item.Trim();
            cleaned = cleaned.Trim('[', ']');
            cleaned = cleaned.Trim('_');
            if (!string.IsNullOrWhiteSpace(cleaned))
            {
                results.Add(cleaned);
            }
        }
        return results;
    }

    private static IEnumerable<string> ExtractRequires(string? requiresJson)
    {
        if (string.IsNullOrWhiteSpace(requiresJson)) return Array.Empty<string>();
        try
        {
            using var doc = JsonDocument.Parse(requiresJson);
            var root = doc.RootElement;
            var results = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            ExtractRequiresRecursive(root, results);
            return results;
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static void ExtractRequiresRecursive(JsonElement element, HashSet<string> results)
    {
        if (element.ValueKind != JsonValueKind.Object) return;
        foreach (var prop in element.EnumerateObject())
        {
            if (prop.NameEquals("and") || prop.NameEquals("or"))
            {
                if (prop.Value.ValueKind == JsonValueKind.Array)
                {
                    foreach (var child in prop.Value.EnumerateArray())
                    {
                        ExtractRequiresRecursive(child, results);
                    }
                }
                continue;
            }
            if (prop.NameEquals("not"))
            {
                ExtractRequiresRecursive(prop.Value, results);
                continue;
            }
            if (prop.NameEquals("tags"))
            {
                continue;
            }

            results.Add(prop.Name);
        }
    }

    private static bool ChoiceMatches(WildcardChoiceViewModel choice, string term)
    {
        if (string.IsNullOrWhiteSpace(term)) return false;
        return choice.Value.Contains(term, StringComparison.OrdinalIgnoreCase)
               || choice.Tags.Contains(term, StringComparison.OrdinalIgnoreCase)
               || choice.Includes.Contains(term, StringComparison.OrdinalIgnoreCase)
               || choice.Requires.Contains(term, StringComparison.OrdinalIgnoreCase);
    }

    private static void ApplyReplace(WildcardChoiceViewModel choice, string find, string replace)
    {
        choice.Value = ReplaceIgnoreCase(choice.Value, find, replace);
        choice.Tags = ReplaceIgnoreCase(choice.Tags, find, replace);
        choice.Includes = ReplaceIgnoreCase(choice.Includes, find, replace);
        choice.Requires = ReplaceIgnoreCase(choice.Requires, find, replace);
    }

    public IReadOnlyList<string> GetWildcardNameList()
    {
        return _wildcardService.GetWildcardNames().ToList();
    }

    public IReadOnlyList<string> GetWildcardValues(string wildcardName)
    {
        return _wildcardService.GetAllValues(wildcardName)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToList();
    }

    public (string? WildcardName, string? Value) GetRequiresSelection()
    {
        if (SelectedChoice == null) return (null, null);
        var requires = SelectedChoice.Requires;
        if (string.IsNullOrWhiteSpace(requires)) return (null, null);
        try
        {
            using var doc = JsonDocument.Parse(requires);
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return (null, null);
            var props = doc.RootElement.EnumerateObject().ToList();
            if (props.Count != 1) return (null, null);
            var prop = props[0];
            if (prop.Value.ValueKind == JsonValueKind.String)
            {
                return (prop.Name, prop.Value.GetString());
            }
        }
        catch
        {
            return (null, null);
        }
        return (null, null);
    }

    public void ApplyRequiresSelection(string wildcardName, string value)
    {
        if (SelectedChoice == null) return;
        if (string.IsNullOrWhiteSpace(wildcardName) || string.IsNullOrWhiteSpace(value)) return;
        var payload = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [wildcardName] = value
        };
        SelectedChoice.Requires = JsonSerializer.Serialize(payload);
        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    public void ClearRequiresSelection()
    {
        if (SelectedChoice == null) return;
        SelectedChoice.Requires = "";
        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    public string? GetIncludeSelection()
    {
        if (SelectedChoice == null) return null;
        var includes = SelectedChoice.Includes;
        if (string.IsNullOrWhiteSpace(includes)) return null;
        if (includes.Contains(',', StringComparison.Ordinal)) return null;
        return includes.Trim();
    }

    public IReadOnlyList<string> GetIncludeSelections()
    {
        if (SelectedChoice == null) return Array.Empty<string>();
        var includes = SelectedChoice.Includes;
        if (string.IsNullOrWhiteSpace(includes)) return Array.Empty<string>();
        return includes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();
    }

    public void ApplyIncludeSelection(string wildcardName)
    {
        if (SelectedChoice == null) return;
        if (string.IsNullOrWhiteSpace(wildcardName)) return;
        SelectedChoice.Includes = wildcardName.Trim();
        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    public void ApplyIncludeSelections(IEnumerable<string> wildcardNames)
    {
        if (SelectedChoice == null) return;
        var items = wildcardNames
            .Where(n => !string.IsNullOrWhiteSpace(n))
            .Select(n => n.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        SelectedChoice.Includes = items.Count == 0 ? "" : string.Join(", ", items);
        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    public record RequirementRule(string WildcardName, string Operator, List<string> Values);

    public IReadOnlyList<RequirementRule> GetRequiresRules()
    {
        if (SelectedChoice == null) return Array.Empty<RequirementRule>();
        var requires = SelectedChoice.Requires;
        if (string.IsNullOrWhiteSpace(requires)) return Array.Empty<RequirementRule>();
        try
        {
            using var doc = JsonDocument.Parse(requires);
            var root = doc.RootElement;
            var rules = new List<RequirementRule>();
            if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("and", out var andNode) && andNode.ValueKind == JsonValueKind.Array)
            {
                foreach (var child in andNode.EnumerateArray())
                {
                    if (TryParseRule(child, out var rule))
                    {
                        rules.Add(rule);
                    }
                }
            }
            else if (TryParseRule(root, out var single))
            {
                rules.Add(single);
            }
            return rules;
        }
        catch
        {
            return Array.Empty<RequirementRule>();
        }
    }

    public void ApplyRequiresRules(IEnumerable<RequirementRule> rules)
    {
        if (SelectedChoice == null) return;
        var list = rules?.ToList() ?? new List<RequirementRule>();
        if (list.Count == 0)
        {
            SelectedChoice.Requires = "";
            MarkStructuredDirty();
            UpdateChoiceWarnings();
            return;
        }

        JsonElement BuildRuleJson(RequirementRule rule)
        {
            object value = rule.Operator == "in"
                ? rule.Values
                : (rule.Values.FirstOrDefault() ?? "");
            var payload = new Dictionary<string, object>
            {
                [rule.WildcardName] = value
            };
            return JsonSerializer.Deserialize<JsonElement>(JsonSerializer.Serialize(payload));
        }

        if (list.Count == 1)
        {
            var single = BuildRuleJson(list[0]);
            SelectedChoice.Requires = JsonSerializer.Serialize(single);
        }
        else
        {
            var array = list.Select(BuildRuleJson).ToList();
            var payload = new Dictionary<string, object>
            {
                ["and"] = array
            };
            SelectedChoice.Requires = JsonSerializer.Serialize(payload);
        }

        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    private static bool TryParseRule(JsonElement element, out RequirementRule rule)
    {
        rule = new RequirementRule("", "equals", new List<string>());
        if (element.ValueKind != JsonValueKind.Object) return false;
        var props = element.EnumerateObject().ToList();
        if (props.Count != 1) return false;
        var prop = props[0];
        if (prop.Value.ValueKind == JsonValueKind.String)
        {
            rule = new RequirementRule(prop.Name, "equals", new List<string> { prop.Value.GetString() ?? "" });
            return true;
        }
        if (prop.Value.ValueKind == JsonValueKind.Array)
        {
            var values = prop.Value.EnumerateArray()
                .Where(v => v.ValueKind == JsonValueKind.String)
                .Select(v => v.GetString() ?? "")
                .Where(s => !string.IsNullOrWhiteSpace(s))
                .ToList();
            rule = new RequirementRule(prop.Name, "in", values);
            return true;
        }
        return false;
    }

    public void ClearIncludeSelection()
    {
        if (SelectedChoice == null) return;
        SelectedChoice.Includes = "";
        MarkStructuredDirty();
        UpdateChoiceWarnings();
    }

    private static string ReplaceIgnoreCase(string input, string search, string replacement)
    {
        if (string.IsNullOrEmpty(input) || string.IsNullOrEmpty(search)) return input;
        return Regex.Replace(input, Regex.Escape(search), replacement ?? string.Empty, RegexOptions.IgnoreCase);
    }
}

public record ValidationIssue(string Message, string Location);
