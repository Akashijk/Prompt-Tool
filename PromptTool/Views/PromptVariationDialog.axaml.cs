using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;

namespace PromptTool.Views;

public partial class PromptVariationDialog : Window
{
    private readonly string _baselinePrompt;
    private readonly List<TextBox> _variantEditors = new();

    public PromptVariationDialog()
    {
        InitializeComponent();
        _baselinePrompt = string.Empty;
    }

    public PromptVariationDialog(string baselinePrompt)
    {
        InitializeComponent();
        _baselinePrompt = baselinePrompt ?? string.Empty;
        BaselinePromptBox.Text = _baselinePrompt;
        HookEvents();
        EnsureVariantEditors(Math.Max(1, Convert.ToInt32(VariantCountInput.Value ?? 1)));
        UpdateSummary();
    }

    public static async Task<PromptVariationOptions?> ShowAsync(Window owner, string baselinePrompt)
    {
        var dialog = new PromptVariationDialog(baselinePrompt)
        {
            Topmost = true
        };
        dialog.Opened += (_, _) => dialog.Activate();
        return await dialog.ShowDialog<PromptVariationOptions?>(owner);
    }

    private void HookEvents()
    {
        VariantCountInput.PropertyChanged += (_, args) =>
        {
            if (args.Property == NumericUpDown.ValueProperty)
            {
                EnsureVariantEditors(Math.Max(1, Convert.ToInt32(VariantCountInput.Value ?? 1)));
                UpdateSummary();
            }
        };
        UseSameSeedCheck.IsCheckedChanged += (_, _) => UpdateSeedModeChecks();
        SequentialSeedCheck.IsCheckedChanged += (_, _) => UpdateSeedModeChecks();
    }

    private void UpdateSeedModeChecks()
    {
        if (UseSameSeedCheck.IsChecked == true && SequentialSeedCheck.IsChecked == true)
        {
            SequentialSeedCheck.IsChecked = false;
        }
    }

    private void UpdateSummary()
    {
        var lineCount = ParseVariants().Count;
        var requested = Math.Max(1, Convert.ToInt32(VariantCountInput.Value ?? 1));
        var used = Math.Min(requested, lineCount);
        VariantSummaryText.Text = $"Will run {used} variant(s).";
    }

    private void OnCancel(object? sender, RoutedEventArgs e)
    {
        Close(null);
    }

    private void OnRun(object? sender, RoutedEventArgs e)
    {
        ErrorText.IsVisible = false;

        var variants = ParseVariants();
        if (variants.Count == 0)
        {
            ErrorText.Text = "Add at least one variation prompt.";
            ErrorText.IsVisible = true;
            return;
        }

        var requested = Math.Max(1, Convert.ToInt32(VariantCountInput.Value ?? 1));
        if (variants.Count > requested)
        {
            variants = variants.Take(requested).ToList();
        }

        var useSameSeed = UseSameSeedCheck.IsChecked == true;
        var useSequentialSeeds = SequentialSeedCheck.IsChecked == true;
        if (!useSameSeed && !useSequentialSeeds)
        {
            useSameSeed = true;
        }

        var options = new PromptVariationOptions(
            _baselinePrompt,
            variants,
            useSameSeed,
            useSequentialSeeds,
            KeepModelSettingsCheck.IsChecked == true);
        Close(options);
    }

    private void EnsureVariantEditors(int count)
    {
        count = Math.Max(1, count);
        while (_variantEditors.Count < count)
        {
            var index = _variantEditors.Count + 1;
            var editor = new TextBox
            {
                Text = _baselinePrompt,
                Watermark = $"Variation prompt {index}",
                MinHeight = 34,
                TextWrapping = TextWrapping.Wrap,
                AcceptsReturn = false,
                HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch,
                Margin = new Thickness(0, 0, 0, 2)
            };
            editor.PropertyChanged += (_, args) =>
            {
                if (args.Property == TextBox.TextProperty)
                {
                    UpdateSummary();
                }
            };
            _variantEditors.Add(editor);
            VariantsPanel.Children.Add(editor);
        }

        while (_variantEditors.Count > count)
        {
            var lastIndex = _variantEditors.Count - 1;
            var editor = _variantEditors[lastIndex];
            _variantEditors.RemoveAt(lastIndex);
            VariantsPanel.Children.Remove(editor);
        }

        for (var i = 0; i < _variantEditors.Count; i++)
        {
            _variantEditors[i].Watermark = $"Variation prompt {i + 1}";
        }
    }

    private List<string> ParseVariants()
    {
        return _variantEditors
            .Select(editor => editor.Text?.Trim() ?? string.Empty)
            .Where(text => !string.IsNullOrWhiteSpace(text))
            .Distinct(StringComparer.Ordinal)
            .ToList();
    }

    public sealed record PromptVariationOptions(
        string BaselinePrompt,
        IReadOnlyList<string> VariantPrompts,
        bool UseSameSeed,
        bool UseSequentialSeeds,
        bool LockModelAndSettings);
}
