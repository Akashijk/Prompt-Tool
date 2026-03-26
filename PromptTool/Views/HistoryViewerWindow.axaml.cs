using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Threading;
using PromptTool.Core.Services;
using PromptTool.Services;
using PromptTool.ViewModels;
using Avalonia.Controls.ApplicationLifetimes;
using System.Collections.Specialized;
using System.ComponentModel; // Added
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;

namespace PromptTool.Views;

public partial class HistoryViewerWindow : Window
{
    private ScrollViewer? _detailsScroll;
    private bool _legacyPromptShown;
    private bool _hasAutoSelected;
    private bool _stateRestored;
    private WindowState _pendingRestoreState = WindowState.Normal;
    private HistoryViewerViewModel? _attachedVm;
    private INotifyCollectionChanged? _historyEntriesCollection;

    public HistoryViewerWindow()
    {
        InitializeComponent();
        Closing += (_, __) => SaveWindowState();
        Closed += OnClosed;
        Opened += HistoryViewerWindow_OnOpened;
        HookDataContext();
        WireContext();
        RestoreWindowState();
    }

    public HistoryViewerWindow(HistoryViewerViewModel viewModel)
    {
        InitializeComponent();
        Closing += (_, __) => SaveWindowState();
        Closed += OnClosed;
        Opened += HistoryViewerWindow_OnOpened;
        DataContext = viewModel;
        WireContext();
        RestoreWindowState();
        
        // Subscribe to PropertyChanged event to observe DialogResult
        viewModel.PropertyChanged += ViewModel_PropertyChanged;
    }

    private void OnHistorySelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (DataContext is not HistoryViewerViewModel vm) return;
        if (sender is not DataGrid grid) return;
        var items = grid.SelectedItems?.OfType<HistoryEntryItem>() ?? Enumerable.Empty<HistoryEntryItem>();
        vm.SetSelectedEntries(items);
    }

    private async void HistoryViewerWindow_OnOpened(object? sender, System.EventArgs e)
    {
        if (Design.IsDesignMode)
            return;

        ApplyPendingWindowStateRestore();
        
        if (DataContext is HistoryViewerViewModel initialVm)
        {
            TrySelectFirstEntry(initialVm);
        }

        if (_legacyPromptShown) return;
        _legacyPromptShown = true;
        if (DataContext is not HistoryViewerViewModel vm) return;
        
        // Guard DI-backed services
        if (vm.HistoryManager is null)
            return;
        
        if (!vm.HistoryManager.HasLegacyHistory(out var missing)) return;

        var message = $"Legacy history data detected ({missing} images missing fields).\n\n" +
                      "Would you like to normalize it now? A backup of your current history files will be created.";
        if (!await ShowConfirmAsync(message)) return;

        if (!vm.HistoryManager.NormalizeHistoryWithBackup(out var backupDir, out var error))
        {
            await ShowMessageAsync($"Normalization failed: {error}");
            return;
        }

        vm.RefreshCommand.Execute(null);
        await ShowMessageAsync($"History normalized.\nBackup saved to:\n{backupDir}");
    }

    private SettingsService? GetSettingsService()
    {
        return (Application.Current as App)?.SettingsService;
    }

    private void RestoreWindowState()
    {
        if (_stateRestored)
        {
            return;
        }
        _stateRestored = true;

        var settings = GetSettingsService()?.Settings;
        if (settings == null)
        {
            return;
        }

        if (Enum.TryParse<WindowState>(settings.HistoryViewerWindowState, out var savedState))
        {
            _pendingRestoreState = savedState;
        }
        else
        {
            _pendingRestoreState = WindowState.Normal;
        }

        if (settings.HistoryViewerWindowWidth > 0 && settings.HistoryViewerWindowHeight > 0)
        {
            Width = settings.HistoryViewerWindowWidth;
            Height = settings.HistoryViewerWindowHeight;
        }

        if (settings.HistoryViewerWindowX != 0 || settings.HistoryViewerWindowY != 0)
        {
            Position = new PixelPoint((int)settings.HistoryViewerWindowX, (int)settings.HistoryViewerWindowY);
        }

        WindowState = WindowState.Normal;
    }

    private void ApplyPendingWindowStateRestore()
    {
        var screen = Owner?.Screens.ScreenFromWindow(Owner)
                     ?? Screens.ScreenFromWindow(this)
                     ?? Screens.Primary;
        var working = screen?.WorkingArea ?? new PixelRect(0, 0, 1280, 720);

        if (WindowState == WindowState.Normal)
        {
            var width = (int)Math.Ceiling(Bounds.Width > 0 ? Bounds.Width : Width);
            var height = (int)Math.Ceiling(Bounds.Height > 0 ? Bounds.Height : Height);
            if (width > 0 && height > 0)
            {
                var clampedX = Math.Clamp(Position.X, working.X, working.X + Math.Max(0, working.Width - width));
                var clampedY = Math.Clamp(Position.Y, working.Y, working.Y + Math.Max(0, working.Height - height));
                Position = new PixelPoint(clampedX, clampedY);
            }
        }

        if (_pendingRestoreState != WindowState.Normal)
        {
            var targetState = _pendingRestoreState;
            _pendingRestoreState = WindowState.Normal;
            Dispatcher.UIThread.Post(() => WindowState = targetState, DispatcherPriority.Background);
        }
    }

    private void SaveWindowState()
    {
        var settingsService = GetSettingsService();
        if (settingsService == null)
        {
            return;
        }
        var settings = settingsService.Settings;

        settings.HistoryViewerWindowState = WindowState.ToString();
        if (WindowState == WindowState.Normal)
        {
            var bounds = Bounds;
            if (bounds.Width > 0 && bounds.Height > 0)
            {
                settings.HistoryViewerWindowWidth = bounds.Width;
                settings.HistoryViewerWindowHeight = bounds.Height;
                settings.HistoryViewerWindowX = bounds.X;
                settings.HistoryViewerWindowY = bounds.Y;
            }
        }

        _ = settingsService.SaveSettingsAsync(settings);
    }

    private void HookDataContext()
    {
        this.DataContextChanged += (_, _) =>
        {
            if (DataContext is HistoryViewerViewModel vm)
            {
                vm.PropertyChanged -= ViewModel_PropertyChanged;
                vm.PropertyChanged += ViewModel_PropertyChanged;
                WireContext();
            }
        };
    }

    private void ViewModel_PropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(HistoryViewerViewModel.DialogResult) &&
            sender is HistoryViewerViewModel viewModel)
        {
            // Unsubscribe to prevent memory leaks and multiple calls
            viewModel.PropertyChanged -= ViewModel_PropertyChanged;
            Close(viewModel.DialogResult);
            return;
        }

        if (e.PropertyName == nameof(HistoryViewerViewModel.SelectedHistoryEntry))
        {
            ScrollDetailsToTop();
            if (sender is HistoryViewerViewModel vm)
            {
                SelectCoverOrFirstImage(vm);
            }
        }

        if (e.PropertyName == nameof(HistoryViewerViewModel.SelectedImages) && sender is HistoryViewerViewModel vm2 && vm2.SelectedImage == null)
        {
            SelectCoverOrFirstImage(vm2);
        }
    }

    private void WireContext()
    {
        _detailsScroll = this.FindControl<ScrollViewer>("DetailsScroll");
        if (_attachedVm != null)
        {
            _attachedVm.PropertyChanged -= ViewModel_PropertyChanged;
            _attachedVm.OnLargeImageRequested -= Vm_OnLargeImageRequested;
            _attachedVm.ShowAllImagesRequested = null;
            _attachedVm.ShowPngMetadataRequested = null;
        }

        if (_historyEntriesCollection != null)
        {
            _historyEntriesCollection.CollectionChanged -= OnHistoryEntriesChanged;
            _historyEntriesCollection = null;
        }

        if (DataContext is HistoryViewerViewModel vm)
        {
            _attachedVm = vm;
            vm.Clipboard = this.Clipboard;
            vm.ConfirmAsync = ShowConfirmAsync;
            vm.EditJsonAsync = ShowEditJsonAsync;
            vm.OnLargeImageRequested -= Vm_OnLargeImageRequested;
            vm.OnLargeImageRequested += Vm_OnLargeImageRequested;
            vm.ShowAllImagesRequested = ShowAllImagesAsync;
            vm.ShowPngMetadataRequested = ShowPngMetadataAsync;

            if (vm.HistoryEntries is INotifyCollectionChanged collection)
            {
                collection.CollectionChanged -= OnHistoryEntriesChanged;
                collection.CollectionChanged += OnHistoryEntriesChanged;
                _historyEntriesCollection = collection;
            }
        }
        ScrollDetailsToTop();
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        if (_historyEntriesCollection != null)
        {
            _historyEntriesCollection.CollectionChanged -= OnHistoryEntriesChanged;
            _historyEntriesCollection = null;
        }

        if (_attachedVm != null)
        {
            _attachedVm.PropertyChanged -= ViewModel_PropertyChanged;
            _attachedVm.OnLargeImageRequested -= Vm_OnLargeImageRequested;
            _attachedVm.ShowAllImagesRequested = null;
            _attachedVm.ShowPngMetadataRequested = null;
            _attachedVm.Dispose();
            _attachedVm = null;
        }
    }

    private void OnHistoryEntriesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (DataContext is HistoryViewerViewModel vm)
        {
            TrySelectFirstEntry(vm);
        }
    }

    private async Task ShowPngMetadataAsync(string filePath)
    {
        var historyManager = (Application.Current as App)?.HistoryManagerService;
        var vm = new PngMetadataViewerViewModel(historyManager);
        var mainVm = (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow?.DataContext as MainWindowViewModel;
        if (mainVm != null)
        {
            vm.GenerateMergedRequested = mainVm.GenerateFromMergedPngAsync;
            vm.GenerateGraphReplayRequested = mainVm.GenerateFromPngGraphAsync;
            vm.BuildGenerationGraphJsonAsync = mainVm.BuildGenerationGraphJsonAsync;
            vm.ShowJsonDiffRequested = mainVm.ShowJsonDiffAsync;
        }
        var win = new PngMetadataViewerWindow(vm);
        win.Show(this);
        await vm.LoadFileAsync(filePath);
    }

    private void TrySelectFirstEntry(HistoryViewerViewModel vm)
    {
        if (!_hasAutoSelected && vm.SelectedHistoryEntry == null && vm.HistoryEntries.Any())
        {
            vm.SelectedHistoryEntry = vm.HistoryEntries.First();
            _hasAutoSelected = true;
        }
    }

    private void SelectCoverOrFirstImage(HistoryViewerViewModel vm)
    {
        if (vm.SelectedImages == null || !vm.SelectedImages.Any()) return;

        var cover = vm.SelectedHistoryEntry != null ? vm.SelectedImages.FirstOrDefault(i => i.Image.ImagePath == vm.SelectedHistoryEntry.Entry.CoverImagePath) : null;
        if (cover != null)
        {
            vm.SelectedImageItem = cover;
        }
        else
        {
            vm.SelectedImageItem = vm.SelectedImages.FirstOrDefault();
        }
    }

    private void Vm_OnLargeImageRequested(HistoryImagePreviewContext? context)
    {
        if (context?.Item.Bitmap == null) return;
        if (DataContext is not HistoryViewerViewModel vm) return;
        ImageDetailPresenter.Show(
            context.Entry,
            context.Item.Image!,
            context.Item.Bitmap,
            this,
            vm.HistoryManager,
            vm.HistoryIndexService,
            vm.ImageCacheService,
            (entry, image) => vm.UpscaleRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.RegenerateRequested?.Invoke(entry, image, null, null) ?? Task.CompletedTask,
            (entry, image) => vm.SeedVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.LoraVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask,
            (entry, image) => vm.ModelVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask);
    }

    private void Image_DoubleTapped(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control control) return;
        if (control.DataContext is not HistoryImageItem item)
        {
            if (e.Source is Control source && source.DataContext is HistoryImageItem sourceItem)
            {
                item = sourceItem;
            }
            else
            {
                return;
            }
        }
        if (DataContext is HistoryViewerViewModel vm)
        {
            vm.ViewLargeCommand.Execute(item);
        }
        e.Handled = true;
    }

    private Task ShowAllImagesAsync()
    {
        if (DataContext is not HistoryViewerViewModel vm) return Task.CompletedTask;
        var allVm = new AllImagesViewerViewModel(
            vm.HistoryManager,
            vm.TemplateService,
            vm.ImageCacheService,
            vm.HistoryIndexService,
            vm.WorkflowFilter);
        allVm.UpscaleRequested = (entry, image) => vm.UpscaleRequested?.Invoke(entry, image) ?? Task.CompletedTask;
        allVm.GenerateMoreRequested = (entry, image) => vm.RegenerateRequested?.Invoke(entry, image, null, null) ?? Task.CompletedTask;
        allVm.SeedVariationsRequested = (entry, image) => vm.SeedVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask;
        allVm.LoraVariationsRequested = (entry, image) => vm.LoraVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask;
        allVm.ModelVariationsRequested = (entry, image) => vm.ModelVariationsRequested?.Invoke(entry, image) ?? Task.CompletedTask;
        var win = new AllImagesWindow(allVm);
        win.Show(this);
        return Task.CompletedTask;
    }

    private async Task<bool> ShowConfirmAsync(string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 340,
            Height = 160,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Confirm",
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "Cancel" }
                        }
                    }
                }
            }
        };

        var buttons = dialog.Content as StackPanel;
        var actionBar = buttons?.Children[1] as StackPanel;
        var cancelButton = actionBar?.Children[0] as Button;
        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(false);
                dialog.Close();
            };
        }
        var ok = new Button { Content = "OK" };
        ok.Click += (_, __) =>
        {
            tcs.TrySetResult(true);
            dialog.Close();
        };
        actionBar?.Children.Add(ok);

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(false);
            }
        };
        await dialog.ShowDialog(this);
        return await tcs.Task;
    }

    private async Task ShowMessageAsync(string message)
    {
        var tcs = new TaskCompletionSource<bool>();
        var dialog = new Window
        {
            Width = 420,
            Height = 200,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Notice",
            Content = new StackPanel
            {
                Margin = new Thickness(12),
                Spacing = 12,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Right,
                        Spacing = 8,
                        Children =
                        {
                            new Button { Content = "OK" }
                        }
                    }
                }
            }
        };

        var ok = ((dialog.Content as StackPanel)?.Children.LastOrDefault() as StackPanel)?.Children.FirstOrDefault() as Button;
        if (ok != null)
        {
            ok.Click += (_, __) =>
            {
                tcs.TrySetResult(true);
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(true);
            }
        };

        await dialog.ShowDialog(this);
        await tcs.Task;
    }

    private async Task<ImageJsonEditResult?> ShowEditJsonAsync(ImageJsonEditRequest request)
    {
        var tcs = new TaskCompletionSource<ImageJsonEditResult?>();
        var promptTypeBox = new TextBox { Text = request.PromptType ?? string.Empty };
        var promptBox = new TextBox
        {
            Text = request.Prompt ?? string.Empty,
            AcceptsReturn = true,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Height = 90
        };

        var normalizedJson = request.GenerationParamsJson ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(normalizedJson))
        {
            try
            {
                using var doc = JsonDocument.Parse(normalizedJson);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                {
                    normalizedJson = JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
                }
            }
            catch
            {
                // Leave as-is if not valid JSON.
            }
        }

        var jsonBox = new TextBox
        {
            Text = normalizedJson,
            AcceptsReturn = true,
            TextWrapping = Avalonia.Media.TextWrapping.NoWrap,
            Height = 320,
            MinWidth = 640
        };
        jsonBox.SetValue(ScrollViewer.VerticalScrollBarVisibilityProperty, ScrollBarVisibility.Auto);
        jsonBox.SetValue(ScrollViewer.HorizontalScrollBarVisibilityProperty, ScrollBarVisibility.Auto);

        var contentPanel = new StackPanel
        {
            Spacing = 10,
            Children =
            {
                new TextBlock
                {
                    Text = "Edit the JSON for this image. Changes are saved to history immediately.",
                    TextWrapping = Avalonia.Media.TextWrapping.Wrap
                },
                new TextBlock { Text = "Prompt Type (e.g., Variation: Hentai)", FontWeight = Avalonia.Media.FontWeight.SemiBold },
                promptTypeBox,
                new TextBlock { Text = "Prompt", FontWeight = Avalonia.Media.FontWeight.SemiBold },
                promptBox,
                new TextBlock { Text = "Generation Params JSON", FontWeight = Avalonia.Media.FontWeight.SemiBold },
                jsonBox
            }
        };

        var scroll = new ScrollViewer
        {
            Content = contentPanel,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        };

        var buttonBar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Spacing = 8,
            Children =
            {
                new Button { Content = "Cancel" },
                new Button { Content = "Save" }
            }
        };

        var root = new DockPanel { LastChildFill = true, Margin = new Thickness(12) };
        DockPanel.SetDock(buttonBar, Dock.Bottom);
        root.Children.Add(buttonBar);
        root.Children.Add(scroll);

        var dialog = new Window
        {
            Width = 760,
            Height = 620,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Title = "Edit Generation JSON",
            Content = root
        };

        var buttons = buttonBar.Children;
        var cancelButton = buttons.FirstOrDefault() as Button;
        var saveButton = buttons.LastOrDefault() as Button;

        if (cancelButton != null)
        {
            cancelButton.Click += (_, __) =>
            {
                tcs.TrySetResult(null);
                dialog.Close();
            };
        }
        if (saveButton != null)
        {
            saveButton.Click += (_, __) =>
            {
                tcs.TrySetResult(new ImageJsonEditResult(
                    promptTypeBox.Text ?? string.Empty,
                    promptBox.Text ?? string.Empty,
                    jsonBox.Text ?? string.Empty));
                dialog.Close();
            };
        }

        dialog.Closed += (_, __) =>
        {
            if (!tcs.Task.IsCompleted)
            {
                tcs.TrySetResult(null);
            }
        };

        await dialog.ShowDialog(this);
        return await tcs.Task;
    }

    private void ScrollDetailsToTop()
    {
        if (_detailsScroll == null) return;
        Dispatcher.UIThread.Post(() =>
        {
            if (_detailsScroll != null)
            {
                var offset = _detailsScroll.Offset;
                _detailsScroll.Offset = new Vector(offset.X, 0);
            }
        }, DispatcherPriority.Background);
    }
}
