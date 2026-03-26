using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class MainWindowViewModel
{
    private Task ShowSettingsAsync(Window? owner)
    {
        return ShowSettingsAsync(owner, null);
    }

    private Task ShowSettingsAsync(Window? owner, string? sectionKey)
    {
        var vm = new SettingsViewModel(_settingsService, _ollamaClient, _notifications, _imageCacheService, _invokeAIClient);
        var win = new Views.SettingsWindow(vm);
        win.Opened += (_, _) =>
        {
            if (!string.IsNullOrWhiteSpace(sectionKey))
            {
                win.NavigateToGenerationSection(sectionKey);
            }
        };
        win.Closed += async (_, __) =>
        {
            if (vm.DialogResult == true)
            {
                _wildcardService.Reload(_settingsService.GetWildcardDirs());
                await LoadTemplatesAsync();
                await LoadModelsAsync();
                await LoadVariationsAsync();
                StatusText = "Settings saved.";
            }
            else
            {
                StatusText = "Settings closed.";
            }
        };
        win.Show(ResolveOwnerWindow(owner));
        return Task.CompletedTask;
    }

    private async Task ShowHistoryAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var variations = await _systemPromptService.LoadVariationPromptsAsync();
        var vm = new HistoryViewerViewModel(_historyManager, _templateService, _imageCacheService, _historyIndexService, Workflow, variations, _settingsService);
        var win = new Views.HistoryViewerWindow { DataContext = vm };
        vm.RegenerateRequested = (entry, image, prompt, promptType) => RegenerateFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.GenerateNewRequested = (entry, image, prompt, promptType) => GenerateNewFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.EditRegenerateRequested = (entry, image, prompt, promptType) => RegenerateFromHistoryAsync(entry, image, prompt, promptType, win);
        vm.SeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, win);
        vm.LoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, win);
        vm.ModelVariationsRequested = (entry, image) => GenerateModelPermutationsFromHistoryAsync(entry, image, win);
        vm.PromptVariationsRequested = (entry, image) => GeneratePromptVariationsFromHistoryAsync(entry, image, win);
        vm.EnhanceRequested = entry => EnhanceFromHistoryAsync(entry, win);
        vm.FillMissingVariationsRequested = (entry, missing) => FillMissingVariationsWithDialogAsync(entry, missing, win);
        vm.UpscaleRequested = (entry, image) => UpscaleImageFromHistoryAsync(entry, image, win);
        vm.ShowModelSimilarityRequested = entry => ShowHistoryModelSimilarityAsync(entry, win);
        vm.ShowSimilarityMatchesRequested = image => ShowSimilarityMatchesForImageAsync(image, win);
        vm.CompareImagesRequested = async (leftEntry, leftImage, rightEntry, rightImage) =>
        {
            var leftBitmap = _imageCacheService.GetOrLoadForUi(leftImage.ImagePath, 1024, _historyManager.GetHistoryDir());
            var rightBitmap = _imageCacheService.GetOrLoadForUi(rightImage.ImagePath, 1024, _historyManager.GetHistoryDir());
            if (leftBitmap == null || rightBitmap == null)
            {
                StatusText = "Could not load one or both images for comparison.";
                return;
            }

            ShowCompareWindow(win, leftEntry, leftImage, leftBitmap, rightEntry, rightImage, rightBitmap);
            await Task.CompletedTask;
        };
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(HistoryViewerViewModel.DialogResult) && vm.DialogResult != null)
            {
                var loaded = vm.LoadPromptOverride
                             ?? vm.DialogResult.ProcessedPrompt
                             ?? vm.DialogResult.OriginalPrompt;
                PromptText = loaded;
                OutputText = loaded;
                SelectedModel = vm.DialogResult.OllamaModel;
                StatusText = "Loaded selected prompt from history.";
            }
        };
        win.Show(resolved);
    }

    private Task ShowAllImagesAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new AllImagesViewerViewModel(_historyManager, _templateService, _imageCacheService, _historyIndexService, Workflow);
        vm.UpscaleRequested = (entry, image) => UpscaleImageFromHistoryAsync(entry, image, resolved);
        vm.GenerateMoreRequested = (entry, image) => GenerateFromHistoryAsync(entry, image, null, null, resolved, applyModelFromSource: true, configureVm: null);
        vm.SeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, resolved);
        vm.LoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, resolved);
        vm.ModelVariationsRequested = (entry, image) => GenerateModelPermutationsFromHistoryAsync(entry, image, resolved);
        var win = new Views.AllImagesWindow(vm);
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowAnalyticsStudioAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new AnalyticsStudioViewModel(
            _historyManager,
            _templateService,
            Workflow,
            _aestheticScoringService,
            _promptMatchScoringService,
            _settingsService,
            _imageCacheService,
            _historyIndexService);
        vm.CompareRequested = async items =>
        {
            if (items.Count != 2) return;
            var leftBitmap = items[0].Bitmap;
            var rightBitmap = items[1].Bitmap;
            if (leftBitmap == null || rightBitmap == null) return;
            ShowCompareWindow(resolved, items[0].Entry, items[0].Image, leftBitmap,
                items[1].Entry, items[1].Image, rightBitmap);
            await Task.CompletedTask;
        };
        var window = new Views.AnalyticsStudioWindow { DataContext = vm };
        vm.ViewDetailsRequested = async (entry, image, bitmap, navigationItems) =>
        {
            ShowHistoryImageDetailsWindow(entry, image, bitmap, window, navigationItems);
            await Task.CompletedTask;
        };
        vm.GenerateMoreRequested = (entry, image) => GenerateFromHistoryAsync(entry, image, null, null, window, applyModelFromSource: true, configureVm: null);
        vm.GenerateSeedVariationsRequested = (entry, image) => GenerateSeedVariationsFromHistoryAsync(entry, image, window);
        vm.GenerateLoraVariationsRequested = (entry, image) => GenerateLoraVariationsFromHistoryAsync(entry, image, window);
        vm.ShowSimilarityMatchesRequested = image => ShowSimilarityMatchesForImageAsync(image, window);
        window.Opened += (_, _) =>
        {
            if (vm.ConfirmAsync == null)
            {
                vm.ConfirmAsync = message => ShowConfirmAsync(window, message);
            }

            if (vm.ScoreByModelConfirmAsync == null)
            {
                vm.ScoreByModelConfirmAsync = request => ShowScoreByModelConfirmAsync(window, request);
            }
        };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowKpiDashboardAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new KpiDashboardViewModel(_historyManager, Workflow, _kpiStats);
        var window = new Views.KpiDashboardWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowSchedulerTunerAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new SchedulerTunerViewModel(_invokeAIClient, _settingsService, _aestheticScoringService, _notifications);
        var window = new Views.SchedulerTunerWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowGenerationQueueAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new GenerationQueueViewModel(_generationQueue);
        var window = new Views.GenerationQueueWindow { DataContext = vm };
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private Task ShowRegressionChecklistAsync(Window? owner)
    {
        var resolved = ResolveOwnerWindow(owner);
        var vm = new RegressionChecklistViewModel();
        var window = new Views.RegressionChecklistWindow { DataContext = vm };
        EventHandler? requestCloseHandler = null;
        requestCloseHandler = (_, _) => window.Close();
        vm.RequestClose += requestCloseHandler;
        window.Closed += (_, _) => vm.RequestClose -= requestCloseHandler;
        window.Show(resolved);
        return Task.CompletedTask;
    }

    private void ShowHistoryImageDetailsWindow(
        HistoryEntry entry,
        HistoryImage image,
        Bitmap bitmap,
        Window owner,
        IReadOnlyList<ImageDetailNavigationItem>? navigationItems = null)
    {
        ImageDetailPresenter.Show(
            entry,
            image,
            bitmap,
            owner,
            _historyManager,
            _historyIndexService,
            _imageCacheService,
            (e, img) => UpscaleImageFromHistoryAsync(e, img, owner),
            (e, img) => GenerateFromHistoryAsync(e, img, null, null, owner, applyModelFromSource: true, configureVm: null),
            (e, img) => GenerateSeedVariationsFromHistoryAsync(e, img, owner),
            (e, img) => GenerateLoraVariationsFromHistoryAsync(e, img, owner),
            (e, img) => GenerateModelPermutationsFromHistoryAsync(e, img, owner),
            navigationItems: navigationItems);
    }

    private async Task ShowGenerationDefaultsDialogAsync(Window? owner)
    {
        var defaultsVm = new GenerationDefaultsViewModel();

        var currentScheduler = _settingsService.Settings.DefaultScheduler ?? "dpmpp_2m_k";
        var invokeOnline = await EnsureInvokeOnlineAsync(showToastOnFailure: true);
        try
        {
            if (invokeOnline)
            {
                var schedulers = await _invokeAIClient.GetSchedulersAsync();
                defaultsVm.SetSchedulers(schedulers, currentScheduler);
            }
            else
            {
                defaultsVm.SetSchedulers(new[] { currentScheduler }, currentScheduler);
                StatusText = "InvokeAI offline; using existing scheduler defaults.";
            }
        }
        catch
        {
            defaultsVm.SetSchedulers(new[] { currentScheduler }, currentScheduler);
        }

        defaultsVm.SetDefaults(_settingsService.Settings.GenerationDefaults ?? new(), _settingsService.Settings.DefaultBaseModelType ?? "sdxl");

        var dialog = new Views.GenerationDefaultsWindow { DataContext = defaultsVm };
        var resolved = ResolveOwnerWindow(owner);
        dialog.Closed += async (_, __) =>
        {
            if (defaultsVm.DialogResult == true)
            {
                _settingsService.Settings.GenerationDefaults = defaultsVm.GetDefaultsSnapshot();
                _settingsService.Settings.DefaultBaseModelType = defaultsVm.CurrentBaseModelType;
                _settingsService.Settings.DefaultScheduler = defaultsVm.DefaultScheduler;
                var ok = await _settingsService.SaveSettingsAsync(_settingsService.Settings);
                if (ok)
                {
                    _notifications?.ShowInfo("Default generation options saved.", "Success");
                    StatusText = "Default generation options saved.";
                }
                else
                {
                    _notifications?.ShowError("Failed to save generation defaults.", "Error");
                    StatusText = "Failed to save generation defaults.";
                }
            }
            else
            {
                StatusText = "Default generation options unchanged.";
            }
        };
        dialog.Show(resolved);
    }

    private Task ShowSystemPromptsAsync(Window? arg)
    {
        var vm = new SystemPromptEditorViewModel(_settingsService);
        var win = new Views.SystemPromptEditorWindow { DataContext = vm };
        var resolved = ResolveOwnerWindow(arg);
        win.Closed += (_, __) =>
        {
            StatusText = vm.DialogResult == true ? "System prompts saved." : "System prompt editor closed.";
        };
        win.Show(resolved);
        return Task.CompletedTask;
    }

    private async Task ShowInvokeAIModelDefaultsAsync(Window? arg)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var vm = new InvokeAIModelDefaultsViewModel(_settingsService, _invokeAIClient, _notifications);
        var win = new Views.InvokeAIModelDefaultsWindow { DataContext = vm };
        win.Show(ResolveOwnerWindow(arg));
    }

    private async Task ShowInvokeAILoraDefaultsAsync(Window? arg)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var vm = new InvokeAILoraDefaultsViewModel(_settingsService, _invokeAIClient, _notifications);
        var win = new Views.InvokeAILoraDefaultsWindow { DataContext = vm };
        win.Show(ResolveOwnerWindow(arg));
    }

    private Task ShowPromptEvolverAsync(Window? arg)
    {
        var vm = new PromptEvolverViewModel(_ollamaClient, _historyManager, _settingsService);
        var ownerWindow = ResolveOwnerWindow(arg);

        async Task HandlePromptActionAsync(string prompt, bool generateImage)
        {
            if (string.IsNullOrWhiteSpace(prompt))
            {
                return;
            }

            PromptText = prompt;
            OutputText = prompt;
            _lastGeneration = null;
            ProcessedPromptSegments.Clear();
            MissingWildcards.Clear();

            if (generateImage)
            {
                await GenerateImageAsync(ownerWindow);
            }
            else
            {
                await EnhancePromptTextAsync(prompt, prompt);
            }
        }

        vm.ChildPromptSelected += (_, prompt) =>
        {
            if (string.IsNullOrWhiteSpace(prompt))
            {
                return;
            }

            PromptText = prompt;
            OutputText = prompt;
            _lastGeneration = null;
            ProcessedPromptSegments.Clear();
            MissingWildcards.Clear();
            StatusText = "Loaded bred prompt into the editor.";
        };
        vm.GenerateImageRequested += (_, prompt) => _ = HandlePromptActionAsync(prompt, generateImage: true);
        vm.EnhancePromptRequested += (_, prompt) => _ = HandlePromptActionAsync(prompt, generateImage: false);

        var win = new Views.PromptEvolverWindow(vm);
        win.Show(ownerWindow);
        return Task.CompletedTask;
    }

    private async Task ShowPngMetadataViewerAsync(Window? owner)
    {
        var historyManager = (Avalonia.Application.Current as App)?.HistoryManagerService;
        var vm = new PngMetadataViewerViewModel(historyManager, _settingsService);
        vm.GenerateMergedRequested = GenerateFromMergedPngAsync;
        vm.GenerateGraphReplayRequested = GenerateFromPngGraphAsync;
        vm.BuildGenerationGraphJsonAsync = BuildGenerationGraphJsonAsync;
        vm.ShowJsonDiffRequested = ShowJsonDiffAsync;
        var win = new Views.PngMetadataViewerWindow(vm);
        win.Show(ResolveOwnerWindow(owner));
        await Task.CompletedTask;
    }

    private Task ShowHistoryIntegrityAsync(Window? owner)
    {
        var vm = new HistoryIntegrityViewModel(_historyManager, _imageCacheService);
        var win = new Views.HistoryIntegrityWindow { DataContext = vm };
        win.Show(ResolveOwnerWindow(owner));
        return Task.CompletedTask;
    }

    private async Task ShowImageInterrogatorAsync(Window? owner)
    {
        if (!await EnsureInvokeOnlineAsync(showToastOnFailure: true))
        {
            return;
        }

        var vm = new ImageInterrogatorViewModel(_ollamaClient);
        var win = new Views.ImageInterrogatorWindow { DataContext = vm };
        win.Closed += (_, __) => StatusText = "Image interrogator closed.";
        win.Show(ResolveOwnerWindow(owner));
    }

    private Task ShowModelStatsAsync(Window? owner)
    {
        var vm = new ModelStatsViewModel(_historyManager);
        var win = new Views.ModelStatsWindow { DataContext = vm };
        win.Show(ResolveOwnerWindow(owner));
        return Task.CompletedTask;
    }

    private async Task ShowWildcardManagerAsync(Window? owner)
    {
        await ShowWildcardManagerAsync(owner, null);
    }

    private async Task OpenWildcardInManagerAsync(string? wildcardName)
    {
        await ShowWildcardManagerAsync(GetOwnerWindow(null), wildcardName);
    }

    private async Task ShowWildcardManagerAsync(Window? owner, string? wildcardName)
    {
        OpenWildcardManagerWindow(owner, wildcardName);
        await Task.CompletedTask;
    }

    private Views.WildcardManagerWindow OpenWildcardManagerWindow(Window? owner, string? wildcardName)
    {
        var vm = new WildcardManagerViewModel(_wildcardService, _templateService);
        var win = new Views.WildcardManagerWindow(vm);
        if (!string.IsNullOrWhiteSpace(wildcardName))
        {
            win.SelectWildcardOnOpen(wildcardName);
        }
        win.Show(ResolveOwnerWindow(owner));
        return win;
    }

    private Window ResolveOwnerWindow(Window? owner)
    {
        return GetOwnerWindow(owner) ?? new Window();
    }

    private static void ShowCompareWindow(
        Window owner,
        HistoryEntry leftEntry,
        HistoryImage leftImage,
        Bitmap leftBitmap,
        HistoryEntry rightEntry,
        HistoryImage rightImage,
        Bitmap rightBitmap)
    {
        var compareVm = new CompareImagesViewModel(leftEntry, leftImage, leftBitmap, rightEntry, rightImage, rightBitmap);
        var compareWindow = new Views.CompareImagesWindow { DataContext = compareVm };
        compareWindow.Show(owner);
    }

    private static Window? GetOwnerWindow(Window? owner)
    {
        if (owner != null) return owner;
        var lifetime = Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime;
        return lifetime?.MainWindow;
    }

    private static Window? ResolvePreviewOwnerWindow(MultiImagePreviewViewModel? previewVm)
    {
        if (previewVm == null)
        {
            return null;
        }

        if (Application.Current?.ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
        {
            return null;
        }

        return desktop.Windows.FirstOrDefault(window => ReferenceEquals(window.DataContext, previewVm));
    }
}
