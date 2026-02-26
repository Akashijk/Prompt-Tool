using CommunityToolkit.Mvvm.ComponentModel;
using System;
using System.IO;

namespace PromptTool.ViewModels;

public partial class AestheticModelOption : ObservableObject
{
    public AestheticModelOption(string name, string? url, string localPath, bool isDefault, bool requiresClip)
    {
        Name = name;
        Url = url;
        LocalPath = localPath;
        IsDefault = isDefault;
        RequiresClip = requiresClip;
    }

    public string Name { get; }
    public string? Url { get; }
    public string LocalPath { get; }
    public bool IsDefault { get; }
    public bool RequiresClip { get; }

    [ObservableProperty] private long? _sizeBytes;
    [ObservableProperty] private bool _isDownloaded;

    public string DisplayName => IsDefault ? $"{Name} (default)" : Name;

    public string SizeLabel => GetSizeLabel();

    public void RefreshFromDisk()
    {
        if (!File.Exists(LocalPath))
        {
            IsDownloaded = false;
            SizeBytes = null;
            OnPropertyChanged(nameof(SizeLabel));
            return;
        }

        var info = new FileInfo(LocalPath);
        IsDownloaded = true;
        SizeBytes = info.Length;
        OnPropertyChanged(nameof(SizeLabel));
    }

    public string GetSizeLabel()
    {
        if (!SizeBytes.HasValue) return "Size: unknown";
        var size = SizeBytes.Value;
        return size >= 1024 * 1024
            ? $"Size: {size / 1024f / 1024f:0.0} MB"
            : $"Size: {size / 1024f:0.0} KB";
    }

    partial void OnSizeBytesChanged(long? value)
    {
        OnPropertyChanged(nameof(SizeLabel));
    }
}
