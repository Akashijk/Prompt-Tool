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
    private readonly TemplateService _templateService;
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
    private ObservableCollection<string> _themeSuggestions = new();

    [ObservableProperty]
    private ObservableCollection<SimilarWildcardCandidate> _similarWildcards = new();

    [ObservableProperty]
    private string _similarWildcardStatus = "Select a wildcard to see merge candidates.";

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

    [ObservableProperty]
    private string _quickAddChoiceText = "";

    [ObservableProperty]
    private bool _canResolveSelectedIssue;

    [ObservableProperty]
    private string _selectedIssueSummary = "Select a validation issue to review it here.";

    [ObservableProperty]
    private string _resolvePrimaryIssueText = "Keep first";

    [ObservableProperty]
    private string _resolveSecondaryIssueText = "Keep second";

    [ObservableProperty]
    private bool _isInspectorOpen;

    [ObservableProperty]
    private string _inspectorToggleText = "Show Inspector";

    [ObservableProperty]
    private int _inspectorTabIndex;

    [ObservableProperty]
    private double _inspectorPaneWidth;

    [ObservableProperty]
    private double _inspectorPaneOpacity;

    [ObservableProperty]
    private double _inspectorSplitterWidth;

    partial void OnFindTextChanged(string value)
    {
        _findIndex = -1;
    }

    public WildcardManagerViewModel(WildcardService wildcardService, TemplateService templateService)
    {
        _wildcardService = wildcardService;
        _templateService = templateService;
        SelectedTabIndex = 0;
        LoadWildcardsCommand.Execute(null);
    }

    public WildcardService WildcardService => _wildcardService;

    public TemplateService TemplateService => _templateService;

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
        var selectedName = SelectedWildcard?.Name;
        var entries = await _wildcardService.GetWildcardFileEntries(ShowArchived);
        var sorted = entries.OrderBy(e => e.Name, StringComparer.OrdinalIgnoreCase).ToList();
        var filtered = ApplyFilter(sorted, FilterText).ToList();
        ThemeSuggestions = new ObservableCollection<string>(BuildThemeSuggestions());
        Wildcards = new ObservableCollection<WildcardFileEntry>(filtered);
        WildcardCount = sorted.Count;
        SelectedWildcard = !string.IsNullOrWhiteSpace(selectedName)
            ? Wildcards.FirstOrDefault(w => string.Equals(w.Name, selectedName, StringComparison.OrdinalIgnoreCase))
            : null;
        if (SelectedWildcard == null)
        {
            SelectedWildcard = Wildcards.FirstOrDefault();
        }
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
        var terms = filter
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (terms.Length == 0) return entries;

        var filtered = entries.Where(e =>
        {
            var haystack = BuildSearchBlob(e);
            return terms.All(term => haystack.Contains(term, StringComparison.OrdinalIgnoreCase));
        });
        return filtered;
    }

    [RelayCommand]
    private void ApplyThemeFilter(string? term)
    {
        if (string.IsNullOrWhiteSpace(term))
        {
            return;
        }

        var cleaned = term.Trim();
        if (string.IsNullOrWhiteSpace(FilterText))
        {
            FilterText = cleaned;
            return;
        }

        var tokens = FilterText
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (tokens.Any(t => string.Equals(t, cleaned, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }

        FilterText = $"{FilterText.Trim()} {cleaned}";
    }

    private string BuildSearchBlob(WildcardFileEntry entry)
    {
        var parts = new List<string> { entry.Name };
        if (!string.IsNullOrWhiteSpace(entry.Content))
        {
            parts.Add(entry.Content);
        }

        if (_wildcardService.GetStructuredWildcards().TryGetValue(entry.Name, out var structured))
        {
            if (!string.IsNullOrWhiteSpace(structured.Description))
            {
                parts.Add(structured.Description);
            }

            foreach (var choice in structured.Choices)
            {
                if (!string.IsNullOrWhiteSpace(choice.Value))
                {
                    parts.Add(choice.Value);
                }

                if (choice.Tags.Count > 0)
                {
                    parts.AddRange(choice.Tags.Where(t => !string.IsNullOrWhiteSpace(t)));
                }

                switch (choice.Includes)
                {
                    case string includeText when !string.IsNullOrWhiteSpace(includeText):
                        parts.Add(includeText);
                        break;
                    case IEnumerable<string> includes:
                        parts.AddRange(includes.Where(i => !string.IsNullOrWhiteSpace(i)));
                        break;
                }

                if (!string.IsNullOrWhiteSpace(choice.RequiresJson))
                {
                    parts.Add(choice.RequiresJson);
                }
            }
        }

        return string.Join('\n', parts);
    }

    private IEnumerable<string> BuildThemeSuggestions()
    {
        return _wildcardService.GetStructuredWildcards()
            .Values
            .SelectMany(w => w.Choices)
            .SelectMany(c => c.Tags)
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Select(t => t.Trim())
            .Where(t => t.Length >= 3)
            .GroupBy(t => t, StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key, StringComparer.OrdinalIgnoreCase)
            .Take(20)
            .Select(g => g.Key);
    }

    partial void OnSelectedWildcardChanged(WildcardFileEntry? value)
    {
        _ = HandleSelectedWildcardAsync(value);
    }

    partial void OnSelectedValidationIssueChanged(ValidationIssue? value)
    {
        CanResolveSelectedIssue = TryParseNearDuplicateIssue(value, out _, out _);
        SelectedIssueSummary = value == null
            ? "Select a validation issue to review it here."
            : value.Message;
        ResolvePrimaryIssueText = "Keep first";
        ResolveSecondaryIssueText = "Keep second";

        if (value == null) return;

        var location = value.Location?.ToLowerInvariant() ?? string.Empty;
        if (string.Equals(location, "json", StringComparison.OrdinalIgnoreCase))
        {
            SelectedTabIndex = 1;
        }
        else
        {
            SelectedTabIndex = 0;
        }

        if (TryParseNearDuplicateIssue(value, out var left, out var right))
        {
            ResolvePrimaryIssueText = $"Keep: {left}";
            ResolveSecondaryIssueText = $"Keep: {right}";
            InspectorTabIndex = 0;
            IsInspectorOpen = true;

            var match = Choices.FirstOrDefault(choice =>
                string.Equals(choice.Value, left, StringComparison.Ordinal) ||
                string.Equals(choice.Value, right, StringComparison.Ordinal));
            if (match != null)
            {
                SelectedChoice = match;
            }
        }

        SetStatus($"Selected issue: {value.Message}");
    }

    partial void OnIsInspectorOpenChanged(bool value)
    {
        InspectorToggleText = value ? "Hide Inspector" : "Show Inspector";
        InspectorPaneWidth = value ? 420 : 0;
        InspectorPaneOpacity = value ? 1 : 0;
        InspectorSplitterWidth = value ? 6 : 0;
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
            SimilarWildcards = new ObservableCollection<SimilarWildcardCandidate>();
            SimilarWildcardStatus = "Select a wildcard to see merge candidates.";
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
        await RefreshSimilarWildcardsAsync(value.Name);
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
        AddChoiceInternal("new choice", insertIndex);
    }

    [RelayCommand]
    private void AddQuickChoice()
    {
        var value = QuickAddChoiceText?.Trim();
        if (string.IsNullOrWhiteSpace(value))
        {
            AddChoice();
            return;
        }

        var insertIndex = SelectedChoice != null ? Choices.IndexOf(SelectedChoice) + 1 : Choices.Count;
        AddChoiceInternal(value, insertIndex);
        QuickAddChoiceText = string.Empty;
        SetStatus($"Added '{value}'.");
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
            var key = BuildCanonicalChoiceKey(choice.Value);
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

    [RelayCommand]
    private void SortChoices()
    {
        if (Choices.Count <= 1)
        {
            return;
        }

        var selectedValue = SelectedChoice?.Value;
        var ordered = Choices
            .OrderBy(choice => BuildCanonicalChoiceKey(choice.Value), StringComparer.OrdinalIgnoreCase)
            .ThenBy(choice => choice.Value, StringComparer.OrdinalIgnoreCase)
            .ToList();

        Choices = new ObservableCollection<WildcardChoiceViewModel>(ordered);
        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        if (!string.IsNullOrWhiteSpace(selectedValue))
        {
            SelectedChoice = Choices.FirstOrDefault(choice => string.Equals(choice.Value, selectedValue, StringComparison.Ordinal));
        }
        MarkStructuredDirty();
        SetStatus("Sorted choices by normalized text.");
    }

    [RelayCommand]
    private void NormalizeChoiceText()
    {
        if (Choices.Count == 0)
        {
            return;
        }

        var changed = 0;
        foreach (var choice in Choices)
        {
            var normalized = NormalizeChoiceDisplayText(choice.Value);
            if (!string.Equals(choice.Value, normalized, StringComparison.Ordinal))
            {
                choice.Value = normalized;
                changed++;
            }
        }

        UpdateChoiceWarnings();
        MarkStructuredDirty();
        SetStatus(changed == 0
            ? "Choice text was already normalized."
            : $"Normalized {changed} choice value(s).");
    }

    [RelayCommand]
    private void FindSimilarChoices()
    {
        ValidationErrors.Clear();
        if (Choices.Count <= 1)
        {
            SetStatus("Need at least two choices to compare.");
            return;
        }

        var matches = new HashSet<string>(StringComparer.Ordinal);
        for (var i = 0; i < Choices.Count; i++)
        {
            for (var j = i + 1; j < Choices.Count; j++)
            {
                if (!AreNearDuplicateChoices(Choices[i].Value, Choices[j].Value))
                {
                    continue;
                }

                var message = $"Possible near-duplicate: '{Choices[i].Value}' / '{Choices[j].Value}'";
                if (matches.Add(message))
                {
                    ValidationErrors.Add(new ValidationIssue(message, "near-duplicate"));
                }
            }
        }

        if (ValidationErrors.Count > 0)
        {
            InspectorTabIndex = 0;
            IsInspectorOpen = true;
            SelectedValidationIssue = ValidationErrors[0];
        }

        SetStatus(ValidationErrors.Count == 0
            ? "No near-duplicate choices found."
            : $"Found {ValidationErrors.Count} possible near-duplicate choice pair(s).");
    }

    [RelayCommand]
    private void MergeSelectedIssueKeepPrimary()
    {
        ResolveSelectedNearDuplicateIssue(keepPrimary: true);
    }

    [RelayCommand]
    private void MergeSelectedIssueKeepSecondary()
    {
        ResolveSelectedNearDuplicateIssue(keepPrimary: false);
    }

    [RelayCommand]
    private void ToggleInspector()
    {
        IsInspectorOpen = !IsInspectorOpen;
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

    private async Task RefreshSimilarWildcardsAsync(string wildcardName)
    {
        if (string.IsNullOrWhiteSpace(wildcardName) ||
            !_wildcardService.GetStructuredWildcards().TryGetValue(wildcardName, out var current))
        {
            SimilarWildcards = new ObservableCollection<SimilarWildcardCandidate>();
            SimilarWildcardStatus = "Select a wildcard to see merge candidates.";
            return;
        }

        var templateUsage = await BuildTemplateUsageMapAsync();
        var currentTemplates = templateUsage.TryGetValue(wildcardName, out var usedBy)
            ? usedBy
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var candidates = _wildcardService.GetStructuredWildcards()
            .Where(kvp => !string.Equals(kvp.Key, wildcardName, StringComparison.OrdinalIgnoreCase))
            .Select(kvp => BuildSimilarWildcardCandidate(wildcardName, current, currentTemplates, kvp.Key, kvp.Value, templateUsage))
            .Where(candidate => candidate != null)
            .Select(candidate => candidate!)
            .OrderByDescending(candidate => candidate.Score)
            .ThenBy(candidate => candidate.Name, StringComparer.OrdinalIgnoreCase)
            .Take(8)
            .ToList();

        SimilarWildcards = new ObservableCollection<SimilarWildcardCandidate>(candidates);
        SimilarWildcardStatus = candidates.Count == 0
            ? "No strong overlap detected. This wildcard looks distinct."
            : $"Showing {candidates.Count} likely overlap candidate(s).";
    }

    public async Task MergeWildcardIntoCurrentAsync(string sourceName)
    {
        var targetName = CurrentWildcardName?.Trim();
        if (string.IsNullOrWhiteSpace(targetName) || string.IsNullOrWhiteSpace(sourceName))
        {
            SetStatus("Pick a target and source wildcard first.");
            return;
        }

        if (string.Equals(targetName, sourceName, StringComparison.OrdinalIgnoreCase))
        {
            SetStatus("Source and target wildcard are the same.");
            return;
        }

        var structured = _wildcardService.GetStructuredWildcards();
        if (!structured.TryGetValue(targetName, out var target) || !structured.TryGetValue(sourceName, out var source))
        {
            SetStatus("Could not load wildcard data for merge.");
            return;
        }

        var sourceEntry = (await _wildcardService.GetWildcardFileEntries(includeArchived: true))
            .FirstOrDefault(w => string.Equals(w.Name, sourceName, StringComparison.OrdinalIgnoreCase));
        if (sourceEntry == null)
        {
            SetStatus($"Could not find source wildcard file for '{sourceName}'.");
            return;
        }

        var merged = MergeStructuredWildcards(targetName, target, source);
        var mergedContent = SerializeStructuredWildcard(merged.Structured);

        await _wildcardService.SaveWildcardFileContent(targetName, mergedContent);
        var updatedTemplates = await ReplaceWildcardReferencesInTemplatesAsync(sourceName, targetName);
        await _wildcardService.DeleteWildcardFileByPath(sourceEntry.FilePath);

        await LoadWildcardsAsync();
        SelectWildcardByName(targetName);
        SetStatus($"Merged '{sourceName}' into '{targetName}'. Added {merged.AddedChoices} new choice(s), merged {merged.MergedChoices} duplicate(s), updated {updatedTemplates} template(s).");
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

    public int AddChoicesFromLines(string? rawText)
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return 0;
        }

        var added = 0;
        var insertIndex = SelectedChoice != null ? Choices.IndexOf(SelectedChoice) + 1 : Choices.Count;
        foreach (var line in rawText
                     .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var cleaned = Regex.Replace(line.Trim(), @"^[-*•]+\s*", string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(cleaned))
            {
                continue;
            }

            AddChoiceInternal(cleaned, insertIndex + added);
            added++;
        }

        if (added > 0)
        {
            SetStatus($"Added {added} choice(s).");
        }

        return added;
    }

    public int AppendChoicesFromWildcardJson(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return 0;
        }

        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("choices", out var choicesElement) || choicesElement.ValueKind != JsonValueKind.Array)
        {
            return 0;
        }

        var added = 0;
        var insertIndex = SelectedChoice != null ? Choices.IndexOf(SelectedChoice) + 1 : Choices.Count;
        foreach (var item in choicesElement.EnumerateArray())
        {
            var parsed = ParseChoiceFromJson(item);
            if (parsed == null || string.IsNullOrWhiteSpace(parsed.Value))
            {
                continue;
            }

            AddChoiceInternal(parsed, insertIndex + added);
            added++;
        }

        if (added > 0)
        {
            SetStatus($"Added {added} AI-suggested choice(s).");
        }

        return added;
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

    public void SetStatusMessage(string message) => Status = message;

    private void SetStatus(string message) => SetStatusMessage(message);

    private static bool IsLegacyText(string? path)
    {
        return !string.IsNullOrWhiteSpace(path) && path.EndsWith(".txt", StringComparison.OrdinalIgnoreCase);
    }

    private void AddChoiceInternal(WildcardChoice model, int insertIndex)
    {
        var vm = new WildcardChoiceViewModel(model, insertIndex + 1, MarkStructuredDirty)
        {
            Includes = model.Includes switch
            {
                string sInc => sInc,
                IEnumerable<string> arr => string.Join(", ", arr),
                _ => ""
            },
            Requires = model.RequiresJson ?? ""
        };

        Choices.Insert(Math.Clamp(insertIndex, 0, Choices.Count), vm);
        SelectedChoice = vm;
        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        MarkStructuredDirty();
    }

    private void AddChoiceInternal(string value, int insertIndex)
    {
        AddChoiceInternal(new WildcardChoice { Value = value }, insertIndex);
    }

    private static WildcardChoice? ParseChoiceFromJson(JsonElement element)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.String:
                return new WildcardChoice
                {
                    Value = element.GetString()?.Trim() ?? string.Empty
                };

            case JsonValueKind.Object:
                var value = string.Empty;
                if (element.TryGetProperty("value", out var valueProp) && valueProp.ValueKind == JsonValueKind.String)
                {
                    value = valueProp.GetString()?.Trim() ?? string.Empty;
                }
                else if (element.TryGetProperty("choice", out var choiceProp) && choiceProp.ValueKind == JsonValueKind.String)
                {
                    value = choiceProp.GetString()?.Trim() ?? string.Empty;
                }

                var choice = new WildcardChoice
                {
                    Value = value,
                    Weight = element.TryGetProperty("weight", out var weightProp) &&
                             weightProp.ValueKind == JsonValueKind.Number &&
                             weightProp.TryGetDouble(out var weight)
                        ? weight
                        : 1
                };

                if (element.TryGetProperty("tags", out var tagsProp))
                {
                    if (tagsProp.ValueKind == JsonValueKind.Array)
                    {
                        choice.Tags = tagsProp.EnumerateArray()
                            .Where(tag => tag.ValueKind == JsonValueKind.String)
                            .Select(tag => tag.GetString()?.Trim())
                            .Where(tag => !string.IsNullOrWhiteSpace(tag))
                            .ToList()!;
                    }
                    else if (tagsProp.ValueKind == JsonValueKind.String)
                    {
                        var tag = tagsProp.GetString()?.Trim();
                        if (!string.IsNullOrWhiteSpace(tag))
                        {
                            choice.Tags = new List<string> { tag };
                        }
                    }
                }

                if (element.TryGetProperty("includes", out var includesProp))
                {
                    choice.Includes = includesProp.ValueKind switch
                    {
                        JsonValueKind.String => includesProp.GetString()?.Trim(),
                        JsonValueKind.Array => includesProp.EnumerateArray()
                            .Where(item => item.ValueKind == JsonValueKind.String)
                            .Select(item => item.GetString()?.Trim())
                            .Where(item => !string.IsNullOrWhiteSpace(item))
                            .ToList(),
                        _ => null
                    };
                }

                if (element.TryGetProperty("requires", out var requiresProp))
                {
                    choice.RequiresJson = requiresProp.GetRawText();
                }

                return choice;

            default:
                return null;
        }
    }

    private static string NormalizeWhitespace(string input)
    {
        if (string.IsNullOrWhiteSpace(input)) return string.Empty;
        var collapsed = Regex.Replace(input.Trim(), @"\s+", " ");
        return collapsed;
    }

    private static string NormalizeChoiceDisplayText(string input)
    {
        var normalized = NormalizeWhitespace(input);
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return string.Empty;
        }

        normalized = Regex.Replace(normalized, @"^(a|an|the)\s+", string.Empty, RegexOptions.IgnoreCase);
        normalized = NormalizeWhitespace(normalized);
        return normalized;
    }

    private static string BuildCanonicalChoiceKey(string input)
    {
        var normalized = NormalizeChoiceDisplayText(input).ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return string.Empty;
        }

        normalized = Regex.Replace(normalized, @"[^a-z0-9\s]", " ");
        normalized = NormalizeWhitespace(normalized);
        return normalized;
    }

    private static bool AreNearDuplicateChoices(string left, string right)
    {
        var leftKey = BuildCanonicalChoiceKey(left);
        var rightKey = BuildCanonicalChoiceKey(right);
        if (string.IsNullOrWhiteSpace(leftKey) || string.IsNullOrWhiteSpace(rightKey) ||
            string.Equals(leftKey, rightKey, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var leftTokens = leftKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var rightTokens = rightKey.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (leftTokens.Length < 2 || rightTokens.Length < 2)
        {
            return false;
        }

        var shorter = leftTokens.Length <= rightTokens.Length ? leftTokens : rightTokens;
        var longer = leftTokens.Length <= rightTokens.Length ? rightTokens : leftTokens;
        var shorterSet = shorter.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var longerSet = longer.ToHashSet(StringComparer.OrdinalIgnoreCase);

        if (!shorterSet.IsSubsetOf(longerSet))
        {
            return false;
        }

        return longerSet.Count - shorterSet.Count <= 3;
    }

    private void ResolveSelectedNearDuplicateIssue(bool keepPrimary)
    {
        if (!TryParseNearDuplicateIssue(SelectedValidationIssue, out var left, out var right))
        {
            SetStatus("Select a near-duplicate validation issue first.");
            return;
        }

        var leftChoice = Choices.FirstOrDefault(choice => string.Equals(choice.Value, left, StringComparison.Ordinal));
        var rightChoice = Choices.FirstOrDefault(choice => string.Equals(choice.Value, right, StringComparison.Ordinal));
        if (leftChoice == null || rightChoice == null)
        {
            SetStatus("Could not find both choices for the selected issue.");
            return;
        }

        var keep = keepPrimary ? leftChoice : rightChoice;
        var remove = ReferenceEquals(keep, leftChoice) ? rightChoice : leftChoice;

        MergeChoiceInto(keep, remove);
        Choices.Remove(remove);
        SelectedChoice = keep;
        ValidationErrors.Remove(SelectedValidationIssue!);
        SelectedValidationIssue = null;
        UpdateChoiceIndices();
        UpdateChoiceWarnings();
        MarkStructuredDirty();

        SetStatus($"Resolved near-duplicate issue. Kept '{keep.Value}'.");
    }

    private static void MergeChoiceInto(WildcardChoiceViewModel target, WildcardChoiceViewModel source)
    {
        target.Weight = Math.Max(target.Weight, source.Weight);

        var mergedTags = (target.Tags ?? string.Empty)
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Concat((source.Tags ?? string.Empty)
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .Where(tag => !string.IsNullOrWhiteSpace(tag))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        target.Tags = string.Join(", ", mergedTags);

        var mergedIncludes = ExtractIncludes(target.Includes)
            .Concat(ExtractIncludes(source.Includes))
            .Where(include => !string.IsNullOrWhiteSpace(include))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        target.Includes = mergedIncludes.Count == 0 ? string.Empty : string.Join(", ", mergedIncludes);

        if (string.IsNullOrWhiteSpace(target.Requires) && !string.IsNullOrWhiteSpace(source.Requires))
        {
            target.Requires = source.Requires;
        }
    }

    private static bool TryParseNearDuplicateIssue(ValidationIssue? issue, out string left, out string right)
    {
        left = string.Empty;
        right = string.Empty;

        if (issue == null || !string.Equals(issue.Location, "near-duplicate", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var match = Regex.Match(issue.Message, @"'(?<left>[^']+)'\s*/\s*'(?<right>[^']+)'");
        if (!match.Success)
        {
            return false;
        }

        left = match.Groups["left"].Value;
        right = match.Groups["right"].Value;
        return !string.IsNullOrWhiteSpace(left) && !string.IsNullOrWhiteSpace(right);
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

    private async Task<Dictionary<string, HashSet<string>>> BuildTemplateUsageMapAsync()
    {
        var result = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        var names = await _templateService.GetTemplateNamesAsync();

        foreach (var templateName in names)
        {
            var content = await _templateService.LoadTemplateAsync(templateName);
            if (string.IsNullOrWhiteSpace(content))
            {
                continue;
            }

            foreach (Match match in Regex.Matches(content, @"__([^_]+(?:_[^_]+)*)__"))
            {
                if (!match.Success || match.Groups.Count < 2)
                {
                    continue;
                }

                var wildcardName = match.Groups[1].Value;
                if (string.IsNullOrWhiteSpace(wildcardName))
                {
                    continue;
                }

                if (!result.TryGetValue(wildcardName, out var templates))
                {
                    templates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    result[wildcardName] = templates;
                }

                templates.Add(templateName);
            }
        }

        return result;
    }

    private SimilarWildcardCandidate? BuildSimilarWildcardCandidate(
        string currentName,
        StructuredWildcard current,
        HashSet<string> currentTemplates,
        string candidateName,
        StructuredWildcard candidate,
        IReadOnlyDictionary<string, HashSet<string>> templateUsage)
    {
        var currentValues = current.Choices
            .Select(c => NormalizeWhitespace(c.Value).ToLowerInvariant())
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var candidateValues = candidate.Choices
            .Select(c => NormalizeWhitespace(c.Value).ToLowerInvariant())
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var sharedValues = currentValues.Intersect(candidateValues, StringComparer.OrdinalIgnoreCase).ToList();

        var currentTags = current.Choices
            .SelectMany(c => c.Tags ?? new List<string>())
            .Select(t => NormalizeWhitespace(t).ToLowerInvariant())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var candidateTags = candidate.Choices
            .SelectMany(c => c.Tags ?? new List<string>())
            .Select(t => NormalizeWhitespace(t).ToLowerInvariant())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var sharedTags = currentTags.Intersect(candidateTags, StringComparer.OrdinalIgnoreCase).ToList();

        var currentNameTokens = TokenizeForSimilarity(currentName);
        var candidateNameTokens = TokenizeForSimilarity(candidateName);
        var sharedNameTokens = currentNameTokens.Intersect(candidateNameTokens, StringComparer.OrdinalIgnoreCase).ToList();

        var currentDescriptionTerms = TokenizeForSimilarity(current.Description);
        var candidateDescriptionTerms = TokenizeForSimilarity(candidate.Description);
        var sharedDescriptionTerms = currentDescriptionTerms.Intersect(candidateDescriptionTerms, StringComparer.OrdinalIgnoreCase).ToList();

        var candidateTemplates = templateUsage.TryGetValue(candidateName, out var usedBy)
            ? usedBy
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var sharedTemplates = currentTemplates.Intersect(candidateTemplates, StringComparer.OrdinalIgnoreCase).ToList();

        var valueRatio = ComputeOverlapRatio(currentValues.Count, candidateValues.Count, sharedValues.Count);
        var tagRatio = ComputeOverlapRatio(currentTags.Count, candidateTags.Count, sharedTags.Count);
        var nameRatio = ComputeOverlapRatio(currentNameTokens.Count, candidateNameTokens.Count, sharedNameTokens.Count);
        var descriptionRatio = ComputeOverlapRatio(currentDescriptionTerms.Count, candidateDescriptionTerms.Count, sharedDescriptionTerms.Count);
        var templateRatio = ComputeOverlapRatio(currentTemplates.Count, candidateTemplates.Count, sharedTemplates.Count);

        var score = (int)Math.Round(
            (valueRatio * 55.0) +
            (tagRatio * 18.0) +
            (nameRatio * 17.0) +
            (descriptionRatio * 5.0) +
            (templateRatio * 5.0));

        if (score < 16 && sharedValues.Count == 0 && sharedTags.Count == 0 && sharedTemplates.Count == 0)
        {
            return null;
        }

        var summaryParts = new List<string>();
        if (sharedValues.Count > 0)
        {
            summaryParts.Add($"{sharedValues.Count} shared choice(s)");
        }
        if (sharedTags.Count > 0)
        {
            summaryParts.Add($"{sharedTags.Count} shared tag(s)");
        }
        if (sharedTemplates.Count > 0)
        {
            summaryParts.Add($"{sharedTemplates.Count} shared template(s)");
        }
        if (summaryParts.Count == 0 && sharedNameTokens.Count > 0)
        {
            summaryParts.Add($"similar naming: {string.Join(", ", sharedNameTokens.Take(3))}");
        }

        return new SimilarWildcardCandidate
        {
            Name = candidateName,
            Score = score,
            ScoreText = $"{Math.Clamp(score, 0, 99)}% overlap",
            Summary = string.Join(" | ", summaryParts),
            Preview = BuildSimilarityPreview(sharedValues, sharedTags, sharedTemplates)
        };
    }

    private static double ComputeOverlapRatio(int leftCount, int rightCount, int intersectionCount)
    {
        var union = leftCount + rightCount - intersectionCount;
        if (union <= 0)
        {
            return 0;
        }

        return intersectionCount / (double)union;
    }

    private static HashSet<string> TokenizeForSimilarity(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        return text
            .Split(new[] { ' ', '_', '-', ',', '.', ';', ':', '\n', '\r', '\t', '/', '\\', '(', ')', '[', ']' }, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(token => token.Length >= 3)
            .Select(token => token.ToLowerInvariant())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static string BuildSimilarityPreview(
        IReadOnlyList<string> sharedValues,
        IReadOnlyList<string> sharedTags,
        IReadOnlyList<string> sharedTemplates)
    {
        var lines = new List<string>();
        if (sharedValues.Count > 0)
        {
            lines.Add($"Shared values: {string.Join(", ", sharedValues.Take(5))}");
        }
        if (sharedTags.Count > 0)
        {
            lines.Add($"Shared tags: {string.Join(", ", sharedTags.Take(5))}");
        }
        if (sharedTemplates.Count > 0)
        {
            lines.Add($"Shared templates: {string.Join(", ", sharedTemplates.Take(4))}");
        }

        return lines.Count == 0 ? "Name and description overlap only." : string.Join(Environment.NewLine, lines);
    }

    private async Task<int> ReplaceWildcardReferencesInTemplatesAsync(string sourceName, string targetName)
    {
        var sourceToken = $"__{sourceName}__";
        var targetToken = $"__{targetName}__";
        var updated = 0;

        foreach (var templateName in await _templateService.GetTemplateNamesAsync())
        {
            var content = await _templateService.LoadTemplateAsync(templateName);
            if (string.IsNullOrWhiteSpace(content) || !content.Contains(sourceToken, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var replaced = ReplaceIgnoreCase(content, sourceToken, targetToken);
            if (string.Equals(replaced, content, StringComparison.Ordinal))
            {
                continue;
            }

            await _templateService.SaveTemplateAsync(templateName, replaced);
            updated++;
        }

        return updated;
    }

    private static SimilarWildcardMergeResult MergeStructuredWildcards(string targetName, StructuredWildcard target, StructuredWildcard source)
    {
        var merged = new StructuredWildcard
        {
            Name = targetName,
            Description = !string.IsNullOrWhiteSpace(target.Description)
                ? target.Description
                : source.Description,
            Includes = target.Includes ?? source.Includes
        };

        var mergedChoices = new List<WildcardChoice>();
        var choiceMap = new Dictionary<string, WildcardChoice>(StringComparer.OrdinalIgnoreCase);
        var addedChoices = 0;
        var mergedChoiceCount = 0;

        foreach (var choice in target.Choices)
        {
            var clone = CloneChoice(choice);
            mergedChoices.Add(clone);
            var key = NormalizeWhitespace(clone.Value);
            if (!string.IsNullOrWhiteSpace(key))
            {
                choiceMap[key] = clone;
            }
        }

        foreach (var choice in source.Choices)
        {
            var key = NormalizeWhitespace(choice.Value);
            if (string.IsNullOrWhiteSpace(key))
            {
                continue;
            }

            if (choiceMap.TryGetValue(key, out var existing))
            {
                MergeChoiceMetadata(existing, choice);
                mergedChoiceCount++;
                continue;
            }

            var clone = CloneChoice(choice);
            mergedChoices.Add(clone);
            choiceMap[key] = clone;
            addedChoices++;
        }

        merged.Choices = mergedChoices;
        return new SimilarWildcardMergeResult(merged, addedChoices, mergedChoiceCount);
    }

    private static WildcardChoice CloneChoice(WildcardChoice choice)
    {
        return new WildcardChoice
        {
            Value = choice.Value,
            Weight = choice.Weight,
            Tags = choice.Tags?.Where(t => !string.IsNullOrWhiteSpace(t)).Distinct(StringComparer.OrdinalIgnoreCase).ToList() ?? new List<string>(),
            Includes = CloneIncludes(choice.Includes),
            RequiresJson = choice.RequiresJson
        };
    }

    private static object? CloneIncludes(object? includes)
    {
        return includes switch
        {
            null => null,
            string text => text,
            IEnumerable<string> values => values.Where(v => !string.IsNullOrWhiteSpace(v)).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
            _ => includes
        };
    }

    private static void MergeChoiceMetadata(WildcardChoice target, WildcardChoice source)
    {
        target.Weight = Math.Max(target.Weight, source.Weight);

        target.Tags = target.Tags
            .Concat(source.Tags ?? new List<string>())
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        target.Includes = MergeIncludes(target.Includes, source.Includes);
        if (string.IsNullOrWhiteSpace(target.RequiresJson) && !string.IsNullOrWhiteSpace(source.RequiresJson))
        {
            target.RequiresJson = source.RequiresJson;
        }
    }

    private static object? MergeIncludes(object? left, object? right)
    {
        var combined = new List<string>();

        void AddIncludes(object? includes)
        {
            switch (includes)
            {
                case null:
                    return;
                case string text when !string.IsNullOrWhiteSpace(text):
                    combined.Add(text.Trim());
                    break;
                case IEnumerable<string> values:
                    combined.AddRange(values.Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v.Trim()));
                    break;
            }
        }

        AddIncludes(left);
        AddIncludes(right);

        var distinct = combined
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        return distinct.Count switch
        {
            0 => null,
            1 => distinct[0],
            _ => distinct
        };
    }

    private static string SerializeStructuredWildcard(StructuredWildcard structured)
    {
        var payload = new
        {
            description = string.IsNullOrWhiteSpace(structured.Description) ? null : structured.Description,
            includes = structured.Includes,
            choices = structured.Choices.Select(choice => new
            {
                value = choice.Value,
                weight = choice.Weight,
                tags = choice.Tags?.Where(t => !string.IsNullOrWhiteSpace(t)).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
                includes = choice.Includes,
                requires = ParseRequires(choice.RequiresJson)
            }).ToList()
        };

        return JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
    }
}

public record ValidationIssue(string Message, string Location);
public sealed class SimilarWildcardCandidate
{
    public string Name { get; init; } = string.Empty;
    public int Score { get; init; }
    public string ScoreText { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
    public string Preview { get; init; } = string.Empty;
}

public sealed record SimilarWildcardMergeResult(StructuredWildcard Structured, int AddedChoices, int MergedChoices);
