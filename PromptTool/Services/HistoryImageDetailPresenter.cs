using System;
using System.IO;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.ViewModels;
using PromptTool.Views;

namespace PromptTool.Services;

public static class HistoryImageDetailPresenter
{
    public static void Show(
        HistoryEntry entry,
        HistoryImage image,
        Bitmap fallbackBitmap,
        Window owner,
        HistoryManagerService historyManager,
        HistoryIndexService historyIndexService,
        ImageCacheService imageCacheService,
        Func<HistoryEntry, HistoryImage, Task>? upscaleRequested)
    {
        var detailBitmap = ResolveDetailBitmap(image, fallbackBitmap, historyManager, imageCacheService);
        var processed = HistoryViewerViewModel.ResolveGeneratedPromptForImage(entry, image);
        if (string.IsNullOrWhiteSpace(processed))
        {
            processed = entry.ProcessedPrompt;
        }

        var detailsText = HistoryViewerViewModel.BuildDetailsText(entry, image);
        var detailVm = new HistoryImageDetailViewModel(
            entry,
            image,
            detailBitmap,
            detailsText,
            processed,
            entry.OriginalPrompt)
        {
            Clipboard = owner.Clipboard,
            UpscaleRequested = upscaleRequested
        };

        var lightbox = new HistoryImageDetailWindow
        {
            DataContext = detailVm,
            HistoryManager = historyManager,
            HistoryIndexService = historyIndexService
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
