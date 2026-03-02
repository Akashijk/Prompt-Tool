using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;

namespace PromptTool.Services;

public enum GenerationJobStatus
{
    Queued,
    Running,
    Completed,
    Failed,
    Canceled
}

public partial class GenerationJob : ObservableObject
{
    public GenerationJob(string name, Func<GenerationJob, CancellationToken, Task> work, string? preferredModel = null, int estimatedWorkUnits = 1)
    {
        Id = Guid.NewGuid();
        Name = name;
        Work = work;
        CreatedAt = DateTime.Now;
        Status = GenerationJobStatus.Queued;
        PreferredModel = string.IsNullOrWhiteSpace(preferredModel) ? null : preferredModel.Trim();
        EstimatedWorkUnits = Math.Max(1, estimatedWorkUnits);
    }

    public Guid Id { get; }
    public string Name { get; }
    public DateTime CreatedAt { get; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public Func<GenerationJob, CancellationToken, Task> Work { get; }

    [ObservableProperty] private GenerationJobStatus _status;
    [ObservableProperty] private string? _statusMessage;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private int _progressCurrent;
    [ObservableProperty] private int _progressTotal;
    [ObservableProperty] private int _retryCount;
    [ObservableProperty] private string? _preferredModel;
    [ObservableProperty] private int _estimatedWorkUnits;

    internal Action? CancelAction { get; set; }

    public bool CanCancel => Status is GenerationJobStatus.Running or GenerationJobStatus.Queued;
    public bool CanRetry => Status == GenerationJobStatus.Failed;

    public void UpdateProgress(int current, int total)
    {
        ProgressTotal = total;
        ProgressCurrent = Math.Min(current, total);
    }
}

public sealed class GenerationQueueService
{
    private readonly List<GenerationJob> _pendingJobs = new();
    private readonly SemaphoreSlim _queueSignal = new(0);
    private readonly CancellationTokenSource _cts = new();
    private readonly object _stateLock = new();
    private Task? _processor;
    private bool _isPaused;
    private TaskCompletionSource<bool>? _resumeTcs;
    private string? _modelAffinity;

    public ObservableCollection<GenerationJob> Jobs { get; } = new();

    public int DelayBetweenJobsMs { get; set; } = 0;
    public int MaxAutoRetries { get; set; } = 2;

    public bool IsPaused
    {
        get => _isPaused;
        set
        {
            if (_isPaused == value) return;
            _isPaused = value;
            if (!_isPaused)
            {
                _resumeTcs?.TrySetResult(true);
            }
        }
    }

    public void Enqueue(GenerationJob job)
    {
        job.Status = GenerationJobStatus.Queued;
        Jobs.Add(job);
        lock (_stateLock)
        {
            _pendingJobs.Add(job);
        }
        _queueSignal.Release();
        EnsureProcessor();
    }

    public void CancelJob(GenerationJob job)
    {
        if (job.Status == GenerationJobStatus.Queued)
        {
            job.Status = GenerationJobStatus.Canceled;
            job.StatusMessage = "Canceled before start.";
            return;
        }

        if (job.Status == GenerationJobStatus.Running)
        {
            job.CancelAction?.Invoke();
        }
    }

    public void RetryJob(GenerationJob job)
    {
        if (!job.CanRetry) return;
        job.ErrorMessage = null;
        job.StatusMessage = null;
        Enqueue(new GenerationJob($"{job.Name} (retry {job.RetryCount + 1})", job.Work, job.PreferredModel, job.EstimatedWorkUnits)
        {
            RetryCount = job.RetryCount + 1
        });
    }

    private void EnsureProcessor()
    {
        lock (_stateLock)
        {
            if (_processor != null && !_processor.IsCompleted) return;
            _processor = Task.Run(ProcessQueueAsync);
        }
    }

    private async Task ProcessQueueAsync()
    {
        var token = _cts.Token;
        while (!token.IsCancellationRequested)
        {
            await _queueSignal.WaitAsync(token);
            if (token.IsCancellationRequested) break;

            var job = TakeNextJob();
            if (job == null) continue;

            if (IsPaused)
            {
                _resumeTcs = new TaskCompletionSource<bool>();
                await _resumeTcs.Task;
            }

            if (!string.IsNullOrWhiteSpace(job.PreferredModel))
            {
                _modelAffinity = job.PreferredModel;
            }

            job.Status = GenerationJobStatus.Running;
            job.StartedAt = DateTime.Now;
            job.StatusMessage = "Running...";
            using var jobCts = CancellationTokenSource.CreateLinkedTokenSource(token);
            job.CancelAction = () => jobCts.Cancel();

            try
            {
                await job.Work(job, jobCts.Token);
                if (jobCts.IsCancellationRequested)
                {
                    job.Status = GenerationJobStatus.Canceled;
                    job.StatusMessage = "Canceled.";
                }
                else
                {
                    job.Status = GenerationJobStatus.Completed;
                    job.StatusMessage = "Completed.";
                }
            }
            catch (OperationCanceledException)
            {
                job.Status = GenerationJobStatus.Canceled;
                job.StatusMessage = "Canceled.";
            }
            catch (Exception ex)
            {
                job.ErrorMessage = ex.Message;
                if (ShouldAutoRetry(job, ex))
                {
                    job.RetryCount++;
                    job.Status = GenerationJobStatus.Queued;
                    job.StatusMessage = "Retrying...";
                    lock (_stateLock)
                    {
                        _pendingJobs.Add(job);
                    }
                    _queueSignal.Release();
                    continue;
                }
                job.Status = GenerationJobStatus.Failed;
                job.StatusMessage = "Failed.";
            }
            finally
            {
                job.CompletedAt = DateTime.Now;
            }

            if (DelayBetweenJobsMs > 0 && !token.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(DelayBetweenJobsMs, token);
                }
                catch (TaskCanceledException)
                {
                    break;
                }
            }
        }
    }

    private bool ShouldAutoRetry(GenerationJob job, Exception ex)
    {
        if (job.RetryCount >= MaxAutoRetries) return false;
        if (ex is TaskCanceledException || ex is OperationCanceledException) return false;
        if (ex is System.Net.Http.HttpRequestException) return true;
        var message = ex.Message?.ToLowerInvariant() ?? "";
        return message.Contains("timeout") || message.Contains("temporarily") || message.Contains("503") || message.Contains("502");
    }

    private GenerationJob? TakeNextJob()
    {
        lock (_stateLock)
        {
            if (_pendingJobs.Count == 0)
            {
                return null;
            }

            _pendingJobs.RemoveAll(job => job.Status == GenerationJobStatus.Canceled);
            if (_pendingJobs.Count == 0)
            {
                return null;
            }

            GenerationJob? selected = null;

            if (!string.IsNullOrWhiteSpace(_modelAffinity))
            {
                selected = _pendingJobs
                    .Where(job => string.Equals(job.PreferredModel, _modelAffinity, StringComparison.OrdinalIgnoreCase))
                    .OrderBy(job => job.CreatedAt)
                    .FirstOrDefault();
            }

            if (selected == null)
            {
                var groupedByModel = _pendingJobs
                    .Where(job => !string.IsNullOrWhiteSpace(job.PreferredModel))
                    .GroupBy(job => job.PreferredModel!, StringComparer.OrdinalIgnoreCase)
                    .Select(group => new
                    {
                        Model = group.Key,
                        TotalWork = group.Sum(job => Math.Max(1, job.EstimatedWorkUnits)),
                        FirstCreatedAt = group.Min(job => job.CreatedAt)
                    })
                    .OrderByDescending(group => group.TotalWork)
                    .ThenBy(group => group.FirstCreatedAt)
                    .FirstOrDefault();

                if (groupedByModel != null)
                {
                    _modelAffinity = groupedByModel.Model;
                    selected = _pendingJobs
                        .Where(job => string.Equals(job.PreferredModel, groupedByModel.Model, StringComparison.OrdinalIgnoreCase))
                        .OrderBy(job => job.CreatedAt)
                        .FirstOrDefault();
                }
            }

            selected ??= _pendingJobs
                .OrderBy(job => job.CreatedAt)
                .FirstOrDefault();

            if (selected != null)
            {
                _pendingJobs.Remove(selected);
            }

            return selected;
        }
    }
}
