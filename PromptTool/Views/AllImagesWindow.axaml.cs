using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using PromptTool.ViewModels;
using PromptTool.Services;
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
        if (DataContext is not AllImagesViewerViewModel vm) return;
        if (item.Image == null) return;

        var fallback = item.Bitmap ?? vm.ImageCacheService.GetOrLoadForUi(item.Image.ImagePath, 320, vm.HistoryManager.GetHistoryDir());
        if (fallback == null) return;

        ImageDetailPresenter.Show(
            item.Entry,
            item.Image,
            fallback,
            this,
            vm.HistoryManager,
            vm.HistoryIndexService,
            vm.ImageCacheService,
            (entry, image) => vm.UpscaleRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.GenerateMoreRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.SeedVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.LoraVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.ModelVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask);
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
