namespace PromptTool.Core.Models
{
public class PromptSegment
{
    public string Text { get; set; }
    public bool IsWildcard { get; set; }
    public string? OriginalWildcardName { get; set; }
    public bool IsFromInclude { get; set; }
    public bool IsMissing { get; set; }

    public PromptSegment(string text, bool isWildcard = false, string? originalWildcardName = null, bool isFromInclude = false, bool isMissing = false)
    {
        Text = text;
        IsWildcard = isWildcard;
        OriginalWildcardName = originalWildcardName;
        IsFromInclude = isFromInclude;
        IsMissing = isMissing;
    }
}
}
