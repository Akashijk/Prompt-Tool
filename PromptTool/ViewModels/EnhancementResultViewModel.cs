using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Threading;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Clients;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using System.Linq;

namespace PromptTool.ViewModels;

public partial class EnhancementResultViewModel : ObservableObject
{
    private readonly OllamaClient _ollama;
    private readonly string _systemPrompt;
    private readonly IReadOnlyList<VariationPrompt> _variationPrompts;
    private CancellationTokenSource? _cts;
    private int _totalCalls;
    private int _completedCalls;

    [ObservableProperty] private string _status = "Enhancing...";
    [ObservableProperty] private string _enhancedPrompt = "";
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private ObservableCollection<VariationViewModel> _variations = new();
    [ObservableProperty] private string _originalPrompt = "";
    [ObservableProperty] private ObservableCollection<string> _models = new();
    [ObservableProperty] private string _selectedModel = "";
    [ObservableProperty] private int _wordCount;
    [ObservableProperty] private string _warning = "";

    public EnhancementResult? Result { get; private set; }

    public IAsyncRelayCommand RegenerateCommand { get; }
    public IAsyncRelayCommand RegenerateVariationsCommand { get; }
    public IRelayCommand<string> CopyCommand { get; }
    public IRelayCommand CloseCommand { get; }
    public IRelayCommand SaveCommand { get; }
    public IRelayCommand CancelCommand { get; }

    public event Action? RequestClose;
    public event Action<string>? RequestCopy;
    public event Action<string?>? RequestReleaseModel;

    public EnhancementResultViewModel() : this(new OllamaClient(new System.Net.Http.HttpClient(), new SettingsService()), "", "", "")
    {
    }

    public EnhancementResultViewModel(
        OllamaClient ollama,
        string model,
        string originalPrompt,
        string? systemPrompt,
        IReadOnlyList<VariationPrompt>? variations = null,
        IReadOnlyList<string>? models = null)
    {
        _ollama = ollama;
        OriginalPrompt = originalPrompt;
        _systemPrompt = systemPrompt ?? "";
        _variationPrompts = variations ?? Array.Empty<VariationPrompt>();
        Models = new ObservableCollection<string>(models ?? Array.Empty<string>());
        if (!string.IsNullOrWhiteSpace(model) &&
            !Models.Contains(model, StringComparer.OrdinalIgnoreCase))
        {
            Models.Add(model);
        }
        SelectedModel = !string.IsNullOrWhiteSpace(model)
            ? model
            : Models.FirstOrDefault() ?? "";
        WordCount = CountWords(originalPrompt);
        Warning = WordCount < 20 ? "Short prompt; consider adding more detail for better enhancement." :
                  WordCount > 150 ? "Long prompt; enhancement may be verbose." : "";

        RegenerateCommand = new AsyncRelayCommand(RegenerateAsync, () => !IsBusy && CanGenerate);
        RegenerateVariationsCommand = new AsyncRelayCommand(RegenerateAllVariationsAsync, () => Variations.Count > 0 && !IsBusy && CanGenerate);
        CopyCommand = new RelayCommand<string>(s => RequestCopy?.Invoke(s ?? string.Empty));
        CloseCommand = new RelayCommand(() =>
        {
            if (!string.IsNullOrWhiteSpace(SelectedModel))
            {
                RequestReleaseModel?.Invoke(SelectedModel);
            }
            RequestClose?.Invoke();
        });
        SaveCommand = new RelayCommand(Save);
        CancelCommand = new RelayCommand(Cancel);

        foreach (var variation in _variationPrompts)
        {
            Variations.Add(new VariationViewModel(variation, RegenerateVariationSingleAsync));
        }
        RegenerateVariationsCommand.NotifyCanExecuteChanged();

    }

    private async Task RegenerateAsync()
    {
        if (IsBusy || !CanGenerate) return;
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        StartProgress(1 + Variations.Count);
        IsBusy = true;
        Status = $"Enhancing with {SelectedModel}...";
        try
        {
            EnhancedPrompt = await GenerateEnhancedPromptAsync(_cts.Token);
            UpdateProgress();
            foreach (var variation in Variations)
            {
                await RegenerateVariationAsync(variation, _cts.Token);
            }
            Status = "Enhancement complete.";
        }
        catch (OperationCanceledException)
        {
            Status = "Enhancement canceled.";
        }
        catch (Exception ex)
        {
            Status = $"Enhancement failed: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RegenerateAllVariationsAsync()
    {
        if (IsBusy || Variations.Count == 0 || !CanGenerate) return;
        if (string.IsNullOrWhiteSpace(EnhancedPrompt))
        {
            Status = "Enhance the prompt first.";
            return;
        }

        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        StartProgress(Variations.Count);
        IsBusy = true;
        try
        {
            foreach (var variation in Variations)
            {
                await RegenerateVariationAsync(variation, _cts.Token);
            }
            Status = "Variations refreshed.";
        }
        catch (OperationCanceledException)
        {
            Status = "Variation refresh canceled.";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RegenerateVariationSingleAsync(VariationViewModel variation, CancellationToken token)
    {
        if (IsBusy || !CanGenerate) return;
        _cts?.Cancel();
        _cts = CancellationTokenSource.CreateLinkedTokenSource(token);
        StartProgress(1);
        Status = $"Regenerating {variation.Title}...";
        IsBusy = true;
        try
        {
            await RegenerateVariationAsync(variation, _cts.Token);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Save()
    {
        if (IsBusy)
        {
            Status = "Wait for generation to finish before saving.";
            return;
        }

        var hasVariations = Variations.Any(v => !string.IsNullOrWhiteSpace(v.Text));
        if (string.IsNullOrWhiteSpace(EnhancedPrompt) && !hasVariations)
        {
            Status = "No enhancements generated yet.";
            return;
        }

        var variationsDict = new System.Collections.Generic.Dictionary<string, string>();
        foreach (var v in Variations)
        {
            if (!string.IsNullOrWhiteSpace(v.Key) && !string.IsNullOrWhiteSpace(v.Text))
            {
                variationsDict[v.Key] = v.Text;
            }
        }
        Result = new EnhancementResult(EnhancedPrompt, variationsDict);
        if (!string.IsNullOrWhiteSpace(SelectedModel))
        {
            RequestReleaseModel?.Invoke(SelectedModel);
        }
        RequestClose?.Invoke();
    }

    private void Cancel()
    {
        _cts?.Cancel();
        if (!string.IsNullOrWhiteSpace(SelectedModel))
        {
            RequestReleaseModel?.Invoke(SelectedModel);
        }
        RequestClose?.Invoke();
    }

    private string BuildPrompt(string content)
    {
        if (string.IsNullOrWhiteSpace(_systemPrompt)) return content;
        return $"{_systemPrompt.Trim()}\n\n{content}";
    }

    private static int CountWords(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) return 0;
        var parts = text.Split(new[] { ' ', '\n', '\r', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        return parts.Length;
    }

    private void StartProgress(int tasks)
    {
        _totalCalls = Math.Max(0, tasks);
        _completedCalls = 0;
        UpdateProgress();
    }

    private void UpdateProgress()
    {
        if (_totalCalls <= 0)
        {
            Status = "Ready.";
            return;
        }
        Status = $"Completed {_completedCalls}/{_totalCalls}.";
    }

    private async Task<string> GenerateEnhancedPromptAsync(CancellationToken token)
    {
        var promptToSend = BuildPrompt(OriginalPrompt);
        var result = await _ollama.GenerateAsync(SelectedModel, promptToSend, token, temperature: 0.7, topP: 0.9);
        var parsed = ParseEnhancedResponse(result);
        _completedCalls++;
        return parsed;
    }

    private async Task RegenerateVariationAsync(VariationViewModel variation, CancellationToken token = default)
    {
        variation.IsBusy = true;
        variation.Status = $"Generating with {SelectedModel}...";
        var counted = false;
        try
        {
            var basePrompt = OriginalPrompt;
            var text = await GenerateVariationAsync(variation.Definition, basePrompt, token);
            variation.Text = text;
            variation.Status = "Ready.";
            _completedCalls++;
            counted = true;
            UpdateProgress();
        }
        catch (OperationCanceledException)
        {
            variation.Status = "Canceled.";
        }
        catch (Exception ex)
        {
            variation.Status = $"Failed: {ex.Message}";
        }
        finally
        {
            if (!counted && !token.IsCancellationRequested)
            {
                _completedCalls++;
                UpdateProgress();
            }
            variation.IsBusy = false;
        }
    }

    private async Task<string> GenerateVariationAsync(VariationPrompt variation, string basePrompt, CancellationToken token)
    {
        var context = string.IsNullOrWhiteSpace(OriginalPrompt) || string.Equals(OriginalPrompt, basePrompt, StringComparison.Ordinal)
            ? string.Empty
            : $"For context, the user's original un-enhanced prompt was: `{OriginalPrompt}`\n\n";

        var fullPrompt = $"{context}{variation.Prompt.Trim()}\n{basePrompt}";
        var result = await _ollama.GenerateAsync(SelectedModel, fullPrompt, token, temperature: 0.8, topP: 0.9);
        return ParseEnhancedResponse(result);
    }

    public static string ParseEnhancedResponse(string response)
    {
        if (string.IsNullOrWhiteSpace(response)) return string.Empty;
        var marker = "ENHANCED_PROMPT:";
        var idx = response.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (idx < 0)
        {
            return response.Trim().Replace("\r", " ").Replace("\n", " ").Replace("  ", " ");
        }

        var content = response[(idx + marker.Length)..];
        return content.Trim().Replace("\r", " ").Replace("\n", " ").Replace("  ", " ");
    }

    partial void OnIsBusyChanged(bool value)
    {
        RegenerateCommand.NotifyCanExecuteChanged();
        RegenerateVariationsCommand.NotifyCanExecuteChanged();
    }

    partial void OnSelectedModelChanged(string value)
    {
        RegenerateCommand?.NotifyCanExecuteChanged();
        RegenerateVariationsCommand?.NotifyCanExecuteChanged();
    }

    private bool CanGenerate => !string.IsNullOrWhiteSpace(SelectedModel);
}

public partial class VariationViewModel : ObservableObject
{
    private readonly Func<VariationViewModel, CancellationToken, Task> _regenerate;

    [ObservableProperty] private string _title = "";
    [ObservableProperty] private string _description = "";
    [ObservableProperty] private string _text = "";
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private bool _isBusy;

    public VariationPrompt Definition { get; }
    public string Key => Definition.Key;
    public IAsyncRelayCommand RegenerateCommand { get; }

    public VariationViewModel(VariationPrompt definition, Func<VariationViewModel, CancellationToken, Task> regenerate)
    {
        Definition = definition;
        _regenerate = regenerate;
        Title = definition.Name;
        Description = definition.Description;
        Status = "Waiting...";
        RegenerateCommand = new AsyncRelayCommand(() => _regenerate(this, CancellationToken.None), () => !IsBusy);
    }

    partial void OnIsBusyChanged(bool value)
    {
        RegenerateCommand.NotifyCanExecuteChanged();
    }
}
