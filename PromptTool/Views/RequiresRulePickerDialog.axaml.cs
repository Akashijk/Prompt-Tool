using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Input;
using PromptTool.ViewModels;

namespace PromptTool.Views;

public partial class RequiresRulePickerDialog : Window
{
    private readonly Func<IReadOnlyList<string>> _getWildcardNames;
    private readonly Func<string, IReadOnlyList<string>> _getWildcardValues;
    private readonly ObservableCollection<string> _wildcards = new();
    private readonly ObservableCollection<string> _values = new();
    private string _wildcardFilter = "";
    private string _valueFilter = "";

    public RequiresRulePickerDialog()
    {
        InitializeComponent();
        _getWildcardNames = () => Array.Empty<string>();
        _getWildcardValues = _ => Array.Empty<string>();
        WildcardListBox.ItemsSource = _wildcards;
        ValueListBox.ItemsSource = _values;
        OperatorBox.ItemsSource = new[] { "equals", "in list" };
        OperatorBox.SelectedIndex = 0;
        UpdateValueSelectionMode();
    }

    public RequiresRulePickerDialog(
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        WildcardManagerViewModel.RequirementRule? initial)
    {
        InitializeComponent();
        _getWildcardNames = getWildcardNames;
        _getWildcardValues = getWildcardValues;

        WildcardListBox.ItemsSource = _wildcards;
        ValueListBox.ItemsSource = _values;

        OperatorBox.ItemsSource = new[] { "equals", "in list" };
        OperatorBox.SelectedIndex = 0;
        if (initial != null && initial.Operator == "in")
        {
            OperatorBox.SelectedIndex = 1;
        }

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

        OperatorBox.SelectionChanged += (_, __) => UpdateValueSelectionMode();
        WildcardListBox.SelectionChanged += (_, __) => LoadValues();

        ApplyWildcardFilter();

        if (initial != null)
        {
            var match = _wildcards.FirstOrDefault(w => string.Equals(w, initial.WildcardName, StringComparison.OrdinalIgnoreCase));
            if (match != null) WildcardListBox.SelectedItem = match;
            UpdateValueSelectionMode();
            foreach (var value in initial.Values)
            {
                if (_values.Contains(value))
                {
                    ValueListBox.SelectedItems?.Add(value);
                }
            }
        }
    }

    public static async Task<WildcardManagerViewModel.RequirementRule?> ShowAsync(
        Window owner,
        Func<IReadOnlyList<string>> getWildcardNames,
        Func<string, IReadOnlyList<string>> getWildcardValues,
        WildcardManagerViewModel.RequirementRule? initial)
    {
        var dlg = new RequiresRulePickerDialog(getWildcardNames, getWildcardValues, initial);
        return await dlg.ShowDialog<WildcardManagerViewModel.RequirementRule?>(owner);
    }

    private void ApplyWildcardFilter()
    {
        _wildcards.Clear();
        var items = _getWildcardNames()
            .Where(w => string.IsNullOrWhiteSpace(_wildcardFilter) ||
                        w.Contains(_wildcardFilter, StringComparison.OrdinalIgnoreCase))
            .OrderBy(w => w, StringComparer.OrdinalIgnoreCase);
        foreach (var item in items)
        {
            _wildcards.Add(item);
        }
        if (_wildcards.Count > 0 && WildcardListBox.SelectedItem == null)
        {
            WildcardListBox.SelectedItem = _wildcards[0];
        }
    }

    private void LoadValues()
    {
        var wildcard = WildcardListBox.SelectedItem as string;
        _values.Clear();
        if (string.IsNullOrWhiteSpace(wildcard)) return;
        var items = _getWildcardValues(wildcard)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .OrderBy(v => v, StringComparer.OrdinalIgnoreCase);
        foreach (var item in items)
        {
            _values.Add(item);
        }
        ApplyValueFilter();
    }

    private void ApplyValueFilter()
    {
        if (string.IsNullOrWhiteSpace(_valueFilter))
        {
            return;
        }
        var wildcard = WildcardListBox.SelectedItem as string;
        if (string.IsNullOrWhiteSpace(wildcard)) return;
        _values.Clear();
        var filtered = _getWildcardValues(wildcard)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Where(v => v.Contains(_valueFilter, StringComparison.OrdinalIgnoreCase))
            .OrderBy(v => v, StringComparer.OrdinalIgnoreCase);
        foreach (var value in filtered)
        {
            _values.Add(value);
        }
    }

    private void UpdateValueSelectionMode()
    {
        var isInList = OperatorBox.SelectedIndex == 1;
        ValueListBox.SelectionMode = isInList ? SelectionMode.Multiple : SelectionMode.Single;
    }

    private void OnOk(object? sender, RoutedEventArgs e)
    {
        var wildcard = WildcardListBox.SelectedItem as string;
        if (string.IsNullOrWhiteSpace(wildcard))
        {
            Close(null);
            return;
        }
        var values = (ValueListBox.SelectedItems ?? Array.Empty<object>())
            .OfType<string>()
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .ToList();
        if (values.Count == 0)
        {
            Close(null);
            return;
        }
        var op = OperatorBox.SelectedIndex == 1 ? "in" : "equals";
        Close(new WildcardManagerViewModel.RequirementRule(wildcard, op, values));
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close(null);

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
}
