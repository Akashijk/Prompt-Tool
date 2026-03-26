using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Threading;
using PromptTool.Core.Clients.InvokeAI;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class MainWindowViewModel
{
    private (Views.MultiImagePreviewView preview, Task<bool?> resultTask, CancellationTokenSource cts)
        ShowPreviewWindow(MultiImagePreviewViewModel previewVm, Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return Dispatcher.UIThread.InvokeAsync(() => ShowPreviewWindowInternal(previewVm, owner)).GetAwaiter().GetResult();
        }

        return ShowPreviewWindowInternal(previewVm, owner);
    }

    private (Views.MultiImagePreviewView preview, Task<bool?> resultTask, CancellationTokenSource cts)
        ShowPreviewWindowInternal(MultiImagePreviewViewModel previewVm, Window? owner)
    {
        var preview = new Views.MultiImagePreviewView { DataContext = previewVm };
        var tcs = new TaskCompletionSource<bool?>();
        var cts = new CancellationTokenSource();
        previewVm.GenerationToken = cts;
        preview.Closed += (_, __) =>
        {
            cts.Cancel();
            previewVm.ClearPendingVariationJobs();
            tcs.TrySetResult(previewVm.DialogResult);
            if (_settingsService.Settings.ServerSafetyModeEnabled)
            {
                _ = TryEmptyModelCacheAsync(CancellationToken.None);
            }
        };
        preview.Show(ResolveOwnerWindow(owner));
        return (preview, tcs.Task, cts);
    }

    private Task<(bool ok, List<InvokeAIGenerationParams>? parameters)> ShowImageGenerationDialogAsync(
        ImageGenerationOptionsViewModel dialogVm,
        Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return Dispatcher.UIThread.InvokeAsync(() => ShowImageGenerationDialogAsync(dialogVm, owner));
        }

        var dialog = new Views.ImageGenerationDialog(dialogVm);
        dialog.Topmost = true;
        dialog.Opened += (_, __) => dialog.Activate();
        var tcs = new TaskCompletionSource<(bool, List<InvokeAIGenerationParams>?)>();
        dialog.Closed += (_, __) => tcs.TrySetResult(dialogVm.Result);
        dialog.Show(ResolveOwnerWindow(owner));
        return tcs.Task;
    }

    private HistoryEntry BuildHistoryEntryForGeneration(
        string originalPrompt,
        string processedPrompt,
        string? templateName,
        string ollamaModel,
        string? invokeModelFallback,
        string workflow,
        List<HistoryImage> images)
    {
        var firstParams = images.FirstOrDefault()?.GenerationParams;
        return new HistoryEntry
        {
            OriginalPrompt = originalPrompt,
            ProcessedPrompt = processedPrompt,
            TemplateName = templateName,
            OllamaModel = ollamaModel,
            InvokeAIModel = firstParams?.Model?.Name ?? invokeModelFallback,
            ImageParameters = firstParams,
            Images = images,
            Workflow = workflow
        };
    }

    private void AddHistoryEntryAndIndex(HistoryEntry entry)
    {
        _historyManager.AddEntry(entry);
        _ = IndexSavedHistoryImagesAsync(entry.Images);
    }

    private void AppendImagesToEntry(string entryId, List<HistoryImage> images)
    {
        var beforePaths = _historyManager.GetAllEntries()
            .FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase))?
            .Images
            .Select(i => i.ImagePath ?? string.Empty)
            .ToHashSet(StringComparer.OrdinalIgnoreCase)
            ?? new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var updated = _historyManager.AppendImages(entryId, images);
        if (updated != null)
        {
            var appended = updated.Images
                .Where(i => !beforePaths.Contains(i.ImagePath ?? string.Empty))
                .ToList();
            _ = IndexSavedHistoryImagesAsync(appended.Count > 0 ? appended : images);
        }

        RefreshOpenHistoryViews();
    }

    private void AppendImagesToEntry(string entryId, List<HistoryImage> images, HistoryImage? sourceImage)
    {
        if (sourceImage != null && !string.IsNullOrWhiteSpace(sourceImage.ImagePath))
        {
            foreach (var image in images)
            {
                image.DerivedFromImagePath ??= sourceImage.ImagePath;
            }
        }

        var beforePaths = _historyManager.GetAllEntries()
            .FirstOrDefault(e => string.Equals(e.Id, entryId, StringComparison.OrdinalIgnoreCase))?
            .Images
            .Select(i => i.ImagePath ?? string.Empty)
            .ToHashSet(StringComparer.OrdinalIgnoreCase)
            ?? new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var updated = _historyManager.AppendImages(entryId, images);
        if (updated != null)
        {
            var appended = updated.Images
                .Where(i => !beforePaths.Contains(i.ImagePath ?? string.Empty))
                .ToList();
            _ = IndexSavedHistoryImagesAsync(appended.Count > 0 ? appended : images);
        }

        RefreshOpenHistoryViews();
    }

    private async Task IndexSavedHistoryImagesAsync(IEnumerable<HistoryImage>? images)
    {
        if (images == null)
        {
            return;
        }

        var imageList = images
            .Where(i => i != null)
            .ToList();
        if (imageList.Count == 0)
        {
            return;
        }

        try
        {
            await _similarityFingerprintCacheService.UpsertImagesAsync(
                imageList,
                _historyManager.GetHistoryDir(),
                _imageCacheService,
                maxCount: 200);

            var duplicateMatches = await _similarityFingerprintCacheService.FindNearDuplicatesAgainstExistingAsync(
                imageList,
                _historyManager.GetHistoryDir(),
                SimilarityAlertThreshold,
                maxMatches: 30);
            if (duplicateMatches.Count > 0)
            {
                var nearestDistance = duplicateMatches.Min(m => m.Distance);
                _notifications?.ShowInfoAction(
                    $"Found {duplicateMatches.Count} near-duplicate match(es) to existing history (nearest distance: {nearestDistance}).",
                    "Similarity",
                    "Show Matches",
                    () => ShowSimilarityDuplicateMatchesWindow(duplicateMatches));
            }
        }
        catch (Exception ex)
        {
            if (_settingsService.Settings.Verbose)
            {
                Console.WriteLine($"Similarity index upsert failed: {ex.Message}");
            }
        }
    }

    private async Task RunExperimentPreviewAsync(
        ExperimentBatchDefinition experiment,
        ExperimentRunRequest request,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        string? originalPrompt = null,
        string? processedPrompt = null,
        string? templateName = null,
        string? ollamaModel = null)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel();
        previewVm.InitializePlaceholders(experiment.Jobs.Count);
        previewVm.StatusText = statusText;
        previewVm.HeaderContextText = experiment.HeaderContextText ?? string.Empty;

        for (var i = 0; i < experiment.Jobs.Count && i < previewVm.Slots.Count; i++)
        {
            previewVm.Slots[i].Label = experiment.Jobs[i].Label;
        }

        if (request.SaveSelectionsToHistory)
        {
            previewVm.OnSaveSlot = slot =>
            {
                var slotIndex = previewVm.Slots.IndexOf(slot);
                var parameters = slot.GenerationParams;
                var imagePrompt = parameters?.Prompt ?? string.Empty;
                var image = CreateHistoryImageFromSlot(
                    slot,
                    parameters,
                    $"Experiment:{request.Mode}",
                    imagePrompt,
                    Workflow);
                image.GenerationParamsJson = parameters != null ? JsonSerializer.Serialize(parameters) : null;
                image.ExperimentVariantIndex = slotIndex >= 0 ? slotIndex : null;
                image.ExperimentVariantLabel = slot.Label;
                image.ExperimentVariantValue = BuildExperimentVariantValue(request, slot, parameters);
                image.PromptTypeSuffix = slot.Label;
                savedImages.Add(image);
                return Task.CompletedTask;
            };
            previewVm.OnSaveCompleted = () =>
            {
                if (savedImages.Count > 0)
                {
                    var entry = BuildExperimentHistoryEntry(
                        request,
                        originalPrompt ?? string.Empty,
                        processedPrompt ?? string.Empty,
                        templateName,
                        ollamaModel ?? string.Empty,
                        savedImages[0].GenerationParams?.Model?.Name,
                        savedImages,
                        experiment.HeaderContextText);
                    AddHistoryEntryAndIndex(entry);
                    StatusText = "Experiment images saved to history.";
                }

                return Task.CompletedTask;
            };
        }
        else
        {
            previewVm.OnSaveSlot = _ => Task.CompletedTask;
            previewVm.OnSaveCompleted = () =>
            {
                StatusText = "Experiment preview closed without saving to history.";
                return Task.CompletedTask;
            };
        }

        ConfigurePreviewCommands(previewVm);
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        _ = saveTask;
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }

        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, experiment.Jobs.Count);
            job.CancelAction = () => cts.Cancel();
        }

        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;

        try
        {
            var jobs = experiment.Jobs
                .Zip(previewVm.Slots, (experimentJob, slot) => (experimentJob.Parameters, slot))
                .ToList();
            await GenerateImagesForSlotsAsync(jobs, previewVm, cts, allowLongPrompts, job);
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            StatusText = StatusGenerationCancelled;
            return;
        }

        previewVm.StatusText = request.SaveSelectionsToHistory
            ? StatusImagesReady
            : "Experiment ready. Save closes the preview without writing history.";
        StatusText = request.SaveSelectionsToHistory
            ? StatusImagesReadyMain
            : "Experiment ready. Review the results and close when done.";
    }

    private async Task<GenerationPreviewResult> RunGenerationPreviewAsync(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        bool waitForSaveSelection = true,
        Func<List<HistoryImage>, Task>? onSaveCompleted = null,
        bool isVerificationComparison = false)
    {
        var (previewVm, savedImages) = CreateGenerationPreviewVm(
            parametersList.Count,
            prompt,
            promptType,
            workflow,
            onSaveCompleted,
            isVerificationComparison);
        var (preview, saveTask, cts) = StartPreviewRun(previewVm, owner, statusText, job, parametersList.Count, externalToken);

        try
        {
            await GenerateImagesAsync(parametersList, previewVm, cts, allowLongPrompts, job);
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        return await FinalizePreviewResultAsync(previewVm, savedImages, cts, saveTask, waitForSaveSelection, checkAllEmptyFailure: true);
    }

    private async Task<GenerationPreviewResult> RunSeedVariationPreviewAsync(
        IReadOnlyList<InvokeAIGenerationParams> parametersList,
        string prompt,
        string promptType,
        string workflow,
        Window? owner,
        string statusText,
        bool allowLongPrompts,
        int rootSeed,
        byte[] rootImageBytes,
        GenerationJob? job = null,
        CancellationToken externalToken = default,
        bool waitForSaveSelection = true,
        Func<List<HistoryImage>, Task>? onSaveCompleted = null)
    {
        var (previewVm, savedImages) = CreateGenerationPreviewVm(
            parametersList.Count,
            prompt,
            promptType,
            workflow,
            onSaveCompleted,
            isVerificationComparison: false);
        var (_, saveTask, cts) = StartPreviewRun(previewVm, owner, statusText, job, parametersList.Count, externalToken);

        try
        {
            var jobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
            for (int i = 0; i < parametersList.Count && i < previewVm.Slots.Count; i++)
            {
                var param = parametersList[i];
                var slot = previewVm.Slots[i];
                ApplySlotGenerationMetadata(slot, param);

                if (param.Seed == rootSeed)
                {
                    slot.IsSelected = false;
                    previewVm.SetImage(i, rootImageBytes);
                }
                else
                {
                    slot.IsLoading = true;
                    jobs.Add((param, slot));
                }
            }

            previewVm.SyncProgressFromSlots();

            if (jobs.Count > 0)
            {
                await GenerateImagesForSlotsAsync(jobs, previewVm, cts, allowLongPrompts, job);
            }
        }
        finally
        {
            if (ReferenceEquals(_activeGenerationCts, cts))
            {
                _activeGenerationCts = null;
            }
        }

        return await FinalizePreviewResultAsync(previewVm, savedImages, cts, saveTask, waitForSaveSelection, checkAllEmptyFailure: false);
    }

    private (MultiImagePreviewViewModel previewVm, List<HistoryImage> savedImages) CreateGenerationPreviewVm(
        int placeholderCount,
        string prompt,
        string promptType,
        string workflow,
        Func<List<HistoryImage>, Task>? onSaveCompleted,
        bool isVerificationComparison)
    {
        var savedImages = new List<HistoryImage>();
        var previewVm = new MultiImagePreviewViewModel
        {
            ShowComparisonMetrics = isVerificationComparison,
            ShowSaveDiscardActions = !isVerificationComparison,
            ShowCompareAction = isVerificationComparison,
            DefaultSlotSelected = !isVerificationComparison
        };
        previewVm.InitializePlaceholders(placeholderCount);
        previewVm.OnSaveSlot = slot =>
        {
            var image = CreateHistoryImageFromSlot(
                slot,
                slot.GenerationParams,
                promptType,
                prompt,
                workflow);
            image.GenerationParamsJson = slot.GenerationParams != null ? JsonSerializer.Serialize(slot.GenerationParams) : null;
            savedImages.Add(image);
            return Task.CompletedTask;
        };
        previewVm.OnSaveCompleted = onSaveCompleted == null
            ? null
            : async () => await onSaveCompleted(savedImages);
        ConfigurePreviewCommands(previewVm);
        return (previewVm, savedImages);
    }

    private (Views.MultiImagePreviewView preview, Task<bool?> saveTask, CancellationTokenSource cts) StartPreviewRun(
        MultiImagePreviewViewModel previewVm,
        Window? owner,
        string statusText,
        GenerationJob? job,
        int totalCount,
        CancellationToken externalToken)
    {
        previewVm.StatusText = statusText;
        var (preview, saveTask, cts) = ShowPreviewWindow(previewVm, owner);
        if (externalToken.CanBeCanceled)
        {
            externalToken.Register(() => cts.Cancel());
        }

        if (job != null)
        {
            job.StatusMessage = statusText;
            job.UpdateProgress(0, totalCount);
            job.CancelAction = () => cts.Cancel();
        }

        _activeGenerationCts = cts;
        previewVm.OnEditAndRegenerate = async slot => await EditAndRegenerateSlotAsync(slot, preview);
        StatusText = statusText;
        return (preview, saveTask, cts);
    }

    private async Task<GenerationPreviewResult> FinalizePreviewResultAsync(
        MultiImagePreviewViewModel previewVm,
        List<HistoryImage> savedImages,
        CancellationTokenSource cts,
        Task<bool?> saveTask,
        bool waitForSaveSelection,
        bool checkAllEmptyFailure)
    {
        if (cts.IsCancellationRequested)
        {
            previewVm.StatusText = StatusGenerationCancelled;
            return new GenerationPreviewResult(null, savedImages);
        }

        if (checkAllEmptyFailure && previewVm.GeneratedCount == 0 && previewVm.Slots.Count > 0)
        {
            var allEmpty = previewVm.Slots.All(s => !s.IsLoading && s.ImageBytes == null);
            if (allEmpty)
            {
                var failedStatus = string.IsNullOrWhiteSpace(previewVm.StatusText)
                    ? "Generation failed. No images were returned."
                    : previewVm.StatusText;
                previewVm.StatusText = failedStatus;
                StatusText = failedStatus;

                if (!waitForSaveSelection)
                {
                    _ = saveTask;
                    return new GenerationPreviewResult(null, savedImages);
                }

                var failedResult = await saveTask;
                return new GenerationPreviewResult(failedResult, savedImages);
            }
        }

        previewVm.StatusText = StatusImagesReady;
        StatusText = StatusImagesReadyMain;

        if (!waitForSaveSelection)
        {
            _ = saveTask;
            return new GenerationPreviewResult(null, savedImages);
        }

        var saveResult = await saveTask;
        return new GenerationPreviewResult(saveResult, savedImages);
    }

    private void ApplyGenerationResultStatus(GenerationPreviewResult result, string savedMessage, string discardedMessage)
    {
        if (result.Saved == true)
        {
            StatusText = savedMessage;
        }
        else if (result.Saved == null)
        {
            StatusText = StatusGenerationCancelled;
        }
        else
        {
            StatusText = discardedMessage;
        }
    }

    private Func<List<HistoryImage>, Task> BuildAppendToEntryOnSaveCallback(
        HistoryEntry entry,
        HistoryImage? sourceImage,
        string successMessage)
    {
        return async images =>
        {
            AppendImagesToEntry(entry.Id, images, sourceImage);
            StatusText = successMessage;
            await Task.CompletedTask;
        };
    }

    private async Task EnqueueVariationJobAsync(
        string jobName,
        string? preferredModel,
        int estimatedWorkUnits,
        Func<GenerationJob, CancellationToken, Task> runAsync,
        string failurePrefix)
    {
        await EnqueueGenerationJobAsync(
            jobName,
            async (job, token) =>
            {
                _generationInProgress = true;
                try
                {
                    await runAsync(job, token);
                }
                catch (Exception ex)
                {
                    StatusText = $"{failurePrefix}: {ex.Message}";
                }
                finally
                {
                    _generationInProgress = false;
                }
            },
            preferredModel,
            estimatedWorkUnits);
    }

    private static bool IsPreviewActivelyGenerating(MultiImagePreviewViewModel previewVm)
        => previewVm.GenerationToken != null &&
           !previewVm.GenerationToken.IsCancellationRequested &&
           previewVm.Slots.Any(existing => existing.IsLoading);

    private static CancellationTokenSource EnsurePreviewGenerationToken(MultiImagePreviewViewModel previewVm)
    {
        var generationToken = previewVm.GenerationToken;
        if (generationToken == null || generationToken.IsCancellationRequested)
        {
            generationToken = new CancellationTokenSource();
            previewVm.GenerationToken = generationToken;
        }

        return generationToken;
    }

    private static void NormalizePreviewSlotModelGrouping(MultiImagePreviewViewModel previewVm)
    {
        if (previewVm.Slots.Count < 2)
        {
            return;
        }

        var firstIndexByModel = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var indexed = previewVm.Slots
            .Select((slot, index) =>
            {
                var model = slot.GenerationParams?.Model?.Name;
                if (string.IsNullOrWhiteSpace(model))
                {
                    model = slot.ModelUsed;
                }

                var key = string.IsNullOrWhiteSpace(model) ? "~unknown" : model.Trim();
                if (!firstIndexByModel.ContainsKey(key))
                {
                    firstIndexByModel[key] = index;
                }

                return new { slot, index, key };
            })
            .ToList();

        var reordered = indexed
            .OrderBy(item => firstIndexByModel[item.key])
            .ThenBy(item => item.index)
            .Select(item => item.slot)
            .ToList();

        var changed = false;
        for (var i = 0; i < reordered.Count; i++)
        {
            if (!ReferenceEquals(reordered[i], previewVm.Slots[i]))
            {
                changed = true;
                break;
            }
        }

        if (!changed)
        {
            return;
        }

        previewVm.Slots.Clear();
        foreach (var slot in reordered)
        {
            previewVm.Slots.Add(slot);
        }
    }

    private bool TryQueuePreviewVariationJobs(
        MultiImagePreviewViewModel previewVm,
        IReadOnlyList<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs,
        string queuedStatus)
    {
        if (!IsPreviewActivelyGenerating(previewVm))
        {
            return false;
        }

        previewVm.EnqueuePendingVariationJobs(jobs);
        previewVm.StatusText = queuedStatus;
        StatusText = queuedStatus;
        return true;
    }

    private async Task GeneratePreviewVariationJobsAsync(
        MultiImagePreviewViewModel previewVm,
        IReadOnlyList<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs,
        string generatingStatus,
        bool updateMainStatus)
    {
        previewVm.StatusText = generatingStatus;
        if (updateMainStatus)
        {
            StatusText = generatingStatus;
        }

        var generationToken = EnsurePreviewGenerationToken(previewVm);
        if (jobs.Count > 0)
        {
            await GenerateImagesForSlotsAsync(jobs, previewVm, generationToken, allowLongPrompts: true, job: null);
        }

        previewVm.StatusText = StatusImagesReady;
        if (updateMainStatus)
        {
            StatusText = StatusImagesReadyMain;
        }
    }

    private static string? GetDominantModelName(IEnumerable<InvokeAIGenerationParams>? parameters)
    {
        return parameters?
            .Where(param => !string.IsNullOrWhiteSpace(param.Model?.Name))
            .GroupBy(param => param.Model!.Name, StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(group => group.Count())
            .ThenBy(group => group.Key, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.Key)
            .FirstOrDefault();
    }

    private void ConfigurePreviewCommands(MultiImagePreviewViewModel previewVm)
    {
        previewVm.OnGenerateSeedVariations = async slot => await GenerateVariationsFromSlotAsync(slot, true, previewVm);
        previewVm.OnGenerateModelVariations = async slot => await GenerateModelPermutationsFromSlotAsync(slot, previewVm);
        previewVm.OnGenerateLoraVariations = async slot => await GenerateLoraPermutationsFromSlotAsync(slot, previewVm);
        previewVm.OnPromoteToBase = async slot => await PromotePreviewSlotToBaseAsync(slot);
        previewVm.OnEnhanceFromThis = async slot => await EnhancePromptFromPreviewSlotAsync(slot);
        previewVm.OnCompareSelected = async slots => await CompareSelectedPreviewSlotsAsync(slots);
    }

    private Task CompareSelectedPreviewSlotsAsync(IReadOnlyList<ImageSlotViewModel> slots)
    {
        if (slots.Count != 2)
        {
            StatusText = "Select exactly two images to compare.";
            return Task.CompletedTask;
        }

        var leftSlot = slots[0];
        var rightSlot = slots[1];
        if (leftSlot.Image == null || rightSlot.Image == null)
        {
            StatusText = "Both selected slots must have generated images.";
            return Task.CompletedTask;
        }

        var leftBitmap = UiBitmapHelper.CloneForUi(leftSlot.Image);
        var rightBitmap = UiBitmapHelper.CloneForUi(rightSlot.Image);
        if (leftBitmap == null || rightBitmap == null)
        {
            leftBitmap?.Dispose();
            rightBitmap?.Dispose();
            StatusText = "Failed to prepare images for comparison.";
            return Task.CompletedTask;
        }

        var leftEntry = new HistoryEntry
        {
            ProcessedPrompt = leftSlot.GenerationParams?.Prompt ?? string.Empty,
            OriginalPrompt = leftSlot.GenerationParams?.Prompt ?? string.Empty
        };
        var rightEntry = new HistoryEntry
        {
            ProcessedPrompt = rightSlot.GenerationParams?.Prompt ?? string.Empty,
            OriginalPrompt = rightSlot.GenerationParams?.Prompt ?? string.Empty
        };

        var leftImage = new HistoryImage
        {
            PromptType = leftSlot.Label,
            Prompt = leftSlot.GenerationParams?.Prompt,
            GenerationParams = leftSlot.GenerationParams,
            GenerationDurationMs = leftSlot.GenerationDurationMs,
            QueueWaitMs = leftSlot.QueueWaitMs,
            TotalDurationMs = leftSlot.TotalDurationMs
        };
        var rightImage = new HistoryImage
        {
            PromptType = rightSlot.Label,
            Prompt = rightSlot.GenerationParams?.Prompt,
            GenerationParams = rightSlot.GenerationParams,
            GenerationDurationMs = rightSlot.GenerationDurationMs,
            QueueWaitMs = rightSlot.QueueWaitMs,
            TotalDurationMs = rightSlot.TotalDurationMs
        };

        ShowCompareWindow(ResolveOwnerWindow(null), leftEntry, leftImage, leftBitmap, rightEntry, rightImage, rightBitmap);
        return Task.CompletedTask;
    }

    private Task PromotePreviewSlotToBaseAsync(ImageSlotViewModel slot)
    {
        var prompt = slot.GenerationParams?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "This image does not have a prompt to promote.";
            return Task.CompletedTask;
        }

        PromptText = prompt;
        OutputText = prompt;
        _lastGeneration = null;
        ProcessedPromptSegments.Clear();
        MissingWildcards.Clear();
        var segmentVm = new PromptSegmentViewModel(new PromptSegment(prompt), 0)
        {
            Tooltip = "Promoted from image preview."
        };
        segmentVm.PropertyChanged += (_, _) => RefreshProcessedOutput();
        ProcessedPromptSegments.Add(segmentVm);
        RefreshProcessedOutput();
        StatusText = "Promoted image prompt to the base prompt.";
        return Task.CompletedTask;
    }

    private async Task EnhancePromptFromPreviewSlotAsync(ImageSlotViewModel slot)
    {
        var prompt = slot.GenerationParams?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt))
        {
            StatusText = "This image does not have a prompt to enhance.";
            return;
        }

        await EnhancePromptTextAsync(prompt, prompt);
    }

    private async Task<List<List<LoraParameter>>?> ShowLoraPermutationDialogAsync(InvokeAIGenerationParams baseParams, Window? owner)
    {
        if (!Dispatcher.UIThread.CheckAccess())
        {
            return await Dispatcher.UIThread.InvokeAsync(() => ShowLoraPermutationDialogAsync(baseParams, owner));
        }

        var baseModel = baseParams.Model?.Base ?? baseParams.BaseModelType;
        var loras = await _invokeAIClient.GetModelsAsync(baseModel, "lora");
        var dialogVm = new LoraPermutationDialogViewModel(loras, baseParams.Loras);
        var dialog = new Views.LoraPermutationDialog(dialogVm);
        var tcs = new TaskCompletionSource<List<List<LoraParameter>>?>();
        EventHandler? requestCloseHandler = null;
        requestCloseHandler = (_, _) => dialog.Close();
        dialogVm.RequestClose += requestCloseHandler;
        dialog.Closed += (_, _) => dialogVm.RequestClose -= requestCloseHandler;
        dialog.Closed += (_, _) => tcs.TrySetResult(dialogVm.Result);
        dialog.Show(ResolveOwnerWindow(owner));
        return await tcs.Task;
    }

    private static InvokeAIGenerationParams CloneParams(InvokeAIGenerationParams src)
    {
        var model = src.Model;
        if (model != null && string.IsNullOrEmpty(model.Type))
        {
            model = model with { Type = "main" };
        }

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
            Model = model,
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

    private void ApplyLoraPromptPrefixes(InvokeAIGenerationParams parameters)
    {
        if (parameters.Loras == null || parameters.Loras.Count == 0) return;
        if (_settingsService.InvokeAILoraDefaults == null || _settingsService.InvokeAILoraDefaults.Count == 0) return;

        var posSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var negSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var lora in parameters.Loras)
        {
            if (lora?.Lora == null || string.IsNullOrWhiteSpace(lora.Lora.Name)) continue;
            var defaults = FindLoraDefaultsForName(lora.Lora.Name);
            if (defaults == null) continue;

            AddPrefixParts(posSet, defaults.PositivePromptPrefix);
            AddPrefixParts(negSet, defaults.NegativePromptPrefix);
        }

        if (posSet.Count > 0)
        {
            var combined = string.Join(", ", posSet.OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
            parameters.Prompt = string.IsNullOrWhiteSpace(parameters.Prompt)
                ? combined
                : $"{combined}, {parameters.Prompt.Trim()}";
        }

        if (negSet.Count > 0)
        {
            var combined = string.Join(", ", negSet.OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
            parameters.NegativePrompt = string.IsNullOrWhiteSpace(parameters.NegativePrompt)
                ? combined
                : $"{combined}, {parameters.NegativePrompt.Trim()}";
        }
    }

    private ModelDefaults? FindLoraDefaultsForName(string? loraName)
    {
        if (string.IsNullOrWhiteSpace(loraName)) return null;
        var defaults = _settingsService.InvokeAILoraDefaults;
        if (defaults == null || defaults.Count == 0) return null;

        var exact = defaults.FirstOrDefault(d => string.Equals(d.ModelName, loraName, StringComparison.OrdinalIgnoreCase));
        if (exact != null) return exact;

        var normalized = NormalizeLoraLookupName(loraName);
        if (string.IsNullOrWhiteSpace(normalized)) return null;
        return defaults.FirstOrDefault(d => string.Equals(NormalizeLoraLookupName(d.ModelName), normalized, StringComparison.Ordinal));
    }

    private static string NormalizeLoraLookupName(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return string.Empty;
        var name = value.Trim();

        while (true)
        {
            var stripped = Path.GetFileNameWithoutExtension(name);
            if (string.IsNullOrWhiteSpace(stripped) || string.Equals(stripped, name, StringComparison.Ordinal))
            {
                break;
            }

            name = stripped;
        }

        var sb = new StringBuilder(name.Length);
        foreach (var ch in name)
        {
            if (char.IsLetterOrDigit(ch))
            {
                sb.Append(char.ToLowerInvariant(ch));
            }
        }

        return sb.ToString();
    }

    private static void AddPrefixParts(HashSet<string> target, string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return;
        var parts = raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        foreach (var part in parts)
        {
            if (!string.IsNullOrWhiteSpace(part))
            {
                target.Add(part.Trim());
            }
        }
    }

    private async Task GenerateImagesAsync(IReadOnlyList<InvokeAIGenerationParams> parametersList, MultiImagePreviewViewModel previewVm, CancellationTokenSource cts, bool allowLongPrompts, GenerationJob? job = null)
    {
        var slotAssignments = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
        for (int i = 0; i < parametersList.Count && i < previewVm.Slots.Count; i++)
        {
            slotAssignments.Add((parametersList[i], previewVm.Slots[i]));
        }

        await GenerateImagesForSlotsAsync(slotAssignments, previewVm, cts, allowLongPrompts, job);
    }

    private async Task GenerateImagesForSlotsAsync(
        IReadOnlyList<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> jobs,
        MultiImagePreviewViewModel previewVm,
        CancellationTokenSource cts,
        bool allowLongPrompts,
        GenerationJob? job = null)
    {
        var completedAny = false;
        var failedCount = 0;
        string? firstFailureMessage = null;
        previewVm.StatusText = "Generating images...";
        if (!ValidateGenerationParams(jobs.Select(j => j.param).ToList(), allowLongPrompts, out var invalidMessage, out var isWarning))
        {
            StatusText = invalidMessage;
            previewVm.StatusText = invalidMessage;
            cts.Cancel();
            return;
        }

        if (isWarning)
        {
            StatusText = invalidMessage;
            previewVm.StatusText = invalidMessage;
        }

        foreach (var (param, slot) in jobs)
        {
            ApplySlotGenerationMetadata(slot, param);
            slot.IsLoading = true;
        }

        previewVm.SyncProgressFromSlots();
        job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);

        var pendingJobs = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>(jobs);
        string? currentModelKey = null;

        void AttachPendingPreviewJobs()
        {
            var attached = previewVm.TakePendingVariationJobs();
            if (attached.Count == 0)
            {
                return;
            }

            foreach (var (param, slot) in attached)
            {
                ApplySlotGenerationMetadata(slot, param);
                slot.IsLoading = true;
            }

            pendingJobs.AddRange(attached);
            previewVm.SyncProgressFromSlots();
            job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);
        }

        static string GetModelKey(InvokeAIGenerationParams param)
            => param.Model?.Name ?? string.Empty;

        static List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakeJobsForModel(
            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> source,
            string modelKey)
        {
            var matches = source
                .Where(item => string.Equals(GetModelKey(item.param), modelKey, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (matches.Count == 0)
            {
                return matches;
            }

            foreach (var match in matches)
            {
                source.Remove(match);
            }

            return matches;
        }

        static List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> TakeLargestModelBatch(
            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> source,
            out string modelKey)
        {
            var selected = source
                .Select((item, index) => new { item, index })
                .GroupBy(x => GetModelKey(x.item.param), StringComparer.OrdinalIgnoreCase)
                .Select(group => new
                {
                    ModelKey = group.Key,
                    Count = group.Count(),
                    FirstIndex = group.Min(x => x.index)
                })
                .OrderByDescending(group => group.Count)
                .ThenBy(group => group.FirstIndex)
                .First();

            modelKey = selected.ModelKey;
            return TakeJobsForModel(source, modelKey);
        }

        while (!cts.IsCancellationRequested)
        {
            AttachPendingPreviewJobs();
            if (pendingJobs.Count == 0)
            {
                break;
            }

            List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)> activeBatch;
            if (!string.IsNullOrWhiteSpace(currentModelKey))
            {
                activeBatch = TakeJobsForModel(pendingJobs, currentModelKey);
            }
            else
            {
                activeBatch = new List<(InvokeAIGenerationParams param, ImageSlotViewModel slot)>();
            }

            if (activeBatch.Count == 0)
            {
                activeBatch = TakeLargestModelBatch(pendingJobs, out var selectedModelKey);
                currentModelKey = selectedModelKey;
            }

            foreach (var (param, slot) in activeBatch)
            {
                if (cts.IsCancellationRequested) break;
                try
                {
                    await ResolveInvokeModelsAsync(param);
                    if (!ValidateGenerationParams(param, allowLongPrompts, out var invalidParamMessage, out var paramWarning))
                    {
                        StatusText = invalidParamMessage;
                        previewVm.StatusText = invalidParamMessage;
                        cts.Cancel();
                        break;
                    }

                    if (paramWarning)
                    {
                        StatusText = invalidParamMessage;
                        previewVm.StatusText = invalidParamMessage;
                    }

                    await _invokeGenerationGate.WaitAsync(cts.Token);
                    InvokeAIGenerationResult result;
                    try
                    {
                        result = await _invokeAIClient.GenerateImageAsync(param, ct: cts.Token);
                    }
                    finally
                    {
                        _invokeGenerationGate.Release();
                    }

                    RecordKpiGeneration(param, result.JobInfo, Workflow);
                    if (result.GenerationParams?.Vae?.Name is { Length: > 0 } vaeName)
                    {
                        param.VaeUsedName = vaeName;
                    }

                    previewVm.UpdateSlotImage(slot, result.ImageBytes);
                    ApplyJobInfoToSlot(slot, result.JobInfo);
                    previewVm.IncrementGenerated();
                    completedAny = true;
                    job?.UpdateProgress(previewVm.GeneratedCount, previewVm.TotalCount);
                }
                catch (OperationCanceledException)
                {
                    StatusText = "Image generation cancelled.";
                    cts.Cancel();
                    previewVm.ClearPendingVariationJobs();
                    foreach (var pendingSlot in previewVm.Slots.Where(s => s.IsLoading))
                    {
                        pendingSlot.IsLoading = false;
                    }

                    previewVm.SyncProgressFromSlots();
                    return;
                }
                catch (InvokeAIJobFailedException ex)
                {
                    RecordKpiGeneration(param, ex.JobInfo, Workflow);
                    slot.IsLoading = false;
                    failedCount++;
                    if (string.IsNullOrWhiteSpace(firstFailureMessage))
                    {
                        firstFailureMessage = ex.Message;
                    }

                    Console.WriteLine($"Generation failed: {ex.Message}");
                }
                catch (Exception ex)
                {
                    slot.IsLoading = false;
                    failedCount++;
                    if (string.IsNullOrWhiteSpace(firstFailureMessage))
                    {
                        firstFailureMessage = ex.Message;
                    }

                    Console.WriteLine($"Generation failed: {ex.Message}");
                }
            }

            if (cts.IsCancellationRequested) break;

            AttachPendingPreviewJobs();
            if (pendingJobs.Any(item => string.Equals(GetModelKey(item.param), currentModelKey ?? string.Empty, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            if (_settingsService.Settings.AutoClearInvokeCacheBetweenModels)
            {
                await TryEmptyModelCacheAsync(cts.Token);
            }

            currentModelKey = null;
        }

        if (cts.IsCancellationRequested)
        {
            previewVm.ClearPendingVariationJobs();
            foreach (var pendingSlot in previewVm.Slots.Where(s => s.IsLoading))
            {
                pendingSlot.IsLoading = false;
            }

            previewVm.SyncProgressFromSlots();
            return;
        }

        if (!completedAny && failedCount > 0 && !cts.IsCancellationRequested)
        {
            var message = string.IsNullOrWhiteSpace(firstFailureMessage)
                ? "Generation failed. No images were returned."
                : $"Generation failed: {firstFailureMessage}";
            previewVm.StatusText = message;
            StatusText = message;
            Console.WriteLine(message);
            return;
        }

        if (completedAny && !cts.IsCancellationRequested && ShouldNotifyGenerationCompletion(job))
        {
            previewVm.StatusText = StatusImagesReadySaveDiscard;
            TryPlayGenerationCompleteSound();
        }
    }

    private static HistoryImage CreateHistoryImageFromSlot(
        ImageSlotViewModel slot,
        InvokeAIGenerationParams? parameters,
        string promptType,
        string prompt,
        string workflow)
    {
        var image = new HistoryImage
        {
            ImageBytes = slot.ImageBytes,
            GenerationParams = parameters,
            PromptType = promptType,
            Prompt = parameters?.Prompt ?? prompt,
            Workflow = workflow,
            IsFavorite = slot.IsFavorite
        };
        ApplyJobInfoToHistoryImage(image, slot);
        return image;
    }

    private static void ApplyJobInfoToSlot(ImageSlotViewModel slot, GenerationJobInfo? jobInfo)
    {
        if (jobInfo == null) return;
        slot.GenerationDurationMs = jobInfo.GenerationDurationMs;
        slot.QueueWaitMs = jobInfo.QueueWaitMs;
        slot.TotalDurationMs = jobInfo.TotalDurationMs;
        slot.GenerationStatus = jobInfo.Status;
        slot.ErrorType = jobInfo.ErrorType;
        slot.ErrorMessage = jobInfo.ErrorMessage;
        slot.ErrorTraceback = jobInfo.ErrorTraceback;
        slot.RefreshComparisonMetricProperties();
    }

    private static void ApplyJobInfoToHistoryImage(HistoryImage image, ImageSlotViewModel slot)
    {
        image.GenerationDurationMs = slot.GenerationDurationMs;
        image.QueueWaitMs = slot.QueueWaitMs;
        image.TotalDurationMs = slot.TotalDurationMs;
        image.GenerationStatus = slot.GenerationStatus;
        image.ErrorType = slot.ErrorType;
        image.ErrorMessage = slot.ErrorMessage;
        image.ErrorTraceback = slot.ErrorTraceback;
    }

    private void RecordKpiGeneration(InvokeAIGenerationParams parameters, GenerationJobInfo? jobInfo, string? workflow)
    {
        _kpiStats?.RecordGeneration(parameters, jobInfo, workflow ?? Workflow);
    }
}
