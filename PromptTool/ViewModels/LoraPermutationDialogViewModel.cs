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
    public ObservableCollection<LoraPermutationViewModel> Permutations { get; } = new();

    [ObservableProperty]
    private LoraPermutationViewModel? _selectedPermutation;

    public event EventHandler? RequestClose;

    public List<List<LoraParameter>>? Result { get; private set; }

    public LoraPermutationDialogViewModel(
        IReadOnlyList<InvokeAIModel> availableLoras,
        IEnumerable<LoraParameter>? initialLoras)
    {
        LoraOptions = new ObservableCollection<LoraOptionViewModel>(
            new[] { new LoraOptionViewModel("(None)", null) }
                .Concat(availableLoras
                    .OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase)
                    .Select(m => new LoraOptionViewModel(m.Name ?? "(Unnamed)", m))));

        AddPermutation(initialLoras);
        SelectedPermutation = Permutations.FirstOrDefault();
        Permutations.CollectionChanged += OnPermutationsChanged;
        ReindexPermutations();
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
    }

    [RelayCommand]
    private void AddLoraRow()
    {
        SelectedPermutation?.AddRow(CreateRow(null));
    }

    [RelayCommand]
    private void DeleteLoraRow(LoraPermutationRowViewModel? row)
    {
        if (row == null || SelectedPermutation == null) return;
        SelectedPermutation.RemoveRow(row);
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
        else
        {
            perm.AddRow(CreateRow(null));
        }

        Permutations.Add(perm);
        SelectedPermutation = perm;
        ReindexPermutations();
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
            row.SelectedOption = LoraOptions.FirstOrDefault();
            row.Weight = 0.75;
        }
        return row;
    }

    private void OnPermutationsChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ReindexPermutations();
    }

    private void ReindexPermutations()
    {
        for (var i = 0; i < Permutations.Count; i++)
        {
            Permutations[i].SetIndex(i + 1);
        }
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

}

public partial class LoraPermutationViewModel : ObservableObject
{
    public ObservableCollection<LoraPermutationRowViewModel> Rows { get; } = new();

    [ObservableProperty]
    private string _displayName = "";

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
        if (e.PropertyName == nameof(LoraPermutationRowViewModel.SelectedOption))
        {
            UpdateDisplayName();
        }
    }

    private void UpdateDisplayName()
    {
        var loraNames = Rows
            .Select(r => r.SelectedOption?.Name)
            .Where(n => !string.IsNullOrWhiteSpace(n) && n != "(None)")
            .ToList();

        DisplayName = loraNames.Count == 0
            ? $"Permutation {_index}"
            : $"Permutation {_index} ({string.Join(" + ", loraNames)})";
    }
}
