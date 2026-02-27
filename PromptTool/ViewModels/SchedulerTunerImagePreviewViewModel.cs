using Avalonia.Media.Imaging;

namespace PromptTool.ViewModels;

public sealed class SchedulerTunerImagePreviewViewModel
{
    public Bitmap Image { get; }
    public string Title { get; }

    public SchedulerTunerImagePreviewViewModel(Bitmap image, string title)
    {
        Image = image;
        Title = title;
    }
}

public sealed class SchedulerTunerImageCompareViewModel
{
    public Bitmap LeftImage { get; }
    public Bitmap RightImage { get; }
    public string LeftTitle { get; }
    public string RightTitle { get; }

    public SchedulerTunerImageCompareViewModel(Bitmap leftImage, string leftTitle, Bitmap rightImage, string rightTitle)
    {
        LeftImage = leftImage;
        LeftTitle = leftTitle;
        RightImage = rightImage;
        RightTitle = rightTitle;
    }
}
