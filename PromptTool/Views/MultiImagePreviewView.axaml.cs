using System;
using System.ComponentModel;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using PromptTool.ViewModels;
using PromptTool.Services;

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
        ImageDetailPresenter.ShowForPreview(slot, this);
    }

    private void Slot_DoubleTapped(object? sender, TappedEventArgs e)
    {
        if (sender is Control control && control.DataContext is ImageSlotViewModel slot)
        {
            ShowFullSize(slot);
        }
    }

    public void ShowFullSizeFromSlot(ImageSlotViewModel slot)
    {
        ShowFullSize(slot);
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
