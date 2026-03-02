using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public sealed record ExperimentRunRequest(
    string Mode,
    int RunCount,
    string? WildcardName,
    IReadOnlyList<string> SelectedChoices,
    IReadOnlyDictionary<string, string> LockedChoices,
    bool SaveSelectionsToHistory);

public partial class ExperimentRunnerViewModel : ObservableObject
{
    public const string NTemplateRollsMode = "N Template Rolls";
    public const string WildcardChoiceSweepMode = "Wildcard Choice Sweep";
    public const string SeedSweepMode = "Seed Sweep";

    private readonly IReadOnlyDictionary<string, StructuredWildcard> _structuredWildcards;
    private readonly Func<string?, IReadOnlyDictionary<string, string>, TemplateGenerationResult>? _baselinePromptBuilder;
    private readonly Dictionary<string, string> _lockedChoices = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty] private ObservableCollection<string> _modes = new();
    [ObservableProperty] private string _selectedMode = NTemplateRollsMode;
    [ObservableProperty] private int _runCount = 10;
    [ObservableProperty] private ObservableCollection<string> _availableWildcards = new();
    [ObservableProperty] private string? _selectedWildcard;
    [ObservableProperty] private ObservableCollection<ExperimentChoiceOptionViewModel> _choiceOptions = new();
    [ObservableProperty] private ObservableCollection<PromptSegmentViewModel> _baselinePromptSegments = new();
    [ObservableProperty] private string _baselinePromptPreview = "";
    [ObservableProperty] private bool _saveSelectionsToHistory = true;
    [ObservableProperty] private string _statusMessage = "";
    [ObservableProperty] private bool? _dialogResult;

    public event EventHandler? RequestClose;

    public ExperimentRunRequest? Result { get; private set; }

    public bool IsWildcardSweepMode => string.Equals(SelectedMode, WildcardChoiceSweepMode, StringComparison.Ordinal);
    public bool UsesRunCount => !IsWildcardSweepMode;

    public ExperimentRunnerViewModel()
        : this(
            Array.Empty<string>(),
            new Dictionary<string, StructuredWildcard>(StringComparer.OrdinalIgnoreCase),
            new Dictionary<string, ContextValue>(StringComparer.OrdinalIgnoreCase),
            null,
            null)
    {
    }

    public ExperimentRunnerViewModel(
        IEnumerable<string> availableWildcards,
        IReadOnlyDictionary<string, StructuredWildcard> structuredWildcards,
        IReadOnlyDictionary<string, ContextValue>? initialContext = null,
        Func<string?, IReadOnlyDictionary<string, string>, TemplateGenerationResult>? baselinePromptBuilder = null,
        string? initialMode = null)
    {
        _structuredWildcards = structuredWildcards;
        _baselinePromptBuilder = baselinePromptBuilder;
        Modes = new ObservableCollection<string>(new[]
        {
            NTemplateRollsMode,
            WildcardChoiceSweepMode,
            SeedSweepMode
        });

        var wildcardList = availableWildcards
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
        AvailableWildcards = new ObservableCollection<string>(wildcardList);
        InitializeLockedChoices(wildcardList, initialContext);

        if (!string.IsNullOrWhiteSpace(initialMode) && Modes.Contains(initialMode))
        {
            SelectedMode = initialMode;
        }

        SelectedWildcard = AvailableWildcards.FirstOrDefault();
        UpdateChoiceOptions();
        UpdateStatus();
        UpdateBaselinePromptPreview();
    }

    partial void OnSelectedModeChanged(string value)
    {
        OnPropertyChanged(nameof(IsWildcardSweepMode));
        OnPropertyChanged(nameof(UsesRunCount));
        UpdateStatus();
        UpdateBaselinePromptPreview();
    }

    partial void OnSelectedWildcardChanged(string? value)
    {
        UpdateSweepTargetPlaceholder();
        UpdateChoiceOptions();
        UpdateStatus();
        UpdateBaselinePromptPreview();
    }

    [RelayCommand]
    private void SelectAllChoices()
    {
        foreach (var option in ChoiceOptions)
        {
            option.IsSelected = true;
        }
    }

    [RelayCommand]
    private void ClearChoiceSelection()
    {
        foreach (var option in ChoiceOptions)
        {
            option.IsSelected = false;
        }
    }

    [RelayCommand]
    private void Run()
    {
        StatusMessage = string.Empty;

        if (IsWildcardSweepMode)
        {
            var selectedChoices = ChoiceOptions
                .Where(option => option.IsSelected)
                .Select(option => option.Value)
                .ToList();

            if (string.IsNullOrWhiteSpace(SelectedWildcard))
            {
                StatusMessage = "Select a wildcard to sweep.";
                return;
            }

            if (selectedChoices.Count == 0)
            {
                StatusMessage = "Select at least one wildcard choice.";
                return;
            }

            Result = new ExperimentRunRequest(
                WildcardChoiceSweepMode,
                selectedChoices.Count,
                SelectedWildcard,
                selectedChoices,
                BuildLockedChoices(),
                SaveSelectionsToHistory);
        }
        else
        {
            if (RunCount < 1 || RunCount > 200)
            {
                StatusMessage = "Run count must be between 1 and 200.";
                return;
            }

            Result = new ExperimentRunRequest(
                SelectedMode,
                RunCount,
                null,
                Array.Empty<string>(),
                new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase),
                SaveSelectionsToHistory);
        }

        DialogResult = true;
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    [RelayCommand]
    private void Cancel()
    {
        DialogResult = false;
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    public IReadOnlyList<string> GetChoicesForBaselineSegment(PromptSegmentViewModel? segment)
    {
        if (segment == null ||
            !segment.IsWildcard ||
            string.IsNullOrWhiteSpace(segment.WildcardName) ||
            string.Equals(segment.WildcardName, SelectedWildcard, StringComparison.OrdinalIgnoreCase) ||
            !_structuredWildcards.TryGetValue(segment.WildcardName, out var wildcard))
        {
            return Array.Empty<string>();
        }

        return wildcard.Choices
            .Where(choice => !string.IsNullOrWhiteSpace(choice.Value))
            .GroupBy(choice => choice.Value, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First().Value)
            .OrderBy(value => value, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public void ApplyBaselineChoice(PromptSegmentViewModel? segment, string value)
    {
        if (segment == null ||
            string.IsNullOrWhiteSpace(segment.WildcardName) ||
            string.IsNullOrWhiteSpace(value) ||
            string.Equals(segment.WildcardName, SelectedWildcard, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        _lockedChoices[segment.WildcardName] = value;
        UpdateBaselinePromptPreview();
    }

    private void UpdateChoiceOptions()
    {
        var selectedValues = ChoiceOptions
            .Where(option => option.IsSelected)
            .Select(option => option.Value)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        ChoiceOptions.Clear();
        if (string.IsNullOrWhiteSpace(SelectedWildcard) ||
            !_structuredWildcards.TryGetValue(SelectedWildcard, out var wildcard))
        {
            return;
        }

        foreach (var choice in wildcard.Choices
                     .Where(choice => !string.IsNullOrWhiteSpace(choice.Value))
                     .GroupBy(choice => choice.Value, StringComparer.OrdinalIgnoreCase)
                     .Select(group => group.First())
                     .OrderBy(choice => choice.Value, StringComparer.OrdinalIgnoreCase))
        {
            ChoiceOptions.Add(new ExperimentChoiceOptionViewModel
            {
                Value = choice.Value,
                Tags = choice.Tags.Count > 0 ? string.Join(", ", choice.Tags) : string.Empty,
                IsSelected = selectedValues.Count == 0 || selectedValues.Contains(choice.Value)
            });
        }
    }

    private void InitializeLockedChoices(
        IReadOnlyList<string> wildcardList,
        IReadOnlyDictionary<string, ContextValue>? initialContext)
    {
        _lockedChoices.Clear();
        foreach (var wildcardName in wildcardList)
        {
            if (!_structuredWildcards.TryGetValue(wildcardName, out var wildcard))
            {
                continue;
            }

            var choices = wildcard.Choices
                .Where(choice => !string.IsNullOrWhiteSpace(choice.Value))
                .GroupBy(choice => choice.Value, StringComparer.OrdinalIgnoreCase)
                .Select(group => group.First().Value)
                .OrderBy(value => value, StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (choices.Count == 0)
            {
                continue;
            }

            var selected = initialContext != null &&
                           initialContext.TryGetValue(wildcardName, out var contextValue) &&
                           choices.Contains(contextValue.Value, StringComparer.OrdinalIgnoreCase)
                ? choices.First(value => string.Equals(value, contextValue.Value, StringComparison.OrdinalIgnoreCase))
                : choices[0];

            _lockedChoices[wildcardName] = selected;
        }

        UpdateSweepTargetPlaceholder();
    }

    private void UpdateSweepTargetPlaceholder()
    {
        if (!string.IsNullOrWhiteSpace(SelectedWildcard))
        {
            _lockedChoices[SelectedWildcard] = $"__{SelectedWildcard}__";
        }
    }

    private IReadOnlyDictionary<string, string> BuildLockedChoices()
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in _lockedChoices)
        {
            if (string.Equals(entry.Key, SelectedWildcard, StringComparison.OrdinalIgnoreCase) ||
                string.IsNullOrWhiteSpace(entry.Value))
            {
                continue;
            }

            result[entry.Key] = entry.Value;
        }

        return result;
    }

    private void UpdateBaselinePromptPreview()
    {
        BaselinePromptSegments.Clear();

        if (!IsWildcardSweepMode || _baselinePromptBuilder == null)
        {
            BaselinePromptPreview = string.Empty;
            return;
        }

        var result = _baselinePromptBuilder(SelectedWildcard, BuildLockedChoices());
        var textParts = new List<string>();
        var index = 0;
        foreach (var segment in result.Segments)
        {
            var vm = new PromptSegmentViewModel(segment, index++);
            BaselinePromptSegments.Add(vm);
            var trimmed = vm.Text?.Trim();
            if (!string.IsNullOrWhiteSpace(trimmed))
            {
                textParts.Add(trimmed);
            }
        }

        BaselinePromptPreview = string.Join(" ", textParts);
    }

    private void UpdateStatus()
    {
        if (IsWildcardSweepMode)
        {
            StatusMessage = AvailableWildcards.Count == 0
                ? "Add a wildcard to the current prompt before running a wildcard sweep."
                : "Choose the sweep wildcard, then click wildcard segments in the baseline prompt to lock the rest.";
            return;
        }

        StatusMessage = string.Equals(SelectedMode, SeedSweepMode, StringComparison.Ordinal)
            ? "Reuse one resolved prompt and vary only the seed."
            : "Resolve the current template fresh for each run.";
    }
}

public partial class ExperimentChoiceOptionViewModel : ObservableObject
{
    [ObservableProperty] private string _value = string.Empty;
    [ObservableProperty] private string _tags = string.Empty;
    [ObservableProperty] private bool _isSelected = true;
}
