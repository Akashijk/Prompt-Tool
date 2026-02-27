using System.IO;
using Avalonia.Media.Imaging;

namespace PromptTool.Services;

public static class UiBitmapHelper
{
    public static Bitmap? CloneForUi(Bitmap? bitmap)
    {
        if (bitmap == null) return null;
        try
        {
            using var ms = new MemoryStream();
            bitmap.Save(ms);
            ms.Position = 0;
            return new Bitmap(ms);
        }
        catch
        {
            return null;
        }
    }
}
