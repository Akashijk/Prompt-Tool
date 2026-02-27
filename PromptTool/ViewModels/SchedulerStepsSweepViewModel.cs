using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public sealed partial class SchedulerStepsSweepViewModel : ObservableObject
{
    private readonly InvokeAIClient _invokeAIClient;
    private readonly AestheticScoringService _aestheticScoringService;
    private readonly Func<string, Task<bool>> _confirmDownloadAsync;
    private CancellationTokenSource? _cts;

    [ObservableProperty] private string _schedulerName = "";
    [ObservableProperty] private string _stepsSummary = "";
    [ObservableProperty] private ObservableCollection<SchedulerStepsResultItem> _results = new();
    [ObservableProperty] private bool _isGenerating;
    [ObservableProperty] private string _statusText = "";
    [ObservableProperty] private string _scoreSummary = "";

    public IRelayCommand CancelCommand { get; }

    public SchedulerStepsSweepViewModel(
        InvokeAIClient invokeAIClient,
        AestheticScoringService aestheticScoringService,
        Func<string, Task<bool>> confirmDownloadAsync)
    {
        _invokeAIClient = invokeAIClient;
        _aestheticScoringService = aestheticScoringService;
        _confirmDownloadAsync = confirmDownloadAsync;
        CancelCommand = new RelayCommand(CancelGeneration, () => IsGenerating);
    }

    partial void OnIsGeneratingChanged(bool value)
    {
        CancelCommand.NotifyCanExecuteChanged();
    }

    public async Task StartAsync(
        string schedulerName,
        InvokeAIGenerationParams baseParams,
        IReadOnlyList<int> stepsList,
        bool enableAestheticScoring,
        bool enableArtifactChecks,
        Action<string>? status = null)
    {
        var items = stepsList
            .Select(step => new SchedulerStepsResultItem
            {
                Label = $"Steps {step}",
                Steps = step,
                IsLoading = true
            })
            .ToList();

        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            SchedulerName = schedulerName;
            Results.Clear();
            ScoreSummary = "";
            StepsSummary = stepsList.Count == 0
                ? ""
                : $"Steps: {stepsList.Min()} → {stepsList.Max()} (x{stepsList.Count})";
            foreach (var item in items)
            {
                Results.Add(item);
            }
        });

        _cts?.Cancel();
        _cts?.Dispose();
        _cts = new CancellationTokenSource();
        var token = _cts.Token;

        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            IsGenerating = true;
            StatusText = "Generating steps sweep...";
        });
        status?.Invoke(StatusText);

        try
        {
            for (var i = 0; i < stepsList.Count; i++)
            {
                if (token.IsCancellationRequested) break;

                var step = stepsList[i];
                var p = CloneParams(baseParams);
                p.Steps = step;
                var item = items[i];

                try
                {
                    var genResult = await _invokeAIClient.GenerateImageAsync(p, token);
                    var bytes = genResult.ImageBytes;
                    Bitmap? bitmap = null;
                    if (bytes != null && bytes.Length > 0)
                    {
                        using var ms = new MemoryStream(bytes);
                        bitmap = new Bitmap(ms);
                    }

                    var durationLabel = FormatDurationLabel(genResult.JobInfo);
                    var heuristicScore = bitmap != null ? (double?)ScoringHelper.CalculateScore(bitmap) : null;
                    var banding = false;
                    var overSmooth = false;
                    var warp = false;
                    if (enableArtifactChecks && bitmap != null)
                    {
                        var flags = ArtifactHeuristics.Evaluate(bitmap);
                        banding = flags.BandingRisk;
                        overSmooth = flags.OverSmoothRisk;
                        warp = flags.WarpRisk;
                    }

                    double? aestheticScore = null;
                    if (enableAestheticScoring && bytes != null)
                    {
                        aestheticScore = await ScoreAestheticAsync(bytes, status, token);
                    }

                    await Dispatcher.UIThread.InvokeAsync(() =>
                    {
                        item.IsLoading = false;
                        item.ImageBytes = bytes;
                        item.Image = bitmap;
                        item.DurationLabel = durationLabel;
                        item.HeuristicScore = heuristicScore;
                        if (enableArtifactChecks)
                        {
                            item.BandingRisk = banding;
                            item.OverSmoothRisk = overSmooth;
                            item.WarpRisk = warp;
                        }
                        if (enableAestheticScoring)
                        {
                            item.AestheticScore = aestheticScore;
                        }
                    });
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    await Dispatcher.UIThread.InvokeAsync(() =>
                    {
                        item.IsLoading = false;
                        item.Error = ex.Message;
                    });
                }
            }
        }
        finally
        {
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                IsGenerating = false;
                StatusText = token.IsCancellationRequested ? "Steps sweep cancelled." : "Steps sweep complete.";
                UpdateScoreSummary(enableAestheticScoring);
            });
            status?.Invoke(StatusText);
            _cts?.Dispose();
            _cts = null;
        }
    }

    private void UpdateScoreSummary(bool preferAesthetic)
    {
        var scores = Results
            .Select(r => preferAesthetic ? r.AestheticScore : r.HeuristicScore)
            .Where(s => s.HasValue)
            .Select(s => s!.Value)
            .ToList();

        if (scores.Count == 0)
        {
            ScoreSummary = "";
            return;
        }

        var mean = scores.Average();
        var variance = scores.Sum(s => Math.Pow(s - mean, 2)) / scores.Count;
        var stdDev = Math.Sqrt(variance);
        ScoreSummary = $"Mean {mean:F2} | σ {stdDev:F2}";
    }

    private void CancelGeneration()
    {
        if (!IsGenerating) return;
        StatusText = "Cancelling steps sweep...";
        _cts?.Cancel();
    }

    private async Task<double?> ScoreAestheticAsync(byte[] imageBytes, Action<string>? status, CancellationToken token)
    {
        var path = Path.Combine(Path.GetTempPath(), $"scheduler_tuner_{Guid.NewGuid():N}.png");
        try
        {
            await File.WriteAllBytesAsync(path, imageBytes, token);
            var result = await _aestheticScoringService.ScoreImageAsync(
                path,
                _confirmDownloadAsync,
                status,
                null,
                token);
            return result?.Score;
        }
        finally
        {
            try
            {
                if (File.Exists(path)) File.Delete(path);
            }
            catch
            {
                // ignore cleanup failures
            }
        }
    }

    private static string? FormatDurationLabel(GenerationJobInfo? jobInfo)
    {
        if (jobInfo == null) return null;

        var gen = jobInfo.GenerationDurationMs;
        var total = jobInfo.TotalDurationMs;
        if (gen == null && total == null) return null;

        var parts = new List<string>();
        if (gen is > 0)
        {
            parts.Add($"Gen {FormatMs(gen.Value)}");
        }
        if (total is > 0)
        {
            parts.Add($"Total {FormatMs(total.Value)}");
        }
        return parts.Count == 0 ? null : string.Join(" | ", parts);
    }

    private static string FormatMs(int ms)
    {
        if (ms < 1000)
        {
            return $"{ms} ms";
        }
        var seconds = ms / 1000d;
        return $"{seconds:F2}s";
    }

    private static InvokeAIGenerationParams CloneParams(InvokeAIGenerationParams src)
    {
        return new InvokeAIGenerationParams
        {
            Prompt = src.Prompt,
            PositiveStylePrompt = src.PositiveStylePrompt,
            NegativeStylePrompt = src.NegativeStylePrompt,
            NegativePrompt = src.NegativePrompt,
            BaseModelType = src.BaseModelType,
            UsedRandomSeed = src.UsedRandomSeed,
            BaseSeed = src.BaseSeed,
            AutoClearedModelCacheBetweenModels = src.AutoClearedModelCacheBetweenModels,
            VaeUsedName = src.VaeUsedName,
            VaePrecision = src.VaePrecision,
            UseCpuNoise = src.UseCpuNoise,
            L2iFp32 = src.L2iFp32,
            UseAutoCfgRescale = src.UseAutoCfgRescale,
            Model = src.Model,
            Steps = src.Steps,
            CfgScale = src.CfgScale,
            Width = src.Width,
            Height = src.Height,
            Seed = src.Seed,
            Scheduler = src.Scheduler,
            CfgRescaleMultiplier = src.CfgRescaleMultiplier,
            Loras = src.Loras?.Select(l => new LoraParameter { Lora = l.Lora, Weight = l.Weight }).ToList() ?? new List<LoraParameter>(),
            SaveToGallery = src.SaveToGallery,
            UsePromptAsStyleWhenEmpty = src.UsePromptAsStyleWhenEmpty
        };
    }
}

public sealed partial class SchedulerStepsResultItem : ObservableObject
{
    [ObservableProperty] private string _label = "";
    [ObservableProperty] private int _steps;
    [ObservableProperty] private Bitmap? _image;
    [ObservableProperty] private byte[]? _imageBytes;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _durationLabel;
    [ObservableProperty] private double? _aestheticScore;
    [ObservableProperty] private double? _heuristicScore;
    [ObservableProperty] private bool _bandingRisk;
    [ObservableProperty] private bool _overSmoothRisk;
    [ObservableProperty] private bool _warpRisk;
    [ObservableProperty] private string? _error;

    public bool HasAestheticScore => AestheticScore.HasValue;
    public bool HasHeuristicScore => HeuristicScore.HasValue;

    partial void OnAestheticScoreChanged(double? value)
    {
        OnPropertyChanged(nameof(HasAestheticScore));
    }

    partial void OnHeuristicScoreChanged(double? value)
    {
        OnPropertyChanged(nameof(HasHeuristicScore));
    }
}
