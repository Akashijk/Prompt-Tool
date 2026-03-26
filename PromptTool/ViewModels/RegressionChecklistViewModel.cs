using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace PromptTool.ViewModels;

public partial class RegressionChecklistViewModel : ObservableObject
{
    public ObservableCollection<RegressionChecklistItemViewModel> Items { get; } = new();

    [ObservableProperty]
    private string _summaryText = string.Empty;

    [ObservableProperty]
    private string _statusText = "Run this after refactors to catch regressions early.";

    public event EventHandler? RequestClose;

    public RegressionChecklistViewModel()
    {
        AddItem("Generate image (fresh prompt)", "Confirm model/scheduler/LoRA/defaults apply and images complete.");
        AddItem("Edit & regenerate from history", "Must recreate the expected image with unchanged params.");
        AddItem("Generate more from image", "Seed/LoRA/model variations enqueue and execute correctly.");
        AddItem("Save selected to history", "Images append/save immediately without needing filter toggles.");
        AddItem("Replay old history entry", "Model resolution fallback works after server restore/key changes.");
        AddItem("Prompt variations", "Runs execute, preserve prompts, and save lineage correctly.");
        AddItem("Queue completion alert", "Sound only plays when queue is fully empty.");
        AddItem("Cancellation behavior", "Closing preview/tuner cancels server jobs and local queue state.");

        RefreshSummary();
    }

    [RelayCommand]
    private void MarkAllPassed()
    {
        foreach (var item in Items)
        {
            item.Passed = true;
        }
        StatusText = "All checks marked as passed.";
    }

    [RelayCommand]
    private void ResetChecklist()
    {
        foreach (var item in Items)
        {
            item.Passed = false;
        }
        StatusText = "Checklist reset.";
    }

    [RelayCommand]
    private void Close()
    {
        RequestClose?.Invoke(this, EventArgs.Empty);
    }

    private void AddItem(string title, string notes)
    {
        var item = new RegressionChecklistItemViewModel(title, notes);
        item.PropertyChanged += OnItemPropertyChanged;
        Items.Add(item);
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(RegressionChecklistItemViewModel.Passed))
        {
            RefreshSummary();
        }
    }

    private void RefreshSummary()
    {
        var total = Items.Count;
        var passed = Items.Count(i => i.Passed);
        SummaryText = $"Passed {passed}/{total}";
    }
}

public partial class RegressionChecklistItemViewModel : ObservableObject
{
    public RegressionChecklistItemViewModel(string title, string notes)
    {
        Title = title;
        Notes = notes;
    }

    public string Title { get; }
    public string Notes { get; }

    [ObservableProperty]
    private bool _passed;
}

