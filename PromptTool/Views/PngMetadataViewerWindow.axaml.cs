using System;
using System.Linq;
using System.IO;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Platform.Storage;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class PngMetadataViewerWindow : Window
{
    public PngMetadataViewerWindow()
    {
        InitializeComponent();
        HookDragDrop();
        if (DataContext is PngMetadataViewerViewModel vm)
        {
            vm.OwnerWindow = this;
        }
    }

    public PngMetadataViewerWindow(PngMetadataViewerViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        HookDragDrop();
        viewModel.OwnerWindow = this;
    }

    private void HookDragDrop()
    {
        DragDrop.SetAllowDrop(DropZone, true);
        DropZone.AddHandler(DragDrop.DropEvent, OnDrop);
        DropZone.AddHandler(DragDrop.DragEnterEvent, OnDragEnter);
        DropZone.AddHandler(DragDrop.DragLeaveEvent, OnDragLeave);
    }

    private void OnDragEnter(object? sender, DragEventArgs e)
    {
        DropZone.BorderBrush = this.FindResource("AccentBrush") as Avalonia.Media.IBrush ?? DropZone.BorderBrush;
    }

    private void OnDragLeave(object? sender, DragEventArgs e)
    {
        DropZone.BorderBrush = this.FindResource("BorderBrushStrong") as Avalonia.Media.IBrush ?? DropZone.BorderBrush;
    }

    private async void OnDrop(object? sender, DragEventArgs e)
    {
        DropZone.BorderBrush = this.FindResource("BorderBrushStrong") as Avalonia.Media.IBrush ?? DropZone.BorderBrush;
#pragma warning disable CS0618
        var files = e.Data.GetFiles();
#pragma warning restore CS0618
        var file = files?.FirstOrDefault();
        var path = file?.TryGetLocalPath() ?? file?.Path.LocalPath;
        if (DataContext is PngMetadataViewerViewModel vm && !string.IsNullOrWhiteSpace(path))
        {
            await vm.LoadFileAsync(path);
        }
    }

    private async void Browse_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (StorageProvider == null || DataContext is not PngMetadataViewerViewModel vm)
        {
            return;
        }

        var options = new FilePickerOpenOptions
        {
            AllowMultiple = false,
            Title = "Select PNG File",
            FileTypeFilter = new[]
            {
                new FilePickerFileType("PNG files") { Patterns = new[] { "*.png" } },
                new FilePickerFileType("All files") { Patterns = new[] { "*.*" } }
            }
        };

        var files = await StorageProvider.OpenFilePickerAsync(options);
        var file = files?.FirstOrDefault();
        var path = file?.TryGetLocalPath() ?? file?.Path.LocalPath;
        if (!string.IsNullOrWhiteSpace(path))
        {
            await vm.LoadFileAsync(path);
        }
    }

    private void ExpandAll_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is PngMetadataViewerViewModel vm)
        {
            vm.ExpandAll();
        }
    }

    private void CollapseAll_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is PngMetadataViewerViewModel vm)
        {
            vm.CollapseAll();
        }
    }

    private async void CopyAll_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (DataContext is not PngMetadataViewerViewModel vm || Clipboard == null)
        {
            return;
        }

        await Clipboard.SetTextAsync(vm.BuildPlainText());
    }

    private async void Export_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (StorageProvider == null || DataContext is not PngMetadataViewerViewModel vm)
        {
            return;
        }

        var options = new FilePickerSaveOptions
        {
            Title = "Export PNG Metadata",
            SuggestedFileName = "png-metadata.json",
            FileTypeChoices = new[]
            {
                new FilePickerFileType("JSON") { Patterns = new[] { "*.json" } },
                new FilePickerFileType("CSV") { Patterns = new[] { "*.csv" } },
                new FilePickerFileType("Text") { Patterns = new[] { "*.txt" } }
            }
        };

        var file = await StorageProvider.SaveFilePickerAsync(options);
        var path = file?.TryGetLocalPath() ?? file?.Path.LocalPath;
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var content = GetExportContent(vm, path);
        await File.WriteAllTextAsync(path, content);
    }

    private static string GetExportContent(PngMetadataViewerViewModel vm, string path)
    {
        if (path.EndsWith(".csv", StringComparison.OrdinalIgnoreCase))
        {
            return vm.BuildCsv();
        }
        if (path.EndsWith(".txt", StringComparison.OrdinalIgnoreCase))
        {
            return vm.BuildPlainText();
        }
        return vm.BuildJson();
    }
}
