using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Input;

namespace PromptTool.Views;

public partial class IncludesPickerDialog : Window
{
    public record WildcardOption(string Name, string Preview);

    private static readonly LinkedList<string> RecentWildcards = new();
    private readonly List<WildcardOption> _allWildcards;
    private readonly ObservableCollection<WildcardOption> _wildcards = new();
    private string _wildcardFilter = "";
    private bool _recentFirst;

    public IncludesPickerDialog()
    {
        InitializeComponent();
        _allWildcards = new List<WildcardOption>();
    }

    public IncludesPickerDialog(
        IReadOnlyList<string> wildcardNames,
        Func<string, IReadOnlyList<string>> getValues,
        IReadOnlyList<string> initialWildcards)
    {
        InitializeComponent();
        _allWildcards = wildcardNames
            .Select(name => new WildcardOption(name, BuildPreview(getValues(name))))
            .ToList();

        WildcardListBox.ItemsSource = _wildcards;
        WildcardListBox.SelectionMode = SelectionMode.Multiple;
        Opened += (_, __) => WildcardFilterBox.Focus();
        KeyDown += OnKeyDown;

        WildcardFilterBox.TextChanged += (_, __) =>
        {
            _wildcardFilter = WildcardFilterBox.Text ?? "";
            ApplyWildcardFilter();
        };

        RecentFirstToggle.IsCheckedChanged += (_, __) =>
        {
            _recentFirst = RecentFirstToggle.IsChecked ?? false;
            ApplyWildcardFilter();
        };

        ApplyWildcardFilter();
        if (WildcardListBox.SelectedItems != null && WildcardListBox.SelectedItems.Count == 0 && _wildcards.Count > 0)
        {
            WildcardListBox.SelectedItems.Add(_wildcards[0]);
        }

        if (WildcardListBox.SelectedItems == null) return;
        foreach (var name in initialWildcards ?? Array.Empty<string>())
        {
            var match = _wildcards.FirstOrDefault(w =>
                string.Equals(w.Name, name, StringComparison.OrdinalIgnoreCase));
            if (match != null)
            {
                WildcardListBox.SelectedItems.Add(match);
            }
        }
    }

    public static async Task<IReadOnlyList<string>?> ShowAsync(
        Window owner,
        IReadOnlyList<string> wildcardNames,
        Func<string, IReadOnlyList<string>> getValues,
        IReadOnlyList<string> initialWildcards)
    {
        var dlg = new IncludesPickerDialog(wildcardNames, getValues, initialWildcards);
        return await dlg.ShowDialog<IReadOnlyList<string>?>(owner);
    }

    private void ApplyWildcardFilter()
    {
        _wildcards.Clear();
        var items = _allWildcards
            .Where(w => string.IsNullOrWhiteSpace(_wildcardFilter) ||
                        w.Name.Contains(_wildcardFilter, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (_recentFirst && RecentWildcards.Count > 0)
        {
            var recentMap = RecentWildcards.Select((name, index) => (name, index))
                .ToDictionary(x => x.name, x => x.index, StringComparer.OrdinalIgnoreCase);
            items = items
                .OrderBy(w => recentMap.TryGetValue(w.Name, out var idx) ? idx : int.MaxValue)
                .ThenBy(w => w.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        else
        {
            items = items.OrderBy(w => w.Name, StringComparer.OrdinalIgnoreCase).ToList();
        }
        foreach (var item in items)
        {
            _wildcards.Add(item);
        }
        if (_wildcards.Count > 0 && WildcardListBox.SelectedItem == null)
        {
            WildcardListBox.SelectedItem = _wildcards[0];
        }
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        var selectedItems = WildcardListBox.SelectedItems ?? Array.Empty<object>();
        var selected = selectedItems
            .OfType<WildcardOption>()
            .Select(o => o.Name)
            .Where(n => !string.IsNullOrWhiteSpace(n))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (selected.Count == 0)
        {
            Close(null);
            return;
        }
        foreach (var name in selected)
        {
            UpdateRecent(name);
        }
        Close(selected);
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close(null);

    private static void UpdateRecent(string name)
    {
        var node = RecentWildcards.First;
        while (node != null)
        {
            if (string.Equals(node.Value, name, StringComparison.OrdinalIgnoreCase))
            {
                RecentWildcards.Remove(node);
                break;
            }
            node = node.Next;
        }
        RecentWildcards.AddFirst(name);
        while (RecentWildcards.Count > 20)
        {
            RecentWildcards.RemoveLast();
        }
    }

    private void OnKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close(null);
            e.Handled = true;
        }
        else if (e.Key == Key.Enter)
        {
            OnOk(sender, new RoutedEventArgs());
            e.Handled = true;
        }
    }

    private static string BuildPreview(IReadOnlyList<string> values)
    {
        if (values == null || values.Count == 0) return "No values.";
        var sample = values.Take(12).ToList();
        var suffix = values.Count > sample.Count ? " ..." : "";
        return string.Join(", ", sample) + suffix;
    }
}
