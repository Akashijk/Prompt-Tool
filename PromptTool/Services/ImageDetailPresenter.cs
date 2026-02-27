using System;
using System.IO;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.ViewModels;
using PromptTool.Services;
using PromptTool.Views;

namespace PromptTool.Services;

public static class ImageDetailPresenter
{
    public static void Show(
        HistoryEntry entry,
        HistoryImage image,
        Bitmap fallbackBitmap,
        Window owner,
        HistoryManagerService historyManager,
        HistoryIndexService historyIndexService,
        ImageCacheService imageCacheService,
        Func<HistoryEntry, HistoryImage, Task>? upscaleRequested,
        Func<HistoryEntry, HistoryImage, Task>? generateMoreRequested,
        Func<HistoryEntry, HistoryImage, Task>? generateSeedVariationsRequested,
        Func<HistoryEntry, HistoryImage, Task>? generateLoraVariationsRequested,
        Func<HistoryEntry, HistoryImage, Task>? generateModelVariationsRequested,
        ImageDetailMode displayMode = ImageDetailMode.History)
    {
        var detailBitmap = ResolveDetailBitmap(image, fallbackBitmap, historyManager, imageCacheService);
        var safeBitmap = UiBitmapHelper.CloneForUi(detailBitmap)
                        ?? UiBitmapHelper.CloneForUi(fallbackBitmap)
                        ?? fallbackBitmap;
        var processed = HistoryViewerViewModel.ResolveGeneratedPromptForImage(entry, image);
        if (string.IsNullOrWhiteSpace(processed))
        {
            processed = entry.ProcessedPrompt;
        }

        var detailsText = HistoryViewerViewModel.BuildDetailsText(entry, image);
        var detailVm = new ImageDetailViewModel(
            entry,
            image,
            safeBitmap,
            detailsText,
            processed,
            entry.OriginalPrompt)
        {
            Clipboard = owner.Clipboard,
            UpscaleRequested = upscaleRequested,
            GenerateMoreRequested = generateMoreRequested,
            GenerateSeedVariationsRequested = generateSeedVariationsRequested,
            GenerateLoraVariationsRequested = generateLoraVariationsRequested,
            GenerateModelVariationsRequested = generateModelVariationsRequested,
            DisplayMode = displayMode
        };
        detailVm.UpdateGenerationActions();

        var lightbox = new ImageDetailWindow
        {
            DataContext = detailVm,
            HistoryManager = historyManager,
            HistoryIndexService = historyIndexService
        };
        lightbox.Show(owner);
        lightbox.Activate();
    }

    public static void ShowForPreview(
        ImageSlotViewModel slot,
        Window owner)
    {
        if (slot.Image == null && (slot.ImageBytes == null || slot.ImageBytes.Length == 0))
        {
            return;
        }

        var entry = new HistoryEntry
        {
            Timestamp = DateTime.Now,
            OriginalPrompt = slot.GenerationParams?.Prompt ?? string.Empty,
            ProcessedPrompt = slot.GenerationParams?.Prompt ?? string.Empty,
            ImageParameters = slot.GenerationParams
        };
        var image = new HistoryImage
        {
            ImageBytes = slot.ImageBytes,
            GenerationParams = slot.GenerationParams,
            Prompt = slot.GenerationParams?.Prompt
        };

        Bitmap? detailBitmap = null;
        if (slot.ImageBytes != null && slot.ImageBytes.Length > 0)
        {
            try
            {
                using var ms = new MemoryStream(slot.ImageBytes);
                detailBitmap = new Bitmap(ms);
            }
            catch
            {
                detailBitmap = null;
            }
        }

        detailBitmap ??= UiBitmapHelper.CloneForUi(slot.Image);
        if (detailBitmap == null)
        {
            return;
        }

        var safeBitmap = UiBitmapHelper.CloneForUi(detailBitmap) ?? detailBitmap;
        var detailsText = HistoryViewerViewModel.BuildDetailsText(entry, image);
        var detailVm = new ImageDetailViewModel(
            entry,
            image,
            safeBitmap,
            detailsText,
            entry.ProcessedPrompt,
            entry.OriginalPrompt)
        {
            Clipboard = owner.Clipboard,
            DisplayMode = ImageDetailMode.ActiveGeneration
        };
        detailVm.UpdateGenerationActions();

        var lightbox = new ImageDetailWindow
        {
            DataContext = detailVm
        };
        lightbox.Show(owner);
        lightbox.Activate();
    }

    private static Bitmap ResolveDetailBitmap(
        HistoryImage image,
        Bitmap fallback,
        HistoryManagerService historyManager,
        ImageCacheService imageCacheService)
    {
        var path = image.ImagePath;
        if (!string.IsNullOrWhiteSpace(path))
        {
            var full = imageCacheService.GetOrLoad(path, null, historyManager.GetHistoryDir());
            if (full != null)
            {
                return full;
            }
        }

        if (image.ImageBytes != null && image.ImageBytes.Length > 0)
        {
            try
            {
                using var ms = new MemoryStream(image.ImageBytes);
                return new Bitmap(ms);
            }
            catch
            {
                return fallback;
            }
        }

        return fallback;
    }
}
