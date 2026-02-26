using System;
using System.ComponentModel;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media.Imaging;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class MultiImagePreviewView : Window
{
    private MultiImagePreviewViewModel? _attachedVm;
    private PropertyChangedEventHandler? _dialogHandler;

    public MultiImagePreviewView()
    {
        InitializeComponent();
        HookClose(DataContext as MultiImagePreviewViewModel);
        this.DataContextChanged += OnDataContextChanged;
        Closed += (_, __) => DisposeSlotImages(DataContext as MultiImagePreviewViewModel);
    }

    private void OnDataContextChanged(object? sender, System.EventArgs e)
    {
        HookClose(DataContext as MultiImagePreviewViewModel);
    }

    private void HookClose(MultiImagePreviewViewModel? vm)
    {
        if (vm == null) return;
        if (_attachedVm != null && _dialogHandler != null)
        {
            _attachedVm.PropertyChanged -= _dialogHandler;
        }
        _attachedVm = vm;
        vm.OnShowFullSize = ShowFullSize;

        _dialogHandler = (s, e) =>
        {
            if (e.PropertyName == nameof(MultiImagePreviewViewModel.DialogResult) && vm.DialogResult.HasValue)
            {
                Close(vm.DialogResult.Value);
            }
        };
        vm.PropertyChanged += _dialogHandler;
    }

    private void ShowFullSize(ImageSlotViewModel slot)
    {
        if (slot.Image == null) return;
        var copy = CloneBitmap(slot.Image);
        if (copy == null) return;
        var screen = Screens.ScreenFromWindow(this) ?? Screens.Primary;
        var working = screen?.WorkingArea ?? new PixelRect(0, 0, 1280, 720);
        var maxWidth = Math.Max(320, working.Width * 0.9);
        var maxHeight = Math.Max(240, working.Height * 0.9);

        var win = new HoverImagePreviewWindow(copy, maxWidth, maxHeight)
        {
            Topmost = false,
            Title = "Full Size Preview"
        };
        win.Show(this);
    }

    public void ShowFullSizeFromSlot(ImageSlotViewModel slot)
    {
        ShowFullSize(slot);
    }

    private static Bitmap? CloneBitmap(Bitmap source)
    {
        try
        {
            using var ms = new System.IO.MemoryStream();
            source.Save(ms);
            ms.Position = 0;
            return new Bitmap(ms);
        }
        catch
        {
            return null;
        }
    }

    private static void DisposeSlotImages(MultiImagePreviewViewModel? vm)
    {
        if (vm == null) return;
        foreach (var slot in vm.Slots)
        {
            slot.Image?.Dispose();
            slot.Image = null;
        }
    }

}
