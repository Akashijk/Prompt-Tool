using System;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Layout;

namespace PromptTool.Views;

public partial class SeedVariationDialog : Window
{
    private bool _suppressSeedUpdates;
    private int _defaultCount;
    private int? _initialSeed;
    private int _rootSeed;

    public SeedVariationDialog()
    {
        InitializeComponent();
    }

    public SeedVariationDialog(int defaultCount, int? initialSeed)
    {
        InitializeComponent();
        _defaultCount = Math.Max(1, defaultCount);
        _initialSeed = initialSeed;
        _rootSeed = _initialSeed ?? 0;
        InitializeSeedFields();
        HookValueChanges();
        UpdateTotalText();
    }

    public static async Task<SeedVariationOptions?> ShowAsync(Window owner, int defaultCount, int? initialSeed)
    {
        var dlg = new SeedVariationDialog(defaultCount, initialSeed);
        dlg.Topmost = true;
        dlg.Opened += (_, __) => dlg.Activate();
        return await dlg.ShowDialog<SeedVariationOptions?>(owner);
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        ErrorText.IsVisible = false;

        var count = Convert.ToInt32(CountInput.Value ?? _defaultCount);
        count = Math.Max(1, count);

        var mirrorSeeds = MirrorSeedsCheck.IsChecked == true;
        if (RandomSeedsCheck.IsChecked == true)
        {
            Close(new SeedVariationOptions(true, mirrorSeeds, _rootSeed, 0, 0, count));
            return;
        }

        var startSeed = Convert.ToInt32(StartSeedInput.Value ?? 0);
        var endSeed = Convert.ToInt32(EndSeedInput.Value ?? 0);
        if (startSeed > endSeed)
        {
            ErrorText.Text = "Start seed cannot be greater than end seed.";
            ErrorText.IsVisible = true;
            return;
        }

        Close(new SeedVariationOptions(false, mirrorSeeds, _rootSeed, startSeed, endSeed, count));
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close(null);

    private void InitializeSeedFields()
    {
        var startSeed = 0;
        if (_initialSeed.HasValue)
        {
            if (_initialSeed.Value == int.MaxValue)
            {
                startSeed = int.MaxValue;
                SeedNoteText.Text = "Seed at max value; starting from the maximum.";
                SeedNoteText.IsVisible = true;
            }
            else
            {
                startSeed = Math.Min(_initialSeed.Value + 1, int.MaxValue);
            }
        }

        _suppressSeedUpdates = true;
        StartSeedInput.Value = startSeed;
        CountInput.Value = _defaultCount;
        EndSeedInput.Value = Math.Min(startSeed + _defaultCount - 1, int.MaxValue);
        _suppressSeedUpdates = false;
    }

    private void HookValueChanges()
    {
        StartSeedInput.PropertyChanged += (_, args) =>
        {
            if (args.Property == NumericUpDown.ValueProperty)
            {
                UpdateEndSeedFromCount();
                UpdateTotalText();
            }
        };
        CountInput.PropertyChanged += (_, args) =>
        {
            if (args.Property == NumericUpDown.ValueProperty)
            {
                UpdateEndSeedFromCount();
                UpdateTotalText();
            }
        };
    }

    private void UpdateEndSeedFromCount()
    {
        if (_suppressSeedUpdates || RandomSeedsCheck.IsChecked == true || MirrorSeedsCheck.IsChecked == true) return;
        var start = Convert.ToInt32(StartSeedInput.Value ?? 0);
        var count = Math.Max(1, Convert.ToInt32(CountInput.Value ?? _defaultCount));
        _suppressSeedUpdates = true;
        EndSeedInput.Value = Math.Min(start + count - 1, int.MaxValue);
        _suppressSeedUpdates = false;
    }

    private void OnRandomSeedsChanged(object? sender, RoutedEventArgs e)
    {
        var isRandom = RandomSeedsCheck.IsChecked == true;
        StartSeedInput.IsEnabled = !isRandom;
        EndSeedInput.IsEnabled = !isRandom;
        MirrorSeedsCheck.IsEnabled = !isRandom;
        UpdateTotalText();
    }

    private void OnMirrorSeedsChanged(object? sender, RoutedEventArgs e)
    {
        var isMirror = MirrorSeedsCheck.IsChecked == true;
        StartSeedInput.IsEnabled = !isMirror && RandomSeedsCheck.IsChecked != true;
        EndSeedInput.IsEnabled = !isMirror && RandomSeedsCheck.IsChecked != true;
        UpdateTotalText();
    }

    private void UpdateTotalText()
    {
        var count = Math.Max(1, Convert.ToInt32(CountInput.Value ?? _defaultCount));
        var isRandom = RandomSeedsCheck.IsChecked == true;
        var isMirror = MirrorSeedsCheck.IsChecked == true;
        var total = isMirror ? (count * 2 + 1) : count;
        var detail = isRandom ? "Random seeds" : "Sequential seeds";
        if (isMirror)
        {
            detail += $" around root seed {_rootSeed}";
        }
        TotalCountText.Text = $"Total images: {total} ({detail})";
    }

    public sealed record SeedVariationOptions(bool RandomSeeds, bool MirrorSeeds, int RootSeed, int StartSeed, int EndSeed, int Count);
}
