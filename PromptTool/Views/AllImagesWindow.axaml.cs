using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using PromptTool.ViewModels;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace PromptTool.Views;

public partial class AllImagesWindow : Window
{
    public AllImagesWindow()
    {
        InitializeComponent();
        HookDataContext();
    }

    public AllImagesWindow(AllImagesViewerViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        WireContext();
    }

    private void HookDataContext()
    {
        DataContextChanged += (_, _) => WireContext();
    }

    private void WireContext()
    {
        if (DataContext is not AllImagesViewerViewModel vm) return;
        vm.CompareRequested = ShowCompareAsync;
        vm.ViewLargeRequested = ShowLarge;
    }

    private void Image_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not GalleryImageItem item) return;
        if (DataContext is AllImagesViewerViewModel vm)
        {
            vm.ToggleSelectCommand.Execute(item);
        }
    }

    private void Image_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not GalleryImageItem item) return;
        ShowLarge(item);
    }

    private void ShowLarge(GalleryImageItem item)
    {
        if (item.Bitmap == null) return;
        var details = HistoryViewerViewModel.BuildDetailsTextForImage(item.Entry, item.Image);
        var processed = item.Entry.ProcessedPrompt;
        if (string.IsNullOrWhiteSpace(processed))
        {
            processed = item.Image?.Prompt
                        ?? item.Entry.EnhancedPrompt
                        ?? item.Entry.VariationPrompts?.Values.FirstOrDefault()
                        ?? item.Entry.OriginalPrompt;
        }

        var detailVm = new HistoryImageDetailViewModel(
            item.Entry,
            item.Image!,
            item.Bitmap,
            details,
            processed,
            item.Entry.OriginalPrompt);
        detailVm.Clipboard = Clipboard;
        detailVm.UpscaleRequested = (entry, image) =>
        {
            var vm = DataContext as AllImagesViewerViewModel;
            return vm?.UpscaleRequested?.Invoke(entry, image) ?? Task.CompletedTask;
        };

        var lightbox = new HistoryImageDetailWindow
        {
            DataContext = detailVm
        };
        lightbox.HistoryManager = (DataContext as AllImagesViewerViewModel)?.HistoryManager;
        lightbox.HistoryIndexService = (DataContext as AllImagesViewerViewModel)?.HistoryIndexService;
        lightbox.Show(this);
    }

    private Task ShowCompareAsync(IReadOnlyList<GalleryImageItem> items)
    {
        if (items.Count != 2) return Task.CompletedTask;
        var left = items[0];
        var right = items[1];
        if (left.Bitmap == null || right.Bitmap == null) return Task.CompletedTask;

        var vm = new CompareImagesViewModel(left.Entry, left.Image, left.Bitmap, right.Entry, right.Image, right.Bitmap);
        var win = new CompareImagesWindow(vm);
        win.Show(this);
        return Task.CompletedTask;
    }
}
