using System;
using System.Collections;
using System.Collections.ObjectModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class GenerationQueueViewModel : ObservableObject
{
    private readonly GenerationQueueService _queue;

    public ObservableCollection<GenerationJob> Jobs => _queue.Jobs;

    [ObservableProperty]
    private bool _isPaused;

    [ObservableProperty]
    private int _delayBetweenJobsMs;

    [ObservableProperty]
    private IList? _selectedJobs;

    [ObservableProperty]
    private bool _hasCancelableSelection;

    public GenerationQueueViewModel(GenerationQueueService queue)
    {
        _queue = queue;
        _isPaused = queue.IsPaused;
        _delayBetweenJobsMs = queue.DelayBetweenJobsMs;
    }

    partial void OnIsPausedChanged(bool value)
    {
        _queue.IsPaused = value;
    }

    partial void OnDelayBetweenJobsMsChanged(int value)
    {
        _queue.DelayBetweenJobsMs = Math.Max(0, value);
    }

    partial void OnSelectedJobsChanged(IList? value)
    {
        RefreshCancelableSelection();
    }

    [RelayCommand]
    private void CancelJob(GenerationJob? job)
    {
        if (job == null) return;
        _queue.CancelJob(job);
    }

    [RelayCommand]
    private void RetryJob(GenerationJob? job)
    {
        if (job == null) return;
        _queue.RetryJob(job);
    }

    private bool CanCancelSelectedJobs()
    {
        return HasCancelableSelection;
    }

    [RelayCommand(CanExecute = nameof(CanCancelSelectedJobs))]
    private void CancelSelectedJobs()
    {
        if (SelectedJobs == null) return;
        var jobs = SelectedJobs.OfType<GenerationJob>().Where(job => job.CanCancel).ToList();
        foreach (var job in jobs)
        {
            _queue.CancelJob(job);
        }
        RefreshCancelableSelection();
    }

    private void RefreshCancelableSelection()
    {
        HasCancelableSelection = SelectedJobs?.OfType<GenerationJob>().Any(job => job.CanCancel) == true;
        CancelSelectedJobsCommand.NotifyCanExecuteChanged();
    }
}
