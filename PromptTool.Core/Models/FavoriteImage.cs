namespace PromptTool.Core.Models;

public class FavoriteImage
{
    public HistoryEntry Entry { get; }
    public HistoryImage Image { get; }

    public FavoriteImage(HistoryEntry entry, HistoryImage image)
    {
        Entry = entry;
        Image = image;
    }
}
