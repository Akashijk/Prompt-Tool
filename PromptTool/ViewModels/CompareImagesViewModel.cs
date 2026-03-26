using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using PromptTool.Core.Models;
using PromptTool.Services;

namespace PromptTool.ViewModels;

public record ImageDetailRow(string Label, string Value);

public partial class CompareImagePaneViewModel : ObservableObject, IDisposable
{
    [ObservableProperty] private Bitmap? _image;
    [ObservableProperty] private string _title = string.Empty;
    [ObservableProperty] private ObservableCollection<ImageDetailRow> _details = new();

    public CompareImagePaneViewModel(Bitmap image, string title, ObservableCollection<ImageDetailRow> details)
    {
        _image = image;
        _title = title;
        _details = details;
    }

    partial void OnImageChanged(Bitmap? oldValue, Bitmap? newValue)
    {
        if (!ReferenceEquals(oldValue, newValue))
        {
            oldValue?.Dispose();
        }
    }

    public void Dispose()
    {
        Image = null;
    }
}

public partial class CompareImagesViewModel : ObservableObject, IDisposable
{
    [ObservableProperty] private CompareImagePaneViewModel _left;
    [ObservableProperty] private CompareImagePaneViewModel _right;

    public CompareImagesViewModel(HistoryEntry leftEntry, HistoryImage leftImage, Bitmap leftBitmap,
                                  HistoryEntry rightEntry, HistoryImage rightImage, Bitmap rightBitmap)
    {
        var leftOwned = UiBitmapHelper.CloneForUi(leftBitmap) ?? throw new InvalidOperationException("Failed to clone left compare bitmap.");
        var rightOwned = UiBitmapHelper.CloneForUi(rightBitmap) ?? throw new InvalidOperationException("Failed to clone right compare bitmap.");
        _left = new CompareImagePaneViewModel(leftOwned, leftImage.PromptType ?? "Image", BuildDetailRows(leftEntry, leftImage));
        _right = new CompareImagePaneViewModel(rightOwned, rightImage.PromptType ?? "Image", BuildDetailRows(rightEntry, rightImage));
    }

    private static ObservableCollection<ImageDetailRow> BuildDetailRows(HistoryEntry entry, HistoryImage image)
    {
        var rows = new List<ImageDetailRow>();
        var gen = HistoryViewerViewModel.GetOrParseGenParams(image);
        var prompt = HistoryViewerViewModel.FirstNonEmpty(
            image.Prompt,
            gen?.Prompt,
            entry.ProcessedPrompt,
            entry.EnhancedPrompt,
            entry.OriginalPrompt);

        void Add(string label, string? value)
        {
            if (string.IsNullOrWhiteSpace(value)) return;
            rows.Add(new ImageDetailRow(label, value.Trim()));
        }

        Add("Prompt", prompt);
        Add("Model", gen?.Model?.Name);
        Add("Seed", gen != null ? gen.Seed.ToString() : null);
        Add("Gen Duration", image.GenerationDurationMs.HasValue ? $"{image.GenerationDurationMs.Value} ms" : null);
        Add("Queue Wait", image.QueueWaitMs.HasValue ? $"{image.QueueWaitMs.Value} ms" : null);
        Add("Total Time", image.TotalDurationMs.HasValue ? $"{image.TotalDurationMs.Value} ms" : null);

        if (gen?.Loras != null && gen.Loras.Count > 0)
        {
            var loraText = string.Join(", ", gen.Loras.Select(l =>
                string.IsNullOrWhiteSpace(l.Lora?.Name) ? null : $"{l.Lora.Name} ({l.Weight:0.##})").Where(s => s != null));
            Add("LoRAs", loraText);
        }

        Add("Negative", gen?.NegativePrompt);
        Add("Style +", gen?.PositiveStylePrompt);
        Add("Style -", gen?.NegativeStylePrompt);

        var parts = new List<string>();
        if (gen != null)
        {
            if (gen.Steps > 0) parts.Add($"Steps {gen.Steps}");
            if (gen.CfgScale > 0) parts.Add($"CFG {gen.CfgScale:0.##}");
            if (gen.Width > 0 && gen.Height > 0) parts.Add($"{gen.Width}x{gen.Height}");
            if (!string.IsNullOrWhiteSpace(gen.Scheduler)) parts.Add($"Sched {gen.Scheduler}");
            if (!string.IsNullOrWhiteSpace(gen.BaseModelType)) parts.Add($"Base {gen.BaseModelType}");
        }
        Add("Params", parts.Count > 0 ? string.Join(" • ", parts) : null);

        return new ObservableCollection<ImageDetailRow>(rows);
    }

    public void Dispose()
    {
        Left.Dispose();
        Right.Dispose();
    }
}
