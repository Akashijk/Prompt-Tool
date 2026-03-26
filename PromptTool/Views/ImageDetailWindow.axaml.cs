using System;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using PromptTool.Core.Models;
using Avalonia.Threading;
using PromptTool.ViewModels;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.Views;

public partial class ImageDetailWindow : Window
{
    public HistoryManagerService? HistoryManager { get; set; }
    public HistoryIndexService? HistoryIndexService { get; set; }
    public ImageCacheService? ImageCacheService { get; set; }

    private bool _isPanning;
    private Point _panStart;
    private Vector _offsetStart;
    private double _imageWidth;
    private double _imageHeight;
    private double _fitScale = 1.0;
    private TranslateTransform? _translate;
    private ScaleTransform? _scale;
    private bool _hasInitialFit;
    private bool _initialSizeApplied;

    public ImageDetailWindow()
    {
        InitializeComponent();
        AddHandler(InputElement.KeyDownEvent, OnPreviewKeyDown, RoutingStrategies.Tunnel, handledEventsToo: true);
        InitializeTransforms();
        RenderOptions.SetBitmapInterpolationMode(DetailImage, BitmapInterpolationMode.None);
        DetailImage.PropertyChanged += DetailImageOnPropertyChanged;
        ZoomSlider.PropertyChanged += ZoomSliderOnPropertyChanged;
        Opened += OnOpened;
        Closed += OnClosed;
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            e.Handled = true;
            return;
        }

        base.OnKeyDown(e);
    }

    private void OnPreviewKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Handled || e.Key is not (Key.Left or Key.Right or Key.Home or Key.End))
        {
            return;
        }

        if (ShouldIgnoreImageNavigation(e.Source))
        {
            return;
        }

        if (TryNavigateImages(e.Key, e.Source, consumeWhenUnavailable: true))
        {
            e.Handled = true;
            return;
        }

        if (ShouldConsumeNavigationKeyWithoutMovement())
        {
            e.Handled = true;
        }
    }

    private void Close_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        Close();
    }

    private void PreviousImage_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (TryNavigateImages(Key.Left, null, consumeWhenUnavailable: false))
        {
            e.Handled = true;
        }
    }

    private void NextImage_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (TryNavigateImages(Key.Right, null, consumeWhenUnavailable: false))
        {
            e.Handled = true;
        }
    }

    private void EditImageData_Click(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (HistoryManager == null) return;
        if (DataContext is not ImageDetailViewModel vm) return;
        var editorVm = new ImageJsonEditorViewModel(HistoryManager, vm.Entry, vm.Image, HistoryIndexService);
        var editor = new ImageJsonEditorWindow(editorVm)
        {
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };
        editor.ShowDialog(this);
    }

    private void ToggleFavorite_Click(object? sender, RoutedEventArgs e)
    {
        if (HistoryManager == null) return;
        if (DataContext is not ImageDetailViewModel vm) return;

        var newValue = !vm.Image.IsFavorite;
        vm.Image.IsFavorite = newValue;
        if (newValue)
        {
            vm.Entry.IsFavorite = true;
        }
        else
        {
            vm.Entry.IsFavorite = vm.Entry.Images.Any(img => img.IsFavorite);
        }

        HistoryManager.UpdateImage(vm.Entry.Id, vm.Image, save: false);
        HistoryManager.SaveChanges();
        vm.UpdateFavoriteState();
        e.Handled = true;
    }

    private void Image_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (e.GetCurrentPoint(this).Properties.IsLeftButtonPressed && IsPannable())
        {
            _isPanning = true;
            _panStart = e.GetPosition(ImageScrollViewer);
            _offsetStart = new Vector(_translate?.X ?? 0, _translate?.Y ?? 0);
            DetailImage.Cursor = new Cursor(StandardCursorType.Hand);
            e.Pointer.Capture(DetailImage);
        }
    }

    private void Image_PointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        _isPanning = false;
        DetailImage.Cursor = new Cursor(StandardCursorType.Arrow);
        e.Pointer.Capture(null);
    }

    private void Image_PointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_isPanning || !e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            return;
        }

        var current = e.GetPosition(ImageScrollViewer);
        var delta = current - _panStart;
        var scale = ZoomSlider.Value;
        var scaledWidth = _imageWidth * scale;
        var scaledHeight = _imageHeight * scale;

        var minX = Math.Min(0, ImageScrollViewer.Viewport.Width - scaledWidth);
        var minY = Math.Min(0, ImageScrollViewer.Viewport.Height - scaledHeight);

        var newX = Math.Clamp(_offsetStart.X + delta.X, minX, 0);
        var newY = Math.Clamp(_offsetStart.Y + delta.Y, minY, 0);

        if (_translate != null)
        {
            _translate.X = newX;
            _translate.Y = newY;
        }
    }

    private void ZoomSlider_PointerWheelChanged(object? sender, PointerWheelEventArgs e)
    {
        var delta = e.Delta.Y;
        if (Math.Abs(delta) < double.Epsilon) return;
        AdjustZoom(delta, new Point(ImageScrollViewer.Viewport.Width / 2, ImageScrollViewer.Viewport.Height / 2));
        e.Handled = true;
    }

    private void DetailImage_PointerWheelChanged(object? sender, PointerWheelEventArgs e)
    {
        var delta = e.Delta.Y;
        if (Math.Abs(delta) < double.Epsilon) return;
        AdjustZoom(delta, e.GetPosition(ImageScrollViewer));
        e.Handled = true;
    }

    private void AdjustZoom(double delta, Point zoomCenter)
    {
        var currentScale = ZoomSlider.Value;
        var minScale = Math.Max(_fitScale, ZoomSlider.Minimum);
        var step = delta > 0 ? 1 : -1;
        var targetScale = Math.Clamp(Math.Round(currentScale) + step, minScale, ZoomSlider.Maximum);
        if (Math.Abs(targetScale - currentScale) < 0.0001) return;

        var offsetBefore = new Vector(_translate?.X ?? 0, _translate?.Y ?? 0);
        var contentX = (zoomCenter.X - offsetBefore.X) / currentScale;
        var contentY = (zoomCenter.Y - offsetBefore.Y) / currentScale;

        ZoomSlider.Value = targetScale;

        var newOffsetX = zoomCenter.X - contentX * targetScale;
        var newOffsetY = zoomCenter.Y - contentY * targetScale;

        ApplyPan(newOffsetX, newOffsetY, targetScale);
    }

    private void ApplyPan(double newX, double newY, double scale)
    {
        var scaledWidth = _imageWidth * scale;
        var scaledHeight = _imageHeight * scale;

        if (scaledWidth <= ImageScrollViewer.Viewport.Width)
        {
            newX = (ImageScrollViewer.Viewport.Width - scaledWidth) / 2;
        }
        else
        {
            var minX = ImageScrollViewer.Viewport.Width - scaledWidth;
            newX = Math.Clamp(newX, minX, 0);
        }

        if (scaledHeight <= ImageScrollViewer.Viewport.Height)
        {
            newY = (ImageScrollViewer.Viewport.Height - scaledHeight) / 2;
        }
        else
        {
            var minY = ImageScrollViewer.Viewport.Height - scaledHeight;
            newY = Math.Clamp(newY, minY, 0);
        }

        if (_translate != null)
        {
            _translate.X = newX;
            _translate.Y = newY;
        }
    }

    private void DetailImageOnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Image.SourceProperty && DetailImage.Source != null)
        {
            _imageWidth = DetailImage.Source.Size.Width;
            _imageHeight = DetailImage.Source.Size.Height;
            _hasInitialFit = false;
            UpdateFitScale();
            CenterImage();
            ApplyInitialWindowSize();
        }
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        if (DataContext is IDisposable disposable)
        {
            disposable.Dispose();
        }
    }

    private void ZoomSliderOnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Slider.ValueProperty)
        {
            var scale = ZoomSlider.Value;
            // Keep current offset but clamp to new bounds
            var x = _translate?.X ?? 0;
            var y = _translate?.Y ?? 0;
            ApplyPan(x, y, scale);
            if (_scale != null)
            {
                _scale.ScaleX = scale;
                _scale.ScaleY = scale;
            }
        }
    }

    private void CenterImage()
    {
        var scale = ZoomSlider.Value;
        var scaledWidth = _imageWidth * scale;
        var scaledHeight = _imageHeight * scale;

        double x, y;
        if (scaledWidth <= ImageScrollViewer.Viewport.Width)
        {
            x = (ImageScrollViewer.Viewport.Width - scaledWidth) / 2;
        }
        else
        {
            x = Math.Min(0, (ImageScrollViewer.Viewport.Width - scaledWidth) / 2);
        }

        if (scaledHeight <= ImageScrollViewer.Viewport.Height)
        {
            y = (ImageScrollViewer.Viewport.Height - scaledHeight) / 2;
        }
        else
        {
            y = Math.Min(0, (ImageScrollViewer.Viewport.Height - scaledHeight) / 2);
        }

        if (_translate != null)
        {
            _translate.X = x;
            _translate.Y = y;
        }
    }

    private void UpdateFitScale()
    {
        _fitScale = 1.0;
        var minScale = Math.Max(1.0, ZoomSlider.Minimum);
        ZoomSlider.Minimum = minScale;
        if (!_hasInitialFit)
        {
            var initial = Math.Clamp(1.0, minScale, ZoomSlider.Maximum);
            ZoomSlider.Value = initial;
            if (_scale != null)
            {
                _scale.ScaleX = initial;
                _scale.ScaleY = initial;
            }
            CenterImage();
            _hasInitialFit = true;
        }
        else if (ZoomSlider.Value < minScale)
        {
            ZoomSlider.Value = minScale;
            if (_scale != null)
            {
                _scale.ScaleX = minScale;
                _scale.ScaleY = minScale;
            }
            CenterImage();
        }
    }

    private void ImageScrollViewer_SizeChanged(object? sender, SizeChangedEventArgs e)
    {
        UpdateFitScale();
        CenterImage();
    }

    private void OnOpened(object? sender, EventArgs e)
    {
        ApplyInitialWindowSize();
        Dispatcher.UIThread.Post(CenterWindow, DispatcherPriority.Background);
    }

    private void ApplyInitialWindowSize()
    {
        if (_initialSizeApplied || _imageWidth <= 0 || _imageHeight <= 0)
        {
            return;
        }

        Dispatcher.UIThread.Post(() =>
        {
            if (_initialSizeApplied || _imageWidth <= 0 || _imageHeight <= 0)
            {
                return;
            }

            var detailsWidth = DetailsPanel.Bounds.Width;
            var extraWidth = RootGrid.Bounds.Width - (ImageScrollViewer.Bounds.Width + detailsWidth);
            var extraHeight = RootGrid.Bounds.Height - ImageScrollViewer.Bounds.Height;

            if (double.IsNaN(detailsWidth) || detailsWidth <= 1)
            {
                detailsWidth = 360;
            }

            if (double.IsNaN(extraWidth) || extraWidth <= 0)
            {
                extraWidth = 24;
            }

            if (double.IsNaN(extraHeight) || extraHeight <= 0)
            {
                extraHeight = 140;
            }

            var targetWidth = _imageWidth + detailsWidth + extraWidth;
            var targetHeight = _imageHeight + extraHeight;

            Width = Math.Max(Width, targetWidth);
            Height = Math.Max(Height, targetHeight);

            _initialSizeApplied = true;
            CenterWindow();
        }, DispatcherPriority.Background);
    }

    private void CenterWindow()
    {
        var screen = Owner != null
            ? Owner.Screens.ScreenFromWindow(Owner)
            : Screens.ScreenFromWindow(this) ?? Screens.Primary;
        var working = screen?.WorkingArea ?? new PixelRect(0, 0, 1280, 720);

        var windowWidth = (int)Math.Ceiling(Bounds.Width > 0 ? Bounds.Width : Width);
        var windowHeight = (int)Math.Ceiling(Bounds.Height > 0 ? Bounds.Height : Height);
        if (windowWidth <= 0 || windowHeight <= 0) return;

        var centerX = working.X + (int)Math.Round((working.Width - windowWidth) / 2d);
        var centerY = working.Y + (int)Math.Round((working.Height - windowHeight) / 2d);
        var clampedX = Math.Clamp(centerX, working.X, working.X + Math.Max(0, working.Width - windowWidth));
        var clampedY = Math.Clamp(centerY, working.Y, working.Y + Math.Max(0, working.Height - windowHeight));
        Position = new PixelPoint(clampedX, clampedY);
    }
    private void InitializeTransforms()
    {
        if (DetailImage.RenderTransform is TransformGroup group)
        {
            foreach (var t in group.Children)
            {
                if (t is ScaleTransform s) _scale = s;
                if (t is TranslateTransform tr) _translate = tr;
            }
        }
        if (_scale == null || _translate == null)
        {
            _scale = new ScaleTransform();
            _translate = new TranslateTransform();
            DetailImage.RenderTransform = new TransformGroup
            {
                Children = new Transforms { _scale, _translate }
            };
        }
    }

    private bool IsPannable()
    {
        var scale = ZoomSlider.Value;
        var scaledWidth = _imageWidth * scale;
        var scaledHeight = _imageHeight * scale;
        return scaledWidth > ImageScrollViewer.Viewport.Width + 1e-3
               || scaledHeight > ImageScrollViewer.Viewport.Height + 1e-3;
    }

    private bool TryNavigateImages(Key key, object? source, bool consumeWhenUnavailable)
    {
        if (ShouldIgnoreImageNavigation(source) ||
            DataContext is not ImageDetailViewModel vm ||
            vm.DisplayMode != ImageDetailMode.History)
        {
            return false;
        }

        if (vm.NavigationItems is { Count: > 1 })
        {
            var currentIndex = vm.FindNavigationIndex();
            if (currentIndex < 0)
            {
                return false;
            }

            var targetIndex = key switch
            {
                Key.Left => currentIndex - 1,
                Key.Right => currentIndex + 1,
                Key.Home => 0,
                Key.End => vm.NavigationItems.Count - 1,
                _ => currentIndex
            };

            if (targetIndex < 0 || targetIndex >= vm.NavigationItems.Count || targetIndex == currentIndex)
            {
                return consumeWhenUnavailable;
            }

            var target = vm.NavigationItems[targetIndex];
            var bitmap = ResolveBitmapForImage(target.Image, vm.Bitmap);
            if (bitmap == null)
            {
                return false;
            }

            var detailsText = HistoryViewerViewModel.BuildDetailsText(target.Entry, target.Image);
            var processed = HistoryViewerViewModel.ResolveGeneratedPromptForImage(target.Entry, target.Image);
            if (string.IsNullOrWhiteSpace(processed))
            {
                processed = target.Entry.ProcessedPrompt;
            }

            vm.SetDisplayedImage(target.Entry, target.Image, bitmap, detailsText, processed, target.Entry.OriginalPrompt);
            ResetImageViewport();
            return true;
        }

        if (vm.Entry.Images.Count <= 1)
        {
            return false;
        }

        var entryCurrentIndex = vm.Entry.Images.IndexOf(vm.Image);
        if (entryCurrentIndex < 0)
        {
            return false;
        }

        var entryTargetIndex = key switch
        {
            Key.Left => entryCurrentIndex - 1,
            Key.Right => entryCurrentIndex + 1,
            Key.Home => 0,
            Key.End => vm.Entry.Images.Count - 1,
            _ => entryCurrentIndex
        };

        if (entryTargetIndex < 0 || entryTargetIndex >= vm.Entry.Images.Count || entryTargetIndex == entryCurrentIndex)
        {
            return consumeWhenUnavailable;
        }

        var targetImage = vm.Entry.Images[entryTargetIndex];
        var targetBitmap = ResolveBitmapForImage(targetImage, vm.Bitmap);
        if (targetBitmap == null)
        {
            return false;
        }

        var targetDetailsText = HistoryViewerViewModel.BuildDetailsText(vm.Entry, targetImage);
        var targetProcessed = HistoryViewerViewModel.ResolveGeneratedPromptForImage(vm.Entry, targetImage);
        if (string.IsNullOrWhiteSpace(targetProcessed))
        {
            targetProcessed = vm.Entry.ProcessedPrompt;
        }

        vm.SetDisplayedImage(vm.Entry, targetImage, targetBitmap, targetDetailsText, targetProcessed, vm.Entry.OriginalPrompt);
        ResetImageViewport();
        return true;
    }

    private bool ShouldConsumeNavigationKeyWithoutMovement()
    {
        return DataContext is ImageDetailViewModel vm &&
               vm.DisplayMode == ImageDetailMode.History &&
               ((vm.NavigationItems?.Count ?? 0) > 1 || vm.Entry.Images.Count > 1);
    }

    private Bitmap? ResolveBitmapForImage(HistoryImage image, Bitmap? fallback)
    {
        if (HistoryManager != null && ImageCacheService != null && !string.IsNullOrWhiteSpace(image.ImagePath))
        {
            var loaded = ImageCacheService.GetOrLoad(image.ImagePath, null, HistoryManager.GetHistoryDir());
            if (loaded != null)
            {
                return loaded;
            }
        }

        if (image.ImageBytes is { Length: > 0 })
        {
            try
            {
                using var ms = new System.IO.MemoryStream(image.ImageBytes);
                return new Bitmap(ms);
            }
            catch
            {
                return fallback;
            }
        }

        return fallback;
    }

    private void ResetImageViewport()
    {
        _hasInitialFit = false;
        UpdateFitScale();
        CenterImage();
    }

    private static bool ShouldIgnoreImageNavigation(object? source)
    {
        return source is TextBox
            || source is ComboBox
            || source is NumericUpDown
            || source is RangeBase;
    }
}
