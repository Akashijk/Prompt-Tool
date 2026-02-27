using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class LoraPermutationDialogViewModel : ObservableObject
{
    public ObservableCollection<LoraOptionViewModel> LoraOptions { get; }
    public ObservableCollection<LoraOptionViewModel> FilteredLoraOptions { get; } = new();
    public ObservableCollection<LoraPermutationViewModel> Permutations { get; } = new();

    [ObservableProperty]
    private LoraPermutationViewModel? _selectedPermutation;
    [ObservableProperty]
    private double _loraOptionsDropdownWidth;
    [ObservableProperty]
    private string _loraSearchText = "";
    [ObservableProperty]
    private string _summaryText = "";
    [ObservableProperty]
    private LoraOptionViewModel? _selectedLoraOption;

    public event EventHandler? RequestClose;

    public List<List<LoraParameter>>? Result { get; private set; }

    public LoraPermutationDialogViewModel(
        IReadOnlyList<InvokeAIModel> availableLoras,
        IEnumerable<LoraParameter>? initialLoras)
    {
        LoraOptions = new ObservableCollection<LoraOptionViewModel>(
            availableLoras
                .OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase)
                .Select(m => new LoraOptionViewModel(m.Name ?? "(Unnamed)", m)));

        LoraOptionsDropdownWidth = CalculateDropdownWidth(LoraOptions.Select(o => o.Name), 240, 420);

        AddPermutation(initialLoras);
        SelectedPermutation = Permutations.FirstOrDefault();
        Permutations.CollectionChanged += OnPermutationsChanged;
        ReindexPermutations();
        ApplyLoraFilter();
        UpdateSummaryText();
    }

    [RelayCommand]
    private void AddPermutation()
    {
        AddPermutation(null);
    }

    [RelayCommand]
    private void DuplicatePermutation()
    {
        if (SelectedPermutation == null) return;
        var cloned = SelectedPermutation.Rows
            .Select(r => r.SelectedOption?.Model is { } model
                ? new LoraParameter { Lora = model, Weight = r.Weight }
                : null)
            .Where(p => p != null)
            .Select(p => p!)
            .ToList();
        AddPermutation(cloned);
    }

    [RelayCommand]
    private void RemovePermutation()
    {
        if (SelectedPermutation == null) return;
        var index = Permutations.IndexOf(SelectedPermutation);
        Permutations.Remove(SelectedPermutation);
        if (Permutations.Count == 0)
        {
            AddPermutation(null);
            SelectedPermutation = Permutations.FirstOrDefault();
            return;
        }
        SelectedPermutation = Permutations[Math.Clamp(index, 0, Permutations.Count - 1)];
        UpdateSummaryText();
    }

    [RelayCommand]
    private void AddLoraRow()
    {
        SelectedPermutation?.AddRow(CreateRow(null));
    }

    [RelayCommand]
    private void AddLoraOption(LoraOptionViewModel? option)
    {
        if (option?.Model == null || SelectedPermutation == null) return;
        if (SelectedPermutation.ContainsModel(option.Model)) return;
        SelectedPermutation.AddRow(CreateRow(new LoraParameter { Lora = option.Model, Weight = 0.75 }));
        UpdateSummaryText();
    }

    [RelayCommand]
    private void AddSelectedLoraOption()
    {
        AddLoraOption(SelectedLoraOption);
    }

    [RelayCommand]
    private void ClearSelectedPermutation()
    {
        if (SelectedPermutation == null) return;
        SelectedPermutation.ClearRows();
        UpdateSummaryText();
    }

    [RelayCommand]
    private void DeleteLoraRow(LoraPermutationRowViewModel? row)
    {
        if (row == null || SelectedPermutation == null) return;
        SelectedPermutation.RemoveRow(row);
        UpdateSummaryText();
    }

    [RelayCommand]
    private void Generate()
    {
        var result = new List<List<LoraParameter>>();
        foreach (var perm in Permutations)
        {
            var loras = new List<LoraParameter>();
            foreach (var row in perm.Rows)
            {
                var model = row.SelectedOption?.Model;
                if (model == null) continue;
                loras.Add(new LoraParameter { Lora = model, Weight = row.Weight });
            }
            result.Add(loras);
        }

        if (result.Count == 0)
        {
            result.Add(new List<LoraParameter>());
        }

        Result = result;
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    [RelayCommand]
    private void Cancel()
    {
        Result = null;
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    private void AddPermutation(IEnumerable<LoraParameter>? initialLoras)
    {
        var perm = new LoraPermutationViewModel();
        if (initialLoras != null)
        {
            foreach (var lora in initialLoras)
            {
                perm.AddRow(CreateRow(lora));
            }
        }

        Permutations.Add(perm);
        SelectedPermutation = perm;
        ReindexPermutations();
        UpdateSummaryText();
    }

    private LoraPermutationRowViewModel CreateRow(LoraParameter? lora)
    {
        var row = new LoraPermutationRowViewModel();
        if (lora?.Lora != null)
        {
            row.SelectedOption = LoraOptions.FirstOrDefault(o =>
                o.Model != null &&
                string.Equals(o.Model.Name, lora.Lora.Name, StringComparison.OrdinalIgnoreCase));
            row.Weight = lora.Weight;
        }
        else
        {
            row.SelectedOption = null;
            row.Weight = 0.75;
        }
        return row;
    }

    private void OnPermutationsChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ReindexPermutations();
        UpdateSummaryText();
    }

    private static double CalculateDropdownWidth(IEnumerable<string> items, double minWidth, double maxWidth)
    {
        var maxLen = items.Select(i => i?.Length ?? 0).DefaultIfEmpty(0).Max();
        var width = maxLen * 7.5 + 48;
        return Math.Min(maxWidth, Math.Max(minWidth, width));
    }

    private void ReindexPermutations()
    {
        for (var i = 0; i < Permutations.Count; i++)
        {
            Permutations[i].SetIndex(i + 1);
        }
    }

    partial void OnSelectedPermutationChanged(LoraPermutationViewModel? value)
    {
        UpdateSummaryText();
    }

    partial void OnLoraSearchTextChanged(string value)
    {
        ApplyLoraFilter();
    }

    private void ApplyLoraFilter()
    {
        FilteredLoraOptions.Clear();
        var term = (LoraSearchText ?? string.Empty).Trim();
        var filtered = string.IsNullOrWhiteSpace(term)
            ? LoraOptions
            : LoraOptions.Where(o => o.Name.Contains(term, StringComparison.OrdinalIgnoreCase));
        foreach (var option in filtered)
        {
            FilteredLoraOptions.Add(option);
        }
        if (SelectedLoraOption != null && !FilteredLoraOptions.Contains(SelectedLoraOption))
        {
            SelectedLoraOption = FilteredLoraOptions.FirstOrDefault();
        }
    }

    private void UpdateSummaryText()
    {
        var totalPerms = Permutations.Count;
        var totalRows = Permutations.Sum(p => p.Rows.Count);
        SummaryText = $"Permutations: {totalPerms} · LoRAs: {totalRows}";
    }
}

public sealed class LoraOptionViewModel
{
    public string Name { get; }
    public InvokeAIModel? Model { get; }

    public LoraOptionViewModel(string name, InvokeAIModel? model)
    {
        Name = name;
        Model = model;
    }
}

public partial class LoraPermutationRowViewModel : ObservableObject
{
    [ObservableProperty] private double _weight = 0.75;

//new lines
    private LoraOptionViewModel? _selectedOption;
    public LoraOptionViewModel? SelectedOption
    {
        get => _selectedOption;
        set
        {
            // Avalonia can push null during control teardown / rebinding.
            // Ignore it so switching permutations doesn't wipe the stored choice.
            if (value is null) return;

            SetProperty(ref _selectedOption, value);
        }
    }

    public bool HasModel => SelectedOption?.Model != null;

    public string DisplayName => SelectedOption?.Name ?? "(None)";

    [RelayCommand]
    private void SetWeight(string? value)
    {
        if (double.TryParse(value, out var weight))
        {
            Weight = weight;
        }
    }
}

public partial class LoraPermutationViewModel : ObservableObject
{
    public ObservableCollection<LoraPermutationRowViewModel> Rows { get; } = new();

    [ObservableProperty]
    private string _displayName = "";
    [ObservableProperty]
    private string _summary = "";
    [ObservableProperty]
    private bool _hasDuplicates;
    [ObservableProperty]
    private string _duplicateLabel = "";

    private int _index;

    public void SetIndex(int index)
    {
        _index = index;
        UpdateDisplayName();
    }

    public void AddRow(LoraPermutationRowViewModel row)
    {
        HookRow(row);
        Rows.Add(row);
        UpdateDisplayName();
    }

    public void ClearRows()
    {
        foreach (var row in Rows.ToList())
        {
            UnhookRow(row);
        }
        Rows.Clear();
        UpdateDisplayName();
    }

    public void RemoveRow(LoraPermutationRowViewModel row)
    {
        UnhookRow(row);
        Rows.Remove(row);
        UpdateDisplayName();
    }

    private void HookRow(LoraPermutationRowViewModel row)
    {
        row.PropertyChanged += RowOnPropertyChanged;
    }

    private void UnhookRow(LoraPermutationRowViewModel row)
    {
        row.PropertyChanged -= RowOnPropertyChanged;
    }

    private void RowOnPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LoraPermutationRowViewModel.SelectedOption)
            || e.PropertyName == nameof(LoraPermutationRowViewModel.Weight))
        {
            UpdateDisplayName();
        }
    }

    private void UpdateDisplayName()
    {
        var loraNames = Rows
            .Select(r => r.SelectedOption?.Name)
            .Where(n => !string.IsNullOrWhiteSpace(n))
            .ToList();

        var summaryParts = Rows
            .Where(r => r.SelectedOption?.Name != null)
            .Select(r => $"{r.SelectedOption!.Name} ({r.Weight:0.##})")
            .ToList();

        DisplayName = loraNames.Count == 0
            ? $"Permutation {_index}"
            : $"Permutation {_index} ({string.Join(" + ", loraNames)})";

        Summary = summaryParts.Count == 0
            ? "No LoRAs selected"
            : string.Join(" + ", summaryParts);

        var dupes = loraNames
            .GroupBy(n => n, StringComparer.OrdinalIgnoreCase)
            .Where(g => g.Count() > 1)
            .Select(g => g.Key)
            .ToList();

        HasDuplicates = dupes.Count > 0;
        DuplicateLabel = HasDuplicates ? $"Duplicate: {string.Join(", ", dupes)}" : string.Empty;
    }

    public bool ContainsModel(InvokeAIModel model)
    {
        return Rows.Any(r =>
            r.SelectedOption?.Model != null &&
            string.Equals(r.SelectedOption.Model.Name, model.Name, StringComparison.OrdinalIgnoreCase));
    }
}
