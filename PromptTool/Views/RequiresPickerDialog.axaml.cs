using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Input;

namespace PromptTool.Views;

public partial class RequiresPickerDialog : Window
{
    public record Selection(string WildcardName, string Value);
    public record WildcardOption(string Name, string Preview);

    private static readonly LinkedList<string> RecentWildcards = new();
    private readonly List<WildcardOption> _allWildcards;
    private readonly Func<string, IReadOnlyList<string>> _getValues;
    private readonly ObservableCollection<WildcardOption> _wildcards = new();
    private readonly ObservableCollection<string> _values = new();
    private string _wildcardFilter = "";
    private string _valueFilter = "";
    private bool _recentFirst;

    public RequiresPickerDialog()
    {
        InitializeComponent();
        _allWildcards = new List<WildcardOption>();
        _getValues = _ => Array.Empty<string>();
    }

    public RequiresPickerDialog(
        IReadOnlyList<string> wildcardNames,
        Func<string, IReadOnlyList<string>> getValues,
        string? initialWildcard,
        string? initialValue)
    {
        InitializeComponent();
        _allWildcards = wildcardNames
            .Select(name => new WildcardOption(name, BuildPreview(getValues(name))))
            .ToList();
        _getValues = getValues;

        WildcardListBox.ItemsSource = _wildcards;
        ValueListBox.ItemsSource = _values;

        Opened += (_, __) => WildcardFilterBox.Focus();
        KeyDown += OnKeyDown;

        WildcardFilterBox.TextChanged += (_, __) =>
        {
            _wildcardFilter = WildcardFilterBox.Text ?? "";
            ApplyWildcardFilter();
        };

        ValueFilterBox.TextChanged += (_, __) =>
        {
            _valueFilter = ValueFilterBox.Text ?? "";
            ApplyValueFilter();
        };

        RecentFirstToggle.IsCheckedChanged += (_, __) =>
        {
            _recentFirst = RecentFirstToggle.IsChecked ?? false;
            ApplyWildcardFilter();
        };

        WildcardListBox.SelectionChanged += (_, __) =>
        {
            LoadValuesForSelection();
        };

        ApplyWildcardFilter();

        if (!string.IsNullOrWhiteSpace(initialWildcard))
        {
            WildcardListBox.SelectedItem = _wildcards.FirstOrDefault(w =>
                string.Equals(w.Name, initialWildcard, StringComparison.OrdinalIgnoreCase));
        }

        if (!string.IsNullOrWhiteSpace(initialValue))
        {
            ValueListBox.SelectedItem = _values.FirstOrDefault(v =>
                string.Equals(v, initialValue, StringComparison.OrdinalIgnoreCase));
        }
    }

    public static async Task<Selection?> ShowAsync(
        Window owner,
        IReadOnlyList<string> wildcardNames,
        Func<string, IReadOnlyList<string>> getValues,
        string? initialWildcard,
        string? initialValue)
    {
        var dlg = new RequiresPickerDialog(wildcardNames, getValues, initialWildcard, initialValue);
        return await dlg.ShowDialog<Selection?>(owner);
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

    private void LoadValuesForSelection()
    {
        var option = WildcardListBox.SelectedItem as WildcardOption;
        var wildcard = option?.Name;
        _values.Clear();
        if (string.IsNullOrWhiteSpace(wildcard)) return;

        var values = _getValues(wildcard)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .OrderBy(v => v, StringComparer.OrdinalIgnoreCase)
            .ToList();

        foreach (var value in values)
        {
            _values.Add(value);
        }

        ApplyValueFilter();
    }

    private void ApplyValueFilter()
    {
        if (string.IsNullOrWhiteSpace(_valueFilter))
        {
            return;
        }

        var option = WildcardListBox.SelectedItem as WildcardOption;
        var wildcard = option?.Name;
        if (string.IsNullOrWhiteSpace(wildcard)) return;
        _values.Clear();
        var filtered = _getValues(wildcard)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Where(v => v.Contains(_valueFilter, StringComparison.OrdinalIgnoreCase))
            .OrderBy(v => v, StringComparer.OrdinalIgnoreCase);
        foreach (var value in filtered)
        {
            _values.Add(value);
        }
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        var option = WildcardListBox.SelectedItem as WildcardOption;
        var wildcard = option?.Name;
        var value = ValueListBox.SelectedItem as string;
        if (string.IsNullOrWhiteSpace(wildcard) || string.IsNullOrWhiteSpace(value))
        {
            Close(null);
            return;
        }
        UpdateRecent(wildcard);
        Close(new Selection(wildcard, value));
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
        if (e.Key == Avalonia.Input.Key.Escape)
        {
            Close(null);
            e.Handled = true;
        }
        else if (e.Key == Avalonia.Input.Key.Enter)
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
