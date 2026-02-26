using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;

namespace PromptTool.ViewModels;

public sealed partial class AssetGroupViewModel : ObservableObject
{
    public AssetGroupViewModel(string name, ObservableCollection<AssetItemViewModel> items)
    {
        Name = name;
        Items = items;
        IsExpanded = true;
    }

    public string Name { get; }
    public ObservableCollection<AssetItemViewModel> Items { get; }

    [ObservableProperty]
    private bool _isExpanded;
}

public sealed partial class AssetItemViewModel : ObservableObject
{
    public AssetItemViewModel(string name, bool hasDefaults, string? groupName = null)
    {
        Name = name;
        HasDefaults = hasDefaults;
        GroupName = groupName ?? string.Empty;
    }

    public string Name { get; }
    public string GroupName { get; }
    [ObservableProperty] private bool _hasDefaults;
}
