using System.Linq;
using System.Threading.Tasks;
using Avalonia.Platform.Storage;

namespace PromptTool.Helpers;

public static class FilePickerHelper
{
    public static async Task<string?> PickFolderAsync(IStorageProvider provider, FolderPickerOpenOptions options)
    {
        var folders = await provider.OpenFolderPickerAsync(options);
        var folder = folders?.FirstOrDefault();
        return folder?.TryGetLocalPath() ?? folder?.Path?.LocalPath;
    }

    public static async Task<string?> PickOpenFileAsync(IStorageProvider provider, FilePickerOpenOptions options)
    {
        var files = await provider.OpenFilePickerAsync(options);
        var file = files?.FirstOrDefault();
        return file?.TryGetLocalPath() ?? file?.Path?.LocalPath;
    }

    public static async Task<string?> PickSaveFileAsync(IStorageProvider provider, FilePickerSaveOptions options)
    {
        var file = await provider.SaveFilePickerAsync(options);
        return file?.TryGetLocalPath() ?? file?.Path?.LocalPath;
    }
}
