using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Models;

namespace PromptTool.ViewModels;

public partial class PromptSegmentViewModel : ObservableObject
{
    public int Index { get; }

    [ObservableProperty]
    private string _text;

    [ObservableProperty]
    private bool _isWildcard;

    [ObservableProperty]
    private string? _wildcardName;

    [ObservableProperty]
    private string? _tooltip;

    [ObservableProperty]
    private bool _isFromInclude;

    [ObservableProperty]
    private bool _isMissing;

    public PromptSegmentViewModel(PromptSegment segment, int index)
    {
        Index = index;
        _text = segment.Text;
        _isWildcard = segment.IsWildcard;
        _wildcardName = segment.OriginalWildcardName;
        _isFromInclude = segment.IsFromInclude;
        _isMissing = segment.IsMissing;
    }
}
