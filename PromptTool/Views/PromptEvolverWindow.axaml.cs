using System;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class PromptEvolverWindow : Window
{
    private Point? _historyDragStart;
    private string? _historyDragPrompt;

    public PromptEvolverWindow()
    {
        InitializeComponent();
        HookDragDrop();
        Closing += OnWindowClosing;
    }

    public PromptEvolverWindow(PromptEvolverViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookDragDrop();
        Closing += OnWindowClosing;
    }

    private void OnHistoryDoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is PromptEvolverViewModel vm)
        {
            vm.AddSelectedHistoryToParentsCommand.Execute(null);
        }
    }

    private void OnChildDoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (DataContext is PromptEvolverViewModel vm)
        {
            vm.SendSelectedChildToEditorCommand.Execute(null);
        }
    }

    private void OnCloseClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is PromptEvolverViewModel vm)
        {
            _ = vm.PersistSettingsAsync();
        }
        Close();
    }

    private void HookDragDrop()
    {
        DragDrop.SetAllowDrop(ParentsListBox, true);
        ParentsListBox.AddHandler(DragDrop.DragOverEvent, OnParentsDragOver);
        ParentsListBox.AddHandler(DragDrop.DropEvent, OnParentsDrop);
    }

    private void OnWindowClosing(object? sender, WindowClosingEventArgs e)
    {
        if (DataContext is PromptEvolverViewModel vm)
        {
            _ = vm.PersistSettingsAsync();
        }
    }

    private void OnParentsDragOver(object? sender, DragEventArgs e)
    {
        var hasText = e.DataTransfer.Contains(DataFormat.Text);
        e.DragEffects = hasText ? DragDropEffects.Copy : DragDropEffects.None;
        e.Handled = true;
    }

    private void OnParentsDrop(object? sender, DragEventArgs e)
    {
        if (DataContext is not PromptEvolverViewModel vm)
        {
            return;
        }

        var text = e.DataTransfer.TryGetText();
        if (!string.IsNullOrWhiteSpace(text))
        {
            vm.AddParentPrompt(text);
        }
        e.Handled = true;
    }

    private void OnHistoryItemPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            return;
        }

        _historyDragStart = e.GetPosition(this);
        _historyDragPrompt = (sender as Control)?.DataContext is PromptEvolverHistoryItemViewModel item
            ? item.Prompt
            : null;
    }

    private async void OnHistoryItemPointerMoved(object? sender, PointerEventArgs e)
    {
        if (_historyDragStart == null || string.IsNullOrWhiteSpace(_historyDragPrompt))
        {
            return;
        }

        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            _historyDragStart = null;
            _historyDragPrompt = null;
            return;
        }

        var current = e.GetPosition(this);
        var delta = current - _historyDragStart.Value;
        if (Math.Abs(delta.X) < 6 && Math.Abs(delta.Y) < 6)
        {
            return;
        }

        var data = new DataTransfer();
        data.Add(DataTransferItem.CreateText(_historyDragPrompt));
        _historyDragStart = null;
        _historyDragPrompt = null;
        await DragDrop.DoDragDropAsync(e, data, DragDropEffects.Copy);
    }

    private async void OnCopySelectedHistoryPromptClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not PromptEvolverViewModel vm) return;
        var prompt = vm.SelectedHistoryPrompt?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt)) return;
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            await clipboard.SetTextAsync(prompt);
        }
    }

    private async void OnCopySelectedParentPromptClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not PromptEvolverViewModel vm) return;
        var prompt = vm.SelectedParentPrompt;
        if (string.IsNullOrWhiteSpace(prompt)) return;
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            await clipboard.SetTextAsync(prompt);
        }
    }

    private async void OnCopySelectedChildPromptClicked(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not PromptEvolverViewModel vm) return;
        var prompt = vm.SelectedChildPrompt?.Prompt;
        if (string.IsNullOrWhiteSpace(prompt)) return;
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            await clipboard.SetTextAsync(prompt);
        }
    }
}
