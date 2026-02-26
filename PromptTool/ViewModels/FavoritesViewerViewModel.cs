using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PromptTool.Core.Models;
using PromptTool.Core.Services;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public partial class FavoriteImageItem : ObservableObject
{
    public FavoriteImage Favorite { get; }
    [ObservableProperty] private Bitmap? _bitmap;

    public FavoriteImageItem(FavoriteImage favorite, Bitmap? bitmap)
    {
        Favorite = favorite;
        _bitmap = bitmap;
    }

    public string Prompt => Favorite.Entry.ProcessedPrompt ?? Favorite.Entry.OriginalPrompt;
    public DateTime Timestamp => Favorite.Entry.Timestamp;
}

public partial class FavoritesViewerViewModel : ObservableObject
{
    private readonly HistoryManagerService _historyManager;
    private readonly ImageCacheService _imageCache;
    private readonly string _historyDir;
    private CancellationTokenSource? _loadCts;

    [ObservableProperty] private ObservableCollection<FavoriteImageItem> _favoriteImages = new();
    [ObservableProperty] private bool _isLoading = true;
    [ObservableProperty] private string _statusText = "Loading favorite images...";

    public FavoritesViewerViewModel(HistoryManagerService historyManager, ImageCacheService imageCache)
    {
        _historyManager = historyManager;
        _imageCache = imageCache;
        _historyDir = historyManager.GetHistoryDir();
        LoadFavorites();
    }
    
    // Design-time constructor
    public FavoritesViewerViewModel()
    {
        _historyManager = null!;
        _imageCache = new ImageCacheService();
        _historyDir = string.Empty;
        _favoriteImages = new ObservableCollection<FavoriteImageItem>
        {
            // Add sample data for design-time view
        };
        _isLoading = false;
        _statusText = "Found 3 favorite images.";
    }

    [RelayCommand]
    private void LoadFavorites()
    {
        _loadCts?.Cancel();
        _loadCts?.Dispose();
        _loadCts = new CancellationTokenSource();
        var token = _loadCts.Token;

        using var perf = PerfLogger.Time("Favorites.Load");
        PerfLogger.ResetTimings("Favorites.Decode");
        IsLoading = true;
        StatusText = "Loading favorite images...";
        FavoriteImages.Clear();

        _ = Task.Run(() =>
        {
            var favorites = _historyManager.GetAllFavoriteImages();
            if (favorites.Count == 0)
            {
                Dispatcher.UIThread.Post(() =>
                {
                    StatusText = "No favorite images found.";
                    IsLoading = false;
                });
                return;
            }

            var items = new List<FavoriteImageItem>();
            foreach (var fav in favorites.OrderByDescending(f => f.Entry.Timestamp))
            {
                if (token.IsCancellationRequested) return;
                var bmp = LoadBitmap(fav.Image.ImagePath);
                if (bmp != null)
                {
                    items.Add(new FavoriteImageItem(fav, bmp));
                }
            }

            if (token.IsCancellationRequested) return;

            Dispatcher.UIThread.Post(() =>
            {
                FavoriteImages = new ObservableCollection<FavoriteImageItem>(items);
                IsLoading = false;
                StatusText = $"Found {FavoriteImages.Count} favorite images.";
                PerfLogger.Log($"Favorites.Load favorites={favorites.Count} loaded={FavoriteImages.Count}");
                PerfLogger.LogSummary("Favorites.Load", "Favorites.Decode");
            });
        }, token);
    }
    
    [RelayCommand]
    private void UnfavoriteImage(FavoriteImageItem? item)
    {
        if (item == null) return;

        item.Favorite.Image.IsFavorite = false;
        // if this is the last favorite image in the entry, unfavorite the entry too
        if (!item.Favorite.Entry.Images.Any(i => i.IsFavorite))
        {
            item.Favorite.Entry.IsFavorite = false;
        }

        _historyManager.SaveChanges();
        // Refresh the view
        LoadFavorites();
    }

    private Bitmap? LoadBitmap(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        using var _ = PerfLogger.Measure("Favorites.Decode");
        return _imageCache.GetOrLoad(path, null, _historyDir);
    }
}
